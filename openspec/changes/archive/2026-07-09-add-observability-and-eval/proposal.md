## Why

The retrieval and generation path produces rich signal at every hop (intent, confidence, cache level, chunk scores, retrieved doc_ids, tier, degradation, per-hop latency), but `QueryService.query()` discards almost all of it — emitting a single `cache_hit` log line and returning a thin `Answer`. The full observability stack (`observability/metrics.py`, `tracing.py`, `alerts.py`) is already built but **never called from the online path**, and there is **no golden dataset** to measure RAG quality even though the eval framework (L1 intent, L2 MRR/Recall/NDCG, L3 RAGAs, release gate) is complete. We need to (1) wire full-stack observability into the live query path and (2) ship a curated offline test set that runs against the real pipeline so RAG effectiveness is measurable and gated.

## What Changes

- **Enrich the query path with a `QueryTrace`**: `QueryService.query()` captures per-hop timing plus intent, cache level, retrieved doc_ids, contexts, tier, and degradation into a structured trace surfaced on `Answer`. This is the shared spine both goals depend on.
- **Add a `bypass_cache` flag to `query()`** so offline eval scores retrieval+generation rather than the semantic cache.
- **Correlation IDs**: mint a `request_id` via `contextvars` at query entry and configure `raglog` (structlog `merge_contextvars`) so every downstream log line auto-carries it.
- **Tracing**: wrap each hop (embed → intent → cache → retrieve[dense/sparse/rerank/graph] → generate → cache_store) in `tracer.span()`, exported via OTLP when OpenTelemetry is present, degrading to log spans otherwise.
- **Metrics call sites**: invoke `observe_request()` / `observe_degradation()` on the hot path and add per-stage latency histograms; expose `/metrics` via a standalone Prometheus HTTP server (`start_http_server`, no web framework) launched from wiring.
- **Golden test set (curated, option a)**: ship `data/eval/{intent_eval,retrieval_eval,golden_set}.jsonl` with a small hand-curated seed (~30-60 rows each) covering all three intents plus edge cases.
- **Offline eval runner**: an entry point that runs the curated set against the real pipeline by calling `QueryService.query(bypass_cache=True)`, derives L1/L2/L3 inputs from the returned `QueryTrace`, and feeds the existing `evaluation/pipeline.py` gates.

## Capabilities

### New Capabilities
- `observability`: full-stack request-correlated observability (request_id contextvar, structlog correlation, hop-level tracing spans, hot-path metric emission, and a standalone Prometheus exposition endpoint) for the online query path.
- `offline-evaluation`: a curated golden dataset plus a runner that evaluates the real retrieval+generation pipeline via `QueryService`, producing gated L1/L2/L3 reports.

### Modified Capabilities
- `query-serving`: `QueryService.query()` gains a `bypass_cache` parameter and returns an enriched `Answer` carrying a `QueryTrace` (request_id, per-hop latency, retrieved doc_ids, contexts, intent, tier, degradation). Existing return fields are preserved.

## Impact

- **Code**: `query/service.py` (trace capture, bypass flag, span/metric instrumentation), `query/types.py` (`QueryTrace`, enriched `Answer`), `query/wiring.py` (start metrics server, eval wiring), `raglog.py` (contextvars processor), `retrieval/router.py` (sub-hop spans), and a new eval runner module.
- **Observability modules**: `observability/metrics.py`, `tracing.py` become live (call sites added); no API changes to those modules.
- **Data**: new `data/eval/*.jsonl` curated fixtures.
- **Dependencies**: optional `prometheus_client`, `opentelemetry-*`, `structlog` — all already have graceful no-op fallbacks, so no hard new runtime requirement.
- **No breaking changes**: `Answer` fields are additive; `bypass_cache` defaults to `False`.
