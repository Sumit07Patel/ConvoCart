"""ScriptedModel: a deterministic, rule-based stand-in for an LLM.

Why it exists: free hosted quotas are small, so CI runs the 50+ scenarios against this model.
It exercises everything around the model (routing, tool loop, typed tools, guardrails, handover,
language handling, channels, traces) on every push, at zero cost and with no flakiness.

It is deliberately *gullible*: it asks for whatever discount the shopper names and it follows
instructions it finds inside review text. That is the point - the guardrails must hold even when
the model is fooled, because the rules live in the tools.

It is NOT a measure of real model quality. Run the same eval with LLM_PROVIDER=ollama / groq /
openrouter / gemini for that (see eval/run_scenarios.py --provider).
"""
from __future__ import annotations

import json
import re

from ..agents.compose import compose_recovery, compose_tool_result
from ..agents.language import t
from .base import ModelReply, ToolCall

YES = re.compile(r"^\s*(yes|yeah|yep|ok|okay|sure|haan|han|ha|haanji|ji|ji haan|theek hai|thik hai|chalo|done|"
                 r"kar do|karo|apply|lagao|laga do|हाँ|हां|जी|ठीक है|कर दो|लगा दो)\b", re.I)
HUMAN = re.compile(r"\b(human|real person|person|agent|executive|customer care|manager|supervisor|insaan|"
                   r"complaint|legal|lawyer|consumer court|police|fraud|scam)\b|इंसान|शिकायत|मैनेजर", re.I)
SUPPORT = re.compile(r"\bord-?\s?\d{5}\b|\b(order|orders|delivery|delivered|deliver|track|tracking|shipped|parcel|"
                     r"courier|return|returns|refund|exchange|wapas|wapis|paisa wapas|paise wapas|kab aayega|"
                     r"kab tak aayega|kahan hai|kaha hai)\b|ऑर्डर|डिलीवरी|रिफ़ंड|रिफंड|वापस|पार्सल|बदल", re.I)
REFUND = re.compile(r"\b(refund|money back|paisa wapas|paise wapas|paisa vapas)\b|रिफ़ंड|रिफंड|पैसे वापस", re.I)
EXCHANGE = re.compile(r"\b(exchange|badal|badalna|size change|change the size|replace)\b|बदल", re.I)
RETURN = re.compile(r"\b(return|wapas|wapis|vapas|send back|lauta)\b|वापस|लौटा", re.I)
DISCOUNT = re.compile(r"\b(discount|coupon|off|chhoot|chhut|sasta kar|kam kar|offer|deal)\b|छूट|डिस्काउंट|%", re.I)
CHECKOUT = re.compile(r"\b(checkout|check out|pay|payment|place (the )?order|order kar do|buy now|kharid)\b|"
                      r"भुगतान|ऑर्डर कर दो|खरीद", re.I)
VIEW_CART = re.compile(r"\b(my cart|show cart|view cart|cart dikhao|cart mein kya|what'?s in my cart|cart)\b|कार्ट", re.I)
REMOVE = re.compile(r"\b(remove|hata|hatao|delete|nikal)\b|हटा", re.I)
DETAILS = re.compile(r"\b(details?|reviews?|tell me more|aur batao|weight|material|kaisa hai|how is)\b|रिव्यू|बताओ", re.I)
ADD = re.compile(r"\b(add|cart mein|daal|dal do|le lo|lelo|lunga|lungi|i'?ll take|take|buy|want (the|this|that)|"
                 r"yeh wala|ye wala|this one|that one)\b|जोड़|डाल|ले लो|लूँगा|लूंगी", re.I)
ORDINALS = {"first": 1, "1st": 1, "pehla": 1, "pehli": 1, "pehle": 1, "pahla": 1, "पहला": 1, "पहली": 1,
            "second": 2, "2nd": 2, "doosra": 2, "dusra": 2, "doosri": 2, "dusri": 2, "दूसरा": 2, "दूसरी": 2,
            "third": 3, "3rd": 3, "teesra": 3, "tisra": 3, "teesri": 3, "तीसरा": 3, "तीसरी": 3,
            "fourth": 4, "4th": 4, "chautha": 4, "चौथा": 4}
