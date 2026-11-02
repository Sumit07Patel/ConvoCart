"""Shared helpers for eval scripts: a fresh seeded database per run."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def fresh_db(name: str = "eval") -> str:
    """Point the app at a new seeded SQLite file (unless DATABASE_URL is already Postgres)."""
    from convocart.db import create_all, reset_caches, session_scope
    from convocart.search.index import reset_search
    from convocart.store.seed import seed

    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgres"):
        path = Path(tempfile.gettempdir()) / f"convocart_{name}_{os.getpid()}.db"
        for suffix in ("", "-wal", "-shm"):
            Path(f"{path}{suffix}").unlink(missing_ok=True)
        url = f"sqlite:///{path}"
        os.environ["DATABASE_URL"] = url
    reset_caches()
    reset_search()
    from convocart.db import Base, get_engine
    from convocart.store import models  # noqa: F401
    from convocart import ops_models  # noqa: F401

    Base.metadata.drop_all(get_engine())
    create_all()
    with session_scope() as s:
        seed(s)
    return url


def matches(p: dict, expect: dict) -> bool:
    if "ids" in expect:
        return p["product_id"] in expect["ids"] if "product_id" in p else p["id"] in expect["ids"]
    cat = expect.get("category")
    if cat and p["category"] not in ([cat] if isinstance(cat, str) else cat):
        return False
    tags = set(p["tags"])
    if expect.get("tags_any") and not tags & set(expect["tags_any"]):
        return False
    if expect.get("tags_all") and not set(expect["tags_all"]) <= tags:
        return False
    if expect.get("max_price") is not None and p["price"] > expect["max_price"]:
        return False
    if expect.get("min_price") is not None and p["price"] < expect["min_price"]:
        return False
    if expect.get("gender") and p.get("gender") not in (expect["gender"], "unisex"):
        return False
    return True
