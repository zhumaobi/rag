from __future__ import annotations

import json

from config import get_settings
from raglog import get_logger

log = get_logger("redis")


class RedisClient:
    """Wraps Redis for the offline pipeline: doc_id -> cache_key reverse index and
    precise semantic-cache invalidation on document update."""

    def __init__(self) -> None:
        import redis

        s = get_settings()
        self._r = redis.Redis.from_url(s.redis_url, decode_responses=True)

    def _reverse_key(self, tenant_id: str, doc_id: str) -> str:
        return f"revidx:{tenant_id}:{doc_id}"

    def add_cache_ref(self, tenant_id: str, doc_ids: list[str], cache_key: str) -> None:
        """Called by the online path when a cache entry is written."""
        pipe = self._r.pipeline()
        for doc_id in doc_ids:
            pipe.sadd(self._reverse_key(tenant_id, doc_id), cache_key)
        pipe.execute()

    def invalidate_docs(self, tenant_id: str, doc_ids: list[str]) -> int:
        """Precisely evict every semantic-cache entry that referenced a changed doc."""
        deleted = 0
        pipe = self._r.pipeline()
        for doc_id in doc_ids:
            rev = self._reverse_key(tenant_id, doc_id)
            cache_keys = self._r.smembers(rev)
            for ck in cache_keys:
                pipe.delete(ck)
                deleted += 1
            pipe.delete(rev)
        pipe.execute()
        log.info("cache_invalidated", tenant_id=tenant_id, docs=len(doc_ids), evicted=deleted)
        return deleted

    def hot_queries(self, tenant_id: str, top: int = 50) -> list[str]:
        """Top-N hottest queries tracked online (sorted set of query -> count)."""
        key = f"hotq:{tenant_id}"
        return [q for q, _ in self._r.zrevrange(key, 0, top - 1, withscores=True)]

    def set_pipeline_state(self, run_id: str, state: dict) -> None:
        self._r.set(f"pipeline:{run_id}", json.dumps(state))

    def get_pipeline_state(self, run_id: str) -> dict | None:
        raw = self._r.get(f"pipeline:{run_id}")
        return json.loads(raw) if raw else None
