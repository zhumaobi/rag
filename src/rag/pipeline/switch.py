from __future__ import annotations

from clients.es_client import ESClient
from clients.milvus_client import MilvusClient
from clients.neo4j_client import Neo4jClient
from raglog import get_logger

log = get_logger("switch")


class AtomicSwitch:
    """Three-index atomic switch (task 3.11): flip Milvus alias, ES alias, and Neo4j
    active graph version to the freshly validated shadow. Records prior targets so the
    pipeline can roll back within the retention window."""

    def __init__(
        self,
        milvus: MilvusClient | None = None,
        es: ESClient | None = None,
        neo4j: Neo4jClient | None = None,
    ) -> None:
        self._milvus = milvus or MilvusClient()
        self._es = es or ESClient()
        self._neo4j = neo4j or Neo4jClient()

    def capture_current(self, tenant_id: str, vector_alias: str, bm25_alias: str) -> dict:
        return {
            "vector": self._milvus.current_alias_target(vector_alias),
            "bm25": self._es.current_alias_target(bm25_alias),
            "graph": self._neo4j.active_version(tenant_id),
        }

    def switch(
        self,
        tenant_id: str,
        vector_alias: str,
        shadow_collection: str,
        bm25_alias: str,
        shadow_index: str,
        shadow_graph_version: str,
    ) -> None:
        self._milvus.switch_alias(vector_alias, shadow_collection)
        self._es.switch_alias(bm25_alias, shadow_index)
        self._neo4j.switch_active_version(tenant_id, shadow_graph_version)
        log.info(
            "atomic_switch_done",
            tenant_id=tenant_id,
            vector=shadow_collection,
            bm25=shadow_index,
            graph=shadow_graph_version,
        )

    def rollback(
        self, tenant_id: str, vector_alias: str, bm25_alias: str, previous: dict
    ) -> None:
        if previous.get("vector"):
            self._milvus.switch_alias(vector_alias, previous["vector"])
        if previous.get("bm25"):
            self._es.switch_alias(bm25_alias, previous["bm25"])
        if previous.get("graph"):
            self._neo4j.switch_active_version(tenant_id, previous["graph"])
        log.info("atomic_switch_rolled_back", tenant_id=tenant_id, previous=previous)
