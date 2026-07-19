# Query Facade (`query/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

The online orchestration layer. `QueryService` ties together embedding, intent, cache, retrieval, and serving into a single async `query()` call. It constructs nothing itself — everything is injected — so the **identical code path** runs against fakes (laptop) and real clients (production).

## `QueryService` — `query/service.py`

Constructor (`query/service.py:27`) injects: `embedder`, `intent: IntentService`, `cache: SemanticCache`, `router: RetrievalRouter`, `dispatcher: Dispatcher`, plus `system_prefix` and `max_tokens`.

`async query(tenant_id, text, bypass_cache=False)` (`query/service.py:45`):

1. **Embed once** — reused for both cache lookup and retrieval.
2. **Intent** — `intent.recognize(tenant_id, text)`.
3. **Cache lookup** — skipped when `bypass_cache` or the query is time-sensitive; on hit returns immediately with `cached=True`.
4. **Retrieve** — `await router.route(...)`; collects contexts, `retrieved_doc_ids`, `retrieval_degraded`.
5. **Generate** — builds `GenRequest` (`est_prompt_tokens = len(context)//4`) and calls `dispatcher.generate(...)`.
6. **Fire-and-forget store** — `asyncio.create_task(cache.store_async(...))`; never awaited on the response path (runs even on bypassed misses to warm the cache for eval).

Cross-cutting: every hop is wrapped in `tracer.span(...)` + `trace.hop(...)`; metrics via `observe_request/observe_degradation/observe_stages`; `request_id` bound with `bind_request_id()` and cleared in `finally`. Errors record an `"error"` outcome and re-raise.

## Types — `query/types.py`

- `QueryTrace(request_id, hop_latency_ms, intent, cache_level, retrieved_doc_ids, contexts, tier, degraded_level, retrieval_degraded)` with a `hop(name)` context manager for timing.
- `Answer(text, intent, cached, degraded_level, tier, meta, trace)`.
- `intent_to_request_str(Intent)` — maps enum → `"Intent-1|2|3"` used by serving.

## Wiring — `query/wiring.py`

- **`build_mock()`** (`wiring.py:35`) — full path, no infra/GPU. Uses the **real** `IntentService` (rules path), `RetrievalRouter`, `Dispatcher` + `ModelPool` seeded with healthy fake `Instance`s; fakes the embedder, retrieval leaf clients, cache backend, and vLLM. Starts the metrics server.
- **`build_production()`** (`wiring.py:64`) — documents the intended real wiring shape and raises `NotImplementedError` until live endpoints/instance discovery are wired.

## CLI — `query/__main__.py`

```bash
# with src/rag on PYTHONPATH
python -m query "订单中心和支付网关有什么区别?" --tenant t1
```

Runs `build_mock().query(...)` and prints the answer plus a diagnostics footer: `intent`, `source`, `tier`, flags (`cached`, `degraded=`), `request_id`, per-hop latencies, and retrieved `doc_ids`.

## Fakes — `query/fakes.py`

Deterministic, dependency-free doubles for laptop runs:
- `FakeEmbedder` — hash-seeded 1024-dim normalized vectors.
- `FakeEntityRecognizer` — two canned entities. `FakeClassifier` — always PRECISE/0.90.
- `_FakeDense`, `_FakeSparse`, `_FakeReranker`, `_FakeNeo4j` — canned chunks/paths; `fake_retriever_kwargs()` returns them for `RetrievalRouter`.
- `FakeVLLM` — simulated async generation. `FakeCache` — force-miss.

## Agentic self-correction loop — `query/agentic.py`

Opt-in for `(tenant, intent)` pairs configured via `RAG_AGENTIC_ENABLED_TENANTS` / `RAG_AGENTIC_ENABLED_INTENTS`. Non-whitelist requests run the default single-pass path with zero overhead.

### `AgenticController` (agentic.py:154)

Orchestrates the retrieve → generate → score → (HyDE rewrite → re-retrieve) loop:
- **Budget:** independent wall-clock deadline (`deadline_s`, default 20s) + `max_iters` (default 2).
- **Quality gate:** Faithfulness ≥ 0.90 AND Answer Relevance ≥ 0.85 (via `RagasEvaluator.score_one`). Context Utilization is excluded (offline-only).
- **Best-so-far:** ranks candidates by `faithfulness + answer_relevance`; always returns the highest-scoring candidate.
- **Low confidence:** if no candidate passes the gate, returns best-so-far with `low_confidence=True`.

### `HyDERewriter` (agentic.py:78)

Generates a hypothetical answer passage via the **7B/SMALL** pool, then embeds it to produce a dense-arm override vector. The sparse/BM25 arm always uses the original query terms. Falls back to embedding the original query on generation failure.

### `AgenticRetriever` (agentic.py:118)

Dedicated hybrid retrieval path that calls `DenseRetriever` + `SparseRetriever` directly (via `asyncio.to_thread`), fuses with RRF, and reranks. Accepts an optional embedding override for the dense arm. Does **not** touch the shared `RetrievalRouter`.

- `recall_k=20`, `final_k=5`.

### `AgenticConfig` (agentic.py:25)

Static env-derived configuration: `enabled_tenants`, `enabled_intents`, `deadline_s`, `max_iters`. Constructed via `AgenticConfig.from_settings(settings)`.

### Types

- `IterationRecord(iteration, rewritten, faithfulness, answer_relevance, passed, latency_ms)` — per-iteration provenance on `QueryTrace.agentic_scores`.
- `AgenticResult(text, contexts, doc_ids, tier, degraded_level, ..., low_confidence, iterations, iteration_records)`.

## Files

| File | Purpose |
|------|---------|  
| `query/service.py` | `QueryService` — online orchestration facade |
| `query/agentic.py` | `AgenticController`, `HyDERewriter`, `AgenticRetriever` — self-correction loop |
| `query/types.py` | `QueryTrace`, `Answer`, `intent_to_request_str()` |
| `query/wiring.py` | `build_mock()` / `build_production()` assembly |
| `query/fakes.py` | Deterministic fakes for infra-free runs |
| `query/__main__.py` | `python -m query` CLI entry point |
