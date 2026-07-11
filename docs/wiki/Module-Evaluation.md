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

Runs the golden set through `QueryService.query(bypass_cache=True)` so evaluation always exercises the full RAG path (never a cache hit).

## Other modules

| File | Purpose |
|------|---------|
| `evaluation/pipeline.py` | Daily auto-eval pipeline orchestration |
| `evaluation/symmetry.py` | Intent-2 comparison symmetry check (A-vs-B ≈ B-vs-A) |
| `evaluation/kg_eval.py` | Knowledge-graph extraction quality |
| `evaluation/feedback.py` | Implicit user-feedback collection |
| `evaluation/business_monitor.py` | L4 business metric aggregation |

## Related specs

See `openspec/specs/evaluation-framework/` and `openspec/specs/offline-evaluation/`.
