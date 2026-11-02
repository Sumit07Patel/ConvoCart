"""Phase 4: the rules live in the tools. These tests call the tools directly, no model involved."""
import uuid

from convocart.commerce import LocalCommerce
from convocart.config import load_rules
from convocart.ops import Tracer
from convocart.tools.core import ToolContext, run_tool, tool_schemas


def ctx(customer="C0001", agent="advisor"):
    sid = f"test:{uuid.uuid4()}"
    return ToolContext(commerce=LocalCommerce(), rules=load_rules(), session={"id": sid, "customer_id": customer,
                                                                              "memory": {}},
                       tracer=Tracer(sid), agent=agent)


def test_search_then_add_uses_store_price(db):
    c = ctx()
    res = run_tool(c, "search_products", {"query": "waterproof rain jacket"})
    assert res["ok"] and res["results"]
    first = res["results"][0]
    size = first["available_sizes"][0]
    added = run_tool(c, "add_to_cart", {"option": 1, "size": size})
    assert added["ok"], added
    store_price = LocalCommerce().get_product(first["product_id"])["price"]
    assert added["cart"]["items"][0]["unit_price"] == store_price


def test_add_needs_size(db):
    c = ctx()
    run_tool(c, "search_products", {"query": "linen kurta"})
    res = run_tool(c, "add_to_cart", {"option": 1})
    assert not res["ok"] and res["error"] == "need_size" and res["in_stock_sizes"]


def _cart_with(c, pid="KL-RJ-003", size="M"):
    res = run_tool(c, "add_to_cart", {"product_id": pid, "size": size})
    assert res["ok"], res
    return res["cart"]


def test_discount_cap_enforced(db):
    c = ctx()
    _cart_with(c)
    over = run_tool(c, "apply_discount", {"percent": 90})
    assert not over["ok"] and over["error"] == "over_limit" and over["allowed_max"] == 10
    assert LocalCommerce().get_cart(c.session["cart_id"])["discount_pct"] == 0
    ok = run_tool(c, "apply_discount", {"percent": 10})
    assert ok["ok"] and ok["cart"]["discount_pct"] == 10


def test_discount_needs_minimum_cart(db):
    c = ctx()
    _cart_with(c, "KL-SC-001", "ONE")  # cheap socks
    cart = LocalCommerce().get_cart(c.session["cart_id"])
    res = run_tool(c, "apply_discount", {"percent": 5})
    if cart["subtotal"] < 999:
        assert res["error"] == "below_minimum"


def test_discount_invalid_args_rejected(db):
    c = ctx()
    assert run_tool(c, "apply_discount", {"percent": "lots"})["error"] == "invalid_arguments"
    assert run_tool(c, "apply_discount", {"percent": 500})["error"] == "invalid_arguments"


def test_other_customers_order_is_not_found(db):
    c = ctx("C0001", "support")
    res = run_tool(c, "get_order", {"order_id": "ORD-10004"})  # belongs to C0002
    assert not res["ok"] and res["error"] == "order_not_found"
    assert "customer_id" not in str(res) and "Kochi" not in str(res)
    assert any(e["name"] == "ownership_denied" for e in c.tracer.events)


def test_order_lookup_requires_login(db):
    c = ctx(None, "support")
    assert run_tool(c, "get_order", {"order_id": "ORD-10001"})["error"] == "need_login"


def test_refund_waits_for_approval(db):
    from convocart import ops

    c = ctx("C0004", "support")
    res = run_tool(c, "create_return", {"order_id": "ORD-10006", "kind": "refund", "reason": "too small"})
    assert res["ok"] and res["return_request"]["status"] == "pending_approval"
    pending = [a for a in ops.list_approvals("pending") if a["ref_id"] == res["return_request"]["id"]]
    assert len(pending) == 1
    decided = ops.decide_approval(pending[0]["id"], True, "test", LocalCommerce())
    assert decided["status"] == "approved"
    assert LocalCommerce().get_order("ORD-10006")["status"] == "returned"


def test_return_window(db):
    c = ctx("C0001", "support")
    res = run_tool(c, "create_return", {"order_id": "ORD-10003", "kind": "return", "reason": "x"})
    assert res["error"] == "outside_window"
    res = run_tool(c, "create_return", {"order_id": "ORD-10002", "kind": "return", "reason": "x"})
    assert res["error"] == "not_delivered"


def test_review_injection_is_flagged(db):
    c = ctx()
    res = run_tool(c, "get_product_details", {"product_id": "KL-RJ-001"})
    assert res["ok"]
    assert any(r.get("possible_injection") for r in res["reviews"])
    assert all("untrusted_text" in r for r in res["reviews"])


def test_agent_cannot_use_other_agents_tools(db):
    c = ctx(agent="advisor")
    assert run_tool(c, "create_return", {"order_id": "ORD-10001", "kind": "refund", "reason": "x"})["error"] == "unknown_tool"


def test_tool_schemas_are_valid_json_schema():
    for agent in ("router", "advisor", "support", "recovery"):
        for s in tool_schemas(agent):
            assert s["type"] == "function"
            assert s["function"]["parameters"]["type"] == "object"


def test_broken_rule_switch(monkeypatch):
    monkeypatch.setenv("BREAK_RULE", "discount")
    assert load_rules().max_discount_pct == 90
