from __future__ import annotations

from clients.redis_client import RedisClient
from raglog import get_logger
from models import ChangeSet

log = get_logger("cache_invalidate")


class CacheInvalidator:
    """Precise semantic-cache invalidation (task 3.12).

    Uses the doc_id -> cache_key reverse index (maintained online at cache-write time)
    to evict only entries whose answers cited a changed or deleted document, preserving
    the ~50% hit rate instead of flushing the whole tenant namespace.
    """

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or RedisClient()

    def invalidate(self, tenant_id: str, changeset: ChangeSet) -> int:
        affected = changeset.upserted + changeset.deleted
        if not affected:
            return 0
        return self._redis.invalidate_docs(tenant_id, affected)
