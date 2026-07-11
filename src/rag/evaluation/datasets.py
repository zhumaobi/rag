from __future__ import annotations

import json
from pathlib import Path

from evaluation.types import GoldenSample, IntentSample, RetrievalSample


def _read_jsonl(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_intent_samples(path: str) -> list[IntentSample]:
    return [IntentSample(query=r["query"], label=r["label"]) for r in _read_jsonl(path)]


def load_retrieval_samples(path: str) -> list[RetrievalSample]:
    return [
        RetrievalSample(
            query=r["query"], intent=r["intent"], ground_truth_doc_ids=r["ground_truth_doc_ids"]
        )
        for r in _read_jsonl(path)
    ]


def load_golden_samples(path: str) -> list[GoldenSample]:
    return [
        GoldenSample(
            query=r["query"],
            intent=r["intent"],
            reference_answer=r["reference_answer"],
            ground_truth_doc_ids=r.get("ground_truth_doc_ids", []),
        )
        for r in _read_jsonl(path)
    ]
