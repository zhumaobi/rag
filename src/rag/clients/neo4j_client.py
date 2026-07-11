from __future__ import annotations

from contextlib import contextmanager

from config import get_settings
from raglog import get_logger

log = get_logger("neo4j")


class Neo4jClient:
    """Wraps Neo4j. Tenant isolation via mandatory tenant_id property on every node/query.

    Shadow/Active separation is modeled with a `graph_version` property so a switch is
    an atomic pointer update in the meta node rather than physical index rebuild.
    """

    def __init__(self) -> None:
        from neo4j import GraphDatabase

        s = get_settings()
        self._driver = GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password))

    def close(self) -> None:
        self._driver.close()

    @contextmanager
    def _session(self):
        with self._driver.session() as session:
            yield session

    def ensure_constraints(self) -> None:
        with self._session() as s:
            s.run(
                "CREATE CONSTRAINT entity_key IF NOT EXISTS "
                "FOR (e:Entity) REQUIRE (e.tenant_id, e.name, e.graph_version) IS UNIQUE"
            )

    def upsert_entity(
        self, tenant_id: str, name: str, entity_type: str, doc_ids: list[str],
        embedding: list[float], graph_version: str,
    ) -> None:
        with self._session() as s:
            s.run(
                "MERGE (e:Entity {tenant_id:$tid, name:$name, graph_version:$gv}) "
                "SET e.entity_type=$etype, e.doc_ids=$docs, e.embedding=$emb",
                tid=tenant_id, name=name, etype=entity_type, docs=doc_ids,
                emb=embedding, gv=graph_version,
            )

    def upsert_relation(
        self, tenant_id: str, source: str, target: str, rel_type: str,
        confidence: float, doc_id: str, graph_version: str,
    ) -> None:
        with self._session() as s:
            s.run(
                "MATCH (a:Entity {tenant_id:$tid, name:$src, graph_version:$gv}) "
                "MATCH (b:Entity {tenant_id:$tid, name:$dst, graph_version:$gv}) "
                "MERGE (a)-[r:REL {rel_type:$rt}]->(b) "
                "SET r.confidence=$conf, r.doc_id=$doc",
                tid=tenant_id, src=source, dst=target, rt=rel_type,
                conf=confidence, doc=doc_id, gv=graph_version,
            )

    def delete_edges_for_docs(self, tenant_id: str, doc_ids: list[str], graph_version: str) -> int:
        with self._session() as s:
            rec = s.run(
                "MATCH (:Entity {tenant_id:$tid, graph_version:$gv})-[r:REL]->() "
                "WHERE r.doc_id IN $docs DELETE r RETURN count(r) AS n",
                tid=tenant_id, docs=doc_ids, gv=graph_version,
            ).single()
            return rec["n"] if rec else 0

    def delete_orphan_nodes(self, tenant_id: str, graph_version: str) -> int:
        with self._session() as s:
            rec = s.run(
                "MATCH (e:Entity {tenant_id:$tid, graph_version:$gv}) "
                "WHERE NOT (e)--() DELETE e RETURN count(e) AS n",
                tid=tenant_id, gv=graph_version,
            ).single()
            return rec["n"] if rec else 0

    def copy_active_to_shadow(self, tenant_id: str, active_version: str, shadow_version: str) -> None:
        """Clone the active graph into a shadow version so incremental diff builds on it."""
        with self._session() as s:
            s.run(
                "MATCH (e:Entity {tenant_id:$tid, graph_version:$av}) "
                "CREATE (c:Entity {tenant_id:$tid, name:e.name, entity_type:e.entity_type, "
                "doc_ids:e.doc_ids, embedding:e.embedding, graph_version:$sv})",
                tid=tenant_id, av=active_version, sv=shadow_version,
            )
            s.run(
                "MATCH (a:Entity {tenant_id:$tid, graph_version:$av})-[r:REL]->(b:Entity {graph_version:$av}) "
                "MATCH (na:Entity {tenant_id:$tid, name:a.name, graph_version:$sv}) "
                "MATCH (nb:Entity {tenant_id:$tid, name:b.name, graph_version:$sv}) "
                "CREATE (na)-[:REL {rel_type:r.rel_type, confidence:r.confidence, doc_id:r.doc_id}]->(nb)",
                tid=tenant_id, av=active_version, sv=shadow_version,
            )

    def switch_active_version(self, tenant_id: str, new_version: str) -> None:
        with self._session() as s:
            s.run(
                "MERGE (m:GraphMeta {tenant_id:$tid}) SET m.active_version=$gv",
                tid=tenant_id, gv=new_version,
            )
        log.info("graph_version_switched", tenant_id=tenant_id, version=new_version)

    def active_version(self, tenant_id: str) -> str | None:
        with self._session() as s:
            rec = s.run(
                "MATCH (m:GraphMeta {tenant_id:$tid}) RETURN m.active_version AS v",
                tid=tenant_id,
            ).single()
            return rec["v"] if rec else None

    def find_paths(
        self, tenant_id: str, source: str, target: str, active_version: str, max_hops: int = 3
    ) -> tuple[list[list[str]], list[str]]:
        """Variable-length path search (<= max_hops) between two entities in the active
        graph version. Returns (paths as entity-name lists, doc_ids along those paths)."""
        query = (
            f"MATCH p = (a:Entity {{tenant_id:$tid, name:$src, graph_version:$gv}})"
            f"-[:REL*1..{int(max_hops)}]-"
            f"(b:Entity {{tenant_id:$tid, name:$dst, graph_version:$gv}}) "
            "RETURN [n IN nodes(p) | n.name] AS names, "
            "[n IN nodes(p) | n.doc_ids] AS doc_id_lists LIMIT 10"
        )
        paths: list[list[str]] = []
        doc_ids: set[str] = set()
        with self._session() as s:
            for rec in s.run(query, tid=tenant_id, src=source, dst=target, gv=active_version):
                paths.append(rec["names"])
                for lst in rec["doc_id_lists"]:
                    doc_ids.update(lst or [])
        return paths, sorted(doc_ids)

    def neighbor_doc_ids(
        self, tenant_id: str, entity_name: str, active_version: str, max_hops: int = 3
    ) -> list[str]:
        """doc_ids on entities reachable within max_hops from a single entity."""
        query = (
            f"MATCH (a:Entity {{tenant_id:$tid, name:$name, graph_version:$gv}})"
            f"-[:REL*0..{int(max_hops)}]-"
            "(n:Entity {tenant_id:$tid, graph_version:$gv}) "
            "UNWIND n.doc_ids AS doc_id RETURN DISTINCT doc_id"
        )
        with self._session() as s:
            return [rec["doc_id"] for rec in s.run(query, tid=tenant_id, name=entity_name, gv=active_version)]

    def drop_version(self, tenant_id: str, graph_version: str) -> None:
        with self._session() as s:
            s.run(
                "MATCH (e:Entity {tenant_id:$tid, graph_version:$gv}) DETACH DELETE e",
                tid=tenant_id, gv=graph_version,
            )
        log.info("graph_version_dropped", tenant_id=tenant_id, version=graph_version)

    def enqueue_review(self, tenant_id: str, relation: dict) -> None:
        with self._session() as s:
            s.run(
                "CREATE (:ReviewItem {tenant_id:$tid, source:$src, target:$dst, "
                "rel_type:$rt, confidence:$conf, doc_id:$doc, status:'pending'})",
                tid=tenant_id, src=relation["source"], dst=relation["target"],
                rt=relation["rel_type"], conf=relation["confidence"], doc=relation["doc_id"],
            )
