"""Phase 1: 10-case tool-calling test for picking a model.

Does the model call the right tool with valid arguments? Run it on each candidate:
  LLM_PROVIDER=ollama LLM_MODEL=qwen2.5:7b-instruct python -m eval.tool_calling_test
  LLM_PROVIDER=groq LLM_API_KEY=... python -m eval.tool_calling_test
Keep the models that pass (default bar: 9/10).
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from pydantic import ValidationError

from .common import RESULTS_DIR

STATE_WITH_RESULTS = {"signed_in": True, "customer_name": "Aarav Mehta",
                      "last_results": [{"option": 1, "product_id": "KL-RJ-003", "title": "Kesar Lane StormPack Rain Jacket",
                                        "price": 3399, "sizes": ["M", "L"]},
                                       {"option": 2, "product_id": "KL-RJ-006", "title": "Kesar Lane Drizzle Windcheater",
                                        "price": 2599, "sizes": ["S", "M"]}],
                      "cart": {"items": ["Kesar Lane StormPack Rain Jacket (M) x1"], "total": 3399, "discount_pct": 0}}

# (role, language, state, user message, expected tool, argument check)
CASES = [
    ("advisor", "en", {"signed_in": True}, "show me a waterproof jacket under 3000", "search_products",
     lambda a: a.get("max_price") in (3000, None) and "jacket" in a.get("query", "").lower()),
    ("advisor", "hinglish", {"signed_in": True}, "monsoon ke liye halki jacket dikhao 3000 ke andar", "search_products",
     lambda a: bool(a.get("query"))),
    ("advisor", "hi", {"signed_in": True}, "बारिश के लिए जूते दिखाओ", "search_products", lambda a: bool(a.get("query"))),
    ("advisor", "en", STATE_WITH_RESULTS, "add the second one in size M", "add_to_cart",
     lambda a: (a.get("option") == 2 or a.get("product_id") == "KL-RJ-006") and str(a.get("size", "")).upper() == "M"),
    ("advisor", "hinglish", STATE_WITH_RESULTS, "pehla wala L size mein daal do", "add_to_cart",
     lambda a: (a.get("option") == 1 or a.get("product_id") == "KL-RJ-003") and str(a.get("size", "")).upper() == "L"),
    ("advisor", "en", STATE_WITH_RESULTS, "can you give me 50% off?", "apply_discount", lambda a: a.get("percent") == 50),
    ("advisor", "en", STATE_WITH_RESULTS, "ok I'm ready to pay", "start_checkout", lambda a: True),
    ("support", "en", {"signed_in": True}, "where is my order ORD-10002?", "get_order",
     lambda a: a.get("order_id", "").upper().replace(" ", "") in ("ORD-10002", "10002")),
    ("support", "hinglish", {"signed_in": True}, "ORD-10001 ka paisa wapas chahiye, jacket phat gayi", "create_return",
     lambda a: a.get("kind") == "refund" and "10001" in a.get("order_id", "")),
    ("router", "en", {"signed_in": True}, "I want to speak to a real person now", "route_to",
     lambda a: a.get("agent") == "human"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-pass", type=int, default=9)
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args(argv)

    from convocart.agents.prompts import system_prompt
    from convocart.llm import ModelError, get_model
    from convocart.tools.core import TOOLS, tool_schemas

    from .preflight import preflight
    preflight()
    model = get_model()
    rows, passed = [], 0
    for i, (role, lang, state, msg, want, check) in enumerate(CASES, 1):
        messages = [{"role": "system", "content": system_prompt(role, lang, state)}, {"role": "user", "content": msg}]
        t0 = time.perf_counter()
        try:
            r = model.chat(messages, tools=tool_schemas(role),
                           tool_choice={"type": "function", "function": {"name": "route_to"}} if role == "router" else None)
            calls = r.tool_calls
            err = None
        except ModelError as e:
            calls, err = [], str(e)[:200]
        ms = (time.perf_counter() - t0) * 1000
        got = calls[0] if calls else None
        valid = False
        if got and got.name == want and isinstance(got.arguments, dict):
            try:
                TOOLS[want].args.model_validate(got.arguments)
                valid = bool(check(got.arguments))
            except ValidationError:
                valid = False
        passed += valid
        rows.append({"case": i, "role": role, "lang": lang, "message": msg, "expected": want,
                     "got": got.name if got else None, "args": got.arguments if got else None, "pass": valid,
                     "latency_ms": round(ms), "error": err})
        print(f"{'PASS' if valid else 'FAIL'} {i:>2} [{role}/{lang}] {msg[:50]!r} -> {rows[-1]['got']} {rows[-1]['args']}")
        if args.sleep:
            time.sleep(args.sleep)
    summary = {"model": model.name, "passed": passed, "total": len(CASES), "keep": passed >= args.min_pass}
    RESULTS_DIR.mkdir(exist_ok=True)
    safe = model.name.replace(":", "_").replace("/", "_")
    (RESULTS_DIR / f"tool_calling_{safe}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2,
                                                                       ensure_ascii=False, default=str))
    print(json.dumps(summary))
    return 0 if summary["keep"] else 1


if __name__ == "__main__":
    sys.exit(main())
