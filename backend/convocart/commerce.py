"""The agent layer's only door into the store.

`LocalCommerce` calls the store functions in-process (tests, single-container demo).
`HttpCommerce` calls the store service's API (Docker Compose, the composable setup).
Both return the same dicts and raise `CommerceError`.
"""
from __future__ import annotations

from typing import Any, Protocol

import httpx

from .config import get_settings
from .db import session_scope
from .store import service as svc


class CommerceError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class Commerce(Protocol):
    def list_products(self) -> list[dict]: ...
    def get_product(self, product_id: str) -> dict: ...
    def get_customer(self, customer_id: str) -> dict: ...
    def find_customer_by_phone(self, phone: str) -> dict | None: ...
    def find_customer_by_email(self, address: str) -> dict | None: ...
    def create_cart(self, customer_id: str | None) -> dict: ...
    def get_cart(self, cart_id: str) -> dict: ...
    def attach_customer(self, cart_id: str, customer_id: str) -> dict: ...
    def add_to_cart(self, cart_id: str, variant_id: str, qty: int) -> dict: ...
    def remove_from_cart(self, cart_id: str, variant_id: str) -> dict: ...
    def set_discount(self, cart_id: str, pct: int, reason: str) -> dict: ...
    def checkout(self, cart_id: str) -> dict: ...
    def get_order(self, order_id: str) -> dict: ...
    def list_orders(self, customer_id: str, limit: int = 5) -> list[dict]: ...
    def create_return(self, order_id: str, kind: str, reason: str, status: str, refund_amount: int = 0,
                      exchange_size: str | None = None) -> dict: ...
    def set_return_status(self, return_id: str, status: str) -> dict: ...
    def set_opt_in(self, customer_id: str, opt_in: bool) -> dict: ...
    def complete_payment(self, cart_id: str) -> dict: ...
    def touch_cart(self, cart_id: str, minutes_ago: int) -> dict: ...


class LocalCommerce:
    def __init__(self, db_url: str | None = None):
        self.db_url = db_url

    def _call(self, fn, *args):
        try:
            with session_scope(self.db_url) as s:
                return fn(s, *args)
        except svc.StoreError as e:
            raise CommerceError(e.code, e.message) from e

    def list_products(self): return self._call(svc.list_products)
    def get_product(self, product_id): return self._call(svc.get_product, product_id)
    def get_customer(self, customer_id): return self._call(svc.get_customer, customer_id)
    def find_customer_by_phone(self, phone): return self._call(svc.find_customer_by_phone, phone)
    def find_customer_by_email(self, address): return self._call(svc.find_customer_by_email, address)
    def create_cart(self, customer_id): return self._call(svc.create_cart, customer_id)
    def get_cart(self, cart_id): return self._call(svc.get_cart, cart_id)
    def attach_customer(self, cart_id, customer_id): return self._call(svc.attach_customer, cart_id, customer_id)
    def add_to_cart(self, cart_id, variant_id, qty): return self._call(svc.add_to_cart, cart_id, variant_id, qty)
    def remove_from_cart(self, cart_id, variant_id): return self._call(svc.remove_from_cart, cart_id, variant_id)
    def set_discount(self, cart_id, pct, reason): return self._call(svc.set_discount, cart_id, pct, reason)
    def checkout(self, cart_id): return self._call(svc.checkout, cart_id)
    def complete_payment(self, cart_id): return self._call(svc.complete_payment, cart_id)
    def touch_cart(self, cart_id, minutes_ago): return self._call(svc.touch_cart, cart_id, minutes_ago)
    def get_order(self, order_id): return self._call(svc.get_order, order_id)
    def list_orders(self, customer_id, limit=5): return self._call(svc.list_orders, customer_id, limit)
    def set_return_status(self, return_id, status): return self._call(svc.set_return_status, return_id, status)
    def set_opt_in(self, customer_id, opt_in): return self._call(svc.set_opt_in, customer_id, opt_in)

    def create_return(self, order_id, kind, reason, status, refund_amount=0, exchange_size=None):
        return self._call(svc.create_return, order_id, kind, reason, status, refund_amount, exchange_size)


class HttpCommerce:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, client: httpx.Client | None = None):
        st = get_settings()
        self.client = client or httpx.Client(base_url=base_url or st.store_url, timeout=20)
        self.headers = {"x-api-key": api_key or st.store_api_key}

    def _req(self, method: str, path: str, json: Any = None, params: dict | None = None):
        r = self.client.request(method, path, json=json, params=params, headers=self.headers)
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {}
            raise CommerceError(body.get("error", f"http_{r.status_code}"), body.get("message", r.text[:200]))
        return r.json()

    def list_products(self): return self._req("GET", "/products")
    def get_product(self, product_id): return self._req("GET", f"/products/{product_id}")
    def get_customer(self, customer_id): return self._req("GET", f"/customers/{customer_id}")

    def find_customer_by_phone(self, phone):
        return self._find_customer({"phone": phone})

    def find_customer_by_email(self, address):
        return self._find_customer({"email": address})

    def _find_customer(self, params):
        try:
            return self._req("GET", "/customers", params=params)
        except CommerceError as e:
            if e.code == "http_404":
                return None
            raise

    def create_cart(self, customer_id): return self._req("POST", "/carts", json={"customer_id": customer_id})
    def get_cart(self, cart_id): return self._req("GET", f"/carts/{cart_id}")
    def attach_customer(self, cart_id, customer_id): return self._req("POST", f"/carts/{cart_id}/customer/{customer_id}")

    def add_to_cart(self, cart_id, variant_id, qty):
        return self._req("POST", f"/carts/{cart_id}/items", json={"variant_id": variant_id, "qty": qty})

    def remove_from_cart(self, cart_id, variant_id): return self._req("DELETE", f"/carts/{cart_id}/items/{variant_id}")

    def set_discount(self, cart_id, pct, reason):
        return self._req("POST", f"/carts/{cart_id}/discount", json={"pct": pct, "reason": reason})

    def checkout(self, cart_id): return self._req("POST", f"/carts/{cart_id}/checkout")
    def complete_payment(self, cart_id): return self._req("POST", f"/carts/{cart_id}/simulate-payment")
    def touch_cart(self, cart_id, minutes_ago): return self._req("POST", f"/carts/{cart_id}/touch", json={"minutes_ago": minutes_ago})
    def get_order(self, order_id): return self._req("GET", f"/orders/{order_id}")
    def list_orders(self, customer_id, limit=5): return self._req("GET", f"/customers/{customer_id}/orders", params={"limit": limit})
    def set_return_status(self, return_id, status): return self._req("POST", f"/returns/{return_id}/status", json={"status": status})

    def set_opt_in(self, customer_id, opt_in):
        return self._req("POST", f"/customers/{customer_id}/reminder-opt-in", json={"opt_in": opt_in})

    def create_return(self, order_id, kind, reason, status, refund_amount=0, exchange_size=None):
        return self._req("POST", "/returns", json={"order_id": order_id, "kind": kind, "reason": reason,
                                                   "status": status, "refund_amount": refund_amount,
                                                   "exchange_size": exchange_size})


def get_commerce() -> Commerce:
    st = get_settings()
    return HttpCommerce() if st.store_mode == "http" else LocalCommerce()
