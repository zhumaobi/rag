from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path

from evaluation.datasets import (
    load_golden_samples,
    load_intent_samples,
    load_retrieval_samples,
)
from evaluation.intent_eval import evaluate_intent
from evaluation.ragas_eval import RagasEvaluator
from evaluation.release_gate import evaluate_gate, load_baseline, save_baseline
from evaluation.retrieval_eval import evaluate_retrieval
from evaluation.types import EvalReport
from raglog import get_logger

log = get_logger("eval_pipeline")


@dataclass
class Harness:
    """Callables wiring the eval framework to the live system. Injected so the pipeline
    stays testable and does not hard-depend on online services."""

    intent_predict: callable          # (query) -> label
    retrieve: callable                # (query, intent) -> ranked doc_ids
    generate: callable | None = None  # (query, intent) -> (answer, contexts)
    ragas_scorer: callable | None = None  # (query, answer, contexts) -> dict
    embedder: object | None = None    # sentence embedder for answer_similarity


def run_daily(harness: Harness, data_dir: str, report_dir: str, ts: float, tier: str = "ci") -> dict:
    """Task 8.7: run L1 (intent) + L2 (retrieval) + L3 (generation) on the eval sets and
    write a timestamped report. `ts` is passed in (no wall-clock read) for determinism.
    `tier` controls which metrics are computed: "ci" (fast) or "nightly" (full)."""
    reports: list[EvalReport] = []

    intent_samples = load_intent_samples(f"{data_dir}/intent_eval.jsonl")
    if intent_samples:
        reports.append(evaluate_intent(intent_samples, harness.intent_predict))

    retrieval_samples = load_retrieval_samples(f"{data_dir}/retrieval_eval.jsonl")
    if retrieval_samples:
        reports.append(evaluate_retrieval(retrieval_samples, harness.retrieve))

    golden = load_golden_samples(f"{data_dir}/golden_set.jsonl")
    if golden and harness.generate is not None:
        reports.append(_run_generation_eval(golden, harness))

    out = {"ts": ts, "reports": [r.to_dict() for r in reports]}
    Path(report_dir).mkdir(parents=True, exist_ok=True)
    report_path = Path(report_dir) / f"daily_{int(ts)}.json"
    report_path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("daily_eval_written", path=str(report_path), reports=len(reports))
    return out


def _run_generation_eval(golden, harness: Harness) -> EvalReport:
    evaluator = RagasEvaluator()
    scores = []
    similarities: list[float] = []
    for s in golden:
        answer, contexts = harness.generate(s.query, s.intent)
        scores.append(
            evaluator.score_one(s.query, answer, contexts, scorer=harness.ragas_scorer, reference_answer=s.reference_answer)
        )
        # Answer similarity: cosine between answer and reference embeddings.
        if s.reference_answer and hasattr(harness, "embedder") and harness.embedder is not None:
            sim = _answer_similarity(harness.embedder, answer, s.reference_answer)
            similarities.append(sim)
    agg = evaluator.aggregate(scores)
    if similarities:
        agg["answer_similarity"] = sum(similarities) / len(similarities)
    report = EvalReport(name="generation", metrics=agg)
    from evaluation.ragas_eval import (
        ANSWER_RELEVANCE_MIN,
        CONTEXT_UTILIZATION_MIN,
        FAITHFULNESS_MIN,
    )

    if agg["faithfulness"] < FAITHFULNESS_MIN:
        report.failures.append(f"faithfulness {agg['faithfulness']:.4f} < {FAITHFULNESS_MIN}")
    if agg["answer_relevance"] < ANSWER_RELEVANCE_MIN:
        report.failures.append(f"answer_relevance {agg['answer_relevance']:.4f} < {ANSWER_RELEVANCE_MIN}")
    if agg["context_utilization"] < CONTEXT_UTILIZATION_MIN:
        report.failures.append(f"context_utilization {agg['context_utilization']:.4f} < {CONTEXT_UTILIZATION_MIN}")
    report.passed = not report.failures
    report.metrics["low_quality_count"] = float(len(evaluator.low_quality))
    return report


def run_release_gate(harness: Harness, data_dir: str, baseline_path: str, e2e_accuracy: float | None):
    """Task 8.8 entrypoint: full Golden Set eval + regression gate against baseline."""
    reports: list[EvalReport] = []
    intent_samples = load_intent_samples(f"{data_dir}/intent_eval.jsonl")
    if intent_samples:
        reports.append(evaluate_intent(intent_samples, harness.intent_predict))
    retrieval_samples = load_retrieval_samples(f"{data_dir}/retrieval_eval.jsonl")
    if retrieval_samples:
        reports.append(evaluate_retrieval(retrieval_samples, harness.retrieve))

    baseline = load_baseline(baseline_path)
    result = evaluate_gate(reports, baseline, e2e_accuracy)
    return result


def _answer_similarity(embedder, answer: str, reference: str) -> float:
    """Cosine similarity between answer and reference embeddings."""
    vecs = embedder.embed_texts([answer, reference])
    a, b = vecs[0], vecs[1]
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluation pipeline (daily / gate)")
    parser.add_argument("--mode", choices=["daily", "gate"], default="daily")
    parser.add_argument("--data-dir", default="data/eval")
    parser.add_argument("--report-dir", default="reports/eval")
    parser.add_argument("--baseline", default="reports/eval/baseline.json")
    parser.add_argument("--ts", type=float, default=0.0)
    args = parser.parse_args()
    log.info("eval_cli_invoked", mode=args.mode)
    print(f"configure a Harness and call run_daily/run_release_gate; mode={args.mode}")


if __name__ == "__main__":
    main()
