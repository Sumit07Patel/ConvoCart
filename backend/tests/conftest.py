import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Tests never call a real model or send real mail, whatever .env or the shell says.
# (config loads .env without overriding, so these values win.)
os.environ["LLM_PROVIDER"] = "scripted"
for var in ("LLM_MODEL", "LLM_API_KEY", "EMAIL_ADDRESS", "EMAIL_APP_PASSWORD", "EMAIL_FROM", "DEMO_LINKED_EMAIL"):
    os.environ[var] = ""
os.environ["CHAT_LIMIT_PER_VISITOR"] = "100000"  # the suite sends many messages from one test client
os.environ.setdefault("STORE_MODE", "local")
os.environ.pop("BREAK_RULE", None)


@pytest.fixture(scope="module")
def db():
    from eval.common import fresh_db

    url = fresh_db("pytest")
    import convocart.app as app_mod
    app_mod.reset_agent()
    yield url


@pytest.fixture()
def agent(db):
    from convocart.agents.graph import ConvoCartAgent

    return ConvoCartAgent()


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient

    import convocart.app as app_mod
    app_mod.reset_agent()
    with TestClient(app_mod.app) as c:
        yield c
