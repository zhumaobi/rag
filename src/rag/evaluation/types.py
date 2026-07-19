from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class IntentSample:
    query: str
    label: str  # "Intent-1" | "Intent-2" | "Intent-3"


@dataclass
class RetrievalSample:
    query: str
    intent: str
    ground_truth_doc_ids: list[str]


@dataclass
class GoldenSample:
    query: str
    intent: str
    reference_answer: str
    ground_truth_doc_ids: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)


@dataclass
class EvalReport:
    """A named collection of metric values plus pass/fail against thresholds."""

    name: str
    metrics: dict[str, float] = field(default_factory=dict)
    per_intent: dict[str, dict[str, float]] = field(default_factory=dict)
    passed: bool = True
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "metrics": self.metrics,
            "per_intent": self.per_intent,
            "passed": self.passed,
            "failures": self.failures,
        }


@dataclass
class GateResult:
    passed: bool
    reports: list[EvalReport] = field(default_factory=list)
    regressions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "reports": [r.to_dict() for r in self.reports],
            "regressions": self.regressions,
        }


@dataclass
class PointScore:
    """Per-key-point scoring detail."""

    key_point: str
    covered: bool
    best_similarity: float = 0.0
    matched_sentence: str = ""


@dataclass
class KeyPointResult:
    """Result of key-point coverage scoring for one answer."""

    coverage: float
    per_point: list[PointScore] = field(default_factory=list)
    hallucination_rate: float = 0.0
    mode: str = "embedding"  # "embedding" | "nli" | "embedding_fallback"


@dataclass
class RerankTrainingSample:
    """A single labeled (query, chunk) pair for cross-encoder fine-tuning."""

    query: str
    chunk_text: str
    relevance: float  # LLM judge output: 0.0 or 1.0
    reranker_score: float  # original cross-encoder score
    is_hard_negative: bool  # True when reranker_score >= 0.7 AND relevance == 0.0
    intent: str
    doc_id: str
    ts: float
