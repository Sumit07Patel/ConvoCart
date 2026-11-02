"""Agent service API (port 8000): web chat, shopper emails, store webhook, ops endpoints.

Run: uvicorn convocart.app:app --port 8000
"""
from __future__ import annotations

import hmac
import html
import json
import threading
import time
import uuid

from collections import defaultdict, deque

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import ops
from .agents.graph import ConvoCartAgent
from .agents.notify import send_order_confirmation
from .agents.recovery import run_recovery
from .channels.mail import EmailClient, unsubscribe_token, valid_address
from .commerce import CommerceError
from .config import get_settings
from .db import create_all
from .store.api import sign as store_sign

@asynccontextmanager
async def lifespan(_app):
    create_all()
    yield


app = FastAPI(title="ConvoCart agent service", version="1.0", lifespan=lifespan)
settings = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])

_agent: ConvoCartAgent | None = None
_agent_lock = threading.Lock()


def get_agent() -> ConvoCartAgent:
    global _agent
    with _agent_lock:
        if _agent is None:
            _agent = ConvoCartAgent()
        return _agent


def reset_agent() -> None:
    global _agent
    with _agent_lock:
        _agent = None




def require_admin(x_admin_token: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_admin_token, get_settings().admin_token):
        raise HTTPException(401, "bad admin token")


admin = [Depends(require_admin)]


# ------------------------------------------------------------------ web chat

class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = None
    customer_id: str | None = Field(None, description="Demo sign-in. A real deployment takes this from auth.")


@app.get("/health")
def health():
    st = get_settings()
    return {"ok": True, "provider": st.llm_provider, "store_mode": st.store_mode,
            "email": "dry_run" if EmailClient().dry_run else "live"}


class RateLimiter:
    """Sliding-window counters in memory. The demo runs as one process, so memory is enough."""

    def __init__(self):
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, limit: int, window_s: float) -> bool:
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


_limiter = RateLimiter()


def check_rate(request: Request) -> None:
    """Every call that reaches the model counts: per visitor (IP) and for the whole demo."""
    st = get_settings()
    forwarded = request.headers.get("x-forwarded-for", "")  # Render puts the visitor's IP first
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")
    if not _limiter.allow(f"ip:{ip}", st.chat_limit_per_visitor, 600):
        raise HTTPException(429, "You're sending messages very fast. Please wait a few minutes and try again.")
    if not _limiter.allow("site", st.chat_daily_limit, 86400):
        raise HTTPException(429, "The demo has used today's free model quota. Please come back tomorrow.")


@app.post("/chat", dependencies=[Depends(check_rate)])
def chat(body: ChatIn):
    sid = body.session_id or f"web:{uuid.uuid4()}"
    if not sid.startswith("web:"):
        raise HTTPException(400, "web sessions only")
    out = get_agent().handle_message(sid, body.message, channel="web", customer_id=body.customer_id)
    out.pop("_raw_calls", None)
    return out


@app.get("/demo/customers")
def demo_customers():
    agent = get_agent()
    out = []
    for cid in ("C0001", "C0002", "C0003", "C0004"):
        try:
            out.append(agent.commerce.get_customer(cid))
        except CommerceError:
            pass
    return out


@app.get("/sessions/{sid}")
def session(sid: str):
    s = ops.load_session(sid)
    cart = None
    if s.get("cart_id"):
        try:
            cart = get_agent().commerce.get_cart(s["cart_id"])
        except CommerceError:
            pass
    return {**s, "cart": cart}


@app.get("/sessions/{sid}/traces")
def traces(sid: str):
    return ops.get_traces(sid)


class AbandonIn(BaseModel):
    session_id: str
    minutes_ago: int = 120


@app.post("/demo/abandon", dependencies=[Depends(check_rate)])
def demo_abandon(body: AbandonIn):
    """Demo helper: pretend the shopper left `minutes_ago` minutes ago, then run the store's abandoned-cart job."""
    s = ops.load_session(body.session_id)
    if not s.get("cart_id"):
        raise HTTPException(400, "this session has no cart")
    agent = get_agent()
    agent.commerce.touch_cart(s["cart_id"], body.minutes_ago)
    return {"job": run_abandoned_cart_scan()}


def run_abandoned_cart_scan() -> dict:
    """The store's job. In http mode it runs inside the store service and calls our webhook;
    in local mode we run the same scan in-process and feed the same event handler."""
    agent = get_agent()
    st = get_settings()
    if st.store_mode == "http":
        return agent.commerce._req("POST", "/jobs/abandoned-carts")  # type: ignore[attr-defined]
    from .db import session_scope
    from .store import service as svc

    with session_scope() as s:
        carts = svc.find_abandoned_carts(s, agent.rules.abandon_after_minutes)
    results = []
    for cart in carts:
        results.append(process_store_event({"id": f"evt_{uuid.uuid4().hex[:16]}", "type": "cart.abandoned",
                                            "data": {"cart": cart}}))
        with session_scope() as s:
            svc.mark_abandoned_event_sent(s, cart["id"])
    return {"sent": [r.get("cart_id") for r in results], "results": results}


