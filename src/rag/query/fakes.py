from __future__ import annotations

import hashlib
import math

from intent.types import EntityMatch, Intent
from retrieval.types import RetrievedChunk


_DIM = 1024


class FakeEmbedder:
    """Deterministic stand-in for pipeline.embed.Embedder (no bge-m3 load).

    Produces a stable, normalized `_DIM`-vector seeded from the text hash so the same
    query always embeds identically, without any model or GPU.
    """

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str) -> list[float]:
        seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)
        vals: list[float] = []
        x = seed
        for _ in range(_DIM):
            # Deterministic LCG step; no Math.random / time dependence.
            x = (1103515245 * x + 12345) & 0x7FFFFFFF
            vals.append((x / 0x7FFFFFFF) * 2.0 - 1.0)
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]


class FakeEntityRecognizer:
    """Returns two canned entities so COMPARE fans out and RELATION traverses a path,
    without touching the Redis-backed EntityDictionary."""

    def recognize(self, tenant_id: str, query: str) -> list[EntityMatch]:
        return [
            EntityMatch(name="ProductA", collection_id="collA"),
            EntityMatch(name="ProductB", collection_id="collB"),
        ]


class FakeClassifier:
    """Model-free classifier for the fall-through (non-rule) path, e.g. PRECISE queries."""

    def predict(self, query: str) -> tuple[Intent, float]:
        return Intent.PRECISE, 0.90


class _FakeDense:
    def retrieve(self, tenant_id, query_embedding, top_k=10, collection_id=None, doc_ids=None):
        tag = collection_id or "global"
        return [
            RetrievedChunk(
                chunk_id=f"{tag}-d{i}", doc_id=f"doc-{tag}-{i}",
                text=f"[dense:{tag}] canned passage {i} for {tenant_id}",
                score=1.0 - i * 0.1, source="dense",
            )
            for i in range(min(top_k, 3))
        ]


class _FakeSparse:
    def retrieve(self, tenant_id, query_text, top_k=10, collection_id=None):
        tag = collection_id or "global"
        return [
            RetrievedChunk(
                chunk_id=f"{tag}-s{i}", doc_id=f"doc-{tag}-{i}",
                text=f"[sparse:{tag}] canned passage {i}",
                score=1.0 - i * 0.1, source="sparse",
            )
            for i in range(min(top_k, 3))
        ]


class _FakeReranker:
    def rerank(self, query, candidates, top_k=5):
        return candidates[:top_k]


class _FakeNeo4j:
    def active_version(self, tenant_id):
        return "v1"

    def find_paths(self, tenant_id, src, dst, version, hops):
        paths = [[src, "relates_to", dst]]
        doc_ids = ["doc-collA-0", "doc-collB-0"]
        return paths, doc_ids

    def neighbor_doc_ids(self, tenant_id, entity, version, hops):
        return ["doc-collA-0"]


class FakeVLLM:
    """Stand-in for VLLMClient matching its async generate signature (mirrors the
    _FakeVLLM pattern in serving/loadtest.py) so the real Dispatcher runs unmodified."""

    async def generate(self, instance, model, prompt, max_tokens) -> str:
        return f"[{model}] simulated answer ({max_tokens} tok budget)"


class FakeCache:
    """Force-miss cache: always misses on lookup, no-ops on store. Avoids Redis/L2."""

    def lookup(self, tenant_id, query, embedding, time_sensitive=False):
        return None

    async def store_async(self, tenant_id, query, answer, embedding, doc_ids) -> None:
        return None


def fake_retriever_kwargs() -> dict:
    """Injectable fakes for RetrievalRouter's leaf collaborators."""
    return {
        "dense": _FakeDense(),
        "sparse": _FakeSparse(),
        "reranker": _FakeReranker(),
        "neo4j": _FakeNeo4j(),
    }
