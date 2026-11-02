"""Shopper emails: who gets them, the consent and frequency checks, and the order confirmation.

Shoppers talk to the agent only in the web chat. Email is one-way and has two kinds:
- the come-back email for a left cart (marketing: needs consent, carries an unsubscribe link), see recovery.py
- the order confirmation after payment (transactional: written from the order record, no model involved)
Every decision, including blocked ones, is written to outbound_messages for audit.
"""
from __future__ import annotations

from urllib.parse import quote

from .. import ops
from ..channels.mail import EmailClient, address_for, unsubscribe_link, valid_address
from ..commerce import Commerce, CommerceError
from ..config import get_settings
from .compose import compose_order_confirmation
from .language import t


def recipient(customer: dict | None, session: dict | None) -> tuple[str, bool]:
    """(address, marketing consent). An address the visitor typed into the chat wins over the one on file."""
    contact = (session or {}).get("memory", {}).get("contact") or {}
    if contact.get("email") and valid_address(contact["email"]):
        return contact["email"].strip().lower(), bool(contact.get("consent"))
    if customer:
        return address_for(customer), bool(customer.get("reminder_opt_in"))
    return "", False


def chat_link(session_id: str | None) -> str:
    """Link back to the website chat; with a session id the chat reopens with the same cart."""
    base = f"{get_settings().public_web_url}/"
    return f"{base}?resume={quote(session_id)}#assistant" if session_id else f"{base}#assistant"


def deliver(to: str, customer_id: str | None, purpose: str, subject: str, body: str, cart_id: str | None,
            lang: str, marketing: bool, mailer: EmailClient | None = None) -> tuple[str, str, str]:
    """Send one email through the checks. Returns (status, detail, final body)."""
    if marketing and ops.email_opted_out(to):
        status, detail = "blocked", "unsubscribed"
    elif ops.emails_in_last_day(to) >= get_settings().email_daily_limit_per_address:
        status, detail = "blocked", "daily_limit"
    else:
        unsub = unsubscribe_link(to) if marketing else ""
        if marketing:
            body = f"{body}\n\n{t('unsubscribe_line', lang, link=unsub)}"
        status, detail = (mailer or EmailClient()).send(to, subject, body, unsubscribe=unsub)
    ops.record_outbound("email", to, customer_id, purpose, body, status, detail, cart_id, subject=subject)
    return status, detail, body


def send_order_confirmation(order: dict, cart_id: str | None, commerce: Commerce,
                            mailer: EmailClient | None = None) -> dict:
    if cart_id and any(m["purpose"] == "order_confirmation" for m in ops.list_outbound(cart_ids=[cart_id])):
        return {"order_id": order["id"], "status": "duplicate", "detail": "already confirmed"}
    try:
        customer = commerce.get_customer(order["customer_id"])
    except CommerceError:
        customer = None
    session = ops.session_for_cart(cart_id) if cart_id else None
    to, _ = recipient(customer, session)
    if not to:
        return {"order_id": order["id"], "status": "skipped", "detail": "no address"}
    lang = (session or {}).get("language") or (customer or {}).get("preferred_language", "en")
    name = (customer or {}).get("name", "there")
    body = compose_order_confirmation(order, name, lang, chat_link((session or {}).get("id")))
    status, detail, body = deliver(to, order["customer_id"], "order_confirmation", t("order_subject", lang, id=order["id"]),
                                   body, cart_id, lang, marketing=False, mailer=mailer)
    return {"order_id": order["id"], "to": to, "status": status, "detail": detail, "body": body}
