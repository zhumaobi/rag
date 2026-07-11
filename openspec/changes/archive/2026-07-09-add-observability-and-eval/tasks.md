## 1. QueryTrace and Answer enrichment

- [x] 1.1 Add a `QueryTrace` dataclass to `query/types.py`: `request_id: str`, `hop_latency_ms: dict[str, float]`, `intent: IntentResult | None`, `cache_level: str = ""`, `retrieved_doc_ids: list[str]`, `contexts: list[str]`, `tier`, `degraded_level`, `retrieval_degraded: bool`
- [x] 1.2 Add a `trace: QueryTrace | None = None` field to the `Answer` dataclass; keep all existing fields
- [x] 1.3 Add a small `perf_counter`-based hop timer helper (context manager) usable inside `query()` to record per-hop latency into a dict

## 2. Request correlation and logging

- [x] 2.1 Add a module-level `contextvars.ContextVar[str]` for `request_id` (e.g. in `raglog.py` or a small `context.py`) plus `bind_request_id()` / `get_request_id()` helpers
- [x] 2.2 Configure `raglog.get_logger` to include `structlog.contextvars.merge_contextvars` in the processor chain when structlog is present; verify the stdlib fallback still works with no request_id bound
- [x] 2.3 Mint a `uuid4` `request_id` at the top of `QueryService.query()` and bind it for the duration of the call; expose it on the returned `QueryTrace`

## 3. Tracing instrumentation

- [x] 3.1 In `query/service.py`, wrap each hop (embed, intent, cache lookup, retrieve, generate, cache store) in `get_tracer().span(name, ...)`, recording the hop latency into the trace timer from 1.3
- [x] 3.2 In `retrieval/router.py`, add sub-hop spans around dense, sparse, rerank, and graph calls inside `_hybrid` / `_intent3`
- [x] 3.3 Verify spans degrade to structured log events when OpenTelemetry is absent (the `_SpanShim` path) and carry `request_id`

## 4. Metrics on the hot path

- [x] 4.1 In `QueryService.query()`, measure end-to-end latency and call `get_metrics().observe_request(intent=<Intent-N>, latency_s, outcome)` on success and on error (outcome="error")
- [x] 4.2 Call `get_metrics().observe_degradation(level)` when the dispatcher result reports a degradation level
- [x] 4.3 Add per-stage latency observation (reuse the hop timings from 1.3) — either via existing histograms or a new stage-labeled histogram in `observability/metrics.py`

## 5. Metrics exposition endpoint

- [x] 5.1 Add a `start_metrics_server(port=9090)` helper (in `observability/metrics.py` or wiring) that calls `prometheus_client.start_http_server` guarded by an import check; no-op and no raise when absent
- [x] 5.2 Call `start_metrics_server()` from `query/wiring.py` build paths (idempotent — start at most once)

## 6. bypass_cache

- [x] 6.1 Add `bypass_cache: bool = False` to `QueryService.query()` and skip cache lookup when true (reuse the time-sensitive bypass branch); ensure `Answer.cached` is `false` on that path
- [x] 6.2 Confirm the cache store still runs on a bypassed miss (or document why it is skipped for eval)

## 7. Curated golden dataset

- [x] 7.1 Create `data/eval/intent_eval.jsonl` (~30-60 rows) of `{query, label}` covering all three intents and edge cases
- [x] 7.2 Create `data/eval/retrieval_eval.jsonl` (~30-60 rows) of `{query, intent, ground_truth_doc_ids}` aligned with the mock fake doc ids so it runs green in mock mode
- [x] 7.3 Create `data/eval/golden_set.jsonl` (~30-60 rows) of `{query, intent, reference_answer, ground_truth_doc_ids}`
- [x] 7.4 Sanity-check the fixtures load via `evaluation/datasets.py` loaders (non-empty, correctly typed)

## 8. Offline eval runner over the real pipeline

- [x] 8.1 Add an eval runner module (e.g. `evaluation/run_offline.py`) that builds a `QueryService` (mock-swappable wiring) and iterates the curated dataset
- [x] 8.2 For each sample, call `await query(tenant, text, bypass_cache=True)` once and derive L1 intent, L2 retrieved doc_ids, and L3 answer+contexts from `Answer.trace`
- [x] 8.3 Feed derived inputs into the existing `evaluation/pipeline.py` gates (intent_eval, retrieval_eval, ragas_eval) and produce per-level reports with pass/fail
- [x] 8.4 Add a `python -m evaluation.run_offline --data-dir data/eval` CLI entry that prints the reports and exits 0

## 9. Verify end-to-end

- [x] 9.1 Run `python -m query "怎么对比A产品和B产品的售后政策?" --tenant t1` and confirm the printed footer/trace shows request_id, hop latencies, and doc_ids
- [x] 9.2 Run `python -m evaluation.run_offline --data-dir data/eval` in mock mode; confirm L1/L2/L3 reports are produced and the run exits 0
- [x] 9.3 Confirm metrics are exposed (scrape `localhost:9090/metrics` when prometheus_client is installed) and that absence of prometheus_client/opentelemetry/structlog does not raise
- [x] 9.4 Confirm no network/DB/GPU connection is attempted during mock query or offline eval runs
