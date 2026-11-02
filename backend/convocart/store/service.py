"""Store operations as plain functions (Phase 2: "write the cart and order calls as plain functions first").

They return plain dicts so the same shapes travel over the store's HTTP API unchanged.
The store does not know about the agent or its rules; prices and stock come only from here.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import (Cart, CartItem, Customer, Order, Product, ReturnRequest, Variant, utcnow)


class StoreError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


# ---------- catalog ----------

def product_dict(p: Product, with_reviews: bool = False) -> dict:
    sizes = sorted({v.size for v in p.variants}, key=_size_key)
    colors = sorted({v.color for v in p.variants})
    d = {
        "id": p.id, "title": p.title, "description": p.description, "category": p.category, "gender": p.gender,
        "tags": list(p.tags or []), "price": p.price, "mrp": p.mrp, "rating": p.rating, "weight_g": p.weight_g,
        "sizes": sizes, "colors": colors,
        "in_stock_sizes": sorted({v.size for v in p.variants if v.stock > 0}, key=_size_key),
        "variants": [{"id": v.id, "size": v.size, "color": v.color, "stock": v.stock} for v in p.variants],
    }
    if with_reviews:
        d["reviews"] = [{"author": r.author, "rating": r.rating, "text": r.text} for r in p.reviews]
    return d


_SIZE_ORDER = {s: i for i, s in enumerate(["XS", "S", "M", "L", "XL", "XXL"])}


def _size_key(s: str):
    if s in _SIZE_ORDER:
        return (0, _SIZE_ORDER[s], s)
    digits = "".join(ch for ch in s if ch.isdigit())
    return (1, int(digits) if digits else 0, s)


def list_products(s: Session) -> list[dict]:
    rows = s.scalars(select(Product).where(Product.active.is_(True)).options(selectinload(Product.variants))).all()
    return [product_dict(p) for p in rows]


def get_product(s: Session, product_id: str, with_reviews: bool = True) -> dict:
    p = s.get(Product, product_id)
    if not p or not p.active:
        raise StoreError("product_not_found", f"No product {product_id}", 404)
    return product_dict(p, with_reviews=with_reviews)


# ---------- customers ----------

def customer_dict(c: Customer) -> dict:
    return {"id": c.id, "name": c.name, "phone": c.phone, "email": c.email, "city": c.city,
            "preferred_language": c.preferred_language, "reminder_opt_in": c.reminder_opt_in}


def get_customer(s: Session, customer_id: str) -> dict:
    c = s.get(Customer, customer_id)
    if not c:
        raise StoreError("customer_not_found", f"No customer {customer_id}", 404)
    return customer_dict(c)


def find_customer_by_phone(s: Session, phone: str) -> dict | None:
    digits = "".join(ch for ch in phone if ch.isdigit())
    c = s.scalar(select(Customer).where(Customer.phone == f"+{digits}"))
    return customer_dict(c) if c else None


def find_customer_by_email(s: Session, address: str) -> dict | None:
    c = s.scalar(select(Customer).where(func.lower(Customer.email) == address.strip().lower()))
    return customer_dict(c) if c else None


def set_opt_in(s: Session, customer_id: str, opt_in: bool) -> dict:
    c = s.get(Customer, customer_id)
    if not c:
        raise StoreError("customer_not_found", f"No customer {customer_id}", 404)
    c.reminder_opt_in = opt_in
    return customer_dict(c)


# ---------- carts ----------

def _cart_dict(s: Session, c: Cart) -> dict:
    items = []
    subtotal = 0
    for it in c.items:
        v = s.get(Variant, it.variant_id)
        line = it.unit_price * it.qty
        subtotal += line
        items.append({"variant_id": it.variant_id, "product_id": v.product_id, "title": v.product.title,
                      "size": v.size, "color": v.color, "qty": it.qty, "unit_price": it.unit_price,
                      "line_total": line})
    discount = round(subtotal * c.discount_pct / 100)
    return {"id": c.id, "customer_id": c.customer_id, "status": c.status, "items": items, "subtotal": subtotal,
            "discount_pct": c.discount_pct, "discount_amount": discount, "total": subtotal - discount,
            "updated_at": c.updated_at.isoformat()}


def create_cart(s: Session, customer_id: str | None = None) -> dict:
    c = Cart(id=str(uuid.uuid4()), customer_id=customer_id)
    s.add(c)
    s.flush()
    return _cart_dict(s, c)


def _open_cart(s: Session, cart_id: str) -> Cart:
    c = s.get(Cart, cart_id)
    if not c:
        raise StoreError("cart_not_found", f"No cart {cart_id}", 404)
    return c


def get_cart(s: Session, cart_id: str) -> dict:
    return _cart_dict(s, _open_cart(s, cart_id))


def attach_customer(s: Session, cart_id: str, customer_id: str) -> dict:
    c = _open_cart(s, cart_id)
    c.customer_id = customer_id
    return _cart_dict(s, c)


def add_to_cart(s: Session, cart_id: str, variant_id: str, qty: int = 1) -> dict:
    c = _open_cart(s, cart_id)
    if c.status == "completed":
        raise StoreError("cart_closed", "This cart has already been paid for.")
    if qty < 1 or qty > 10:
        raise StoreError("bad_qty", "Quantity must be between 1 and 10.")
    v = s.get(Variant, variant_id)
    if not v:
        raise StoreError("variant_not_found", f"No variant {variant_id}", 404)
    existing = next((it for it in c.items if it.variant_id == variant_id), None)
    want = qty + (existing.qty if existing else 0)
    if v.stock < want:
        raise StoreError("out_of_stock", f"Only {v.stock} left in {v.color} {v.size}.", 409)
    if existing:
        existing.qty = want
    else:
        c.items.append(CartItem(variant_id=variant_id, qty=qty, unit_price=v.product.price))
    c.updated_at = utcnow()
    c.abandoned_event_sent = False
    s.flush()
    return _cart_dict(s, c)


def remove_from_cart(s: Session, cart_id: str, variant_id: str) -> dict:
    c = _open_cart(s, cart_id)
    c.items = [it for it in c.items if it.variant_id != variant_id]
    c.updated_at = utcnow()
    s.flush()
    return _cart_dict(s, c)


def set_discount(s: Session, cart_id: str, pct: int, reason: str) -> dict:
    """The store applies whatever its trusted caller asks. The agent's rules live in the tool layer."""
    c = _open_cart(s, cart_id)
    if pct < 0 or pct > 100:
        raise StoreError("bad_discount", "Discount must be 0-100.")
    c.discount_pct = pct
    c.discount_reason = reason
    c.updated_at = utcnow()
    return _cart_dict(s, c)


