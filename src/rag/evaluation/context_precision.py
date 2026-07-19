from __future__ import annotations

import json
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path

from evaluation.types import EvalReport, GoldenSample, RerankTrainingSample
from raglog import get_logger

log = get_logger("context_precision")

# Per-intent CP@K thresholds (initial conservative values).
_CP_THRESHOLDS = {
    "Intent-1": 0.60,
    "Intent-2": 0.55,
    "Intent-3": 0.50,
}

_HARD_NEGATIVE_RERANKER_SCORE = 0.7


class ContextPrecisionEvaluator:
    """Chunk-level context precision evaluation via LLM judge.

    For each golden sample, judges each retrieved chunk's relevance given the query
    and reference answer. Computes CP@K and exports labeled data for reranker fine-tuning.
    """

    def __init__(self, judge_fn=None) -> None:
        """
        Args:
            judge_fn: Injectable (query: str, reference: str, chunk: str) -> float
                      returning relevance (0.0 or 1.0). If None, uses vLLM in production.
        """
        self._judge_fn = judge_fn

    def _judge(self, query: str, reference: str, chunk: str) -> float:
        if self._judge_fn is not None:
            return self._judge_fn(query, reference, chunk)
        # Production path: call vLLM serving layer (lazy import to avoid hard dep).
        return self._judge_with_llm(query, reference, chunk)

    def _judge_with_llm(self, query: str, reference: str, chunk: str) -> float:
        """Default LLM judge using the vLLM serving layer."""
        from serving.vllm_client import get_client

        prompt = (
            f"判断以下检索片段是否与问题相关（给定参考答案）。\n"
            f"问题：{query}\n参考答案：{reference}\n检索片段：{chunk}\n"
            f"如果该片段对回答有帮助，输出1；否则输出0。只输出数字："
        )
        client = get_client()
        resp = client.generate(prompt, max_tokens=4)
        text = (resp or "").strip()
        return 1.0 if text.startswith("1") else 0.0

    def evaluate_sample(
        self,
        sample: GoldenSample,
        chunks: list[dict],
    ) -> tuple[float, list[RerankTrainingSample]]:
        """Evaluate one sample's retrieved chunks.

        Args:
            sample: Golden sample with query, intent, reference_answer.
            chunks: List of dicts with keys: text, doc_id, score (reranker score).

        Returns:
            (cp_at_k, training_samples) tuple.
        """
        if not chunks:
            return 0.0, []

        k = len(chunks)
        weighted_sum = 0.0
        training: list[RerankTrainingSample] = []
        ts = time.time()

        for i, chunk in enumerate(chunks, start=1):
            relevance = self._judge(sample.query, sample.reference_answer, chunk["text"])
            weighted_sum += relevance * (1.0 / i)

            reranker_score = chunk.get("score", 0.0)
            is_hard_negative = reranker_score >= _HARD_NEGATIVE_RERANKER_SCORE and relevance == 0.0
            training.append(
                RerankTrainingSample(
                    query=sample.query,
                    chunk_text=chunk["text"],
                    relevance=relevance,
                    reranker_score=reranker_score,
                    is_hard_negative=is_hard_negative,
                    intent=sample.intent,
                    doc_id=chunk.get("doc_id", ""),
                    ts=ts,
                )
            )

        cp_at_k = weighted_sum / k
        return cp_at_k, training


def evaluate_context_precision(
    samples: list[GoldenSample],
    chunks_per_sample: dict[str, list[dict]],
    judge_fn=None,
    thresholds: dict[str, float] | None = None,
) -> tuple[EvalReport, list[RerankTrainingSample]]:
    """Evaluate context precision across golden samples with per-intent breakdown.

    Args:
        samples: Golden samples with reference_answer.
        chunks_per_sample: Mapping of query -> list of chunk dicts (text, doc_id, score).
        judge_fn: Injectable judge function for testability.
        thresholds: Per-intent CP@K thresholds (defaults to _CP_THRESHOLDS).

    Returns:
        (EvalReport, all_training_samples) tuple.
    """
    thresholds = thresholds or _CP_THRESHOLDS
    evaluator = ContextPrecisionEvaluator(judge_fn=judge_fn)

    buckets: dict[str, list[float]] = defaultdict(list)
    all_training: list[RerankTrainingSample] = []

    eligible = [s for s in samples if s.reference_answer]
    for s in eligible:
        chunks = chunks_per_sample.get(s.query, [])
        cp, training = evaluator.evaluate_sample(s, chunks)
        buckets[s.intent].append(cp)
        all_training.extend(training)

    report = EvalReport(name="context_precision")
    for intent, scores in buckets.items():
        mean_cp = sum(scores) / len(scores) if scores else 0.0
        report.per_intent[intent] = {"cp@k": mean_cp}
        threshold = thresholds.get(intent)
        if threshold is not None and mean_cp < threshold:
            report.failures.append(f"{intent} cp@k {mean_cp:.4f} < {threshold}")

    report.passed = not report.failures
    log.info("context_precision_done", intents=list(buckets), passed=report.passed)
    return report, all_training


def export_rerank_labels(samples: list[RerankTrainingSample], output_dir: str) -> str:
    """Write training samples to a dated JSONL file.

    Args:
        samples: Labeled (query, chunk) pairs from context precision evaluation.
        output_dir: Directory to write labels (created if absent).

    Returns:
        Path to the written file.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    date_str = time.strftime("%Y-%m-%d")
    path = out / f"{date_str}.jsonl"

    lines = [json.dumps(asdict(s), ensure_ascii=False) for s in samples]
    # Append if file already exists (multiple runs per day).
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n" if lines else "")

    log.info("rerank_labels_exported", path=str(path), count=len(samples))
    return str(path)
