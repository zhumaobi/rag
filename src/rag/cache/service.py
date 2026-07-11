from __future__ import annotations

import asyncio
import hashlib

from cache.l1_cache import L1Cache
from cache.l2_cache import L2Cache
from cache.metrics import HitRateMonitor
from cache.types import CacheEntry, CacheHit
from clients.redis_client import RedisClient
from raglog import get_logger

log = get_logger("semantic_cache")

_SIM_THRESHOLD = 0.92


class SemanticCache:
    """Two-level semantic cache orchestrator (tasks 6.3 - 6.6).

    Read path: time-sensitive bypass -> L1 (local, <1ms) -> L2 (Redis VSS) -> miss.
    On an L2 hit the entry is promoted into L1 for subsequent sub-ms hits.
    Write path: fire-and-forget async write to L2 + L1 + doc_id reverse index, so it
    never blocks the user response.
    """

    def __init__(
        self,
        l1: L1Cache | None = None,
        l2: L2Cache | None = None,
        redis_client: RedisClient | None = None,
        monitor: HitRateMonitor | None = None,
        threshold: float = _SIM_THRESHOLD,
    ) -> None:
        self._l1 = l1 or L1Cache(threshold=threshold)
        self._l2 = l2 or L2Cache()
        self._redis = redis_client or RedisClient()
        self._monitor = monitor or HitRateMonitor()
        self._threshold = threshold

    @staticmethod
    def _cache_key(tenant_id: str, query: str) -> str:
        return hashlib.sha1(f"{tenant_id}:{query}".encode("utf-8")).hexdigest()

    def lookup(
        self, tenant_id: str, query: str, embedding: list[float], time_sensitive: bool = False
    ) -> CacheHit | None:
        """Task 6.3: cosine>threshold hit; time-sensitive queries force a full RAG pass."""
        if time_sensitive:
            self._monitor.record(hit=False)
            return None

        hit = self._l1.get(tenant_id, embedding)
        if hit is not None:
            self._monitor.record(hit=True)
            return hit

        hit = self._l2.get(tenant_id, embedding, self._threshold)
        if hit is not None:
            # Promote to L1 so repeat asks are served locally.
            self._l1.put(
                CacheEntry(
                    cache_key=hit.cache_key, tenant_id=tenant_id, query=query,
                    answer=hit.answer, embedding=embedding,
                )
            )
            self._monitor.record(hit=True)
            return hit

        self._monitor.record(hit=False)
        return None

    async def store_async(
        self, tenant_id: str, query: str, answer: str, embedding: list[float], doc_ids: list[str]
    ) -> None:
        """Task 6.4: non-blocking background write. Callers should not await this on the
        response path; schedule it with asyncio.create_task after returning to the user."""
        await asyncio.to_thread(self._store, tenant_id, query, answer, embedding, doc_ids)

    def _store(
        self, tenant_id: str, query: str, answer: str, embedding: list[float], doc_ids: list[str]
    ) -> None:
        cache_key = self._cache_key(tenant_id, query)
        entry = CacheEntry(
            cache_key=cache_key, tenant_id=tenant_id, query=query,
            answer=answer, embedding=embedding, doc_ids=doc_ids,
        )
        self._l2.put(entry)
        self._l1.put(entry)
        # Task 6.5: maintain doc_id -> cache_key reverse index for precise invalidation.
        if doc_ids:
            self._redis.add_cache_ref(tenant_id, doc_ids, f"semcache:{tenant_id}:{cache_key}")
        log.info("cache_stored", tenant_id=tenant_id, cache_key=cache_key, docs=len(doc_ids))

    def hit_rate(self) -> float:
        return self._monitor.hit_rate()

    def check_alert(self) -> bool:
        return self._monitor.check_alert()