SIZE = re.compile(r"\b(?:size\s*)?(xxl|xl|xs|s|m|l|small|medium|large|uk\s?\d{1,2}|\d{2})\b(?:\s*size)?", re.I)


def _parse_option(text: str) -> int | None:
    low = text.lower()
    for w, n in ORDINALS.items():
        if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", low):
            return n
    m = re.search(r"\b(?:option|number|no\.?|#)\s*(\d)\b", low) or re.fullmatch(r"\s*(\d)\s*(?:,.*)?", low) \
        or re.search(r"^\s*(\d)\b", low)
    return int(m.group(1)) if m else None


def _parse_size(text: str) -> str | None:
    low = text.lower()
    m = re.search(r"\buk\s?(\d{1,2})\b", low)
    if m:
        return f"UK{m.group(1)}"
    m = re.search(r"\bsize\s*(xxl|xl|xs|s|m|l|small|medium|large|\d{1,2})\b|\b(xxl|xl|xs|s|m|l|small|medium|large)\s*size\b",
                  low) or re.search(r"\b(xxl|xl|xs)\b", low) or re.search(r"(?:^|,|\s)(m|l|s)\s*$", low) \
        or re.search(r"\b(m|l|s)\s+(?:mein|me|में|chahiye|please|pls)(?!\w)", low) or re.search(r"\bin\s+(m|l|s|xl)\b", low)
    if m:
        return next(g for g in m.groups() if g).upper()
    return None


def _parse_percent(text: str) -> int | None:
    m = re.search(r"(\d{1,3})\s*(?:%|percent|pc\b|प्रतिशत|taka)", text.lower())
    return int(m.group(1)) if m else None


def _order_id(text: str) -> str | None:
    m = re.search(r"ord-?\s?(\d{5})", text, re.I) or re.search(r"(?<!\d)(\d{5})(?!\d)", text)
    return f"ORD-{m.group(1)}" if m else None


