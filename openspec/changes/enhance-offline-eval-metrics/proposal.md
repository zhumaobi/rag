## Why

The offline evaluation framework covers L1–L4 metrics but has three structural blind spots: (1) `GoldenSample.reference_answer` is collected but never scored — answer correctness against ground truth is unmeasured; (2) retrieval eval operates at document-ID level (NDCG/Recall) while the confirmed weak link is chunk-level reranker precision — high NDCG coexists with poor generation quality; (3) the Agentic RAG loop captures per-iteration data in `QueryTrace.agentic_scores` but has no aggregation layer to inform tenant/intent enablement decisions before production rollout.

## What Changes

- Introduce **Answer Correctness** evaluation: wire `reference_answer` into RAGAs `ground_truth`, add `key_points` field to golden set schema, implement dual-mode key-point coverage scorer (embedding-based for CI, NLI/LLM-based for deep analysis), add `answer_similarity` metric.
- Introduce **Context Precision** evaluation: LLM-judged chunk-level relevance scoring per intent, with structured label export (`query, chunk, relevance`) to accumulate reranker fine-tuning training data (data flywheel for cross-encoder calibration).
- Introduce **Agentic Loop Efficiency** reporting: aggregate `IterationRecord` data into an `AgenticEfficiencyReport` with first-pass rate, improvement delta, wasted loop rate, deadline exhaustion rate — broken down per (tenant, intent) to support enablement decisions. Add `latency_ms` to `IterationRecord`.
- Split evaluation execution into **CI tier** (fast, no LLM, every build) and **Nightly tier** (LLM-judged, scheduled/on-demand).

## Capabilities

### New Capabilities
- `answer-correctness`: Dual-mode key-point coverage scoring (embedding fast-path + NLI precise-path), reference_answer wiring into RAGAs ground_truth, answer_similarity metric, and CI gate integration.
- `context-precision`: Chunk-level relevance evaluation using LLM judge with reference, per-intent breakdown, and structured reranker training label export for cross-encoder fine-tuning flywheel.
- `agentic-efficiency`: Offline aggregation of agentic loop iteration records into efficiency metrics (first-pass rate, improvement delta, wasted loop rate, deadline exhaustion) per (tenant, intent), with latency_ms extension to IterationRecord.

### Modified Capabilities
- `offline-evaluation`: Integrate new metrics (key-point coverage, context precision, agentic efficiency) into the offline runner and golden set pipeline; extend `GoldenSample` schema with `key_points` field.
- `evaluation-framework`: Add answer correctness and context precision to the L3/L2 metric tiers; define CI vs Nightly execution split with separate threshold gates.

## Impact

- **Code**: `evaluation/` module gains 3 new files (`keypoint_eval.py`, `context_precision.py`, `agentic_efficiency.py`); modifications to `types.py`, `datasets.py`, `ragas_eval.py`, `pipeline.py`, `release_gate.py`; `query/agentic.py` gains `latency_ms` on `IterationRecord`.
- **Data**: `data/eval/golden_set.jsonl` schema extends with `key_points` field; new `data/eval/rerank_labels/` directory for accumulated training samples.
- **Dependencies**: No new hard dependencies; NLI scorer optionally uses `sentence-transformers` (already present); LLM-judged metrics use existing vLLM serving layer.
- **CI**: Evaluation pipeline splits into fast (CI) and deep (nightly) tiers; release gate gains key-point coverage threshold.
