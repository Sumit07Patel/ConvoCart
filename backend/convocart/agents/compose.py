"""Deterministic reply writer: turns tool results into a shopper-facing message.

Used by the scripted model (offline/CI runs) and as the safe fallback when a real model's
reply fails a guardrail check (for example it mentions a price no tool returned).
"""
from __future__ import annotations

from datetime import datetime

from .language import t


def _sizes(xs) -> str:
    return ", ".join(xs) if xs else "-"


def _item_line(i: int, r: dict) -> str:
    mrp = f" (MRP ₹{r['mrp']})" if r.get("mrp", 0) > r["price"] else ""
    sizes = r.get("available_sizes") or []
    size_txt = "" if sizes == ["ONE"] else f" · {_sizes(sizes)}"
    return f"{i}. {r['title']} - ₹{r['price']}{mrp}{size_txt}"


def compose_search(res: dict, lang: str) -> str:
    understood = res.get("understood", {})
    budget = t("budget", lang, max=understood["max_price"]) if understood.get("max_price") else ""
    results = res.get("results", [])
    if not results:
        out = [t("no_results", lang, budget=budget)]
        alts = res.get("over_budget_alternatives") or []
        if alts:
            out.append(t("over_budget", lang))
            out += [_item_line(i + 1, r) for i, r in enumerate(alts)]
        return "\n".join(out)
    lines = [t("results_header", lang, n=len(results), budget=budget)]
    lines += [_item_line(i + 1, r) for i, r in enumerate(results)]
    lines.append(t("results_footer", lang))
    return "\n".join(lines)


def compose_cart(cart: dict, lang: str) -> str:
    if not cart.get("items"):
        return t("cart_empty", lang)
    lines = "\n".join(f"- {i['title']} ({i['color']}, {i['size']}) x{i['qty']} - ₹{i['line_total']}"
                      for i in cart["items"])
    if cart.get("discount_pct"):
        lines += f"\n- {cart['discount_pct']}% off: -₹{cart['discount_amount']}"
    return t("cart", lang, lines=lines, total=cart["total"])


def _date(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%d %b %Y") if iso else "-"


def compose_order(o: dict, lang: str) -> str:
    st = o["status"]
    if st == "shipped":
        return t("order_shipped", lang, id=o["id"], courier=o["courier"], tracking=o["tracking_id"])
    if st == "delivered":
        return t("order_delivered", lang, id=o["id"], date=_date(o["delivered_at"]))
    if st in ("returned", "cancelled"):
        return t(f"order_{st}", lang, id=o["id"])
    return t("order_paid", lang, id=o["id"], total=o["total"])


def compose_tool_result(name: str, args: dict, res: dict, lang: str, state: dict | None = None) -> str:
    state = state or {}
    if not res.get("ok"):
        code = res.get("error")
        if code == "need_size":
            return t("need_size", lang, title=res["title"], sizes=_sizes(res.get("in_stock_sizes")))
        if code == "out_of_stock":
            return t("out_of_stock", lang, sizes=_sizes(res.get("in_stock_sizes")))
        if code == "product_not_found":
            return t("pick_first", lang)
        if code == "over_limit":
            return t("discount_refused", lang, asked=res["asked"], max=res["allowed_max"])
        if code == "below_minimum":
            return t("discount_min_cart", lang, min=res["min_cart_value"], subtotal=res["subtotal"])
        if code == "empty_cart":
            return t("discount_empty", lang) if name == "apply_discount" else t("cart_empty", lang)
        if code == "already_discounted":
            return t("discount_already", lang, pct=res["current_pct"])
        if code == "need_login":
            return t("need_login", lang)
        if code == "order_not_found":
            return t("order_not_found", lang, id=res.get("order_id", args.get("order_id", "")))
        if code == "outside_window":
            return t("return_window", lang, id=res["order_id"], days=res["window_days"])
        if code in ("not_delivered",):
            return t("return_not_delivered", lang, id=res["order_id"])
        if code in ("return_exists", "already_returned"):
            return t("return_exists", lang, id=res.get("order_id", args.get("order_id", "")))
        return t("fallback", lang)
    if name == "search_products":
        return compose_search(res, lang)
    if name == "add_to_cart":
        a = res["added"]
        return t("added", lang, title=a["title"], color=a["color"], size=a["size"], total=res["cart"]["total"])
    if name in ("view_cart", "remove_from_cart"):
        return compose_cart(res["cart"], lang)
    if name == "apply_discount":
        c = res["cart"]
        return t("discount_applied", lang, pct=res["applied_pct"], total=c["total"], amount=c["discount_amount"])
    if name == "start_checkout":
        return t("checkout", lang, total=res["cart"]["total"], link=res["payment_link"])
    if name == "get_product_details":
        p = res["product"]
        mrp = f" (MRP ₹{p['mrp']})" if p["mrp"] > p["price"] else ""
        return t("details", lang, title=p["title"], price=p["price"], mrp=mrp, weight=p["weight_g"],
                 tags=", ".join(p["tags"]), rating=p["rating"], sizes=_sizes(p["in_stock_sizes"]))
    if name == "get_order":
        return compose_order(res["order"], lang)
    if name == "list_my_orders":
        if not res["orders"]:
            return t("no_orders", lang)
        lines = "\n".join(f"- {o['id']} ({o['created_at']}): {o['status']}, ₹{o['total']}" for o in res["orders"])
        return t("orders_list", lang, lines=lines)
    if name == "create_return":
        r = res["return_request"]
        if r["kind"] == "refund":
            key = "refund_pending" if r["status"] == "pending_approval" else "refund_done"
            return t(key, lang, rid=r["id"], id=r["order_id"], amount=r["refund_amount"])
        if r["kind"] == "exchange":
            size = f" (size {r['exchange_size']})" if r.get("exchange_size") else ""
            return t("exchange_created", lang, rid=r["id"], id=r["order_id"], size=size)
        return t("return_created", lang, rid=r["id"], id=r["order_id"])
    if name == "handover_to_human":
        return t("handover", lang)
    return t("fallback", lang)


def compose_recovery(cart: dict, name: str, lang: str, link: str) -> str:
    items = cart.get("items", [])
    first = items[0]["title"] if items else "your items"
    more = t("more_items", lang, n=len(items) - 1) if len(items) > 1 else ""
    if cart.get("discount_pct"):  # the discount the shopper already bargained for, never a new one
        return t("recovery_discount", lang, name=name.split()[0], item=first, more=more, total=cart["total"],
                 pct=cart["discount_pct"], link=link)
    return t("recovery", lang, name=name.split()[0], item=first, more=more, total=cart["total"], link=link)


def compose_order_confirmation(order: dict, name: str, lang: str, link: str) -> str:
    lines = "".join(f"- {i['title']} x{i['qty']}: ₹{i['unit_price'] * i['qty']}\n" for i in order["items"])
    discount = sum(i["unit_price"] * i["qty"] for i in order["items"]) - order["total"]
    if discount > 0:  # the bargained discount, so the items add up to the total paid
        lines += f"- {t('discount_word', lang)}: -₹{discount}\n"
    return t("order_confirmation", lang, name=name.split()[0], id=order["id"], lines=lines, total=order["total"],
             link=link)