def checkout(s: Session, cart_id: str) -> dict:
    c = _open_cart(s, cart_id)
    if not c.items:
        raise StoreError("empty_cart", "The cart is empty.")
    if not c.customer_id:
        raise StoreError("no_customer", "A customer must be attached before checkout.")
    c.status = "checkout"
    c.updated_at = utcnow()
    d = _cart_dict(s, c)
    d["payment_link"] = f"https://pay.example.invalid/kesarlane/{c.id[:8]}"
    return d


def complete_payment(s: Session, cart_id: str) -> dict:
    """Simulates the payment provider's success callback: turns the cart into a paid order."""
    c = _open_cart(s, cart_id)
    if c.status == "completed":
        raise StoreError("cart_closed", "Already paid.")
    if not c.items or not c.customer_id:
        raise StoreError("not_ready", "Cart needs items and a customer.")
    d = _cart_dict(s, c)
    n = len(s.scalars(select(Order.id)).all())
    oid = f"ORD-{20001 + n}"
    o = Order(id=oid, customer_id=c.customer_id, status="paid", total=d["total"], created_at=utcnow())
    from .models import OrderItem
    for it in c.items:
        v = s.get(Variant, it.variant_id)
        if v.stock < it.qty:
            raise StoreError("out_of_stock", f"{v.id} sold out before payment.", 409)
        v.stock -= it.qty
        o.items.append(OrderItem(variant_id=v.id, title=f"{v.product.title} ({v.color}, {v.size})", qty=it.qty,
                                 unit_price=it.unit_price))
    s.add(o)
    c.status = "completed"
    c.updated_at = utcnow()
    s.flush()
    return order_dict(o)


