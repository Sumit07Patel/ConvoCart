"""Embedders.

`HashingEmbedder` (default): word + character n-gram feature hashing. Runs anywhere, no download,
fully deterministic, so CI results are reproducible. It matches on shared words and spellings,
not on meaning; the query layer (query.py) maps Hindi/Hinglish to catalog words first.

`FastEmbedEmbedder`: a real sentence-embedding model on your machine (EMBEDDER=fastembed,
`pip install fastembed`). Better on paraphrases; needs a one-time model download.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int
    name: str

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _h(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little")


class HashingEmbedder:
    name = "hashing-ngram-v1"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _features(self, text: str) -> dict[str, float]:
        feats: dict[str, float] = {}
        words = [w.rstrip("s") if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
                 for w in re.findall(r"[\w\-]+", text.lower())]
        for w in words:
            feats[f"w:{w}"] = feats.get(f"w:{w}", 0) + 1.0
            padded = f"<{w}>"
            for n in (3, 4):
                for i in range(len(padded) - n + 1):
                    k = f"c{n}:{padded[i:i + n]}"
                    feats[k] = feats.get(k, 0) + 0.25
        for a, b in zip(words, words[1:]):
            feats[f"b:{a}_{b}"] = feats.get(f"b:{a}_{b}", 0) + 0.5
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, t in enumerate(texts):
            for k, v in self._features(t).items():
                h = _h(k)
                out[row, h % self.dim] += (1.0 if (h >> 40) & 1 else -1.0) * (1 + math.log(v) if v >= 1 else v)
            n = np.linalg.norm(out[row])
            if n:
                out[row] /= n
        return out


class FastEmbedEmbedder:  # pragma: no cover - needs model download
    def __init__(self, model: str = "BAAI/bge-small-en-v1.5"):
        from fastembed import TextEmbedding

        self._m = TextEmbedding(model_name=model)
        self.name = f"fastembed:{model}"
        self.dim = len(next(iter(self._m.embed(["probe"]))))

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = np.array(list(self._m.embed(texts)), dtype=np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def get_embedder(kind: str = "hashing") -> Embedder:
    if kind == "fastembed":
        return FastEmbedEmbedder()
    return HashingEmbedder()
