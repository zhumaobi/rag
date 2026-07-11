from __future__ import annotations

from dataclasses import dataclass

from clients.postgres_client import PostgresClient
from clients.redis_client import RedisClient
from raglog import get_logger
from models import ChangeSet, DocStatus
from naming import (
    active_name,
    collection_for_tenant,
    shadow_name,
)
from pipeline.bm25_index import BM25IndexBuilder
from pipeline.cache_invalidate import CacheInvalidator
from pipeline.change_detect import detect_changes
from pipeline.chunk import chunk_document
from pipeline.embed import Embedder
from pipeline.graph.builder import GraphBuilder
from pipeline.graph.ner import EntityExtractor
from pipeline.graph.relation import RelationExtractor
from pipeline.ingest import Ingestor
from pipeline.state_machine import PipelineState, StateMachine
from pipeline.switch import AtomicSwitch
from pipeline.validate import SwitchValidator
from pipeline.vector_index import VectorIndexBuilder

log = get_logger("orchestrator")


@dataclass
class PipelineResult:
    run_id: str
    tenant_id: str
    state: PipelineState
    changeset: ChangeSet
    stats: dict


class IndexPipeline:
    """Orchestrates the full offline index build for one tenant with the PENDING ->
    PROCESSING -> VALIDATING -> READY -> SWITCHING -> DONE state machine and rollback
    on any failure (task 3.13). Builds all three indices on shadow, validates, then
    performs a single atomic switch; if the switch or any stage fails, aliases are
    rolled back and shadow artifacts left for inspection."""

    def __init__(
        self,
        domain_terms: dict[str, str],
        ingestor: Ingestor | None = None,
        embedder: Embedder | None = None,
        vector_builder: VectorIndexBuilder | None = None,
        bm25_builder: BM25IndexBuilder | None = None,
        entity_extractor: EntityExtractor | None = None,
        relation_extractor: RelationExtractor | None = None,
        graph_builder: GraphBuilder | None = None,
        validator: SwitchValidator | None = None,
        switcher: AtomicSwitch | None = None,
        cache_invalidator: CacheInvalidator | None = None,
        pg: PostgresClient | None = None,
        redis: RedisClient | None = None,
    ) -> None:
        self._ingestor = ingestor or Ingestor()
        self._embedder = embedder or Embedder()
        self._vector_builder = vector_builder or VectorIndexBuilder()
        self._bm25_builder = bm25_builder or BM25IndexBuilder()
        self._entity_extractor = entity_extractor or EntityExtractor(domain_terms)
        self._relation_extractor = relation_extractor or RelationExtractor()
        self._graph_builder = graph_builder or GraphBuilder()
        self._validator = validator or SwitchValidator()
        self._switcher = switcher or AtomicSwitch()
        self._cache_invalidator = cache_invalidator or CacheInvalidator()
        self._pg = pg or PostgresClient()
        self._redis = redis or RedisClient()

    def run(self, tenant_id: str, run_id: str) -> PipelineResult:
        sm = StateMachine()
        base = collection_for_tenant(tenant_id)
        vector_alias, bm25_alias = active_name(base), active_name(base)
        shadow_collection = shadow_name(base) + f"_{run_id}"
        shadow_index = shadow_name(base) + f"_{run_id}"
        shadow_graph_version = f"v_{run_id}"
        self._persist(run_id, tenant_id, sm.state, "")

        previous = self._switcher.capture_current(tenant_id, vector_alias, bm25_alias)

        try:
            sm.to(PipelineState.PROCESSING)
            self._persist(run_id, tenant_id, sm.state, "")

            docs = self._ingestor.ingest_tenant(tenant_id)
            changeset = detect_changes(tenant_id, docs, self._pg)
            if changeset.is_empty:
                sm.to(PipelineState.VALIDATING)
                sm.to(PipelineState.READY)
                sm.to(PipelineState.SWITCHING)
                sm.to(PipelineState.DONE)
                self._persist(run_id, tenant_id, sm.state, "no changes")
                return PipelineResult(run_id, tenant_id, sm.state, changeset, {"skipped": True})

            # Chunk + embed the full active doc set for the shadow (full rebuild of shadow).
            all_chunks = []
            for doc in docs:
                all_chunks.extend(chunk_document(doc))
            self._embedder.embed_chunks(all_chunks)

            # Three-index parallel build on shadow.
            v_written = self._vector_builder.build_shadow(shadow_collection, all_chunks)
            b_written = self._bm25_builder.build_shadow(shadow_index, all_chunks)

            entities = self._entity_extractor.extract(all_chunks)
            entity_embeddings = self._embed_entities(entities)
            relations = self._relation_extractor.extract(all_chunks, entities)
            graph_stats = self._graph_builder.build_shadow(
                tenant_id, shadow_graph_version, changeset, entities, relations, entity_embeddings
            )

            sm.to(PipelineState.VALIDATING)
            self._persist(run_id, tenant_id, sm.state, "")
            result = self._validator.validate(
                tenant_id, shadow_collection, shadow_index, self._embedder.embed_texts
            )
            if not result.ok:
                raise RuntimeError(f"validation failed: {result.reasons}")

            sm.to(PipelineState.READY)
            self._persist(run_id, tenant_id, sm.state, "")

            sm.to(PipelineState.SWITCHING)
            self._persist(run_id, tenant_id, sm.state, "")
            self._switcher.switch(
                tenant_id, vector_alias, shadow_collection, bm25_alias,
                shadow_index, shadow_graph_version,
            )

            # Post-switch: precise cache invalidation + mark docs ready + drop deleted metadata.
            evicted = self._cache_invalidator.invalidate(tenant_id, changeset)
            for doc in docs:
                self._pg.upsert_document(doc.doc_id, tenant_id, doc.key, doc.content_hash, DocStatus.READY)
            self._pg.delete_documents(changeset.deleted)

            sm.to(PipelineState.DONE)
            stats = {
                "vectors": v_written,
                "bm25": b_written,
                "cache_evicted": evicted,
                **graph_stats,
            }
            self._persist(run_id, tenant_id, sm.state, "", stats)
            log.info("pipeline_done", run_id=run_id, tenant_id=tenant_id, **stats)
            return PipelineResult(run_id, tenant_id, sm.state, changeset, stats)

        except Exception as exc:
            log.error("pipeline_failed", run_id=run_id, tenant_id=tenant_id, error=str(exc))
            self._safe_rollback(sm, tenant_id, vector_alias, bm25_alias, previous)
            self._persist(run_id, tenant_id, sm.state, str(exc))
            raise

    def _embed_entities(self, entities: dict) -> dict[str, list[float]]:
        if not entities:
            return {}
        names = list(entities)
        vectors = self._embedder.embed_texts(names)
        return dict(zip(names, vectors))

    def _safe_rollback(self, sm, tenant_id, vector_alias, bm25_alias, previous) -> None:
        # Only aliases already flipped need rollback; capture_current gives the prior targets.
        if sm.state == PipelineState.SWITCHING:
            self._switcher.rollback(tenant_id, vector_alias, bm25_alias, previous)
            sm.to(PipelineState.ROLLED_BACK)
        else:
            sm.to(PipelineState.FAILED)
            sm.to(PipelineState.ROLLED_BACK)

    def _persist(self, run_id, tenant_id, state, note, stats=None) -> None:
        self._redis.set_pipeline_state(
            run_id,
            {"tenant_id": tenant_id, "state": state.value, "note": note, "stats": stats or {}},
        )