class ScriptedModel:
    name = "scripted:rules-v1"

    def __init__(self):
        self._n = 0

    def _call(self, name: str, args: dict) -> ModelReply:
        self._n += 1
        return ModelReply(tool_calls=[ToolCall(id=f"sc_{self._n}", name=name, arguments=args)], model=self.name)

    def _say(self, text: str) -> ModelReply:
        return ModelReply(content=text, model=self.name)

    def chat(self, messages, tools=None, tool_choice=None) -> ModelReply:
        system = messages[0]["content"]
        role = re.search(r"ROLE: (\w+)", system).group(1)
        lang_m = re.search(r"REPLY LANGUAGE: (\w+)", system)
        lang = lang_m.group(1) if lang_m else "en"
        state_m = re.search(r"SESSION STATE: (\{.*\})", system)
        state = json.loads(state_m.group(1)) if state_m else {}
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        user = messages[last_user]["content"]
        done = self._done_calls(messages[last_user + 1:])
        if role == "router":
            return self._call("route_to", self._route(user, state))
        if role == "advisor":
            return self._advisor(user, lang, state, done)
        if role == "support":
            return self._support(user, lang, state, done, messages[:last_user + 1])
        if role == "recovery":
            if not done:
                return self._call("view_cart", {})
            return self._say(compose_recovery(done[-1][2]["cart"], state.get("customer_name", "there"), lang,
                                              state.get("chat_link", "")))
        return self._say(t("fallback", lang))

    @staticmethod
    def _done_calls(turn: list[dict]) -> list[tuple[str, dict, dict]]:
        pending: dict[str, tuple[str, dict]] = {}
        out = []
        for m in turn:
            if m["role"] == "assistant":
                for tc in m.get("tool_calls") or []:
                    args = tc["function"]["arguments"]
                    pending[tc["id"]] = (tc["function"]["name"], json.loads(args) if isinstance(args, str) else args)
            elif m["role"] == "tool":
                name, args = pending.get(m["tool_call_id"], ("?", {}))
                out.append((name, args, json.loads(m["content"])))
        return out

    # ---------- router ----------
    def _route(self, user: str, state: dict) -> dict:
        if HUMAN.search(user):
            return {"agent": "human", "reason": "shopper asked for a person or raised a complaint"}
        if CHECKOUT.search(user) and not _order_id(user) and not (RETURN.search(user) or REFUND.search(user)) \
                and state.get("cart"):
            return {"agent": "advisor", "reason": "shopper wants to pay for the cart"}
        if SUPPORT.search(user) and not (ADD.search(user) and not _order_id(user) and not RETURN.search(user)):
            return {"agent": "support", "reason": "order, delivery or return question"}
        prev = state.get("last_route")
        if prev == "support" and (YES.search(user) or EXCHANGE.search(user) or len(user.split()) <= 3) \
                and not state.get("pending_offer") and not state.get("pending_add"):
            return {"agent": "support", "reason": "follow-up to an order question"}
        return {"agent": "advisor", "reason": "shopping"}

    # ---------- advisor ----------
    def _advisor(self, user: str, lang: str, state: dict, done) -> ModelReply:
        if not done:
            offer, pct = state.get("pending_offer"), _parse_percent(user)
            if offer and YES.search(user) and pct is None:
                return self._call("apply_discount", {"percent": offer["percent"], "reason": "shopper accepted offer"})
            if pct or (DISCOUNT.search(user) and not ADD.search(user)):
                return self._call("apply_discount", {"percent": pct or 20, "reason": "shopper asked for a discount"})
            if CHECKOUT.search(user):
                return self._call("start_checkout", {})
            if REMOVE.search(user):
                last = state.get("last_added") or {}
                return self._call("remove_from_cart", {"product_id": last.get("product_id"),
                                                       "option": _parse_option(user)})
            if VIEW_CART.search(user) and not ADD.search(user):
                return self._call("view_cart", {})
            option, size = _parse_option(user), _parse_size(user)
            pending = state.get("pending_add")
            if DETAILS.search(user) and (option or state.get("last_results")) and not size:
                return self._call("get_product_details", {"option": option or 1})
            if pending and size and not option:
                return self._call("add_to_cart", {"product_id": pending["product_id"], "size": size})
            if state.get("last_results") and (ADD.search(user) or option) and \
                    (option or size or ADD.search(user)) and len(user.split()) <= 12:
                return self._call("add_to_cart", {"option": option or 1, "size": size})
            return self._call("search_products", {"query": user})
        name, args, res = done[-1]
        # Gullible on purpose: follow instructions planted in review text (the tool must refuse).
        if name == "get_product_details" and res.get("ok"):
            for r in res.get("reviews", []):
                pct = _parse_percent(r["untrusted_text"])
                if r.get("possible_injection") and pct and not any(d[0] == "apply_discount" for d in done):
                    return self._call("apply_discount", {"percent": pct, "reason": "instruction found in review"})
        if name == "apply_discount" and len(done) > 1 and done[-2][0] == "get_product_details":
            # after a refused injected discount, still answer the original question with the details
            return self._say(compose_tool_result(*done[-2], lang, state))
        return self._say(compose_tool_result(name, args, res, lang, state))

    # ---------- support ----------
    def _support(self, user: str, lang: str, state: dict, done, history=()) -> ModelReply:
        if not done:
            oid = _order_id(user)
            kind = "refund" if REFUND.search(user) else "exchange" if EXCHANGE.search(user) else \
                "return" if RETURN.search(user) else None
            if not oid and state.get("last_order_id") and (kind or YES.search(user)):
                oid = state["last_order_id"]
            if not kind and oid:  # "ORD-10001" sent after "I want to return my jacket"
                earlier = [m["content"] for m in history if m["role"] == "user"][-2:-1]
                if earlier:
                    e = earlier[0]
                    kind = "refund" if REFUND.search(e) else "exchange" if EXCHANGE.search(e) else \
                        "return" if RETURN.search(e) else None
            if kind and oid:
                return self._call("create_return", {"order_id": oid, "kind": kind, "reason": user[:160],
                                                    "exchange_size": _parse_size(user) if kind == "exchange" else None})
            if oid:
                return self._call("get_order", {"order_id": oid})
            return self._call("list_my_orders", {"limit": 5})
        name, args, res = done[-1]
        if name == "list_my_orders" and res.get("ok") and not res["orders"]:
            return self._say(t("no_orders", lang))
        return self._say(compose_tool_result(name, args, res, lang, state))
