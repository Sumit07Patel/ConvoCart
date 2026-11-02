"""One cheap model call before a long eval run, so a bad key, a retired model or a model without
tool calling fails in seconds with a clear message instead of after many scenarios."""
from __future__ import annotations

import sys


def preflight() -> None:
    from convocart.llm import ModelError, get_model
    from convocart.tools.core import tool_schemas

    model = get_model()
    if model.name.startswith("scripted"):
        return
    messages = [{"role": "system", "content": "Route the shopper's message by calling route_to."},
                {"role": "user", "content": "where is my order ORD-10002?"}]
    try:
        r = model.chat(messages, tools=tool_schemas("router"),
                       tool_choice={"type": "function", "function": {"name": "route_to"}})
    except ModelError as e:
        sys.exit(f"preflight: {model.name} cannot be reached: {e}")
    if not r.tool_calls:
        sys.exit(f"preflight: {model.name} answered but did not call a tool; it cannot run the agent.")
    print(f"preflight: {model.name} OK ({r.latency_ms:.0f} ms)")
