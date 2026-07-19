## 1. Schema & Data Layer

- [x] 1.1 Extend `GoldenSample` in `evaluation/types.py` with `key_points: list[str] = field(default_factory=list)`
- [x] 1.2 Update `load_golden_samples` in `evaluation/datasets.py` to parse `key_points` from JSONL (default `[]` when absent)
- [x] 1.3 Add `key_points` field to `data/eval/golden_set.jsonl` entries (at least 10 samples with 2-4 key points each)
- [x] 1.4 Add `RerankTrainingSample` dataclass to `evaluation/types.py` (query, chunk_text, relevance, reranker_score, is_hard_negative, intent, doc_id, ts)
- [x] 1.5 Add `KeyPointResult` and `PointScore` dataclasses to `evaluation/types.py`

## 2. Answer Correctness — Key-Point Coverage

- [x] 2.1 Create `evaluation/keypoint_eval.py` with `KeyPointScorer` protocol and `EmbeddingKeyPointScorer` implementation (cosine similarity against MiniLM, threshold τ=0.65)
- [x] 2.2 Implement `NLIKeyPointScorer` in `evaluation/keypoint_eval.py` with graceful fallback to embedding mode when NLI unavailable
- [x] 2.3 Implement `evaluate_keypoints(samples, scorer) -> EvalReport` aggregation function with coverage threshold gating (≥ 0.80)
- [x] 2.4 Write unit tests for `EmbeddingKeyPointScorer` (covered/not-covered cases, empty key_points skip, threshold boundary)
- [x] 2.5 Write unit tests for `NLIKeyPointScorer` fallback behavior

## 3. Answer Correctness — Reference Wiring & Similarity

- [x] 3.1 Modify `ragas_eval.py` `score_one` to accept optional `reference_answer` parameter and pass it as `ground_truth` to RAGAs dataset
- [x] 3.2 Add `answer_similarity` computation (cosine of answer embedding vs reference embedding) to the generation eval path
- [x] 3.3 Update `_run_generation_eval` in `pipeline.py` to pass `s.reference_answer` through to the evaluator and compute answer_similarity
- [x] 3.4 Write unit tests verifying `ground_truth` is populated (not empty string) when reference_answer is provided

## 4. Context Precision

- [x] 4.1 Create `evaluation/context_precision.py` with `ContextPrecisionEvaluator` class accepting injectable judge function `(query, reference, chunk) -> float`
- [x] 4.2 Implement CP@K computation: `(1/K) × Σ(relevance_i × (1/i))` with per-intent bucketing
- [x] 4.3 Implement `evaluate_context_precision(samples, chunks_per_sample, judge_fn) -> EvalReport` with per-intent thresholds
- [x] 4.4 Implement `export_rerank_labels(results, output_dir)` writing dated JSONL to `data/eval/rerank_labels/` with hard-negative flagging (reranker_score ≥ 0.7 AND relevance = 0.0)
- [x] 4.5 Write unit tests with mock judge (deterministic relevance values, CP@K computation, hard negative detection, empty chunks)

## 5. Agentic Loop Efficiency

- [x] 5.1 Add `latency_ms: float = 0.0` field to `IterationRecord` in `query/agentic.py`
- [x] 5.2 Instrument `AgenticController.run()` to measure and record per-iteration wall-clock time into `latency_ms`
- [x] 5.3 Create `evaluation/agentic_efficiency.py` with `aggregate_agentic_efficiency(records, groups) -> AgenticEfficiencyReport`
- [x] 5.4 Implement per-(tenant, intent) breakdown and enablement recommendation logic (enable/skip/tune)
- [x] 5.5 Implement `cost_effectiveness` metric (improvement_delta / mean_latency_s) with None fallback for legacy data
- [x] 5.6 Write unit tests for aggregation (first-pass rate, wasted loop, improvement delta, empty input, legacy latency=0)

## 6. Pipeline Integration & CI/Nightly Split

- [x] 6.1 Add `tier` parameter to `run_offline()` in `evaluation/run_offline.py` (default "ci")
- [x] 6.2 Wire key-point coverage (embedding mode) and answer_similarity into CI tier path
- [x] 6.3 Wire context precision, NLI key-point mode, answer_correctness, and agentic efficiency into nightly tier path
- [x] 6.4 Update `pipeline.py` `run_daily` to accept and propagate `tier` parameter
- [x] 6.5 Update `release_gate.py` to include key_point_coverage in gate metrics and reference last nightly report
- [x] 6.6 Add `--tier` CLI argument to `run_offline.py` main()
- [x] 6.7 Write integration test: CI tier completes without LLM calls; nightly tier invokes judge functions

## 7. Golden Set Data & Validation

- [x] 7.1 Populate `key_points` for all 30 existing golden set entries (2-4 atomic claims per sample)
- [x] 7.2 Validate backward compat: run existing test suite against updated schema with no failures
- [x] 7.3 Run full offline eval in CI mode and verify all new metrics appear in report output
