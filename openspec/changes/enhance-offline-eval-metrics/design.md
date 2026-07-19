## Context

The evaluation module (`src/rag/evaluation/`) implements a four-layer system (L1 intent, L2 retrieval, L3 generation/RAGAs, L4 business) with gated release. Three gaps were identified through analysis:

1. `GoldenSample.reference_answer` is loaded but never passed to RAGAs (`ground_truth` is hardcoded to `""`). A `key_points` field is planned but doesn't exist in the schema yet.
2. L2 retrieval eval measures document-level ranking (MRR/NDCG/Recall against `ground_truth_doc_ids`) but the reranker (`bge-reranker-v2-m3`) is confirmed as the weak link: high NDCG coexists with poor generation quality due to irrelevant chunks from correct documents.
3. `IterationRecord` captures per-iteration faithfulness/relevance/passed but has no latency field and no cross-query aggregation. The agentic loop is pre-production, scoped to specific (tenant, intent) pairs.

Current execution model: a single `run_offline()` / `run_daily()` pass with no tier separation between fast deterministic metrics and LLM-dependent metrics.

## Goals / Non-Goals

**Goals:**
- Enable answer correctness scoring with zero LLM cost in CI (embedding mode) and optional NLI/LLM precision on demand.
- Provide chunk-level context precision measurement that directly diagnoses reranker failures and generates labeled training data for cross-encoder fine-tuning.
- Produce an agentic efficiency report from offline runs that supports per-(tenant, intent) enablement decisions.
- Split evaluation into CI tier (< 2 min, no LLM) and Nightly tier (LLM-judged, ~30 min).

**Non-Goals:**
- Fine-tuning the cross-encoder model itself (this change produces the training data; model training is a separate effort).
- Online/real-time context precision scoring (too expensive for the query path; offline only).
- Changing the agentic loop's gating logic or thresholds (only observing and reporting efficiency).
- Migrating existing eval data or breaking the current `run_offline()` interface.

## Decisions

### D1: Dual-mode key-point scorer behind a common interface

**Decision**: Implement `KeyPointScorer` protocol with two implementations: `EmbeddingKeyPointScorer` (CI default) and `NLIKeyPointScorer` (on-demand).

**Rationale**: CI needs sub-2-minute execution with no LLM dependency. The embedding path uses the existing MiniLM model (`paraphrase-multilingual-MiniLM-L12-v2`) to compute max cosine similarity between each key point and answer sentences. The NLI path uses an LLM judge for entailment-level precision including hallucination detection. Both produce a `KeyPointResult` with `coverage` as the gated metric.

**Alternatives considered**:
- RAGAs `answer_correctness` only: requires LLM decomposition of both answer and reference into statements — too slow for CI, and the verbose reference style dilutes F1 signal.
- Embedding-only with no NLI option: cannot detect contradictions/hallucinations at key-point level.

### D2: `key_points` as a list field on GoldenSample

**Decision**: Extend `GoldenSample` with `key_points: list[str]` (default empty for backward compat). Each key point is an atomic factual claim the answer must cover.

**Rationale**: Pre-decomposed atomic claims eliminate the need for LLM statement decomposition on the reference side. The embedding scorer can directly match each claim against answer sentences. The field is optional so existing golden set files load without error.

### D3: Context Precision with reference, per-intent, with label export

**Decision**: Implement `ContextPrecisionEvaluator` that uses an LLM judge to assess each retrieved chunk's relevance given (query, reference_answer). Results are scored per-intent and exported as `RerankTrainingSample` records.

**Rationale**: The with-reference variant avoids false negatives on indirectly relevant chunks (especially Intent-3 multi-hop). Per-intent breakdown is needed because precision failure modes differ: Intent-1 needs exact factual chunks, Intent-2 needs balanced multi-product chunks, Intent-3 needs bridging context. Label export creates the data flywheel for reranker fine-tuning.

**Alternatives considered**:
- Without-reference variant: faster but misclassifies indirectly relevant chunks in Intent-3.
- Binary relevance only: graded labels (0.0–1.0) produce better cross-encoder calibration; we use a 0/1 judgment from the LLM but store the raw confidence when available.

### D4: Reranker training labels accumulated as JSONL

**Decision**: Persist `RerankTrainingSample` records to `data/eval/rerank_labels/<date>.jsonl`, one file per eval run. Include `reranker_score`, `llm_relevance`, `is_hard_negative` flag, `intent`, `doc_id`, and `ts`.

**Rationale**: JSONL matches the existing eval data format, requires no infrastructure, and is trivially consumable by `sentence-transformers` CrossEncoder training (`InputExample(texts=[query, chunk], label=relevance)`). Hard negatives (high reranker score + low LLM relevance) are flagged for priority sampling during fine-tuning.

**Alternatives considered**:
- Postgres table: adds infrastructure dependency for what is currently a batch offline process.
- Single growing file: harder to manage retention, dedup, and provenance.

### D5: AgenticEfficiencyReport as pure aggregation over IterationRecord lists

**Decision**: Implement `aggregate_agentic_efficiency(records: list[list[IterationRecord]], config) -> AgenticEfficiencyReport` as a pure function. Add `latency_ms: float` to `IterationRecord`. Report metrics: first_pass_rate, loop_trigger_rate, improvement_delta, loop_success_rate, wasted_loop_rate, deadline_exhaustion_rate, low_confidence_rate, avg_iterations — all per (tenant, intent).

**Rationale**: No new data collection needed beyond `latency_ms`. The pure-function design keeps it testable and decoupled from the query path. Per-(tenant, intent) breakdown maps directly to `AgenticConfig.is_enabled()` decisions.

### D6: CI / Nightly execution tier split

**Decision**: `pipeline.py` gains a `tier` parameter (`"ci"` | `"nightly"`). CI tier runs: L1 intent, L2 retrieval (NDCG/MRR/Recall), key-point coverage (embedding mode), answer_similarity. Nightly tier adds: RAGAs full suite, answer_correctness (statement F1), context precision, NLI key-point mode, agentic efficiency, KG eval.

**Rationale**: CI must be fast and deterministic to gate every build. LLM-judged metrics are expensive and non-deterministic — suitable for nightly/on-demand. The release gate uses CI-tier metrics plus the last nightly report.

## Risks / Trade-offs

- **[Embedding threshold calibration]** → The cosine threshold τ for key-point coverage needs calibration against a hand-labeled subset (20–30 samples). Mitigation: ship with conservative τ=0.65 and expose as config; add a calibration script in a follow-up.
- **[LLM judge non-determinism]** → Context Precision and answer_correctness use LLM judgments that vary across runs. Mitigation: nightly tier accepts ±2% variance; release gate regression tolerance already accounts for this (2% tolerance).
- **[Label volume for fine-tuning]** → Golden set × 5 chunks = ~150 labels per run; thin for fine-tuning. Mitigation: labels accumulate across nightly runs; implicit feedback (FeedbackCollector) provides supplementary weak-positive signals.
- **[IterationRecord.latency_ms backward compat]** → Existing serialized traces lack this field. Mitigation: default to 0.0 when absent; efficiency report marks latency-dependent metrics as N/A for legacy data.
- **[NLI model availability]** → NLIKeyPointScorer needs an NLI model or LLM endpoint. Mitigation: gracefully falls back to embedding mode with a warning when NLI is unavailable.
