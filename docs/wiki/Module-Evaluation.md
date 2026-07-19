# Evaluation (`evaluation/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

A layered evaluation framework covering intent accuracy, retrieval quality, answer quality (RAGAs), and live business metrics — plus a CI release gate that blocks regressions.

## Four evaluation levels

| Level | Module | What it measures |
|-------|--------|------------------|
| **L1 Intent** | `evaluation/intent_eval.py` | Intent classification accuracy / F1 |
| **L2 Retrieval** | `evaluation/retrieval_eval.py` | MRR, Recall@K, NDCG@K (per intent) |
| **L3 Answer (RAGAs)** | `evaluation/ragas_eval.py` | Faithfulness, answer relevance, context utilization |
| **L4 Business** | `evaluation/business_monitor.py` | Resolution rate, negative-feedback rate, follow-up rate, citation-click rate |

## Datasets — `evaluation/datasets.py`

JSONL loaders (`_read_jsonl` helper):
- `load_intent_samples(path)` → `list[IntentSample(query, label)]`
- `load_retrieval_samples(path)` → `list[RetrievalSample(query, intent, ground_truth_doc_ids)]`
- `load_golden_samples(path)` → `list[GoldenSample(query, intent, reference_answer, ground_truth_doc_ids)]`

Datasets live under `data/eval/`.

## Types — `evaluation/types.py`

- `IntentSample`, `RetrievalSample`, `GoldenSample` — labeled inputs.
- `EvalReport(name, metrics, per_intent, passed, failures, to_dict())`.
- `GateResult(passed, reports, regressions, to_dict())`.

## Release gate — `evaluation/release_gate.py`

CI gate that runs the eval suite and **blocks a release on regressions** (e.g. > 2% drop vs. baseline). Produces a `GateResult`.

## Offline runner — `evaluation/run_offline.py`

Runs the golden set through `QueryService.query(bypass_cache=True)` so evaluation always exercises the full RAG path (never a cache hit). Supports two tiers:

```bash
# CI tier — fast (<2min), no LLM calls
python -m evaluation.run_offline --data-dir data/eval --tier ci

# Nightly tier — full metrics with LLM judge
python -m evaluation.run_offline --data-dir data/eval --tier nightly
```

### CI tier metrics

| Metric | Module | Description |
|--------|--------|-------------|
| Intent accuracy/F1 | `intent_eval.py` | L1 classification quality |
| MRR, Recall@K, NDCG@K | `retrieval_eval.py` | L2 retrieval quality per intent |
| RAGAs (Faithfulness, Answer Relevance, Context Utilization) | `ragas_eval.py` | L3 answer quality |
| **Key-Point Coverage** (embedding mode) | `keypoint_eval.py` | Atomic-claim coverage via MiniLM cosine (τ=0.65); gate ≥ 0.80 |
| **Answer Similarity** | `pipeline.py` | Embedding cosine between generated and reference answer |

### Nightly tier (adds to CI)

| Metric | Module | Description |
|--------|--------|-------------|
| **Context Precision@K** (CP@K) | `context_precision.py` | LLM judge per-chunk relevance; `(1/K) × Σ(relevance_i × 1/i)`; per-intent thresholds (Intent-1: 0.60, Intent-2: 0.55, Intent-3: 0.50) |
| **Rerank training label export** | `context_precision.py` | `(query, chunk, relevance, reranker_score)` → dated JSONL; auto-flags hard negatives (score ≥ 0.7 & relevance = 0) |
| **NLI Key-Point Coverage** | `keypoint_eval.py` | NLI/LLM entailment mode + hallucination detection (contradiction rate) |
| **Agentic Loop Efficiency** | `agentic_efficiency.py` | first_pass_rate, loop_trigger_rate, improvement_delta, wasted_loop_rate, cost_effectiveness; per-(tenant,intent) enable/skip/tune recommendation |

## Key-Point Coverage — `evaluation/keypoint_eval.py`

Pre-decomposes reference answers into atomic claims (key_points on `GoldenSample`). Two scorer implementations:

- **`EmbeddingKeyPointScorer`** — fast, deterministic; MiniLM cosine ≥ 0.65 per point. Used in CI tier.
- **`NLIKeyPointScorer`** — precise; NLI/LLM entailment checking + hallucination detection (contradiction rate). Falls back to embedding mode when no NLI backend is available. Used in Nightly tier.

`evaluate_keypoints(samples, answers, scorer)` → `EvalReport` with mean coverage; fails if < `COVERAGE_MIN = 0.80`.

## Context Precision — `evaluation/context_precision.py`

`ContextPrecisionEvaluator` judges each retrieved chunk's relevance via an injectable `judge_fn(query, reference, chunk) → 0.0|1.0`. In production, uses vLLM; in offline mock, a deterministic text-overlap heuristic.

`evaluate_context_precision(samples, chunks_per_sample)` → `(EvalReport, list[RerankTrainingSample])`:
- Per-intent CP@K breakdown.
- Training samples exported via `export_rerank_labels(samples, output_dir)` → dated JSONL under `data/eval/rerank_labels/`.

## Agentic Efficiency — `evaluation/agentic_efficiency.py`

`aggregate_agentic_efficiency(records_by_query, groups)` aggregates `IterationData` from `QueryTrace.agentic_scores`:

| Metric | Meaning |
|--------|---------|  
| `first_pass_rate` | Fraction passing at iteration 0 (no loop needed) |
| `loop_trigger_rate` | Fraction where iteration 0 failed (loop engaged) |
| `improvement_delta` | Mean rank improvement between consecutive iterations |
| `loop_success_rate` | Of triggered loops, fraction that eventually passed |
| `wasted_loop_rate` | Of triggered loops, fraction where final rank ≤ first rank |
| `cost_effectiveness` | `improvement_delta / mean_loop_latency_s` |

Per-group `(tenant:intent)` recommendations: `enable` / `skip` / `tune` — guides production whitelist configuration.

## Other modules

| File | Purpose |
|------|---------|  
| `evaluation/pipeline.py` | Daily auto-eval pipeline orchestration |
| `evaluation/keypoint_eval.py` | Key-point coverage (embedding + NLI modes) |
| `evaluation/context_precision.py` | CP@K via LLM judge + rerank label export |
| `evaluation/agentic_efficiency.py` | Agentic loop efficiency aggregation + recommendations |
| `evaluation/symmetry.py` | Intent-2 comparison symmetry check (A-vs-B ≈ B-vs-A) |
| `evaluation/kg_eval.py` | Knowledge-graph extraction quality |
| `evaluation/feedback.py` | Implicit user-feedback collection |
| `evaluation/business_monitor.py` | L4 business metric aggregation |

## Related specs

See `openspec/specs/evaluation-framework/` and `openspec/specs/offline-evaluation/`.
