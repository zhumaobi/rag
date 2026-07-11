from __future__ import annotations

from typing import Optional

from config import get_settings
from raglog import get_logger

log = get_logger("milvus")

_pm = None


def _milvus():
    """Lazily import pymilvus symbols so this module imports without the package."""
    global _pm
    if _pm is None:
        from pymilvus import DataType, MilvusClient as _PMClient

        _pm = {"MilvusClient": _PMClient, "DataType": DataType}
    return _pm


class MilvusClient:
    """Wraps Milvus operations for the offline pipeline: shadow build + alias switch.

    Backed by the pymilvus high-level MilvusClient rather than the ORM
    connections/Collection API, so all state lives on a single client handle.
    """

    def __init__(self) -> None:
        s = get_settings()
        self._dim = s.embedding_dim
        self._client = _milvus()["MilvusClient"](uri=f"http://{s.milvus_host}:{s.milvus_port}")

    def _schema(self):
        DataType = _milvus()["DataType"]
        schema = self._client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("chunk_id", DataType.VARCHAR, is_primary=True, max_length=128)
        schema.add_field("doc_id", DataType.VARCHAR, max_length=128)
        schema.add_field("tenant_id", DataType.VARCHAR, max_length=64)
        schema.add_field("ordinal", DataType.INT64)
        schema.add_field("text", DataType.VARCHAR, max_length=8192)
        schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=self._dim)
        return schema

    def _index_params(self):
        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="IP",
            params={"M": 16, "efConstruction": 200},
        )
        return index_params

    def create_shadow(self, name: str) -> None:
        if self._client.has_collection(name):
            self._client.drop_collection(name)
        self._client.create_collection(
            collection_name=name,
            schema=self._schema(),
            index_params=self._index_params(),
        )
        log.info("shadow_collection_created", name=name)

    def insert(self, name: str, rows: list[dict]) -> None:
        self._client.insert(collection_name=name, data=rows)

    def flush_and_load(self, name: str) -> None:
        self._client.flush(name)
        self._client.load_collection(name)

    def search(
        self,
        name: str,
        query_embedding: list[float],
        top_k: int = 10,
        doc_ids: Optional[list[str]] = None,
    ) -> list[tuple[str, str, str, float]]:
        """Dense search against a collection/alias. Returns (chunk_id, doc_id, text, score)."""
        expr = ""
        if doc_ids:
            joined = ",".join(f'"{d}"' for d in doc_ids)
            expr = f"doc_id in [{joined}]"
        results = self._client.search(
            collection_name=name,
            data=[query_embedding],
            anns_field="embedding",
            search_params={"metric_type": "IP", "params": {"ef": 128}},
            limit=top_k,
            filter=expr,
            output_fields=["chunk_id", "doc_id", "text"],
        )
        hits: list[tuple[str, str, str, float]] = []
        for hit in results[0]:
            entity = hit.get("entity", {})
            hits.append(
                (
                    entity.get("chunk_id"),
                    entity.get("doc_id"),
                    entity.get("text"),
                    float(hit.get("distance")),
                )
            )
        return hits

    def count(self, name: str) -> int:
        self._client.flush(name)
        return int(self._client.get_collection_stats(name).get("row_count", 0))

    def switch_alias(self, alias: str, target_collection: str) -> None:
        """Atomically point alias to target collection (< 1ms)."""
        if alias in _existing_aliases(self._client):
            self._client.alter_alias(target_collection, alias)
        else:
            self._client.create_alias(target_collection, alias)
        log.info("alias_switched", alias=alias, target=target_collection)

    def current_alias_target(self, alias: str) -> Optional[str]:
        try:
            return self._client.describe_alias(alias).get("collection")
        except Exception:
            return None

    def drop(self, name: str) -> None:
        if self._client.has_collection(name):
            self._client.drop_collection(name)
            log.info("collection_dropped", name=name)


def _existing_aliases(client) -> set[str]:
    try:
        return set(client.list_aliases())
    except Exception:
        return set()
