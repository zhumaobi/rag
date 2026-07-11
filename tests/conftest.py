"""Shared fakes for integration tests so suites run without live infrastructure.

These stand in for Milvus/ES/Neo4j/Redis/vLLM at the client boundary, letting the
routing, degradation, isolation, and rollout logic be exercised deterministically.
"""
from __future__ import annotations

from rag.intent.types import EntityMatch, Intent, IntentResult
from rag.retrieval.types import RetrievedChunk, RetrievalResult


class FakeEmbedder:
    """Deterministic embeddings: hash text to a small fixed-dim vector."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    def _vec(self, text: str) -> list[float]:
        h = abs(hash(text))
        return [((h >> (i * 3)) & 7) / 7.0 for i in range(self._dim)]

    def embed_texts(self, texts):
        return [self._vec(t) for t in texts]

    def __call__(self, text: str):
        return self._vec(text)


class FakeIntentService:
    """Rule-only intent service driven by keyword cues; no model dependency."""

    def recognize(self, tenant_id: str, query: str) -> IntentResult:
        if any(k in query for k in ("对比", "vs", "区别", "比较")):
            intent = Intent.COMPARE
        elif any(k in query for k in ("关系", "是什么", "依赖", "概念")):
            intent = Intent.RELATION
        else:
            intent = Intent.PRECISE
        entities = [EntityMatch(name=w, collection_id=f"{tenant_id}_{w}") for w in query.split() if w.isalpha()]
        return IntentResult(intent=intent, confidence=0.95, entities=entities, source="rule")


class FakeCorpus:
    """Per-tenant doc store. Retrieval returns only the queried tenant's docs, so
    cross-tenant leakage would surface as a test failure (task 10.2)."""

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, str]] = {}

    def add(self, tenant_id: str, doc_id: str, text: str) -> None:
        self._docs.setdefault(tenant_id, {})[doc_id] = text

    def retrieve(self, tenant_id: str, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        docs = self._docs.get(tenant_id, {})
        out = []
        for doc_id, text in docs.items():
            score = sum(1 for w in query.split() if w in text)
            if score:
                out.append(RetrievedChunk(chunk_id=f"{doc_id}#0", doc_id=doc_id, text=text, score=float(score), source="dense"))
        out.sort(key=lambda c: c.score, reverse=True)
        return out[:top_k]
