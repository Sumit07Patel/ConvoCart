"""Agent-layer tables: sessions, traces, handovers, approvals, outbound messages.

Kept separate from the store's tables so the agent layer could move to its own database.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .store.models import utcnow


class ConversationSession(Base):
    __tablename__ = "agent_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # web:<uuid>
    channel: Mapped[str] = mapped_column(String(16))
    customer_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cart_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    language: Mapped[str] = mapped_column(String(12), default="en")
    history: Mapped[list] = mapped_column(JSON, default=list)   # [{role, content}] user/assistant only
    memory: Mapped[dict] = mapped_column(JSON, default=dict)    # last_search ids, last_order etc.
    status: Mapped[str] = mapped_column(String(16), default="active")  # active|with_human
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TraceEvent(Base):
    __tablename__ = "trace_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # route|llm|tool|guard|reply|handover|error
    agent: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Handover(Base):
    __tablename__ = "handovers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reason: Mapped[str] = mapped_column(String(200))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)  # context for the human agent
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24))  # refund
    ref_id: Mapped[str] = mapped_column(String(32))  # return request id
    customer_id: Mapped[str] = mapped_column(String(16))
    amount: Mapped[int] = mapped_column(Integer, default=0)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected
    decided_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OutboundMessage(Base):
    """Every email sent to a shopper (come-back emails, order confirmations), including blocked ones.
    In dry-run mode (no mail credentials) this table *is* the delivery channel."""

    __tablename__ = "outbound_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(16))
    to: Mapped[str] = mapped_column(String(254), index=True)
    customer_id: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    purpose: Mapped[str] = mapped_column(String(24))  # cart_recovery|order_confirmation
    subject: Mapped[str] = mapped_column(String(200), default="")
    cart_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))  # sent|dry_run|failed|blocked
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailOptOut(Base):
    """Addresses that used the unsubscribe link: no more marketing email (order confirmations still go)."""

    __tablename__ = "email_opt_outs"
    address: Mapped[str] = mapped_column(String(254), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProcessedEvent(Base):
    """Idempotency for store webhooks (the store retries failed deliveries)."""

    __tablename__ = "processed_events"
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ConversationOutcome(Base):
    """One row per finished turn, used for deflection numbers."""

    __tablename__ = "conversation_outcomes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    trace_id: Mapped[str] = mapped_column(String(36))
    route: Mapped[str] = mapped_column(String(24))
    language: Mapped[str] = mapped_column(String(12))
    handed_over: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
