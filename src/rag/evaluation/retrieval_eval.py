from __future__ import annotations

import math
from collections import defaultdict

from evaluation.types import EvalReport, RetrievalSample
from raglog import get_logger

log = get_logger("retrieval_eval")

# Per-intent baselines from the spec (retrieval quality targets).
_THRESHOLDS = {
    "Intent-1": {"mrr": 0.80, "recall@5": 0.88},
    "Intent-2": {"recall@5": 0.85},
    "Intent-3": {"recall@5": 0.82},
}


def _mrr(gt: set[str], ranked_doc_ids: list[str]) -> float:
    for rank, doc_id in enumerate(ranked_doc_ids, start=1):
        if doc_id in gt:
            return 1.0 / rank
    return 0.0


def _recall_at_k(gt: set[str], ranked_doc_ids: list[str], k: int) -> float:
    if not gt:
        return 0.0
    topk = set(ranked_doc_ids[:k])
    return len(gt & topk) / len(gt)


def _ndcg_at_k(gt: set[str], ranked_doc_ids: list[str], k: int) -> float:
    dcg = 0.0
    for i, doc_id in enumerate(ranked_doc_ids[:k]):
        if doc_id in gt:
            dcg += 1.0 / math.log2(i + 2)
    ideal_hits = min(len(gt), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    return dcg / idcg if idcg else 0.0


def evaluate_retrieval(samples: list[RetrievalSample], retrieve_fn, k: int = 5) -> EvalReport:
    """Task 8.2: compute MRR, Recall@K, NDCG@K per intent (not merged).
    `retrieve_fn(query, intent) -> list[doc_id]` in ranked order."""
    if not samples:
        return EvalReport(name="retrieval", passed=False, failures=["empty eval set"])

    buckets: dict[str, list[dict]] = defaultdict(list)
    for s in samples:
        ranked = retrieve_fn(s.query, s.intent)
        gt = set(s.ground_truth_doc_ids)
        buckets[s.intent].append(
            {
                "mrr": _mrr(gt, ranked),
                f"recall@{k}": _recall_at_k(gt, ranked, k),
                f"ndcg@{k}": _ndcg_at_k(gt, ranked, k),
            }
        )

    report = EvalReport(name="retrieval")
    for intent, rows in buckets.items():
        agg = {metric: sum(r[metric] for r in rows) / len(rows) for metric in rows[0]}
        report.per_intent[intent] = agg
        for metric, threshold in _THRESHOLDS.get(intent, {}).items():
            if agg.get(metric, 0.0) < threshold:
                report.failures.append(f"{intent} {metric} {agg.get(metric, 0.0):.4f} < {threshold}")

    report.passed = not report.failures
    log.info("retrieval_eval_done", intents=list(buckets), passed=report.passed)
    return report
