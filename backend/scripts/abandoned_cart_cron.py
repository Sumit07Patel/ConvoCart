"""Tiny scheduler for the store's abandoned-cart job (stands in for a cron entry).

python -m scripts.abandoned_cart_cron --every 300
"""
from __future__ import annotations

import argparse
import os
import time

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=int(os.environ.get("ABANDON_SCAN_SECONDS", "300")))
    args = ap.parse_args()
    store = os.environ.get("STORE_URL", "http://localhost:9000")
    key = os.environ.get("STORE_API_KEY", "dev-store-key")
    while True:
        try:
            r = httpx.post(f"{store}/jobs/abandoned-carts", headers={"x-api-key": key}, timeout=120)
            print("abandoned-cart job:", r.status_code, r.text[:300], flush=True)
        except httpx.HTTPError as e:
            print("store not reachable:", e, flush=True)
        time.sleep(args.every)


if __name__ == "__main__":
    main()