def find_abandoned_carts(s: Session, idle_minutes: int) -> list[dict]:
    cutoff = utcnow() - timedelta(minutes=idle_minutes)
    rows = s.scalars(select(Cart).where(Cart.status.in_(["open", "checkout"]), Cart.updated_at <= cutoff,
                                        Cart.abandoned_event_sent.is_(False), Cart.customer_id.is_not(None))).all()
    return [_cart_dict(s, c) for c in rows if c.items]


def mark_abandoned_event_sent(s: Session, cart_id: str) -> None:
    _open_cart(s, cart_id).abandoned_event_sent = True


def touch_cart(s: Session, cart_id: str, minutes_ago: int) -> dict:
    """Test/demo helper: pretend the cart was last updated `minutes_ago`."""
    c = _open_cart(s, cart_id)
    c.updated_at = utcnow() - timedelta(minutes=minutes_ago)
    return _cart_dict(s, c)


# ---------- orders ----------

def order_dict(o: Order) -> dict:
    return {
        "id": o.id, "customer_id": o.customer_id, "status": o.status, "total": o.total,
        "created_at": o.created_at.isoformat(),
        "shipped_at": o.shipped_at.isoformat() if o.shipped_at else None,
        "delivered_at": o.delivered_at.isoformat() if o.delivered_at else None,
        "courier": o.courier, "tracking_id": o.tracking_id,
        "items": [{"variant_id": i.variant_id, "title": i.title, "qty": i.qty, "unit_price": i.unit_price}
                  for i in o.items],
    }


def get_order(s: Session, order_id: str) -> dict:
    o = s.get(Order, order_id.upper().strip())
    if not o:
        raise StoreError("order_not_found", f"No order {order_id}", 404)
    return order_dict(o)


def list_orders(s: Session, customer_id: str, limit: int = 5) -> list[dict]:
    rows = s.scalars(select(Order).where(Order.customer_id == customer_id).order_by(Order.created_at.desc())
                     .limit(limit)).all()
    return [order_dict(o) for o in rows]


# ---------- returns ----------

def return_dict(r: ReturnRequest) -> dict:
    return {"id": r.id, "order_id": r.order_id, "customer_id": r.customer_id, "kind": r.kind, "reason": r.reason,
            "status": r.status, "refund_amount": r.refund_amount, "exchange_size": r.exchange_size,
            "created_at": r.created_at.isoformat()}


def create_return(s: Session, order_id: str, kind: str, reason: str, status: str,
                  refund_amount: int = 0, exchange_size: str | None = None) -> dict:
    o = s.get(Order, order_id)
    if not o:
        raise StoreError("order_not_found", f"No order {order_id}", 404)
    open_ = s.scalar(select(ReturnRequest).where(ReturnRequest.order_id == order_id,
                                                 ReturnRequest.status.in_(["pickup_scheduled", "pending_approval"])))
    if open_:
        raise StoreError("return_exists", f"Return {open_.id} is already open for this order.", 409)
    n = len(s.scalars(select(ReturnRequest.id)).all())
    r = ReturnRequest(id=f"RET-{5001 + n}", order_id=order_id, customer_id=o.customer_id, kind=kind, reason=reason,
                      status=status, refund_amount=refund_amount, exchange_size=exchange_size)
    s.add(r)
    s.flush()
    return return_dict(r)


def set_return_status(s: Session, return_id: str, status: str) -> dict:
    r = s.get(ReturnRequest, return_id)
    if not r:
        raise StoreError("return_not_found", f"No return {return_id}", 404)
    r.status = status
    if status == "approved" and r.kind == "refund":
        o = s.get(Order, r.order_id)
        o.status = "returned"
    return return_dict(r)


def get_return(s: Session, return_id: str) -> dict:
    r = s.get(ReturnRequest, return_id)
    if not r:
        raise StoreError("return_not_found", f"No return {return_id}", 404)
    return return_dict(r)
