import json

from convocart.config import get_settings
from convocart.store.api import sign as store_sign


def test_chat_end_to_end(client):
    r = client.post("/chat", json={"message": "monsoon ke liye halki waterproof jacket dikhao", "customer_id": "C0001"})
    body = r.json()
    assert r.status_code == 200 and body["route"] == "advisor" and body["language"] == "hinglish"
    sid = body["session_id"]
    size = next(c for c in body["tool_calls"] if c["name"] == "search_products")
    r = client.post("/chat", json={"message": "pehla wala size M", "session_id": sid, "customer_id": "C0001"})
    assert r.json()["cart"]["items"], r.json()
    r = client.post("/chat", json={"message": "ORD-10002 kab aayega?", "session_id": sid, "customer_id": "C0001"})
    assert r.json()["route"] == "support" and "ORD-10002" in r.json()["reply"]
    assert client.get(f"/sessions/{sid}/traces").json()


def test_handover_and_admin(client):
    r = client.post("/chat", json={"message": "I want to speak to a real person", "customer_id": "C0003"})
    body = r.json()
    assert body["handover"] and body["status"] == "with_human"
    r2 = client.post("/chat", json={"message": "hello?", "session_id": body["session_id"], "customer_id": "C0003"})
    assert r2.json()["route"] == "human" and not r2.json()["handover"]
    h = client.get("/admin/handovers", headers={"x-admin-token": get_settings().admin_token}).json()
    mine = [x for x in h if x["session_id"] == body["session_id"]]
    assert mine and mine[0]["summary"]["last_messages"]
    assert client.get("/admin/handovers").status_code == 401
    client.post(f"/admin/handovers/{mine[0]['id']}/close", headers={"x-admin-token": get_settings().admin_token})
    r3 = client.post("/chat", json={"message": "show me sneakers", "session_id": body["session_id"],
                                    "customer_id": "C0003"})
    assert r3.json()["route"] == "advisor"


def test_chat_rate_limit_per_visitor(client, monkeypatch):
    import convocart.app as app_mod

    monkeypatch.setattr(app_mod, "_limiter", app_mod.RateLimiter())
    monkeypatch.setenv("CHAT_LIMIT_PER_VISITOR", "2")
    send = lambda ip: client.post("/chat", json={"message": "hi"}, headers={"x-forwarded-for": ip})
    assert send("1.1.1.1").status_code == 200 and send("1.1.1.1").status_code == 200
    blocked = send("1.1.1.1")
    assert blocked.status_code == 429 and "wait" in blocked.json()["detail"]
    assert send("2.2.2.2").status_code == 200  # another visitor is not affected


def test_store_webhook_signature(client):
    event = {"id": "evt_test_sig", "type": "cart.abandoned", "data": {"cart": {"id": "nope"}}}
    raw = json.dumps(event).encode()
    assert client.post("/webhooks/store", content=raw, headers={"x-store-signature": "sha256=bad"}).status_code == 401
    good = client.post("/webhooks/store", content=raw,
                       headers={"x-store-signature": store_sign(raw, get_settings().store_webhook_secret)})
    assert good.status_code == 200


def test_abandoned_cart_recovery_consent_and_limit(client):
    # C0001 opted in
    r = client.post("/chat", json={"message": "show me compact umbrellas", "customer_id": "C0001"}).json()
    sid = r["session_id"]
    client.post("/chat", json={"message": "add the first one", "session_id": sid, "customer_id": "C0001"})
    job = client.post("/demo/abandon", json={"session_id": sid}).json()["job"]
    res = job["results"][0]
    assert res["status"] in ("dry_run", "blocked"), res
    if res["status"] == "dry_run":
        assert "unsubscribe" in res["body"].lower()
    # second run: same cart, must not message again
    job2 = client.post("/demo/abandon", json={"session_id": sid}).json()["job"]
    assert not job2["results"] or job2["results"][0]["status"] in ("blocked", "skipped", "duplicate")

    # C0002 did not opt in
    r = client.post("/chat", json={"message": "show me compact umbrellas", "customer_id": "C0002"}).json()
    client.post("/chat", json={"message": "add the first one", "session_id": r["session_id"], "customer_id": "C0002"})
    job3 = client.post("/demo/abandon", json={"session_id": r["session_id"]}).json()["job"]
    assert job3["results"][0]["status"] == "blocked" and job3["results"][0]["detail"] == "no_consent"


def test_http_commerce_matches_local(db):
    """The agent layer can talk to the store over HTTP with the same results."""
    from fastapi.testclient import TestClient

    from convocart.commerce import HttpCommerce, LocalCommerce
    from convocart.store.api import app as store_app

    with TestClient(store_app) as sc:
        http = HttpCommerce(client=sc, api_key=get_settings().store_api_key)
        assert http.get_order("ORD-10001") == LocalCommerce().get_order("ORD-10001")
        cart = http.create_cart("C0001")
        v = http.get_product("KL-RJ-003")["variants"][0]
        cart = http.add_to_cart(cart["id"], v["id"], 1)
        assert cart["items"][0]["unit_price"] == LocalCommerce().get_product("KL-RJ-003")["price"]
        try:
            http.get_order("ORD-99999")
            raise AssertionError("expected error")
        except Exception as e:
            assert getattr(e, "code", "") == "order_not_found"
        assert sc.get("/products", headers={"x-api-key": "wrong"}).status_code == 401
