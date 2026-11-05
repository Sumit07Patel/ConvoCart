"""Multi-agent orchestration (Phase 5) with LangGraph.

    understand -> router -> advisor | support | human -> guard -> END
                               \\________ step limit / handover_to_human ________/-> human

Shared state per turn; session memory (history, last results, cart, pending offers) persists in
the agent_sessions table between turns.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .. import ops
from ..commerce import Commerce, CommerceError, get_commerce
from ..config import Rules, load_rules
from ..llm import ChatModel, ModelError, get_model
from ..llm.scripted import ScriptedModel
from ..tools.core import ToolContext, run_tool, tool_schemas
from .compose import compose_tool_result
from .guards import ODD_HYPHENS, check_reply
from .language import detect_language, t
from .prompts import system_prompt

HISTORY_TURNS = 10


class TurnState(TypedDict, total=False):
    rt: Any                 # runtime objects for this turn (ToolContext); not persisted
    user_message: str
    language: str
    route: str
    route_reason: str
    reply: str
    handover_reason: str | None
    issues: dict
    model_calls: int


class ConvoCartAgent:
    def __init__(self, commerce: Commerce | None = None, model: ChatModel | None = None, rules: Rules | None = None):
        self.commerce = commerce or get_commerce()
        self.model = model or get_model()
        self.rules = rules or load_rules()
        self._fallback_router = ScriptedModel()
        self.graph = self._build()

    # ------------------------------------------------------------------ graph
    def _build(self):
        g = StateGraph(TurnState)
        g.add_node("understand", self._understand)
        g.add_node("router", self._router)
        g.add_node("advisor", lambda s: self._specialist(s, "advisor"))
        g.add_node("support", lambda s: self._specialist(s, "support"))
        g.add_node("human", self._human)
        g.add_node("guard", self._guard)
        g.set_entry_point("understand")
        g.add_edge("understand", "router")
        g.add_conditional_edges("router", lambda s: s["route"], {"advisor": "advisor", "support": "support",
                                                                 "human": "human"})
        for node in ("advisor", "support"):
            g.add_conditional_edges(node, lambda s: "human" if s.get("handover_reason") else "guard",
                                    {"human": "human", "guard": "guard"})
        g.add_edge("human", "guard")
        g.add_edge("guard", END)
        return g.compile()

    # ------------------------------------------------------------------ nodes
    def _understand(self, s: TurnState) -> dict:
        ctx: ToolContext = s["rt"]
        lang = detect_language(s["user_message"], previous=ctx.session.get("language"))
        ctx.session["language"] = lang
        return {"language": lang}

    def _state_summary(self, ctx: ToolContext) -> dict:
        mem = ctx.memory
        state: dict = {"signed_in": bool(ctx.session.get("customer_id"))}
        if ctx.session.get("customer_name"):
            state["customer_name"] = ctx.session["customer_name"]
        if ctx.session.get("cart_id"):
            try:
                c = self.commerce.get_cart(ctx.session["cart_id"])
                state["cart"] = {"items": [f"{i['title']} ({i['size']}) x{i['qty']}" for i in c["items"]],
                                 "total": c["total"], "discount_pct": c["discount_pct"]}
            except CommerceError:
                pass
        for k in ("last_results", "last_added", "pending_offer", "pending_add", "last_order_id", "last_route"):
            if mem.get(k) or ctx.session.get("_carry", {}).get(k):
                state[k] = ctx.session.get("_carry", {}).get(k) or mem.get(k)
        return state

    def _history(self, ctx: ToolContext) -> list[dict]:
        return [{"role": m["role"], "content": m["content"]} for m in ctx.session.get("history", [])[-HISTORY_TURNS:]]

    def _router(self, s: TurnState) -> dict:
        ctx: ToolContext = s["rt"]
        ctx.agent = "router"
        messages = [{"role": "system", "content": system_prompt("router", s["language"], self._state_summary(ctx))},
                    *self._history(ctx)[-6:], {"role": "user", "content": s["user_message"]}]
        route, reason, how = None, "", "model"
        t0 = time.perf_counter()
        try:
            reply = self.model.chat(messages, tools=tool_schemas("router"),
                                    tool_choice={"type": "function", "function": {"name": "route_to"}})
            ctx.tracer.add("llm", "router", self.model.name, {"usage": reply.usage},
                           latency_ms=(time.perf_counter() - t0) * 1000)
            for tc in reply.tool_calls:
                if tc.name == "route_to" and isinstance(tc.arguments, dict) and \
                        tc.arguments.get("agent") in ("advisor", "support", "human"):
                    route, reason = tc.arguments["agent"], tc.arguments.get("reason", "")
        except ModelError as e:
            ctx.tracer.add("error", "router", "model_error", {"error": str(e)[:300]})
        if route is None:  # invalid or failed routing falls back to the rule router
            how = "rules_fallback"
            fb = self._fallback_router.chat(messages, tool_choice="route_to").tool_calls[0].arguments
            route, reason = fb["agent"], fb["reason"]
        ctx.tracer.add("route", "router", route, {"reason": reason, "how": how})
        ctx.memory["last_route"] = route if route != "human" else ctx.memory.get("last_route")
        return {"route": route, "route_reason": reason, "model_calls": s.get("model_calls", 0) + 1}

    def _specialist(self, s: TurnState, role: str) -> dict:
        ctx: ToolContext = s["rt"]
        ctx.agent = role
        lang = s["language"]
        messages: list[dict] = [{"role": "system", "content": system_prompt(role, lang, self._state_summary(ctx))},
                                *self._history(ctx), {"role": "user", "content": s["user_message"]}]
        tools = tool_schemas(role)
        calls = s.get("model_calls", 0)
        final, last_tool = None, None
        for _ in range(self.rules.max_agent_steps):
            t0 = time.perf_counter()
            try:
                reply = self.model.chat(messages, tools=tools)
            except ModelError as e:
                ctx.tracer.add("error", role, "model_error", {"error": str(e)[:300]})
                final = compose_tool_result(*last_tool, lang) if last_tool else t("error", lang)
                return {"reply": final, "model_calls": calls, "issues": {"model_error": str(e)[:200]}}
            calls += 1
            ctx.tracer.add("llm", role, self.model.name, {"tool_calls": [tc.name for tc in reply.tool_calls],
                                                          "usage": reply.usage},
                           latency_ms=reply.latency_ms or (time.perf_counter() - t0) * 1000)
            if not reply.tool_calls:
                final = (reply.content or "").strip()
                break
            messages.append({"role": "assistant", "content": reply.content or None, "tool_calls": [
                {"id": tc.id, "type": "function", "function": {
                    "name": tc.name,
                    "arguments": tc.arguments if isinstance(tc.arguments, str) else json.dumps(tc.arguments)}}
                for tc in reply.tool_calls]})
            for tc in reply.tool_calls:
                result = run_tool(ctx, tc.name, tc.arguments)
                last_tool = (tc.name, tc.arguments if isinstance(tc.arguments, dict) else {}, result)
                messages.append({"role": "tool", "tool_call_id": tc.id, "name": tc.name,
                                 "content": json.dumps(result, ensure_ascii=False, default=str)[:6000]})
            if ctx.handover_reason:
                return {"handover_reason": ctx.handover_reason, "model_calls": calls}
        else:
            ctx.tracer.add("guard", role, "step_limit", {"max_steps": self.rules.max_agent_steps})
            return {"handover_reason": "step_limit", "model_calls": calls}
        if not final:
            final = compose_tool_result(*last_tool, lang) if last_tool else t("fallback", lang)
        return {"reply": final, "model_calls": calls}

    def _human(self, s: TurnState) -> dict:
        ctx: ToolContext = s["rt"]
        reason = s.get("handover_reason") or s.get("route_reason") or "shopper asked for a person"
        summary = {
            "last_messages": (ctx.session.get("history", []) + [{"role": "user", "content": s["user_message"]}])[-8:],
            "customer_id": ctx.session.get("customer_id"), "cart_id": ctx.session.get("cart_id"),
            "language": s["language"], "last_order_id": ctx.memory.get("last_order_id"),
            "tools_this_turn": [{"name": c["name"], "ok": c["ok"], "error": c["error"]} for c in ctx.calls],
        }
        hid = ops.create_handover(ctx.session["id"], ctx.session.get("customer_id"), reason, summary)
        ctx.session["status"] = "with_human"
        ctx.tracer.add("handover", ctx.agent or "router", reason, {"handover_id": hid})
        return {"reply": t("handover", s["language"]), "handover_reason": reason}

    def _guard(self, s: TurnState) -> dict:
        ctx: ToolContext = s["rt"]
        reply = (s.get("reply") or t("fallback", s["language"])).translate(ODD_HYPHENS)
        results = [c["result"] for c in ctx.calls]
        extra = set()
        for r in ctx.memory.get("last_results", []):
            extra.add(r["price"])
        if ctx.session.get("cart_id"):
            try:
                c = self.commerce.get_cart(ctx.session["cart_id"])
                extra |= {c["total"], c["subtotal"], c["discount_amount"]} | {i["line_total"] for i in c["items"]}
            except CommerceError:
                pass
        refused = any(c["name"] == "apply_discount" and c["error"] == "over_limit" for c in ctx.calls)
        issues = dict(s.get("issues") or {})
        issues.update(check_reply(reply, s["language"], results, extra, self.rules.max_discount_pct, refused))
        good_calls = [c for c in ctx.calls if c["name"] not in ("route_to",)]
        if issues.get("unverified_price") or issues.get("discount_over_cap") or issues.get("wrong_currency") \
                or issues.get("tool_name_leak") or (issues.get("language_mismatch") and good_calls):
            ctx.tracer.add("guard", "guard", "reply_replaced", issues)
            reply = compose_tool_result(good_calls[-1]["name"], good_calls[-1]["args"], good_calls[-1]["result"],
                                        s["language"]) if good_calls else t("fallback", s["language"])
        elif issues:
            ctx.tracer.add("guard", "guard", "flag", issues)
        return {"reply": reply, "issues": issues}

    # ------------------------------------------------------------------ entry point
    def handle_message(self, session_id: str, text: str, channel: str = "web", customer_id: str | None = None) -> dict:
        t_start = time.perf_counter()
        sess = ops.load_session(session_id, channel)
        if customer_id and sess.get("customer_id") != customer_id:
            if sess.get("customer_id"):  # a different shopper on this session: never reuse their cart
                sess["cart_id"] = None
                sess["memory"] = {}
            sess["customer_id"] = customer_id
        if sess.get("customer_id"):
            try:
                sess["customer_name"] = self.commerce.get_customer(sess["customer_id"])["name"]
            except CommerceError:
                sess["customer_id"] = None
        tracer = ops.Tracer(session_id)
        text = (text or "").strip()[:2000]
        tracer.add("input", channel, "user_message", {"text": text})
        ctx = ToolContext(commerce=self.commerce, rules=self.rules, session=sess, tracer=tracer)
        sess["_carry"] = {k: sess.setdefault("memory", {}).pop(k) for k in ("pending_offer", "pending_add")
                          if k in sess["memory"]}

        if sess.get("status") == "with_human":
            lang = detect_language(text, sess.get("language"))
            out: dict = {"reply": t("with_human", lang), "language": lang, "route": "human",
                         "handover_reason": "already_with_human", "issues": {}}
        else:
            try:
                out = self.graph.invoke({"rt": ctx, "user_message": text, "model_calls": 0})
            except Exception as e:  # noqa: BLE001 - never leave the shopper without a reply
                tracer.add("error", "graph", type(e).__name__, {"error": str(e)[:500]})
                lang = sess.get("language", "en")
                out = {"reply": t("error", lang), "language": lang, "route": "error", "issues": {"crash": str(e)[:200]}}
            out.pop("rt", None)

        sess.pop("_carry", None)
        sess.pop("customer_name", None)
        sess["history"] = sess.get("history", []) + [{"role": "user", "content": text},
                                                     {"role": "assistant", "content": out["reply"]}]
        ops.save_session(sess)
        latency = (time.perf_counter() - t_start) * 1000
        tracer.add("reply", out.get("route", ""), "assistant_message", {"text": out["reply"],
                                                                        "issues": out.get("issues", {})},
                   latency_ms=latency)
        tracer.flush()
        handed = bool(out.get("handover_reason")) and out.get("handover_reason") != "already_with_human"
        ops.record_outcome(session_id, tracer.trace_id, out.get("route", ""), out.get("language", "en"), handed, latency)
        cart = None
        if sess.get("cart_id"):
            try:
                cart = self.commerce.get_cart(sess["cart_id"])
            except CommerceError:
                pass
        return {
            "session_id": session_id, "trace_id": tracer.trace_id, "reply": out["reply"],
            "language": out.get("language"), "route": out.get("route"), "handover": handed,
            "handover_reason": out.get("handover_reason"), "status": sess.get("status", "active"),
            "issues": out.get("issues", {}), "cart": cart, "latency_ms": round(latency, 1),
            "tool_calls": [{"agent": c["agent"], "name": c["name"], "args": c["args"], "ok": c["ok"],
                            "error": c["error"]} for c in ctx.calls],
            "_raw_calls": ctx.calls,
        }


def new_session_id(channel: str = "web") -> str:
    return f"{channel}:{uuid.uuid4()}"
