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

### Agentic self-correction loop (opt-in)

For `(tenant, intent)` pairs on the Agentic whitelist (`query/agentic.py`), the query path delegates steps [4]–[5] to `AgenticController` instead of the single-pass flow:

```
Cache MISS + (tenant, intent) on whitelist?
   │ no  → default single-pass [4][5][6] (zero overhead)
   │ yes → independent relaxed deadline (RAG_AGENTIC_DEADLINE_S, default 20s)
   ▼
┌────────────── loop (max RAG_AGENTIC_MAX_ITERS, default 2) ──────────────┐
│  AgenticRetriever.retrieve() → Dispatcher.generate() → RagasEvaluator   │
│       │                                                    │            │
│       │                          Faithfulness ≥ 0.90 AND   │            │
│       │                          Answer Relevance ≥ 0.85?  │            │
│       │                               yes → return immediately          │
│       │                               no + budget remains:              │
│       │                                  HyDERewriter.rewrite()         │
│       │                                    → embed hypothetical passage │
│       │                                    → override dense arm         │
│       │                                    (sparse arm keeps original)  │
│       │                                    → re-retrieve ──────────────┤
│       ▼                                                                 │
│  Track best-so-far by rank = faithfulness + answer_relevance            │
└─────────────────────────────────────────────────────────────────────────┘
   ▼
Return highest-rank candidate; flag meta.low_confidence if none passed gate
```

Key design constraints:
- **Isolation:** `AgenticRetriever` calls dense/sparse retrievers directly — it does NOT touch the shared `RetrievalRouter` (protects SLA-critical path).
- **Resource pools:** RAGAs scoring and HyDE generation use the **7B/SMALL** pool; answer generation uses the intent-appropriate pool.
- **Graceful fallback:** If RAGAs is unavailable or any loop exception occurs, falls back to the single-pass path.
- **Observability:** `QueryTrace.agentic_scores` records per-iteration `faithfulness`, `answer_relevance`, `rewritten`, `passed`; `Answer.meta` carries `agentic: true`, `low_confidence`, `iterations`.

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
| D8 | Agentic loop scoped to (tenant, intent) whitelist | Opt-in per group; non-whitelist traffic has zero overhead |
| D9 | HyDE overrides dense arm only; sparse arm keeps original query | Avoid BM25 matching on hallucinated hypothetical text |
| D10 | CI/Nightly two-tier offline evaluation | CI < 2min (no LLM); Nightly adds LLM-judge metrics (CP@K, NLI, Agentic efficiency) |

Design details live in `openspec/changes/archive/2026-07-09-enterprise-rag-system/design.md`, with 11 capability specs under `openspec/specs/`.

## Component map

| Concern | Package | Key entry |
|---------|---------|-----------|
| Query orchestration | `query/` | `QueryService`, `wiring.build_mock()` |
| Agentic loop | `query/agentic.py` | `AgenticController.run()` |
| Intent | `intent/` | `IntentService.recognize()` |
| Retrieval | `retrieval/` | `RetrievalRouter.route()` |
| Serving | `serving/` | `Dispatcher.generate()` |
| Cache | `cache/` | `SemanticCache.lookup()/store_async()` |
| Offline pipeline | `pipeline/` | `IndexPipeline.run()` |
| Infra clients | `clients/` | Milvus/ES/Neo4j/Redis/Postgres/S3 |
| Evaluation | `evaluation/` | 4-level eval + release gate + CI/Nightly tiers |
| Observability | `observability/` | metrics / tracing / alerts |
| Rollout | `deploy/` | `RolloutController` |
