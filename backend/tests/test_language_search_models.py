import json

import httpx
import pytest

from convocart.agents.guards import check_reply, unverified_prices
from convocart.agents.language import detect_language
from convocart.llm.base import ModelError
from convocart.llm.openai_compat import OpenAICompatModel
from convocart.search.query import parse_query, resolve_category


@pytest.mark.parametrize("text,lang", [
    ("show me a rain jacket", "en"),
    ("monsoon ke liye ek halki jacket dikhao", "hinglish"),
    ("बारिश के लिए जैकेट दिखाओ", "hi"),
    ("mera order kab aayega", "hinglish"),
    ("Where is my order?", "en"),
])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_short_reply_keeps_language():
    assert detect_language("M", previous="hi") == "hi"
    assert detect_language("haan", previous="en") == "hinglish"


def test_parse_hinglish_query():
    pq = parse_query("monsoon ke liye ek halki waterproof jacket dikhao, 3000 ke andar")
    assert pq.max_price == 3000 and pq.categories == ["rain jacket"] and "lightweight" in pq.tokens


def test_parse_hindi_query_and_digits():
    pq = parse_query("बारिश के लिए हल्की जैकेट ३००० से कम")
    assert pq.max_price == 3000 and pq.categories == ["rain jacket"]


def test_parse_size_color_range():
    pq = parse_query("kaale joote uk 9 between 1000 and 3000")
    assert pq.size == "UK9" and pq.color == "black" and (pq.min_price, pq.max_price) == (1000, 3000)


@pytest.mark.parametrize("name,cats", [("rain jacket", ["rain jacket"]), ("Jackets", ["rain jacket", "winter jacket"]),
                                       ("shoes", ["sneakers", "sandals"]), ("जूते", ["sneakers", "sandals"]),
                                       ("footwear", [])])
def test_resolve_model_category(name, cats):
    assert resolve_category(name) == cats


def test_loose_model_category_still_finds_products(db):
    # real models send category="jacket"; the catalog only has "rain jacket" / "winter jacket"
    from convocart.search.index import get_search

    res = get_search().search("light jacket monsoon", max_price=3000, category="jacket")
    assert res["results"] and {r["category"] for r in res["results"]} == {"rain jacket"}


@pytest.mark.parametrize("reply,bad", [("Total: $299", True), ("299 USD", True), ("€ 299", True),
                                       ("Total: ₹299", False), ("Size 32, 2 items", False)])
def test_wrong_currency_guard(reply, bad):
    assert bool(check_reply(reply, "en", [{"price": 299}], set(), 10, False).get("wrong_currency")) is bad


def test_price_guard():
    assert unverified_prices("Total is ₹2,599 and Rs 999", {2599}) == [999]
    issues = check_reply("You get 50% off, total ₹100", "en", [{"price": 200}], set(), 10, False)
    assert issues["unverified_price"] == [100] and issues["discount_over_cap"] == [50]


def _fake(handler):
    return OpenAICompatModel("groq", api_key="k", client=httpx.Client(transport=httpx.MockTransport(handler)),
                             max_retries=1)


def test_openai_compat_parses_tool_calls():
    def handler(req):
        body = json.loads(req.content)
        assert body["tools"][0]["function"]["name"] == "search_products"
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search_products",
                                                          "arguments": "{\"query\": \"jacket\"}"}}]}}]})
    from convocart.tools.core import tool_schemas
    r = _fake(handler).chat([{"role": "user", "content": "hi"}], tools=tool_schemas("advisor"))
    assert r.tool_calls[0].arguments == {"query": "jacket"}


def test_openai_compat_bad_json_args_passed_through():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"tool_calls": [
            {"id": "c1", "function": {"name": "add_to_cart", "arguments": "{oops"}}]}}]})
    r = _fake(handler).chat([{"role": "user", "content": "hi"}])
    assert r.tool_calls[0].arguments == "{oops"


def test_openai_compat_quota_error_raises():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(429, headers={"retry-after": "3600"}, json={"error": "daily quota"})
    with pytest.raises(ModelError):
        _fake(handler).chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 1  # does not sit waiting an hour


