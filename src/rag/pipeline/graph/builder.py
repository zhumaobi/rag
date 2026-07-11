from __future__ import annotations

from clients.neo4j_client import Neo4jClient
from config import get_settings
from raglog import get_logger
from models import ChangeSet, Entity, Relation

log = get_logger("graph_builder")


class GraphBuilder:
    """Builds the Shadow graph version: incremental diff (3.8) + confidence-routed write (3.9).

    Strategy: clone the active graph into a shadow version, delete all edges owned by
    changed/deleted docs, then write freshly extracted relations. High-confidence
    relations auto-ingest; low-confidence ones go to a human review queue. Finally
    orphan nodes (no remaining edges) are pruned.
    """

    def __init__(self, neo4j: Neo4jClient | None = None) -> None:
        self._neo4j = neo4j or Neo4jClient()
        self._threshold = get_settings().kg_confidence_threshold

    def build_shadow(
        self,
        tenant_id: str,
        shadow_version: str,
        changeset: ChangeSet,
        entities: dict[str, Entity],
        relations: list[Relation],
        embeddings: dict[str, list[float]],
    ) -> dict:
        active = self._neo4j.active_version(tenant_id)
        if active:
            self._neo4j.copy_active_to_shadow(tenant_id, active, shadow_version)

        # 3.8: remove edges owned by changed or deleted docs before re-adding fresh ones.
        stale_docs = changeset.upserted + changeset.deleted
        removed = self._neo4j.delete_edges_for_docs(tenant_id, stale_docs, shadow_version)

        # Upsert entity nodes (embeddings attached for node-associated vector search).
        for name, ent in entities.items():
            self._neo4j.upsert_entity(
                tenant_id=tenant_id,
                name=name,
                entity_type=ent.entity_type,
                doc_ids=sorted(ent.doc_ids),
                embedding=embeddings.get(name, []),
                graph_version=shadow_version,
            )

        # 3.9: confidence-based routing.
        auto, review = 0, 0
        for rel in relations:
            if rel.confidence >= self._threshold:
                self._neo4j.upsert_relation(
                    tenant_id=tenant_id,
                    source=rel.source,
                    target=rel.target,
                    rel_type=rel.relation_type.value,
                    confidence=rel.confidence,
                    doc_id=rel.doc_id,
                    graph_version=shadow_version,
                )
                auto += 1
            else:
                self._neo4j.enqueue_review(
                    tenant_id,
                    {
                        "source": rel.source,
                        "target": rel.target,
                        "rel_type": rel.relation_type.value,
                        "confidence": rel.confidence,
                        "doc_id": rel.doc_id,
                    },
                )
                review += 1

        orphans = self._neo4j.delete_orphan_nodes(tenant_id, shadow_version)
        stats = {"edges_removed": removed, "auto_ingested": auto, "queued_review": review, "orphans_pruned": orphans}
        log.info("graph_shadow_built", tenant_id=tenant_id, version=shadow_version, **stats)
        return stats
