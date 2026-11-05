"""Output guardrails applied to every reply before it reaches the shopper."""
from __future__ import annotations

import re

from .language import looks_like

MONEY = re.compile(r"(?:₹|rs\.?|inr|rupees?|रुपये|रु\.?)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*(?:rupees?|rs\b|रुपये)",
                   re.I)
PERCENT = re.compile(r"(\d{1,3})\s*(?:%|percent|प्रतिशत)", re.I)


# The store sells only in rupees; any other currency next to an amount is a made-up price.
WRONG_CURRENCY = re.compile(r"(?:\$|US\$|USD|€|£|EUR|GBP)\s*\d|\d\s*(?:USD|EUR|GBP|dollars?)\b", re.I)


# Internal tool names must never reach a shopper. A test keeps this list in step with TOOLS.
TOOL_NAME = re.compile(r"\b(?:search_products|get_product_details|add_to_cart|view_cart|remove_from_cart|apply_discount|"
                       r"start_checkout|get_order|list_my_orders|create_return|handover_to_human|route_to)\b")
# Models like non-breaking hyphens; "ORD\u201110001" looks right but breaks when a shopper copies it back.
ODD_HYPHENS = str.maketrans({"\u2010": "-", "\u2011": "-"})


def collect_numbers(obj, out: set[int] | None = None) -> set[int]:
    out = set() if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.add(int(round(obj)))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_numbers(v, out)
    elif isinstance(obj, str):
        for m in re.findall(r"\d[\d,]*", obj):
            out.add(int(m.replace(",", "")))
    return out


def unverified_prices(reply: str, allowed: set[int]) -> list[int]:
    bad = []
    for m in MONEY.finditer(reply):
        raw = (m.group(1) or m.group(2) or "").replace(",", "")
        if not raw:
            continue
        val = int(float(raw))
        if val not in allowed:
            bad.append(val)
    return bad


def promised_discounts(reply: str, max_pct: int) -> list[int]:
    """Percentages above the cap that the reply mentions. A refusal may quote the asked number,
    so the caller only treats this as a violation when no refusal happened this turn."""
    return [int(p) for p in PERCENT.findall(reply) if int(p) > max_pct]


def check_reply(reply: str, language: str, tool_results: list[dict], extra_numbers: set[int], max_pct: int,
                discount_refused: bool) -> dict:
    allowed = collect_numbers(tool_results) | extra_numbers
    issues = {}
    bad = unverified_prices(reply, allowed)
    if bad:
        issues["unverified_price"] = bad
    if WRONG_CURRENCY.search(reply):
        issues["wrong_currency"] = True
    if TOOL_NAME.search(reply):
        issues["tool_name_leak"] = True
    over = promised_discounts(reply, max_pct)
    if over and not discount_refused:
        issues["discount_over_cap"] = over
    if not looks_like(reply, language):
        issues["language_mismatch"] = language
    return issues
