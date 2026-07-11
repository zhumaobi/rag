from __future__ import annotations

from clients.es_client import ESClient
from raglog import get_logger
from naming import active_name, collection_for_tenant
from retrieval.types import RetrievedChunk

log = get_logger("sparse")


class SparseRetriever:
    """BM25 sparse retrieval against Elasticsearch, scoped to the tenant (task 5.2)."""

    def __init__(self, es: ESClient | None = None) -> None:
        self._es = es or ESClient()

    def retrieve(
        self,
        tenant_id: str,
        query_text: str,
        top_k: int = 10,
        collection_id: str | None = None,
    ) -> list[RetrievedChunk]:
        base = collection_id or collection_for_tenant(tenant_id)
        index_alias = active_name(base)
        hits = self._es.search(index_alias, tenant_id, query_text, top_k=top_k)
        return [
            RetrievedChunk(chunk_id=c, doc_id=d, text=t, score=s, source="sparse")
            for (c, d, t, s) in hits
        ]
