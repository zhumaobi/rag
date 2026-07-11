## Context

The online query path (`query/service.py:QueryService.query`) already computes rich intermediate signal — intent + confidence + source, cache level, per-chunk scores and sources, retrieved doc_ids, tier, degradation, dispatcher latency — but surfaces almost none of it. The observability modules (`observability/metrics.py`, `tracing.py`, `alerts.py`) are fully built with graceful no-op fallbacks yet have **zero call sites** in production code. The evaluation framework (`evaluation/{intent_eval,retrieval_eval,ragas_eval,release_gate,pipeline}.py`) is complete and gated but has **no dataset** and **no runner bound to the real pipeline**.

Constraints: flat root-relative imports (`src/rag` on `PYTHONPATH`, run as modules); heavy/infra libs are lazy-imported and must stay optional; the mock path must keep running on a laptop with no infra/GPU.

## Goals / Non-Goals

**Goals:**
- Wire full-stack observability (correlated logs + hop spans + hot-path metrics + `/metrics` exposition) into the live query path.
- Capture one `QueryTrace` per query that serves both live observability and offline scoring.
- Ship a small curated golden dataset (option a) and a runner that evaluates the real pipeline through `QueryService.query(bypass_cache=True)`, reusing the existing eval gates.

**Non-Goals:**
- No HTTP serving layer for queries (metrics server only; standalone thread).
- No new eval metrics or gate logic — reuse `evaluation/*` thresholds as-is.
- No production wiring (`build_production()` stays a stub); eval reuses mock-swappable wiring.
- No dashboards/alerting delivery pipeline; `alerts.py` remains driven separately.

## Decisions

**D1 — Shared `QueryTrace` as the single capture point.** Add a `QueryTrace` dataclass (request_id, per-hop latency map, intent, cache_level, retrieved doc_ids, contexts, tier, degraded flags) built inside `query()` and attached to `Answer.trace`. *Why:* both goals need the same intermediate state; capturing once avoids a second instrumentation pass. *Alternative rejected:* separate observability hooks + a distinct eval path — duplicates capture and lets the two drift.

**D2 — `request_id` via `contextvars` + structlog `merge_contextvars`.** Mint an id at `query()` entry, bind it in a contextvar, add the merge processor in `raglog.py`. *Why:* propagates to every existing `log.info(...)` with no signature changes across modules. *Alternative rejected:* threading an id parameter through every collaborator — invasive across ~10 files.

**D3 — Metrics served by `prometheus_client.start_http_server` from wiring (user choice).** No web framework; a background thread exposes `:9090/metrics`. Guarded so absence of `prometheus_client` starts nothing and never raises. *Alternative rejected:* FastAPI route (drags in a web stack we don't need yet); Pushgateway (adds an external dependency).

**D4 — Eval reuses `QueryService.query()` directly (user choice).** The runner calls `query(bypass_cache=True)` once per sample and reads L1/L2/L3 inputs off the returned `QueryTrace`. *Why:* scores the actual production orchestration, not a parallel reimplementation. *Consequence:* forces `QueryTrace` to expose doc_ids + contexts (D1) and forces the `bypass_cache` flag (D5).

**D5 — `bypass_cache` flag on `query()`.** Defaults `False`; when `True` the cache lookup is skipped entirely. *Why:* eval must score retrieval+generation, not the semantic cache. Reuses the existing time-sensitive bypass branch. *Alternative rejected:* inject a force-miss cache in eval wiring — works but hides intent and still stores results.

**D6 — Spans wrap hops in `service.py`, sub-hops in `router.py`.** Coarse spans (embed/intent/cache/retrieve/generate/store) in the facade; finer dense/sparse/rerank/graph spans inside the router where those calls already live. *Why:* keeps the facade readable while still exposing retrieval internals.

## Risks / Trade-offs

- **Trace capture adds overhead on the hot path** → keep it to cheap field assignment + `perf_counter` deltas; no serialization inside `query()`.
- **`contextvars` + `asyncio.create_task` for fire-and-forget store may lose the id** → bind the id before scheduling, or accept that the detached store span is best-effort.
- **Reusing `query()` for eval couples eval to the facade API** → mitigated by `QueryTrace` being an explicit, versioned contract rather than ad-hoc `meta` keys.
- **`bypass_cache` could be misused in production** → default `False`, documented as an eval/diagnostic flag only.
- **Curated dataset is small** → acceptable seed; documented as growable from `FeedbackCollector` weak-positives later (out of scope here).

## Migration Plan

Additive only. `Answer` gains a `trace` field; `query()` gains a defaulted `bypass_cache`. Observability wiring is opt-in and no-ops without optional deps, so existing `python -m query` runs unchanged. Rollback = revert; no data migration. New `data/eval/*.jsonl` are inert fixtures.

## Open Questions

- Metrics port: default `9090` unless it collides with an existing scrape target — confirm at wiring time.
- Whether the eval runner should also invoke `release_gate` against a saved baseline now, or just emit reports first (leaning: emit reports first; gate is a follow-up).
