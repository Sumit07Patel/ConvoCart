"""Come-back email for a left cart: starts from the store's `cart.abandoned` webhook.

Checks, in order, before anything is sent:
  1. the cart is still open and has items
  2. there is an address: one the visitor typed into the chat, or the signed-in shopper's
  3. consent: the visitor ticked the box, or the shopper opted in; and the address has not unsubscribed
  4. no come-back email was sent for this cart yet (max 1 per cart)
  5. none went to this address in the cooldown window (24 h)
If the shopper bargained a discount in the chat, the email reminds them it is still on the cart. It can
never offer a new or bigger one: the only percentage allowed in the text is the cart's own discount.
Every decision, including blocked ones, is written to outbound_messages for audit.
"""
from __future__ import annotations

import json
import re

from .. import ops
from ..channels.mail import EmailClient
from ..commerce import Commerce, CommerceError
from ..config import Rules
from ..llm import ChatModel, ModelError
from ..tools.core import ToolContext, run_tool, tool_schemas
from .compose import compose_recovery
from .guards import WRONG_CURRENCY, collect_numbers, unverified_prices
from .language import t
from .notify import chat_link, deliver, recipient
from .prompts import system_prompt

MAX_LEN = 400
PERCENT = re.compile(r"(\d+)\s*%")
URL = re.compile(r"https?://\S+")  # links are URL-encoded (%3A, %40) and must not count as percentages


def run_recovery(cart_id: str, commerce: Commerce, model: ChatModel, rules: Rules,
                 mailer: EmailClient | None = None) -> dict:
    tracer = ops.Tracer(f"recovery:{cart_id}")

    def done(status: str, detail: str, to: str = "", cid: str | None = None) -> dict:
        if status == "blocked":
            ops.record_outbound("email", to, cid, "cart_recovery", "", "blocked", detail, cart_id)
        tracer.add("recovery", "recovery", status, {"detail": detail})
        tracer.flush()
        return {"cart_id": cart_id, "status": status, "detail": detail, "body": ""}

    try:
        cart = commerce.get_cart(cart_id)
    except CommerceError as e:
        return done("skipped", f"cart lookup failed: {e.code}")
    if cart["status"] == "completed" or not cart["items"]:
        return done("skipped", "cart already paid or empty")
    session = ops.session_for_cart(cart_id)
    customer = commerce.get_customer(cart["customer_id"]) if cart.get("customer_id") else None
    to, consent = recipient(customer, session)
    cid = (customer or {}).get("id")
    if not to:
        return done("skipped", "anonymous cart, nobody to contact")
    if not consent:
        return done("blocked", "no_consent", to, cid)
    per_cart, recent = ops.recovery_counts(to, cart_id, rules.recovery_cooldown_hours)
    if per_cart >= rules.recovery_max_messages_per_cart:
        return done("blocked", "cart_limit_reached", to, cid)
    if recent >= 1:
        return done("blocked", "cooldown", to, cid)

    lang = (session or {}).get("language") or (customer or {}).get("preferred_language", "en")
    name = (customer or {}).get("name", "there")
    link = chat_link((session or {}).get("id"))
    ctx = ToolContext(commerce=commerce, rules=rules, tracer=tracer, agent="recovery",
                      session={"id": f"recovery:{cart_id}", "customer_id": cid, "cart_id": cart_id, "memory": {}})
    state = {"customer_name": name.split()[0], "chat_link": link, "discount_pct": cart.get("discount_pct", 0)}
    messages = [{"role": "system", "content": system_prompt("recovery", lang, state)},
                {"role": "user", "content": "EVENT cart.abandoned: write the email now."}]
    body, model_error = "", ""
    try:
        for _ in range(3):
            reply = model.chat(messages, tools=tool_schemas("recovery"))
            tracer.add("llm", "recovery", model.name, {"tool_calls": [tc.name for tc in reply.tool_calls]},
                       latency_ms=reply.latency_ms)
            if not reply.tool_calls:
                body = (reply.content or "").strip()
                break
            messages.append({"role": "assistant", "content": reply.content or None, "tool_calls": [
                {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)
                                                                if not isinstance(tc.arguments, str) else tc.arguments}}
                for tc in reply.tool_calls]})
            for tc in reply.tool_calls:
                res = run_tool(ctx, tc.name, tc.arguments)
                messages.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name,
                                 "content": json.dumps(res, ensure_ascii=False, default=str)})
    except ModelError as e:
        model_error = str(e)[:300]
        tracer.add("error", "recovery", "model_error", {"error": model_error})
    allowed = collect_numbers(cart)
    bad_pct = [p for p in PERCENT.findall(URL.sub("", body)) if int(p) != cart.get("discount_pct", 0)]
    if not body or len(body) > MAX_LEN or unverified_prices(body, allowed) or bad_pct or WRONG_CURRENCY.search(body) \
            or link not in body:
        if body:
            tracer.add("guard", "recovery", "reply_replaced", {"len": len(body), "bad_pct": bad_pct})
        body = compose_recovery(cart, name, lang, link)
    subject = (t("recovery_subject_discount", lang, pct=cart["discount_pct"]) if cart.get("discount_pct")
               else t("recovery_subject", lang))
    status, detail, body = deliver(to, cid, "cart_recovery", subject, body, cart_id, lang, marketing=True, mailer=mailer)
    tracer.add("recovery", "recovery", status, {"detail": detail[:200]})
    tracer.flush()
    return {"cart_id": cart_id, "to": to, "status": status, "detail": detail, "body": body, "subject": subject,
            "model_error": model_error}
