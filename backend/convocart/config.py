"""Central configuration. Every value can be overridden with an environment variable.

Business rules live here (and are enforced in code by the tools), never in a prompt.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from backend/ or the project root (the same file Docker Compose reads).
# Variables already set in the shell win over the file.
_HERE = Path(__file__).resolve()
for _env_file in (_HERE.parents[1] / ".env", _HERE.parents[2] / ".env"):
    if _env_file.is_file():
        load_dotenv(_env_file, override=False)


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Rules:
    """Guardrail rules from docs/GUARDRAILS.md. Change them here, not in prompts."""

    max_discount_pct: int = 10            # agent may never grant more than this
    discount_min_cart_value: int = 999    # rupees; below this no discount at all
    return_window_days: int = 15          # returns/exchanges allowed this long after delivery
    refunds_need_approval: bool = True    # every refund waits for a human
    max_agent_steps: int = 6              # model calls per specialist per turn
    recovery_max_messages_per_cart: int = 1
    recovery_cooldown_hours: int = 24     # at most one reminder per customer per day
    abandon_after_minutes: int = 60       # cart idle this long counts as abandoned


def load_rules() -> Rules:
    rules = Rules(
        max_discount_pct=_int("MAX_DISCOUNT_PCT", 10),
        discount_min_cart_value=_int("DISCOUNT_MIN_CART_VALUE", 999),
        return_window_days=_int("RETURN_WINDOW_DAYS", 15),
        refunds_need_approval=_bool("REFUNDS_NEED_APPROVAL", True),
        max_agent_steps=_int("MAX_AGENT_STEPS", 6),
        recovery_max_messages_per_cart=_int("RECOVERY_MAX_PER_CART", 1),
        recovery_cooldown_hours=_int("RECOVERY_COOLDOWN_HOURS", 24),
        abandon_after_minutes=_int("ABANDON_AFTER_MINUTES", 60),
    )
    # BREAK_RULE exists only to prove that CI catches a broken guardrail.
    # `BREAK_RULE=discount` raises the discount cap to 90% so the eval must go red.
    broken = os.environ.get("BREAK_RULE", "")
    if broken == "discount":
        rules = Rules(**{**rules.__dict__, "max_discount_pct": 90})
    elif broken == "refund":
        rules = Rules(**{**rules.__dict__, "refunds_need_approval": False})
    return rules


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL", "sqlite:///./convocart.db"))
    # "local" = call store functions in-process; "http" = call the store service over its API
    store_mode: str = field(default_factory=lambda: _env("STORE_MODE", "local"))
    store_url: str = field(default_factory=lambda: _env("STORE_URL", "http://localhost:9000"))
    store_api_key: str = field(default_factory=lambda: _env("STORE_API_KEY", "dev-store-key"))
    store_webhook_secret: str = field(default_factory=lambda: _env("STORE_WEBHOOK_SECRET", "dev-webhook-secret"))
    agent_url: str = field(default_factory=lambda: _env("AGENT_URL", "http://localhost:8000"))

    # Model provider: scripted | groq | openrouter | gemini | ollama
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "scripted"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", ""))
    llm_timeout_s: float = field(default_factory=lambda: float(_env("LLM_TIMEOUT_S", "60")))

    # Search
    embedder: str = field(default_factory=lambda: _env("EMBEDDER", "hashing"))  # hashing | fastembed
    vector_backend: str = field(default_factory=lambda: _env("VECTOR_BACKEND", "numpy"))  # numpy | pgvector

    # Outbound email (Gmail by default): the come-back email and the order confirmation.
    # Empty address or app password = dry run: mail goes to the outbox table only.
    email_address: str = field(default_factory=lambda: _env("EMAIL_ADDRESS", ""))
    email_app_password: str = field(default_factory=lambda: _env("EMAIL_APP_PASSWORD", "").replace(" ", ""))
    email_from: str = field(default_factory=lambda: _env("EMAIL_FROM", ""))  # shown sender, e.g. you+kesarlane@gmail.com
    email_smtp_host: str = field(default_factory=lambda: _env("EMAIL_SMTP_HOST", "smtp.gmail.com"))
    email_smtp_port: int = field(default_factory=lambda: _int("EMAIL_SMTP_PORT", 465))
    # A visitor can type any address into the demo, so each address gets at most this many emails a day.
    email_daily_limit_per_address: int = field(default_factory=lambda: _int("EMAIL_DAILY_LIMIT_PER_ADDRESS", 5))
    # Demo only: the seeded shoppers have undeliverable addresses, so link your real address to one of them.
    demo_linked_email: str = field(default_factory=lambda: _env("DEMO_LINKED_EMAIL", "").strip().lower())
    demo_linked_customer: str = field(default_factory=lambda: _env("DEMO_LINKED_CUSTOMER", "C0001"))
    # Public URLs used inside emails (unsubscribe link, link back to the chat). Render sets RENDER_EXTERNAL_URL.
    public_api_url: str = field(default_factory=lambda: _env("PUBLIC_API_URL", _env("RENDER_EXTERNAL_URL", "http://localhost:8000")).rstrip("/"))
    public_web_url: str = field(default_factory=lambda: _env("PUBLIC_WEB_URL", "http://localhost:5173").rstrip("/"))

    # The public demo spends free model quota: cap messages per visitor (per 10 minutes) and for the whole site (per day).
    chat_limit_per_visitor: int = field(default_factory=lambda: _int("CHAT_LIMIT_PER_VISITOR", 30))
    chat_daily_limit: int = field(default_factory=lambda: _int("CHAT_DAILY_LIMIT", 300))

    admin_token: str = field(default_factory=lambda: _env("ADMIN_TOKEN", "dev-admin-token"))
    cors_origins: str = field(default_factory=lambda: _env("CORS_ORIGINS", "*"))
    brand_name: str = "Kesar Lane"


def get_settings() -> Settings:
    return Settings()