def test_openai_compat_falls_back_when_daily_quota_is_gone():
    seen = []

    def handler(req):
        model = json.loads(req.content)["model"]
        seen.append(model)
        if model == "main":
            return httpx.Response(429, headers={"retry-after": "3600"},
                                  json={"error": {"message": "Rate limit reached on tokens per day (TPD)"}})
        return httpx.Response(200, json={"model": model, "choices": [{"message": {"content": "ok"}}]})
    m = OpenAICompatModel("groq", model="main", api_key="k", max_retries=1, fallback_model="backup",
                          client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert m.chat([{"role": "user", "content": "hi"}]).model == "backup"
    assert m.chat([{"role": "user", "content": "hi"}]).model == "backup"
    assert seen == ["main", "backup", "backup"]  # after one quota error, skip the main model for a while


def test_graph_survives_bad_model(db):
    """A model that returns garbage tool calls must not crash the turn or bypass rules."""
    from convocart.agents.graph import ConvoCartAgent
    from convocart.llm.base import ModelReply, ToolCall

    class Garbage:
        name = "garbage"

        def chat(self, messages, tools=None, tool_choice=None):
            if tool_choice:
                return ModelReply(tool_calls=[ToolCall("x", "route_to", {"agent": "nonsense"})])
            if any(m["role"] == "tool" for m in messages):
                return ModelReply(content="Sure! 80% off applied, your total is ₹12.")
            return ModelReply(tool_calls=[ToolCall("y", "apply_discount", "{not json")])

    out = ConvoCartAgent(model=Garbage()).handle_message("web:garbage", "give me a discount", customer_id="C0001")
    assert out["issues"].get("unverified_price") == [12]
    assert "80%" not in out["reply"] and "₹12" not in out["reply"]


def test_step_limit_hands_over(db):
    from convocart.agents.graph import ConvoCartAgent
    from convocart.llm.base import ModelReply, ToolCall

    class Looper:
        name = "looper"

        def chat(self, messages, tools=None, tool_choice=None):
            if tool_choice:
                return ModelReply(tool_calls=[ToolCall("r", "route_to", {"agent": "advisor"})])
            return ModelReply(tool_calls=[ToolCall(f"v{len(messages)}", "view_cart", {})])

    out = ConvoCartAgent(model=Looper()).handle_message("web:looper", "hi", customer_id="C0001")
    assert out["handover"] and out["handover_reason"] == "step_limit"


def test_tool_name_guard_covers_every_tool():
    from convocart.agents.guards import TOOL_NAME
    from convocart.tools.core import TOOLS

    assert all(TOOL_NAME.search(f"say {n} now") for n in TOOLS)
    assert not TOOL_NAME.search("Your cart has 2 items. Would you like to check out?")


class _Says:
    """A model that routes to the advisor, then says one fixed thing."""
    name = "says"

    def __init__(self, text):
        self.text = text

    def chat(self, messages, tools=None, tool_choice=None):
        from convocart.llm.base import ModelReply, ToolCall

        if tool_choice:
            return ModelReply(tool_calls=[ToolCall("r", "route_to", {"agent": "advisor"})])
        return ModelReply(content=self.text)


def test_reply_with_a_tool_name_is_replaced(db):
    from convocart.agents.graph import ConvoCartAgent

    out = ConvoCartAgent(model=_Says("To see your cart, say `view_cart`.")).handle_message("web:leak", "hi", customer_id="C0001")
    assert out["issues"].get("tool_name_leak") and "view_cart" not in out["reply"]


def test_order_ids_keep_a_plain_hyphen(db):
    from convocart.agents.graph import ConvoCartAgent

    out = ConvoCartAgent(model=_Says("Your order is ORD\u201110001.")).handle_message("web:hyphen", "hi", customer_id="C0001")
    assert "ORD-10001" in out["reply"]


def test_return_reason_is_optional():
    from convocart.tools.core import ReturnArgs

    assert ReturnArgs(order_id="ORD-10001", kind="return").reason == "not given"


def test_reply_in_the_wrong_language_is_replaced(db):
    from convocart.agents.graph import ConvoCartAgent
    from convocart.llm.base import ModelReply, ToolCall

    class AnswersInEnglish:
        name = "english"

        def chat(self, messages, tools=None, tool_choice=None):
            if tool_choice:
                return ModelReply(tool_calls=[ToolCall("r", "route_to", {"agent": "advisor"})])
            if any(m["role"] == "tool" for m in messages):
                return ModelReply(content="Here are some jackets you might like.")
            return ModelReply(tool_calls=[ToolCall("s", "search_products", {"query": "rain jacket"})])

    out = ConvoCartAgent(model=AnswersInEnglish()).handle_message("web:lang", "monsoon ke liye jacket dikhao",
                                                                  customer_id="C0001")
    assert out["issues"].get("language_mismatch") == "hinglish" and "you might like" not in out["reply"]
