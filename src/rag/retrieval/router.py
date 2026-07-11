from __future__ import annotations

import asyncio

from clients.neo4j_client import Neo4jClient
from intent.types import Intent, IntentResult
from observability.tracing import get_tracer
from raglog import get_logger
from retrieval.dense import DenseRetriever
from retrieval.fusion import reciprocal_rank_fusion
from retrieval.rerank import Reranker
from retrieval.sparse import SparseRetriever
from retrieval.types import RetrievedChunk, RetrievalResult

log = get_logger("retrieval_router")

_GRAPH_MAX_HOPS = 3


class RetrievalRouter:
    """Routes a recognized query to the intent-appropriate retrieval strategy.

    Intent-1 (5.5): targeted hybrid retrieval + RRF + rerank -> Top-5.
    Intent-2 (5.6): concurrent per-product hybrid retrieval, grouped by product.
    Intent-3 (5.7/5.8): graph path expansion + vector supplementation, fallback to
                        pure vector when no path/entity exists.

    `embed_fn` maps a query string to its embedding (shared with the online embedder).
    Blocking client calls are offloaded to threads so Intent-2 fan-out is truly parallel.
    """

    def __init__(
        self,
        embed_fn,
        dense: DenseRetriever | None = None,
        sparse: SparseRetriever | None = None,
        reranker: Reranker | None = None,
        neo4j: Neo4jClient | None = None,
    ) -> None:
        self._embed = embed_fn
        self._dense = dense or DenseRetriever()
        self._sparse = sparse or SparseRetriever()
        self._reranker = reranker or Reranker()
        self._neo4j = neo4j or Neo4jClient()

    async def route(self, tenant_id: str, query: str, intent: IntentResult) -> RetrievalResult:
        if intent.intent is Intent.PRECISE:
            return await self._intent1(tenant_id, query, intent)
        if intent.intent is Intent.COMPARE:
            return await self._intent2(tenant_id, query, intent)
        return await self._intent3(tenant_id, query, intent)

    # ---- shared hybrid primitive: dense + sparse -> RRF -> rerank -----------------

    async def _hybrid(
        self,
        tenant_id: str,
        query: str,
        query_embedding: list[float],
        collection_id: str | None,
        recall_k: int,
        final_k: int,
        doc_ids: list[str] | None = None,
    ) -> list[RetrievedChunk]:
        dense_task = asyncio.to_thread(
            self._dense.retrieve, tenant_id, query_embedding, recall_k, collection_id, doc_ids
        )
        sparse_task = asyncio.to_thread(
            self._sparse.retrieve, tenant_id, query, recall_k, collection_id
        )
        tracer = get_tracer()
        with tracer.span("retrieve.dense_sparse", collection=collection_id or "global"):
            dense_hits, sparse_hits = await asyncio.gather(dense_task, sparse_task)
        fused = reciprocal_rank_fusion([dense_hits, sparse_hits], top_k=recall_k)
        with tracer.span("retrieve.rerank", candidates=len(fused)):
            return await asyncio.to_thread(self._reranker.rerank, query, fused, final_k)

    # ---- Intent-1: targeted precise retrieval (task 5.5) --------------------------

    async def _intent1(self, tenant_id: str, query: str, intent: IntentResult) -> RetrievalResult:
        # First entity with a resolved collection_id narrows the search; else global.
        collection_id = next((e.collection_id for e in intent.entities if e.collection_id), None)
        emb = self._embed(query)
        chunks = await self._hybrid(
            tenant_id, query, emb, collection_id, recall_k=20, final_k=5
        )
        return RetrievalResult(chunks=chunks, degraded=collection_id is None)

    # ---- Intent-2: parallel multi-path retrieval (task 5.6) -----------------------

    async def _intent2(self, tenant_id: str, query: str, intent: IntentResult) -> RetrievalResult:
        products = intent.entities or []
        emb = self._embed(query)

        if len(products) < 2:
            # Not enough products to compare; degrade to a single hybrid pass.
            chunks = await self._hybrid(tenant_id, query, emb, None, recall_k=20, final_k=6)
            return RetrievalResult(chunks=chunks, degraded=True)

        async def one_product(entity):
            hits = await self._hybrid(
                tenant_id, query, emb, entity.collection_id, recall_k=10, final_k=3
            )
            return entity.name, hits

        pairs = await asyncio.gather(*(one_product(e) for e in products))
        groups = {name: hits for name, hits in pairs}
        merged: list[RetrievedChunk] = []
        for hits in groups.values():
            merged.extend(hits)
        return RetrievalResult(chunks=merged, groups=groups)

    # ---- Intent-3: graph-assisted retrieval + fallback (tasks 5.7 / 5.8) ----------

    async def _intent3(self, tenant_id: str, query: str, intent: IntentResult) -> RetrievalResult:
        emb = self._embed(query)
        tracer = get_tracer()
        with tracer.span("retrieve.graph", entities=len(intent.entities)):
            version = await asyncio.to_thread(self._neo4j.active_version, tenant_id)
            entities = [e.name for e in intent.entities]

            graph_doc_ids: list[str] = []
            graph_paths: list[list[str]] = []
            if version and len(entities) >= 2:
                graph_paths, graph_doc_ids = await asyncio.to_thread(
                    self._neo4j.find_paths, tenant_id, entities[0], entities[1], version, _GRAPH_MAX_HOPS
                )
            elif version and len(entities) == 1:
                graph_doc_ids = await asyncio.to_thread(
                    self._neo4j.neighbor_doc_ids, tenant_id, entities[0], version, _GRAPH_MAX_HOPS
                )

        if graph_doc_ids:
            # Vector supplementation constrained to graph-associated docs + a global pass.
            graph_hits = await self._hybrid(
                tenant_id, query, emb, None, recall_k=20, final_k=5, doc_ids=graph_doc_ids
            )
            global_hits = await self._hybrid(tenant_id, query, emb, None, recall_k=20, final_k=5)
            fused = reciprocal_rank_fusion([graph_hits, global_hits], top_k=6)
            return RetrievalResult(chunks=fused, graph_paths=graph_paths)

        # Fallback (task 5.8): no path/entity -> pure vector, no graph relations cited.
        chunks = await self._hybrid(tenant_id, query, emb, None, recall_k=20, final_k=6)
        log.info("intent3_fallback_pure_vector", tenant_id=tenant_id, entities=len(entities))
        return RetrievalResult(chunks=chunks, degraded=True)
