"""Phase 3: search hit rate (expected product in the top 4), Hinglish and Hindi reported separately.

python -m eval.run_search_eval [--min-hit-rate 0.8]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import yaml

from .common import RESULTS_DIR, fresh_db, matches


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-hit-rate", type=float, default=0.0)
    ap.add_argument("--k", type=int, default=4)
    args = ap.parse_args(argv)

    fresh_db("search")
    from convocart.commerce import LocalCommerce
    from convocart.search.index import get_search

    commerce = LocalCommerce()
    catalog = commerce.list_products()
    index = get_search(commerce, rebuild=True)
    queries = yaml.safe_load((Path(__file__).parent / "search_queries.yaml").read_text())

    by_lang: dict[str, list[int]] = defaultdict(list)
    by_holdout: dict[str, list[int]] = defaultdict(list)
    rows, invalid = [], []
    for q in queries:
        relevant = [p["id"] for p in catalog if matches(p, q["expect"])]
        if not relevant:
            invalid.append(q["id"])
            continue
        res = index.search(q["q"], limit=args.k)
        top = res["results"]
        hit = any(matches({**r, "gender": catalog_map(catalog)[r["product_id"]]["gender"]}, q["expect"]) for r in top)
        qset = q.get("set", "tuned")
        (by_lang if qset == "tuned" else by_holdout)[q["lang"]].append(int(hit))
        rows.append({"id": q["id"], "set": qset, "lang": q["lang"], "q": q["q"], "hit": hit, "n_relevant": len(relevant),
                     "understood": res["understood"], "top": [r["product_id"] for r in top]})

    def rate(xs):
        return round(sum(xs) / len(xs), 3) if xs else None

    all_hits = [h for xs in by_lang.values() for h in xs]
    summary = {"k": args.k, "queries": len(all_hits), "hit_rate": rate(all_hits),
               "by_language": {lang: {"n": len(xs), "hit_rate": rate(xs)} for lang, xs in sorted(by_lang.items())},
               "holdout": {"queries": sum(len(x) for x in by_holdout.values()),
                           "hit_rate": rate([h for xs in by_holdout.values() for h in xs]),
                           "by_language": {lang: {"n": len(xs), "hit_rate": rate(xs)}
                                           for lang, xs in sorted(by_holdout.items())}},
               "invalid_queries": invalid, "embedder": index.embedder.name, "backend": index.backend_name,
               "catalog_size": len(catalog)}
    RESULTS_DIR.mkdir(exist_ok=True)
    (RESULTS_DIR / "search_eval.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=2,
                                                             ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    misses = [r for r in rows if not r["hit"]]
    if misses:
        print("\nMisses:")
        for r in misses:
            print(f"  {r['id']} ({r['set']}) [{r['lang']}] {r['q']}\n     understood={r['understood']} top={r['top']}")
    if invalid:
        print(f"\nInvalid (no product satisfies expect): {invalid}")
    ok = (summary["hit_rate"] or 0) >= args.min_hit_rate and not invalid
    return 0 if ok else 1


_cmap: dict | None = None


def catalog_map(catalog):
    global _cmap
    if _cmap is None:
        _cmap = {p["id"]: p for p in catalog}
    return _cmap


if __name__ == "__main__":
    sys.exit(main())
