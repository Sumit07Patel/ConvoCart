"""The headless store's own HTTP API (port 9000 in Docker).

Stands in for Medusa or another open-source headless store: catalog, carts, orders, returns,
plus a job that finds abandoned carts and sends a signed webhook to the agent service.
Run: uvicorn convocart.store.api:app --port 9000
"""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid

import httpx
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import get_settings, load_rules
from ..db import create_all, session_scope
from . import service as svc

@asynccontextmanager
async def lifespan(_app):
    create_all()
    yield


app = FastAPI(title="Kesar Lane headless store", version="1.0", lifespan=lifespan)




@app.exception_handler(svc.StoreError)
def _store_error(_: Request, exc: svc.StoreError):
    return JSONResponse(status_code=exc.status, content={"error": exc.code, "message": exc.message})


def require_key(x_api_key: str = Header(default="")) -> None:
    if not hmac.compare_digest(x_api_key, get_settings().store_api_key):
        raise HTTPException(401, "bad api key")


auth = [Depends(require_key)]


class CartCreate(BaseModel):
    customer_id: str | None = None


class CartAdd(BaseModel):
    variant_id: str
    qty: int = 1


class DiscountIn(BaseModel):
    pct: int
    reason: str


class ReturnIn(BaseModel):
    order_id: str
    kind: str
    reason: str
    status: str
    refund_amount: int = 0
    exchange_size: str | None = None


class StatusIn(BaseModel):
    status: str


class OptIn(BaseModel):
    opt_in: bool


class TouchIn(BaseModel):
    minutes_ago: int


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/products", dependencies=auth)
def products():
    with session_scope() as s:
        return svc.list_products(s)


@app.get("/products/{pid}", dependencies=auth)
def product(pid: str):
    with session_scope() as s:
        return svc.get_product(s, pid)


@app.get("/customers/{cid}", dependencies=auth)
def customer(cid: str):
    with session_scope() as s:
        return svc.get_customer(s, cid)


@app.get("/customers", dependencies=auth)
def customer_by_contact(phone: str = "", email: str = ""):
    with session_scope() as s:
        c = svc.find_customer_by_phone(s, phone) if phone else svc.find_customer_by_email(s, email) if email else None
        if not c:
            raise HTTPException(404, "not found")
        return c


@app.post("/customers/{cid}/reminder-opt-in", dependencies=auth)
def opt_in(cid: str, body: OptIn):
    with session_scope() as s:
        return svc.set_opt_in(s, cid, body.opt_in)


@app.post("/carts", dependencies=auth)
def cart_create(body: CartCreate):
    with session_scope() as s:
        return svc.create_cart(s, body.customer_id)


@app.get("/carts/{cart_id}", dependencies=auth)
def cart_get(cart_id: str):
    with session_scope() as s:
        return svc.get_cart(s, cart_id)


@app.post("/carts/{cart_id}/customer/{cid}", dependencies=auth)
def cart_attach(cart_id: str, cid: str):
    with session_scope() as s:
        return svc.attach_customer(s, cart_id, cid)


@app.post("/carts/{cart_id}/items", dependencies=auth)
def cart_add(cart_id: str, body: CartAdd):
    with session_scope() as s:
        return svc.add_to_cart(s, cart_id, body.variant_id, body.qty)


@app.delete("/carts/{cart_id}/items/{variant_id}", dependencies=auth)
def cart_remove(cart_id: str, variant_id: str):
    with session_scope() as s:
        return svc.remove_from_cart(s, cart_id, variant_id)


@app.post("/carts/{cart_id}/discount", dependencies=auth)
def cart_discount(cart_id: str, body: DiscountIn):
    with session_scope() as s:
        return svc.set_discount(s, cart_id, body.pct, body.reason)


@app.post("/carts/{cart_id}/checkout", dependencies=auth)
def cart_checkout(cart_id: str):
    with session_scope() as s:
        return svc.checkout(s, cart_id)


@app.post("/carts/{cart_id}/simulate-payment", dependencies=auth)
def cart_pay(cart_id: str):
    with session_scope() as s:
        order = svc.complete_payment(s, cart_id)
    try:  # the agent sends the order confirmation; a failed delivery must not undo the payment
        _post_event({"id": f"evt_{uuid.uuid4().hex[:16]}", "type": "order.paid", "data": {"order": order, "cart_id": cart_id}})
    except httpx.HTTPError:
        pass
    return order


@app.post("/carts/{cart_id}/touch", dependencies=auth)
def cart_touch(cart_id: str, body: TouchIn):
    with session_scope() as s:
        return svc.touch_cart(s, cart_id, body.minutes_ago)


@app.get("/orders/{oid}", dependencies=auth)
def order_get(oid: str):
    with session_scope() as s:
        return svc.get_order(s, oid)


@app.get("/customers/{cid}/orders", dependencies=auth)
def orders_list(cid: str, limit: int = 5):
    with session_scope() as s:
        return svc.list_orders(s, cid, limit)


@app.post("/returns", dependencies=auth)
def return_create(body: ReturnIn):
    with session_scope() as s:
        return svc.create_return(s, body.order_id, body.kind, body.reason, body.status, body.refund_amount,
                                 body.exchange_size)


@app.get("/returns/{rid}", dependencies=auth)
def return_get(rid: str):
    with session_scope() as s:
        return svc.get_return(s, rid)


@app.post("/returns/{rid}/status", dependencies=auth)
def return_status(rid: str, body: StatusIn):
    with session_scope() as s:
        return svc.set_return_status(s, rid, body.status)


def sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _post_event(event: dict) -> None:
    """Signed webhook to the agent service (cart.abandoned, order.paid)."""
    settings = get_settings()
    body = json.dumps(event).encode()
    r = httpx.post(f"{settings.agent_url}/webhooks/store", content=body, timeout=30,
                   headers={"content-type": "application/json", "x-store-signature": sign(body, settings.store_webhook_secret)})
    r.raise_for_status()


@app.post("/jobs/abandoned-carts", dependencies=auth)
def run_abandoned_cart_job():
    """Finds idle carts and sends `cart.abandoned` webhooks to the agent. Cron calls this every few minutes."""
    rules = load_rules()
    sent, failed = [], []
    with session_scope() as s:
        carts = svc.find_abandoned_carts(s, rules.abandon_after_minutes)
    for cart in carts:
        event = {"id": f"evt_{uuid.uuid4().hex[:16]}", "type": "cart.abandoned", "data": {"cart": cart}}
        try:
            _post_event(event)
            with session_scope() as s:
                svc.mark_abandoned_event_sent(s, cart["id"])
            sent.append(cart["id"])
        except httpx.HTTPError as e:  # retried on the next run
            failed.append({"cart": cart["id"], "error": str(e)})
    return {"sent": sent, "failed": failed}
