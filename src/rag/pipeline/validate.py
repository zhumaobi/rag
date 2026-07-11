from __future__ import annotations

from dataclasses import dataclass

from clients.es_client import ESClient
from clients.milvus_client import MilvusClient
from clients.redis_client import RedisClient
from raglog import get_logger

log = get_logger("validate")


@dataclass
class ValidationResult:
    ok: bool
    reasons: list[str]


class SwitchValidator:
    """Pre-switch gate (task 3.10): chunk-count reconciliation between the two shadow
    indices, plus a Top-50 hot-query retrieval sanity check on the shadow vector index."""

    def __init__(
        self,
        milvus: MilvusClient | None = None,
        es: ESClient | None = None,
        redis: RedisClient | None = None,
    ) -> None:
        self._milvus = milvus or MilvusClient()
        self._es = es or ESClient()
        self._redis = redis or RedisClient()

    def validate(
        self,
        tenant_id: str,
        shadow_collection: str,
        shadow_index: str,
        embed_fn,
        count_tolerance: float = 0.01,
        min_hit_rate: float = 0.9,
    ) -> ValidationResult:
        reasons: list[str] = []

        # 1) Count reconciliation between Milvus and ES shadow indices.
        milvus_n = self._milvus.count(shadow_collection)
        es_n = self._es.count(shadow_index)
        if milvus_n == 0:
            reasons.append("shadow vector index is empty")
        elif abs(milvus_n - es_n) / max(milvus_n, 1) > count_tolerance:
            reasons.append(f"count mismatch: milvus={milvus_n} es={es_n}")

        # 2) Top-50 hot-query retrieval check against the shadow vector index.
        hot = self._redis.hot_queries(tenant_id, top=50)
        if hot:
            vectors = embed_fn(hot)
            from pymilvus import Collection

            col = Collection(shadow_collection)
            results = col.search(
                data=vectors,
                anns_field="embedding",
                param={"metric_type": "IP", "params": {"ef": 64}},
                limit=5,
                output_fields=["doc_id"],
            )
            hits = sum(1 for r in results if len(r) > 0)
            hit_rate = hits / len(hot)
            if hit_rate < min_hit_rate:
                reasons.append(f"hot-query hit rate {hit_rate:.2f} < {min_hit_rate}")

        ok = not reasons
        log.info("switch_validation", tenant_id=tenant_id, ok=ok, reasons=reasons)
        return ValidationResult(ok=ok, reasons=reasons)
