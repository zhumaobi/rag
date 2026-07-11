from __future__ import annotations

import struct

from cache.types import CacheEntry, CacheHit
from config import get_settings
from raglog import get_logger

log = get_logger("l2_cache")

_INDEX_NAME = "idx:semcache"
_KEY_PREFIX = "semcache:"  # hash key prefix; VSS index is built over this prefix


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


class L2Cache:
    """Redis VSS semantic cache (task 6.2).

    Stores each cache entry as a hash with a FLOAT32 embedding field and runs cosine KNN
    queries. Per-tenant isolation is enforced with a tenant_id tag filter in the query so
    one tenant can never match another's cached answer (spec: no cross-tenant leakage).
    """

    def __init__(self, client: "redis.Redis | None" = None) -> None:
        import redis

        s = get_settings()
        self._dim = s.embedding_dim
        self._ttl = s.shadow_retention_hours * 3600  # 24h default
        # bytes client for hash+vector payloads
        self._r = client or redis.Redis.from_url(s.redis_url, decode_responses=False)

    def ensure_index(self) -> None:
        from redis.commands.search.field import TagField, TextField, VectorField
        from redis.commands.search.index_definition import IndexDefinition, IndexType

        try:
            self._r.ft(_INDEX_NAME).info()
            return
        except Exception:
            pass
        schema = [
            TagField("tenant_id"),
            TextField("answer"),
            TextField("query"),
            VectorField(
                "embedding",
                "HNSW",
                {"TYPE": "FLOAT32", "DIM": self._dim, "DISTANCE_METRIC": "COSINE"},
            ),
        ]
        definition = IndexDefinition(prefix=[_KEY_PREFIX], index_type=IndexType.HASH)
        self._r.ft(_INDEX_NAME).create_index(schema, definition=definition)
        log.info("l2_index_created", index=_INDEX_NAME, dim=self._dim)

    def get(self, tenant_id: str, embedding: list[float], threshold: float = 0.92) -> CacheHit | None:
        from redis.commands.search.query import Query

        q = (
            Query(f"(@tenant_id:{{{tenant_id}}})=>[KNN 1 @embedding $vec AS score]")
            .sort_by("score")
            .return_fields("answer", "score")
            .dialect(2)
        )
        try:
            res = self._r.ft(_INDEX_NAME).search(q, query_params={"vec": _pack(embedding)})
        except Exception as exc:
            log.warning("l2_query_failed", error=str(exc))
            return None
        if not res.docs:
            return None
        doc = res.docs[0]
        # RediSearch COSINE distance = 1 - cosine_similarity.
        similarity = 1.0 - float(doc.score)
        if similarity <= threshold:
            return None
        answer = doc.answer.decode() if isinstance(doc.answer, bytes) else doc.answer
        return CacheHit(answer=answer, similarity=similarity, level="L2", cache_key=doc.id)

    def put(self, entry: CacheEntry) -> None:
        key = f"{_KEY_PREFIX}{entry.tenant_id}:{entry.cache_key}"
        mapping = {
            "tenant_id": entry.tenant_id,
            "query": entry.query,
            "answer": entry.answer,
            "embedding": _pack(entry.embedding),
        }
        pipe = self._r.pipeline()
        pipe.hset(key, mapping=mapping)
        pipe.expire(key, self._ttl)
        pipe.execute()

    def delete(self, tenant_id: str, cache_key: str) -> None:
        self._r.delete(f"{_KEY_PREFIX}{tenant_id}:{cache_key}")
