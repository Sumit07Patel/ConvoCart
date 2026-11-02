"""Outbound email (SMTP): the come-back email for a left cart and the order confirmation.

Shoppers talk to the agent only in the web chat; email is one-way. Works with a Gmail account and an
app password. Without EMAIL_ADDRESS / EMAIL_APP_PASSWORD the client runs in dry-run mode and only
records mail in the outbound_messages table, so the flow is testable offline.

Safety:
- Mail is only ever sent to deliverable addresses. The seeded shoppers use @example.invalid, which
  is never sent to; their mail is recorded as dry run instead.
- Each address gets at most EMAIL_DAILY_LIMIT_PER_ADDRESS emails a day, so a visitor who types a
  stranger's address into the demo cannot turn the shop into a spammer.
- Marketing mail (the come-back email) carries a one-click unsubscribe link.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import smtplib
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from ..config import Settings, get_settings

UNDELIVERABLE = (".invalid", ".test", ".example", ".localhost", "@example.com", "@example.org", "@example.net")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_address(address: str) -> bool:
    return bool(EMAIL_RE.match(address.strip()))


def deliverable(address: str) -> bool:
    a = address.strip().lower()
    return valid_address(a) and not a.endswith(UNDELIVERABLE)


def to_plain(text: str) -> str:
    """Models write Markdown; a plain-text email should not show ** or # or [link](url)."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"\1", text, flags=re.M)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1: \2", text)
    return re.sub(r"[ \t]+$", "", text, flags=re.M).replace("*", "")


def unsubscribe_token(address: str, st: Settings | None = None) -> str:
    st = st or get_settings()
    return hmac.new(st.admin_token.encode(), address.strip().lower().encode(), hashlib.sha256).hexdigest()[:32]


def unsubscribe_link(address: str, st: Settings | None = None) -> str:
    st = st or get_settings()
    from urllib.parse import urlencode
    return f"{st.public_api_url}/unsubscribe?{urlencode({'email': address, 'token': unsubscribe_token(address, st)})}"


def address_for(customer: dict, st: Settings | None = None) -> str:
    """Where mail for this shopper goes: the demo-linked real address, or the (simulated) one on file."""
    st = st or get_settings()
    if st.demo_linked_email and customer.get("id") == st.demo_linked_customer:
        return st.demo_linked_email
    return customer.get("email", "")


class EmailClient:
    def __init__(self, settings: Settings | None = None):
        self.st = settings or get_settings()

    @property
    def dry_run(self) -> bool:
        return not (self.st.email_address and self.st.email_app_password)

    @property
    def from_address(self) -> str:
        return self.st.email_from or self.st.email_address

    def send(self, to: str, subject: str, body: str, unsubscribe: str = "") -> tuple[str, str]:
        if self.dry_run:
            return "dry_run", "no EMAIL_ADDRESS / EMAIL_APP_PASSWORD set; recorded only"
        if not deliverable(to):
            return "dry_run", f"{to} is a simulated address; recorded only"
        m = EmailMessage()
        m["From"] = formataddr((self.st.brand_name, self.from_address))
        m["To"] = to
        m["Subject"] = subject
        m["Message-ID"] = make_msgid(domain=self.st.email_address.split("@")[-1])
        m["Auto-Submitted"] = "auto-generated"
        if unsubscribe:
            m["List-Unsubscribe"] = f"<{unsubscribe}>"
        m.set_content(to_plain(body))
        err = ""
        for attempt in range(3):  # Gmail sometimes drops a connection; a lost email is worse than a short wait
            try:
                with smtplib.SMTP_SSL(self.st.email_smtp_host, self.st.email_smtp_port, timeout=30) as s:
                    s.login(self.st.email_address, self.st.email_app_password)
                    s.send_message(m)
                return "sent", m["Message-ID"]
            except smtplib.SMTPAuthenticationError as e:
                return "failed", f"smtp login: {e}"[:500]
            except (smtplib.SMTPException, OSError) as e:
                err = f"smtp: {e}"
                time.sleep(2 * (attempt + 1))
        return "failed", err[:500]