@app.post("/demo/pay/{sid}")
def demo_pay(sid: str):
    """Demo helper: simulate the payment provider confirming payment for this session's cart."""
    s = ops.load_session(sid)
    if not s.get("cart_id"):
        raise HTTPException(400, "no cart")
    try:
        order = get_agent().commerce.complete_payment(s["cart_id"])  # type: ignore[attr-defined]
    except CommerceError as e:
        raise HTTPException(400, e.message)
    # in http mode the store sends this event itself; here we feed the same handler in-process
    if get_settings().store_mode != "http":
        email = process_store_event({"id": f"evt_{uuid.uuid4().hex[:16]}", "type": "order.paid",
                                     "data": {"order": order, "cart_id": s["cart_id"]}})
    else:
        email = {"status": "sent_by_store"}
    return {"order": order, "email": email}


@app.get("/outbox")
def outbox(customer_id: str | None = None, limit: int = Query(50, le=200)):
    return ops.list_outbound(customer_id, limit)


# ------------------------------------------------------------------ store webhook

def process_store_event(event: dict) -> dict:
    """Every shopper email starts from a signed store event: cart.abandoned -> come-back email,
    order.paid -> order confirmation."""
    if ops.seen_event(event["id"], "store"):
        return {"status": "duplicate", "event_id": event["id"]}
    agent = get_agent()
    if event.get("type") == "cart.abandoned":
        return run_recovery(event["data"]["cart"]["id"], agent.commerce, agent.model, agent.rules)
    if event.get("type") == "order.paid":
        return send_order_confirmation(event["data"]["order"], event["data"].get("cart_id"), agent.commerce)
    return {"status": "ignored", "type": event.get("type")}


@app.post("/webhooks/store")
async def store_webhook(request: Request, background: BackgroundTasks,
                        x_store_signature: str = Header(default="")):
    raw = await request.body()
    if not hmac.compare_digest(x_store_signature, store_sign(raw, get_settings().store_webhook_secret)):
        raise HTTPException(401, "bad signature")
    event = json.loads(raw)
    background.add_task(process_store_event, event)
    return {"accepted": event.get("id")}


# ------------------------------------------------------------------ shopper emails

class ContactIn(BaseModel):
    email: str = Field(..., max_length=254)
    consent: bool = False


@app.post("/sessions/{sid}/contact")
def set_contact(sid: str, body: ContactIn):
    """The visitor's own address for this chat: order confirmation, and the come-back email if they agree."""
    if not sid.startswith("web:"):
        raise HTTPException(400, "web sessions only")
    if not valid_address(body.email):
        raise HTTPException(422, "that does not look like an email address")
    s = ops.load_session(sid)
    s["memory"]["contact"] = {"email": body.email.strip().lower(), "consent": body.consent}
    ops.save_session(s)
    return s["memory"]["contact"]


@app.get("/sessions/{sid}/emails")
def session_emails(sid: str):
    """Emails sent (or recorded in dry run) for this chat's cart, for the site's Emails tab."""
    s = ops.load_session(sid)
    return ops.list_outbound(cart_ids=[s["cart_id"]]) if s.get("cart_id") else []


@app.get("/unsubscribe", response_class=HTMLResponse)
def unsubscribe(email: str, token: str):
    if not hmac.compare_digest(token, unsubscribe_token(email)):
        raise HTTPException(400, "this unsubscribe link is not valid")
    ops.opt_out_email(email)
    customer = get_agent().commerce.find_customer_by_email(email)
    if customer:
        get_agent().commerce.set_opt_in(customer["id"], False)
    return HTMLResponse(f"<!doctype html><meta charset=utf-8><title>Unsubscribed</title>"
                        f"<body style='font-family:system-ui;max-width:32em;margin:4em auto;padding:0 1em'>"
                        f"<h1>You're unsubscribed</h1><p>{html.escape(email)} will get no more reminder emails from "
                        f"Kesar Lane. Order confirmations still arrive when you buy something.</p></body>")


# ------------------------------------------------------------------ ops (human team)

@app.get("/admin/handovers", dependencies=admin)
def handovers(status: str | None = "open"):
    return ops.list_handovers(status)


class HumanReply(BaseModel):
    text: str


@app.post("/admin/handovers/{hid}/reply", dependencies=admin)
def handover_reply(hid: int, body: HumanReply):
    h = next((x for x in ops.list_handovers(None) if x["id"] == hid), None)
    if not h:
        raise HTTPException(404, "no such handover")
    s = ops.load_session(h["session_id"])
    s["history"] = s.get("history", []) + [{"role": "assistant", "content": f"[Team] {body.text}"}]
    ops.save_session(s)
    return {"ok": True}


@app.post("/admin/handovers/{hid}/close", dependencies=admin)
def handover_close(hid: int):
    try:
        return ops.close_handover(hid)
    except KeyError:
        raise HTTPException(404, "no such handover")


@app.get("/admin/approvals", dependencies=admin)
def approvals(status: str | None = "pending"):
    return ops.list_approvals(status)


class Decision(BaseModel):
    approve: bool
    decided_by: str = "ops"


@app.post("/admin/approvals/{aid}", dependencies=admin)
def decide(aid: int, body: Decision):
    try:
        return ops.decide_approval(aid, body.approve, body.decided_by, get_agent().commerce)
    except KeyError:
        raise HTTPException(404, "no such approval")


@app.get("/admin/metrics", dependencies=admin)
def metrics():
    return ops.metrics()
