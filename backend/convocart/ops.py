"""Agent-side persistence: sessions, traces, handovers, approvals, outbound messages."""
from __future__ import annotations

import time
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from .db import session_scope
from .ops_models import (Approval, ConversationOutcome, ConversationSession, EmailOptOut, Handover,
                         OutboundMessage, ProcessedEvent, TraceEvent)
from .store.models import utcnow


# ---------- sessions ----------

def load_session(session_id: str, channel: str = "web") -> dict:
    with session_scope() as s:
        row = s.get(ConversationSession, session_id)
        if not row:
            row = ConversationSession(id=session_id, channel=channel, history=[], memory={})
            s.add(row)
            s.flush()
        return {"id": row.id, "channel": row.channel, "customer_id": row.customer_id, "cart_id": row.cart_id,
                "language": row.language, "history": list(row.history or []), "memory": dict(row.memory or {}),
                "status": row.status}


def save_session(sess: dict) -> None:
    with session_scope() as s:
        row = s.get(ConversationSession, sess["id"])
        if not row:
            row = ConversationSession(id=sess["id"], channel=sess.get("channel", "web"))
            s.add(row)
        row.customer_id = sess.get("customer_id")
        row.cart_id = sess.get("cart_id")
        row.language = sess.get("language", "en")
        row.history = sess.get("history", [])[-30:]
        row.memory = sess.get("memory", {})
        row.status = sess.get("status", "active")
        row.updated_at = utcnow()


def set_session_status(session_id: str, status: str) -> None:
    with session_scope() as s:
        row = s.get(ConversationSession, session_id)
        if row:
            row.status = status


# ---------- tracing ----------

class Tracer:
    """Collects one turn's events; `flush()` writes them to trace_events (logs in Postgres)."""

    def __init__(self, session_id: str, trace_id: str | None = None):
        self.session_id = session_id
        self.trace_id = trace_id or str(uuid.uuid4())
        self.events: list[dict] = []
        self.t0 = time.perf_counter()

    def add(self, kind: str, agent: str, name: str = "", payload: dict | None = None, latency_ms: float = 0.0):
        self.events.append({"kind": kind, "agent": agent, "name": name, "payload": payload or {},
                            "latency_ms": round(latency_ms, 2), "t_ms": round((time.perf_counter() - self.t0) * 1000, 2)})

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.t0) * 1000

    def flush(self) -> None:
        with session_scope() as s:
            for e in self.events:
                s.add(TraceEvent(trace_id=self.trace_id, session_id=self.session_id, kind=e["kind"], agent=e["agent"],
                                 name=e["name"], payload=_jsonable(e["payload"]), latency_ms=e["latency_ms"]))


def _jsonable(x: Any):
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_jsonable(v) for v in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


def get_traces(session_id: str, limit: int = 200) -> list[dict]:
    with session_scope() as s:
        rows = s.scalars(select(TraceEvent).where(TraceEvent.session_id == session_id)
                         .order_by(TraceEvent.id.desc()).limit(limit)).all()
        return [{"trace_id": r.trace_id, "kind": r.kind, "agent": r.agent, "name": r.name, "payload": r.payload,
                 "latency_ms": r.latency_ms, "at": r.created_at.isoformat()} for r in reversed(rows)]


def record_outcome(session_id: str, trace_id: str, route: str, language: str, handed_over: bool, latency_ms: float,
                   note: str = "") -> None:
    with session_scope() as s:
        s.add(ConversationOutcome(session_id=session_id, trace_id=trace_id, route=route, language=language,
                                  handed_over=int(handed_over), latency_ms=latency_ms, note=note))


def metrics() -> dict:
    with session_scope() as s:
        sessions = s.scalar(select(func.count(func.distinct(ConversationOutcome.session_id)))) or 0
        handed = s.scalar(select(func.count(func.distinct(ConversationOutcome.session_id)))
                          .where(ConversationOutcome.handed_over == 1)) or 0
        lat = sorted(s.scalars(select(ConversationOutcome.latency_ms)).all())
        turns = len(lat)

        def pct(p):
            return round(lat[min(len(lat) - 1, int(p * len(lat)))], 1) if lat else None

        return {"sessions": sessions, "turns": turns, "sessions_handed_over": handed,
                "deflection_rate": round(1 - handed / sessions, 3) if sessions else None,
                "latency_ms_p50": pct(0.5), "latency_ms_p95": pct(0.95),
                "open_handovers": s.scalar(select(func.count()).select_from(Handover).where(Handover.status == "open")),
                "pending_approvals": s.scalar(select(func.count()).select_from(Approval)
                                              .where(Approval.status == "pending"))}


# ---------- handovers & approvals ----------

def create_handover(session_id: str, customer_id: str | None, reason: str, summary: dict) -> int:
    with session_scope() as s:
        h = Handover(session_id=session_id, customer_id=customer_id, reason=reason[:200], summary=_jsonable(summary))
        s.add(h)
        s.flush()
        return h.id


def list_handovers(status: str | None = "open") -> list[dict]:
    with session_scope() as s:
        q = select(Handover).order_by(Handover.id.desc())
        if status:
            q = q.where(Handover.status == status)
        return [{"id": h.id, "session_id": h.session_id, "customer_id": h.customer_id, "reason": h.reason,
                 "summary": h.summary, "status": h.status, "created_at": h.created_at.isoformat()}
                for h in s.scalars(q).all()]


