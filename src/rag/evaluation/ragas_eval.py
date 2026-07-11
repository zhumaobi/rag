from __future__ import annotations

from dataclasses import dataclass

from raglog import get_logger

log = get_logger("ragas_eval")

# Spec thresholds for L3 generation quality.
FAITHFULNESS_MIN = 0.90
ANSWER_RELEVANCE_MIN = 0.85
CONTEXT_UTILIZATION_MIN = 0.60


@dataclass
class GenerationScore:
    faithfulness: float
    answer_relevance: float
    context_utilization: float

    def below_threshold(self) -> list[str]:
        issues = []
        if self.faithfulness < FAITHFULNESS_MIN:
            issues.append(f"faithfulness {self.faithfulness:.3f} < {FAITHFULNESS_MIN}")
        if self.answer_relevance < ANSWER_RELEVANCE_MIN:
            issues.append(f"answer_relevance {self.answer_relevance:.3f} < {ANSWER_RELEVANCE_MIN}")
        if self.context_utilization < CONTEXT_UTILIZATION_MIN:
            issues.append(f"context_utilization {self.context_utilization:.3f} < {CONTEXT_UTILIZATION_MIN}")
        return issues


@dataclass
class LowQualitySample:
    query: str
    answer: str
    score: GenerationScore
    issues: list[str]


class RagasEvaluator:
    """L3 generation-quality evaluation via RAGAs (task 8.4).

    Computes Faithfulness / Answer Relevance / Context Utilization. RAGAs itself is a
    heavy optional dependency loaded lazily; answers scoring below threshold (notably
    Faithfulness, i.e. hallucination) are captured into a low-quality sample store.
    """

    def __init__(self) -> None:
        self._backend = None
        self.low_quality: list[LowQualitySample] = []

    def _lazy_backend(self):
        if self._backend is None:
            from ragas import evaluate as ragas_evaluate  # noqa: F401
            from ragas.metrics import answer_relevancy, context_utilization, faithfulness

            self._backend = {
                "evaluate": ragas_evaluate,
                "metrics": [faithfulness, answer_relevancy, context_utilization],
            }
        return self._backend

    def score_one(
        self, query: str, answer: str, contexts: list[str], scorer=None
    ) -> GenerationScore:
        """Score a single answer. `scorer(query, answer, contexts) -> dict` can be injected
        (used in tests / when RAGAs is unavailable); otherwise the RAGAs backend is used."""
        if scorer is not None:
            raw = scorer(query, answer, contexts)
        else:
            raw = self._score_with_ragas(query, answer, contexts)
        score = GenerationScore(
            faithfulness=float(raw.get("faithfulness", 0.0)),
            answer_relevance=float(raw.get("answer_relevance", 0.0)),
            context_utilization=float(raw.get("context_utilization", 0.0)),
        )
        issues = score.below_threshold()
        if issues:
            self.low_quality.append(LowQualitySample(query, answer, score, issues))
            log.warning("low_quality_answer", query=query[:50], issues=issues)
        return score

    def _score_with_ragas(self, query: str, answer: str, contexts: list[str]) -> dict:
        from datasets import Dataset

        backend = self._lazy_backend()
        ds = Dataset.from_dict(
            {"question": [query], "answer": [answer], "contexts": [contexts], "ground_truth": [""]}
        )
        result = backend["evaluate"](ds, metrics=backend["metrics"])
        df = result.to_pandas().iloc[0]
        return {
            "faithfulness": df.get("faithfulness", 0.0),
            "answer_relevance": df.get("answer_relevancy", 0.0),
            "context_utilization": df.get("context_utilization", 0.0),
        }

    def aggregate(self, scores: list[GenerationScore]) -> dict[str, float]:
        if not scores:
            return {"faithfulness": 0.0, "answer_relevance": 0.0, "context_utilization": 0.0}
        n = len(scores)
        return {
            "faithfulness": sum(s.faithfulness for s in scores) / n,
            "answer_relevance": sum(s.answer_relevance for s in scores) / n,
            "context_utilization": sum(s.context_utilization for s in scores) / n,
        }
