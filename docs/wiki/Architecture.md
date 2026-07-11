# Architecture & Data Flow

[← Home](./Home.md)

The system has two distinct planes: an **online query path** (low-latency, per-request) and an **offline index pipeline** (batch, scheduled). They are decoupled through shared infrastructure (Milvus, Elasticsearch, Neo4j, Redis, PostgreSQL, object storage).

## Online query path

Entry point: `QueryService.query()` — `query/service.py:45`.

```
User Query (tenant_id, text)
   │
   ▼
[1] Embed once              embedder.embed_texts([text])[0]        → bge-m3, 1024-dim
   │
   ▼
[2] Intent recognition      IntentService.recognize()             → Intent-1/2/3 (rules → MiniLM)
   │
   ▼
[3] Semantic cache lookup   SemanticCache.lookup()                → L1 (in-mem) → L2 (Redis VSS)
   │   HIT ─────────────────────────────────────────────────────► return cached Answer
   │   MISS (or time-sensitive / bypass)
   ▼
[4] Intent-routed retrieval RetrievalRouter.route()
   │     Intent-1 PRECISE : targeted dense+sparse → RRF → rerank → Top-5
   │     Intent-2 COMPARE : parallel per-product hybrid, grouped by product
   │     Intent-3 RELATION: Neo4j path traversal (≤3 hops) + vector supplement (fallback pure-vector)
   ▼
[5] LLM generation          Dispatcher.generate()
   │     Intent-1        → 7B pool (SMALL)
   │     Intent-2/3      → 14B pool (LARGE), downgrade to 7B if saturated
   │     degradation chain L1→L2→L3→L4 on failure/timeout
   ▼
[6] Fire-and-forget store   asyncio.create_task(cache.store_async(...))
   │
   ▼
Answer(text, intent, cached, degraded_level, tier, meta, trace)
```

Each hop is wrapped in a tracer span and timed into `QueryTrace.hop_latency_ms` (`query/types.py`). Metrics are emitted via `observe_request` / `observe_degradation` / `observe_stages`. A per-request `request_id` is bound through `raglog.bind_request_id()`.

**Key property:** `QueryService` constructs none of its collaborators — everything is injected (`query/service.py:27`). The identical code path runs against fakes (`build_mock`) and real clients (`build_production`).

## Offline index pipeline

Entry point: `IndexPipeline.run()` — `pipeline/orchestrator.py:76`.

```
Object Storage (S3/MinIO)
   │  Ingestor.ingest_tenant()
   ▼
Change detection            detect_changes(tenant, docs, pg)      → ChangeSet(added/modified/deleted)
   │  (empty? → fast-path DONE)
   ▼
Chunk + embed               chunk_document() → Embedder.embed_chunks()   (512 tok, 50 overlap)
   │
   ▼
Three-index parallel build on SHADOW
   ├─ VectorIndexBuilder.build_shadow()   → Milvus shadow collection (HNSW)
   ├─ BM25IndexBuilder.build_shadow()     → Elasticsearch shadow index
   └─ GraphBuilder.build_shadow()         → Neo4j (NER + LLM relation extraction)
   │
   ▼
Validate                    SwitchValidator.validate()            → chunk reconciliation + query quality
   │  (fail → rollback)
   ▼
Atomic switch               AtomicSwitch.switch()                 → Milvus alias + ES alias + Neo4j version
   │
   ▼
Post-switch                 CacheInvalidator.invalidate() + Postgres upsert/delete
   │
   ▼
DONE
```

Progress is driven by a strict **state machine** (`pipeline/state_machine.py`):

```
PENDING → PROCESSING → VALIDATING → READY → SWITCHING → DONE
   └──────────────── any state ────────────────► FAILED → ROLLED_BACK
```

On any exception the orchestrator calls `_safe_rollback` (`pipeline/orchestrator.py:166`): if the failure happened during `SWITCHING`, aliases are rolled back to the previously captured targets; otherwise it transitions `FAILED → ROLLED_BACK`. Shadow artifacts are left in place for inspection. Run state is persisted to Redis at each transition (`_persist`).

## Multi-tenant isolation

Isolation is enforced at every layer (see `naming.py`):
- **Vector:** per-tenant Milvus collection `docs_{tenant_id}` (`collection_for_tenant`); small tenants can share `docs_shared_small`.
- **Sparse:** Elasticsearch `tenant_id` field filter.
- **Graph:** Neo4j tenant-label isolation + per-tenant active version.
- **Cache:** tenant-namespaced keys in both L1 and L2.
- **Metadata:** `tenant_id` column in PostgreSQL `documents`.

## Key design decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Two-stage intent (rules + MiniLM), not LLM-based | Keep P99 < 15ms; rules short-circuit at confidence ≥ 0.85 |
| D2 | Per-tenant Milvus collections (not shared+filter) | Stable HNSW latency, hard isolation |
| D3 | Neo4j for the knowledge graph | Mature Cypher path queries for ≤3-hop relations |
| D4 | Tiered LLM pools (7B Intent-1, 14B Intent-2/3) | Match model size to task complexity/cost |
| D5 | Semantic cache at cosine > 0.92 | High-precision reuse without stale answers |
| D6 | Shadow/Active dual-collection atomic switch via aliases | Zero-downtime, instantly reversible index updates |
| D7 | Prefix KV cache + consistent-hash tenant affinity | Maximize vLLM prefix cache hit rate (target ≥ 80%) |

Design details live in `openspec/changes/archive/2026-07-09-enterprise-rag-system/design.md`, with 11 capability specs under `openspec/specs/`.

## Component map

| Concern | Package | Key entry |
|---------|---------|-----------|
| Query orchestration | `query/` | `QueryService`, `wiring.build_mock()` |
| Intent | `intent/` | `IntentService.recognize()` |
| Retrieval | `retrieval/` | `RetrievalRouter.route()` |
| Serving | `serving/` | `Dispatcher.generate()` |
| Cache | `cache/` | `SemanticCache.lookup()/store_async()` |
| Offline pipeline | `pipeline/` | `IndexPipeline.run()` |
| Infra clients | `clients/` | Milvus/ES/Neo4j/Redis/Postgres/S3 |
| Evaluation | `evaluation/` | 4-level eval + release gate |
| Observability | `observability/` | metrics / tracing / alerts |
| Rollout | `deploy/` | `RolloutController` |
