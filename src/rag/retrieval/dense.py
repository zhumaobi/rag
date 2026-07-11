from __future__ import annotations

from clients.milvus_client import MilvusClient
from raglog import get_logger
from naming import active_name, collection_for_tenant
from retrieval.types import RetrievedChunk

log = get_logger("dense")


class DenseRetriever:
    """Dense vector retrieval against Milvus (task 5.1).

    Targeting rules:
    - explicit collection_id (from entity recognition) -> query that collection's active alias
    - else the tenant's own collection alias
    - small tenants share `docs_shared_small`; doc_id filter narrows within a shared collection
    Retrieval never crosses tenants: the collection itself is the isolation boundary.
    """

    def __init__(self, milvus: MilvusClient | None = None) -> None:
        self._milvus = milvus or MilvusClient()

    def retrieve(
        self,
        tenant_id: str,
        query_embedding: list[float],
        top_k: int = 10,
        collection_id: str | None = None,
        doc_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        alias = self._resolve_alias(tenant_id, collection_id)
        hits = self._milvus.search(alias, query_embedding, top_k=top_k, doc_ids=doc_ids)
        return [
            RetrievedChunk(chunk_id=c, doc_id=d, text=t, score=s, source="dense")
            for (c, d, t, s) in hits
        ]

    @staticmethod
    def _resolve_alias(tenant_id: str, collection_id: str | None) -> str:
        if collection_id:
            return active_name(collection_id)
        return active_name(collection_for_tenant(tenant_id))
