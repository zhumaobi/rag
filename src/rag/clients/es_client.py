from __future__ import annotations

from config import get_settings
from raglog import get_logger

log = get_logger("elasticsearch")

_BM25_MAPPING = {
    "settings": {"index": {"number_of_shards": 3, "number_of_replicas": 1}},
    "mappings": {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "doc_id": {"type": "keyword"},
            "tenant_id": {"type": "keyword"},
            "ordinal": {"type": "integer"},
            "text": {"type": "text", "analyzer": "standard"},
        }
    },
}


class ESClient:
    """Wraps Elasticsearch for BM25 shadow index build + alias switch."""

    def __init__(self) -> None:
        from elasticsearch import Elasticsearch

        s = get_settings()
        self._es = Elasticsearch(s.es_hosts.split(","))

    def create_shadow(self, index: str) -> None:
        if self._es.indices.exists(index=index):
            self._es.indices.delete(index=index)
        self._es.indices.create(index=index, **_BM25_MAPPING)
        log.info("shadow_index_created", index=index)

    def bulk_index(self, index: str, rows: list[dict]) -> int:
        from elasticsearch import helpers

        actions = [{"_index": index, "_id": r["chunk_id"], "_source": r} for r in rows]
        success, _ = helpers.bulk(self._es, actions, refresh=False)
        return success

    def search(
        self, index: str, tenant_id: str, query_text: str, top_k: int = 10
    ) -> list[tuple[str, str, str, float]]:
        """BM25 search scoped to a tenant. Returns (chunk_id, doc_id, text, score)."""
        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": {"match": {"text": query_text}},
                    "filter": {"term": {"tenant_id": tenant_id}},
                }
            },
        }
        resp = self._es.search(index=index, **body)
        hits: list[tuple[str, str, str, float]] = []
        for h in resp["hits"]["hits"]:
            src = h["_source"]
            hits.append((src["chunk_id"], src["doc_id"], src.get("text", ""), float(h["_score"])))
        return hits

    def refresh(self, index: str) -> None:
        self._es.indices.refresh(index=index)

    def count(self, index: str) -> int:
        self.refresh(index)
        return int(self._es.count(index=index)["count"])

    def switch_alias(self, alias: str, target_index: str) -> None:
        """Atomically remove alias from old indices and add to target."""
        actions: list[dict] = []
        if self._es.indices.exists_alias(name=alias):
            current = self._es.indices.get_alias(name=alias)
            for old_index in current:
                actions.append({"remove": {"index": old_index, "alias": alias}})
        actions.append({"add": {"index": target_index, "alias": alias}})
        self._es.indices.update_aliases(actions=actions)
        log.info("alias_switched", alias=alias, target=target_index)

    def current_alias_target(self, alias: str) -> str | None:
        if not self._es.indices.exists_alias(name=alias):
            return None
        return next(iter(self._es.indices.get_alias(name=alias)), None)

    def delete_index(self, index: str) -> None:
        if self._es.indices.exists(index=index):
            self._es.indices.delete(index=index)
            log.info("index_deleted", index=index)
