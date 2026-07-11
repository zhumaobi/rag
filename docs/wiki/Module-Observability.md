# Observability (`observability/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

Metrics, distributed tracing, and alerting. Both metrics (`prometheus_client`) and tracing (OpenTelemetry) are **optional dependencies** — the modules fall back gracefully to no-op / log-based behavior when not installed.

## Metrics — `observability/metrics.py`

`get_metrics()` returns a process-wide singleton used by `QueryService`:
- `observe_request(intent, latency_s, outcome)` — outcome ∈ `ok | cache_hit | error`.
- `observe_degradation(level)` — records the degradation level of a response (`""`, `L3`, `L4`, …).
- `observe_stages(hop_latency_ms)` — per-hop latency histogram (embed / intent / cache / retrieve / generate).

`start_metrics_server()` launches a standalone Prometheus exposition HTTP server (called from `wiring.build_mock()`).

## Tracing — `observability/tracing.py`

`get_tracer()` returns a tracer whose `span(name, request_id=..., **tags)` is a context manager wrapped around every hop in the query and retrieval paths. Exports via OTLP when OpenTelemetry is present; otherwise emits log spans.

Span nesting mirrors the query path:
```
embed · intent · cache_lookup · retrieve
   └─ retrieve.dense_sparse · retrieve.rerank · retrieve.graph
generate · cache_store
```

## Alerts — `observability/alerts.py`

Alert rule definitions, including:
- P99 latency > 3s
- Semantic cache hit rate < 40%
- Negative-feedback rate > 5%
- Knowledge-graph quality below threshold

## Pipeline dashboard — `observability/pipeline_dashboard.py`

Builds dashboard data for offline pipeline runs: per-stage timings, success rates, and failure categorization (fed from the Redis-persisted pipeline state).

## Integration points

- `QueryService` (`query/service.py`) emits all three metric families and wraps hops in tracer spans.
- `RetrievalRouter` (`retrieval/router.py`) opens nested `retrieve.*` spans.
- `raglog.bind_request_id()` provides the correlation id threaded through spans and logs.
