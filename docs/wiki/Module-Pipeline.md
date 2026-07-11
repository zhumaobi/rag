# Offline Index Pipeline (`pipeline/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

Rebuilds all three indices (vector, BM25, knowledge graph) for a tenant on **shadow** collections, validates them, then performs a single **atomic switch** — enabling zero-downtime, instantly reversible updates.

## Entry point

`IndexPipeline.run(tenant_id, run_id)` — `pipeline/orchestrator.py:76`. Returns a `PipelineResult(run_id, tenant_id, state, changeset, stats)`.

All stage collaborators are injected with defaults (`pipeline/orchestrator.py:47`), so the pipeline can be exercised with fakes or real clients.

## State machine — `pipeline/state_machine.py`

```
PENDING → PROCESSING → VALIDATING → READY → SWITCHING → DONE
   └──────────── any state ────────────► FAILED → ROLLED_BACK
```

`StateMachine` enforces forward-only transitions: `can(target)`, `to(target)` (raises `InvalidTransition`), `is_terminal`. Any state may go to `FAILED`; `FAILED` may go to `ROLLED_BACK`.

## Run sequence

1. **Persist initial state** to Redis (`_persist`) and capture current alias targets (`switcher.capture_current`) for rollback.
2. **PROCESSING** — `Ingestor.ingest_tenant(tenant_id)` pulls docs from S3.
3. **Change detection** — `detect_changes(tenant, docs, pg)` compares content hashes against PostgreSQL → `ChangeSet`. If **empty**, fast-path straight to DONE (`orchestrator.py:93`).
4. **Chunk + embed** — `chunk_document(doc)` (512 tok / 50 overlap) then `Embedder.embed_chunks(all_chunks)` (bge-m3). Full shadow rebuild.
5. **Three-index parallel build on shadow:**
   - `VectorIndexBuilder.build_shadow()` → Milvus shadow collection (HNSW).
   - `BM25IndexBuilder.build_shadow()` → Elasticsearch shadow index.
   - Graph: `EntityExtractor.extract()` (NER) → embed entities → `RelationExtractor.extract()` (LLM) → `GraphBuilder.build_shadow()` → Neo4j shadow version.
6. **VALIDATING** — `SwitchValidator.validate()` (chunk-count reconciliation + hot-query quality). Failure raises → rollback.
7. **READY → SWITCHING** — `AtomicSwitch.switch()` flips Milvus alias + ES alias + Neo4j active version together.
8. **Post-switch** — `CacheInvalidator.invalidate(tenant, changeset)` (precise eviction), Postgres `upsert_document(... READY)`, `delete_documents(changeset.deleted)`.
9. **DONE** — stats persisted (`vectors`, `bm25`, `cache_evicted`, graph stats).

## Rollback — `_safe_rollback` (orchestrator.py:166)

- Failure **during SWITCHING** → `switcher.rollback(...)` restores previous alias targets, state → `ROLLED_BACK`.
- Failure **before SWITCHING** → state → `FAILED` → `ROLLED_BACK`; shadow artifacts left for inspection.

## Knowledge graph sub-pipeline — `pipeline/graph/`

| File | Purpose |
|------|---------|
| `pipeline/graph/ner.py` | `EntityExtractor` — spaCy + domain-term dictionary NER |
| `pipeline/graph/relation.py` | `RelationExtractor` — LLM relation extraction, 5 typed relations, confidence threshold 0.85 (auto-admit vs. review queue) |
| `pipeline/graph/builder.py` | `GraphBuilder` — incremental diff, orphan cleanup, shadow Neo4j writer |

Relation types (`models.py`): `属于` (belongs_to), `依赖` (depends_on), `替代` (replaces), `集成` (integrates), `概念解释` (explains).

## Files

| File | Purpose |
|------|---------|
| `pipeline/orchestrator.py` | `IndexPipeline` — top-level coordinator |
| `pipeline/state_machine.py` | `PipelineState`, `StateMachine`, `InvalidTransition` |
| `pipeline/ingest.py` | `Ingestor` — S3 fetch + PDF/Word/Markdown parsing |
| `pipeline/change_detect.py` | `detect_changes()` → `ChangeSet` via content_hash |
| `pipeline/chunk.py` | `chunk_document()` — token-aware chunking (tiktoken) |
| `pipeline/embed.py` | `Embedder` — bge-m3 batch embedding |
| `pipeline/vector_index.py` | `VectorIndexBuilder` — Milvus shadow (HNSW) |
| `pipeline/bm25_index.py` | `BM25IndexBuilder` — Elasticsearch shadow |
| `pipeline/validate.py` | `SwitchValidator` — pre-switch validation |
| `pipeline/switch.py` | `AtomicSwitch` — alias/version switch + rollback |
| `pipeline/cache_invalidate.py` | `CacheInvalidator` — precise doc_id-based eviction |
| `pipeline/scheduler.py` | Cron scheduler (low-traffic window) + manual trigger |
