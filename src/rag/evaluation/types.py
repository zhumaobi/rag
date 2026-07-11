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
