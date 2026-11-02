"""Product search: meaning-style vector match + hard filters (price, category, size, colour, gender).

Vector backends:
  numpy    - in-memory matrix, default, used in tests and CI eval
  pgvector - Postgres table with a vector column; filters still applied in Python after a
             top-N candidate fetch (VECTOR_BACKEND=pgvector, Postgres with the pgvector extension)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np

from .embed import Embedder, get_embedder
from .query import ParsedQuery, parse_query, resolve_category


def doc_text(p: dict) -> str:
    return " ".join([p["title"], p["category"], p["category"], " ".join(p["tags"]), " ".join(p["tags"]),
                     p["description"], p["gender"]])


@dataclass
class SearchFilters:
    max_price: int | None = None
    min_price: int | None = None
    categories: list[str] | None = None
    size: str | None = None
    color: str | None = None
    gender: str | None = None


class NumpyVectors:
    def __init__(self):
        self.ids: list[str] = []
        self.mat = np.zeros((0, 1), dtype=np.float32)

    def upsert(self, ids: list[str], vecs: np.ndarray) -> None:
        self.ids, self.mat = list(ids), vecs

    def top(self, q: np.ndarray, k: int) -> list[tuple[str, float]]:
        if not self.ids:
            return []
        sims = self.mat @ q
        order = np.argsort(-sims)[:k]
        return [(self.ids[i], float(sims[i])) for i in order]


class PgVectors:  # exercised by the CI job that runs Postgres with pgvector
    def __init__(self, engine, dim: int):
        from sqlalchemy import text

        self.engine, self.dim, self.text = engine, dim, text
        with engine.begin() as c:
            c.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            c.execute(text(f"CREATE TABLE IF NOT EXISTS product_embeddings (product_id text PRIMARY KEY, "
                           f"embedding vector({dim}) NOT NULL)"))

    @staticmethod
    def _lit(v: np.ndarray) -> str:
        return "[" + ",".join(f"{x:.6f}" for x in v.tolist()) + "]"

    def upsert(self, ids: list[str], vecs: np.ndarray) -> None:
        t = self.text
        with self.engine.begin() as c:
            c.execute(t("DELETE FROM product_embeddings"))
            for pid, v in zip(ids, vecs):
                c.execute(t("INSERT INTO product_embeddings (product_id, embedding) VALUES (:id, CAST(:v AS vector))"),
                          {"id": pid, "v": self._lit(v)})
            c.execute(t("CREATE INDEX IF NOT EXISTS product_embeddings_hnsw ON product_embeddings "
                        "USING hnsw (embedding vector_cosine_ops)"))

    def top(self, q: np.ndarray, k: int) -> list[tuple[str, float]]:
        t = self.text
        with self.engine.begin() as c:
            rows = c.execute(t("SELECT product_id, 1 - (embedding <=> CAST(:q AS vector)) AS sim "
                               "FROM product_embeddings ORDER BY embedding <=> CAST(:q AS vector) LIMIT :k"),
                             {"q": self._lit(q), "k": k}).all()
        return [(r[0], float(r[1])) for r in rows]


class ProductSearch:
    def __init__(self, embedder: Embedder | None = None, backend: str = "numpy", engine=None):
        self.embedder = embedder or get_embedder("hashing")
        self.backend_name = backend
        self.vectors = PgVectors(engine, self.embedder.dim) if backend == "pgvector" else NumpyVectors()
        self.products: dict[str, dict] = {}

    def build(self, products: list[dict]) -> "ProductSearch":
        self.products = {p["id"]: p for p in products}
        ids = list(self.products)
        vecs = self.embedder.embed([doc_text(self.products[i]) for i in ids])
        self.vectors.upsert(ids, vecs)
        return self

    # ---- filtering ----
    @staticmethod
    def _passes(p: dict, f: SearchFilters) -> tuple[bool, list[dict]]:
        if f.max_price is not None and p["price"] > f.max_price:
            return False, []
        if f.min_price is not None and p["price"] < f.min_price:
            return False, []
        if f.categories and p["category"] not in f.categories:
            return False, []
        if f.gender:
            ok = {"women": {"women", "unisex"}, "men": {"men", "unisex"}, "kids": {"kids"}}.get(f.gender, {p["gender"]})
            if p["gender"] not in ok and not (f.gender == "kids" and "kids" in p["tags"]):
                return False, []
        variants = [v for v in p["variants"] if v["stock"] > 0]
        if f.size:
            variants = [v for v in variants if v["size"].upper() == f.size.upper()]
        if f.color:
            variants = [v for v in variants if v["color"] == f.color or (f.color == "blue" and v["color"] == "navy")]
        return bool(variants), variants

    def search(self, query: str, limit: int = 4, _relax: bool = True, **overrides) -> dict:
        pq: ParsedQuery = parse_query(query)
        f = SearchFilters(max_price=pq.max_price, min_price=pq.min_price, categories=pq.categories or None,
                          size=pq.size, color=pq.color, gender=pq.gender)
        for k, v in overrides.items():
            if v not in (None, "", []):
                if k == "category":
                    cats = resolve_category(v) if isinstance(v, str) else list(v)
                    # keep the query's own categories when they are a narrower match ("monsoon jacket")
                    if cats and not (pq.categories and set(pq.categories) <= set(cats)):
                        f.categories = cats
                elif hasattr(f, k):
                    setattr(f, k, v)
        qtext = pq.text or query
        qvec = self.embedder.embed([qtext])[0]
        cands = self.vectors.top(qvec, k=len(self.products))
        qtok = set(pq.tokens)
        scored = []
        for pid, sim in cands:
            p = self.products.get(pid)
            if not p:
                continue
            ok, variants = self._passes(p, f)
            if not ok:
                continue
            overlap = len(qtok & set(p["tags"])) / max(1, len(qtok))
            score = sim + 0.25 * overlap + 0.01 * p["rating"]
            if f.gender != "kids" and (p["gender"] == "kids" or "kids" in p["tags"]):
                score -= 0.15  # don't lead with kids' items unless asked
            scored.append((score, p, variants))
        scored.sort(key=lambda x: -x[0])
        results = [self._result(p, variants, score) for score, p, variants in scored[:limit]]
        out = {"query": query, "understood": {"text": qtext, **{k: v for k, v in f.__dict__.items() if v}},
               "results": results}
        if not results and f.max_price is not None and _relax:
            relaxed = self.search(query, limit=3, _relax=False, **{**{k: v for k, v in f.__dict__.items() if k != "categories"},
                                                       "category": f.categories, "max_price": 10**7})
            out["over_budget_alternatives"] = relaxed["results"]
        return out

    @staticmethod
    def _result(p: dict, variants: list[dict], score: float) -> dict:
        return {"product_id": p["id"], "title": p["title"], "category": p["category"], "price": p["price"],
                "mrp": p["mrp"], "rating": p["rating"], "tags": p["tags"], "weight_g": p["weight_g"],
                "available_sizes": sorted({v["size"] for v in variants}),
                "available_colors": sorted({v["color"] for v in variants}), "score": round(score, 4)}


_lock = threading.Lock()
_index: ProductSearch | None = None


def get_search(commerce=None, rebuild: bool = False) -> ProductSearch:
    """Singleton index built from the store's catalog."""
    global _index
    with _lock:
        if _index is None or rebuild:
            from ..commerce import get_commerce
            from ..config import get_settings

            st = get_settings()
            commerce = commerce or get_commerce()
            engine = None
            if st.vector_backend == "pgvector":
                from ..db import get_engine
                engine = get_engine()
            _index = ProductSearch(get_embedder(st.embedder), backend=st.vector_backend, engine=engine)
            _index.build(commerce.list_products())
        return _index


def reset_search() -> None:
    global _index
    with _lock:
        _index = None
