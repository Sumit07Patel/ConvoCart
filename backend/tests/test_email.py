import re

from convocart.channels import mail
from convocart.channels.mail import EmailClient, address_for, deliverable, to_plain, unsubscribe_token


def _cart(client, customer="C0003", message="add the first one"):
    r = client.post("/chat", json={"message": "show me compact umbrellas", "customer_id": customer}).json()
    client.post("/chat", json={"message": message, "session_id": r["session_id"], "customer_id": customer})
    return r["session_id"]


def _abandon(client, sid):
    return client.post("/demo/abandon", json={"session_id": sid}).json()["job"]["results"][0]


def test_simulated_addresses_are_never_delivered():
    assert not deliverable("c0001@example.invalid") and not deliverable("x@example.com") and not deliverable("nope")
    assert deliverable("someone@gmail.com")


def test_markdown_becomes_plain_text():
    assert to_plain("Order **ORD-1** is __shipped__\n## Next\nPay [here](https://x.in/p)  ") == \
        "Order ORD-1 is shipped\nNext\nPay here: https://x.in/p"


def test_come_back_email_links_to_chat_and_can_unsubscribe(client):
    sid = _cart(client)
    res = _abandon(client, sid)
    assert res["status"] == "dry_run" and res["to"] == "c0003@example.invalid"
    assert "resume=web%3A" in res["body"] and "/unsubscribe?" in res["body"]
    sent = client.get(f"/sessions/{sid}/emails").json()
    assert sent[0]["purpose"] == "cart_recovery" and sent[0]["subject"]


def test_bargained_discount_is_the_only_percentage(client):
    r = client.post("/chat", json={"message": "show me sarees", "customer_id": "C0004"}).json()
    sid = r["session_id"]
    client.post("/chat", json={"message": "add the first one", "session_id": sid, "customer_id": "C0004"})
    client.post("/chat", json={"message": "can I get 10% off?", "session_id": sid, "customer_id": "C0004"})
    assert client.get(f"/sessions/{sid}").json()["cart"]["discount_pct"] == 10
    res = _abandon(client, sid)
    assert "10%" in res["subject"] and {int(p) for p in re.findall(r"(\d+)\s*%", re.sub(r"https?://\S+", "", res["body"]))} == {10}
    client.post("/chat", json={"message": "checkout", "session_id": sid, "customer_id": "C0004"})
    confirmation = client.post(f"/demo/pay/{sid}").json()["email"]["body"]
    assert "Discount: -₹" in confirmation  # the items add up to the total paid


def test_visitor_address_and_consent(client):
    sid = _cart(client, customer="C0002")  # C0002 never opted in
    assert client.post(f"/sessions/{sid}/contact", json={"email": "not-an-email", "consent": True}).status_code == 422
    client.post(f"/sessions/{sid}/contact", json={"email": "Visitor@Gmail.com", "consent": False})
    assert _abandon(client, sid)["detail"] == "no_consent"

    sid2 = _cart(client, customer="C0002")
    client.post(f"/sessions/{sid2}/contact", json={"email": "visitor2@gmail.com", "consent": True})
    res = _abandon(client, sid2)
    assert res["to"] == "visitor2@gmail.com" and res["status"] == "dry_run"  # tests never have mail credentials


def test_order_confirmation_after_payment(client):
    sid = _cart(client, customer="C0004")
    client.post(f"/sessions/{sid}/contact", json={"email": "buyer@gmail.com", "consent": False})
    client.post("/chat", json={"message": "checkout", "session_id": sid, "customer_id": "C0004"})
    paid = client.post(f"/demo/pay/{sid}").json()
    email = paid["email"]
    assert email["to"] == "buyer@gmail.com" and paid["order"]["id"] in email["body"]
    assert f"₹{paid['order']['total']}" in email["body"] and "unsubscribe" not in email["body"].lower()
    kinds = [m["purpose"] for m in client.get(f"/sessions/{sid}/emails").json()]
    assert kinds.count("order_confirmation") == 1


def test_unsubscribe_stops_come_back_emails(client):
    bad = client.get("/unsubscribe", params={"email": "c0005@example.invalid", "token": "nope"})
    assert bad.status_code == 400
    ok = client.get("/unsubscribe", params={"email": "c0005@example.invalid",
                                            "token": unsubscribe_token("c0005@example.invalid")})
    assert ok.status_code == 200 and "unsubscribed" in ok.text
    from convocart.commerce import LocalCommerce
    assert LocalCommerce().get_customer("C0005")["reminder_opt_in"] is False


def test_daily_limit_per_address(client, monkeypatch):
    monkeypatch.setenv("EMAIL_DAILY_LIMIT_PER_ADDRESS", "1")
    sid = _cart(client, customer="C0002")
    client.post(f"/sessions/{sid}/contact", json={"email": "limit@gmail.com", "consent": True})
    assert _abandon(client, sid)["status"] == "dry_run"
    client.post("/chat", json={"message": "checkout", "session_id": sid, "customer_id": "C0002"})
    assert client.post(f"/demo/pay/{sid}").json()["email"]["detail"] == "daily_limit"


def test_demo_link_maps_shopper_to_real_address(db, monkeypatch):
    from convocart.commerce import LocalCommerce

    monkeypatch.setenv("DEMO_LINKED_EMAIL", "Me@Gmail.com")
    monkeypatch.setenv("DEMO_LINKED_CUSTOMER", "C0001")
    commerce = LocalCommerce()
    assert address_for(commerce.get_customer("C0001")) == "me@gmail.com"
    assert address_for(commerce.get_customer("C0002")) == "c0002@example.invalid"


def test_smtp_message(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def login(self, *a): pass
        def send_message(self, m): sent.append(m)

    monkeypatch.setenv("EMAIL_ADDRESS", "shop@gmail.com")
    monkeypatch.setenv("EMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.setenv("EMAIL_FROM", "shop+kesarlane@gmail.com")
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSMTP)
    client = EmailClient()
    assert client.send("c0001@example.invalid", "hi", "x")[0] == "dry_run" and not sent
    status, _ = client.send("me@gmail.com", "Your cart", "Your **umbrella** is waiting", unsubscribe="https://x/u")
    m = sent[0]
    assert status == "sent" and "shop+kesarlane@gmail.com" in m["From"] and m["List-Unsubscribe"] == "<https://x/u>"
    assert m["Auto-Submitted"] == "auto-generated" and "**" not in m.get_content()