def close_handover(handover_id: int) -> dict:
    with session_scope() as s:
        h = s.get(Handover, handover_id)
        if not h:
            raise KeyError(handover_id)
        h.status = "closed"
        sid = h.session_id
    set_session_status(sid, "active")
    return {"id": handover_id, "status": "closed"}


def create_approval(kind: str, ref_id: str, customer_id: str, amount: int, details: dict) -> int:
    with session_scope() as s:
        a = Approval(kind=kind, ref_id=ref_id, customer_id=customer_id, amount=amount, details=_jsonable(details))
        s.add(a)
        s.flush()
        return a.id


def list_approvals(status: str | None = "pending") -> list[dict]:
    with session_scope() as s:
        q = select(Approval).order_by(Approval.id.desc())
        if status:
            q = q.where(Approval.status == status)
        return [{"id": a.id, "kind": a.kind, "ref_id": a.ref_id, "customer_id": a.customer_id, "amount": a.amount,
                 "details": a.details, "status": a.status, "decided_by": a.decided_by,
                 "created_at": a.created_at.isoformat()} for a in s.scalars(q).all()]


def decide_approval(approval_id: int, approve: bool, decided_by: str, commerce) -> dict:
    with session_scope() as s:
        a = s.get(Approval, approval_id)
        if not a:
            raise KeyError(approval_id)
        if a.status != "pending":
            return {"id": a.id, "status": a.status}
        a.status = "approved" if approve else "rejected"
        a.decided_by = decided_by
        a.decided_at = utcnow()
        ref, status = a.ref_id, a.status
    commerce.set_return_status(ref, "approved" if approve else "rejected")
    return {"id": approval_id, "status": status}


# ---------- outbound messages ----------

def record_outbound(channel: str, to: str, customer_id: str | None, purpose: str, body: str, status: str,
                    detail: str = "", cart_id: str | None = None, subject: str = "") -> int:
    with session_scope() as s:
        m = OutboundMessage(channel=channel, to=to, customer_id=customer_id, purpose=purpose, body=body,
                            status=status, detail=detail[:2000], cart_id=cart_id, subject=subject[:200])
        s.add(m)
        s.flush()
        return m.id


def recovery_counts(to: str, cart_id: str, cooldown_hours: int) -> tuple[int, int]:
    """(# come-back emails already sent for this cart, # sent to this address inside the cooldown)."""
    since = utcnow() - timedelta(hours=cooldown_hours)
    sent = ["sent", "dry_run"]
    with session_scope() as s:
        per_cart = s.scalar(select(func.count()).select_from(OutboundMessage).where(
            OutboundMessage.purpose == "cart_recovery", OutboundMessage.cart_id == cart_id,
            OutboundMessage.status.in_(sent))) or 0
        recent = s.scalar(select(func.count()).select_from(OutboundMessage).where(
            OutboundMessage.purpose == "cart_recovery", OutboundMessage.to == to,
            OutboundMessage.status.in_(sent), OutboundMessage.created_at >= since)) or 0
    return per_cart, recent


def emails_in_last_day(to: str) -> int:
    """Emails sent (or recorded in dry run) to one address in the last 24 h."""
    since = utcnow() - timedelta(hours=24)
    with session_scope() as s:
        return s.scalar(select(func.count()).select_from(OutboundMessage).where(
            OutboundMessage.to == to, OutboundMessage.status.in_(["sent", "dry_run"]),
            OutboundMessage.created_at >= since)) or 0


def list_outbound(customer_id: str | None = None, limit: int = 50, cart_ids: list[str] | None = None) -> list[dict]:
    with session_scope() as s:
        q = select(OutboundMessage).order_by(OutboundMessage.id.desc()).limit(limit)
        if customer_id:
            q = q.where(OutboundMessage.customer_id == customer_id)
        if cart_ids is not None:
            q = q.where(OutboundMessage.cart_id.in_(cart_ids))
        return [{"id": m.id, "channel": m.channel, "to": m.to, "customer_id": m.customer_id, "purpose": m.purpose,
                 "subject": m.subject, "cart_id": m.cart_id, "body": m.body, "status": m.status, "detail": m.detail,
                 "created_at": m.created_at.isoformat()} for m in s.scalars(q).all()]


# ---------- email consent ----------

def opt_out_email(address: str) -> None:
    with session_scope() as s:
        if not s.get(EmailOptOut, address.strip().lower()):
            s.add(EmailOptOut(address=address.strip().lower()))


def email_opted_out(address: str) -> bool:
    with session_scope() as s:
        return s.get(EmailOptOut, address.strip().lower()) is not None


def session_for_cart(cart_id: str) -> dict | None:
    """The chat session that built this cart (for its contact email and the link back to the chat)."""
    with session_scope() as s:
        row = s.scalar(select(ConversationSession).where(ConversationSession.cart_id == cart_id)
                       .order_by(ConversationSession.updated_at.desc()).limit(1))
        sid = row.id if row else None
    return load_session(sid) if sid else None


def seen_event(event_id: str, source: str) -> bool:
    """True if already processed; otherwise records it and returns False."""
    from sqlalchemy.exc import IntegrityError

    try:
        with session_scope() as s:
            if s.get(ProcessedEvent, event_id):
                return True
            s.add(ProcessedEvent(id=event_id, source=source))
        return False
    except IntegrityError:  # a concurrent duplicate delivery won the insert
        return True
