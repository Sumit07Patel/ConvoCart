"""Create tables and load the invented Kesar Lane data.

python -m scripts.seed           # seeds only if the store is empty
python -m scripts.seed --force   # wipe and reseed
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

from convocart.db import create_all, session_scope  # noqa: E402
from convocart.store.models import Product  # noqa: E402
from convocart.store.seed import seed  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    for attempt in range(30):  # wait for Postgres in Docker
        try:
            create_all()
            break
        except OperationalError:
            print("database not ready, retrying...")
            time.sleep(2)
    with session_scope() as s:
        n = s.scalar(select(func.count()).select_from(Product))
        if n and not args.force:
            print(f"store already has {n} products; use --force to reseed")
            return
        print(seed(s))


if __name__ == "__main__":
    main()
