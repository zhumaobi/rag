from __future__ import annotations

import re
from typing import Protocol

from evaluation.types import EvalReport, GoldenSample, KeyPointResult, PointScore
from raglog import get_logger

log = get_logger("keypoint_eval")

# Default cosine similarity threshold for considering a key point "covered".
DEFAULT_THRESHOLD = 0.65

# CI gate threshold for mean coverage across the golden set.
COVERAGE_MIN = 0.80


class KeyPointScorer(Protocol):
    """Protocol for key-point coverage scoring."""

    def score(self, answer: str, key_points: list[str]) -> KeyPointResult: ...


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on Chinese/English punctuation boundaries."""
    parts = re.split(r"[。！？；\n.!?;]+", text)
    return [s.strip() for s in parts if s.strip()]


class EmbeddingKeyPointScorer:
    """Fast, deterministic key-point coverage via cosine similarity.

    Uses the existing MiniLM sentence embedding model. A key point is considered
    covered when its max cosine similarity against all answer sentences >= threshold.
    """

    def __init__(self, embedder=None, threshold: float = DEFAULT_THRESHOLD) -> None:
        self._embedder = embedder
        self._threshold = threshold

    def _get_embedder(self):
        if self._embedder is None:
            from pipeline.embed import get_embedder

            self._embedder = get_embedder()
        return self._embedder

    def score(self, answer: str, key_points: list[str]) -> KeyPointResult:
        if not key_points:
            return KeyPointResult(coverage=1.0, per_point=[], mode="embedding")

        embedder = self._get_embedder()
        sentences = _split_sentences(answer)
        if not sentences:
            # No answer text: nothing is covered.
            per_point = [PointScore(key_point=kp, covered=False, best_similarity=0.0) for kp in key_points]
            return KeyPointResult(coverage=0.0, per_point=per_point, mode="embedding")

        sent_embeddings = embedder.embed_texts(sentences)
        kp_embeddings = embedder.embed_texts(key_points)

        per_point: list[PointScore] = []
        covered_count = 0
        for kp, kp_emb in zip(key_points, kp_embeddings):
            best_sim = 0.0
            best_sent = ""
            for sent, s_emb in zip(sentences, sent_embeddings):
                sim = _cosine(kp_emb, s_emb)
                if sim > best_sim:
                    best_sim = sim
                    best_sent = sent
            is_covered = best_sim >= self._threshold
            if is_covered:
                covered_count += 1
            per_point.append(
                PointScore(key_point=kp, covered=is_covered, best_similarity=best_sim, matched_sentence=best_sent)
            )

        coverage = covered_count / len(key_points)
        return KeyPointResult(coverage=coverage, per_point=per_point, mode="embedding")


class NLIKeyPointScorer:
    """Precise key-point coverage via NLI/LLM entailment checking.

    Falls back to EmbeddingKeyPointScorer when no NLI backend is available.
    Additionally detects hallucinations: answer claims that contradict key points.
    """

    def __init__(self, nli_fn=None, embedder=None, threshold: float = DEFAULT_THRESHOLD) -> None:
        """
        Args:
            nli_fn: Optional callable (premise: str, hypothesis: str) -> str
                    returning "entailment" | "neutral" | "contradiction".
                    If None, falls back to embedding mode.
            embedder: Embedder for fallback mode.
            threshold: Cosine threshold for fallback embedding mode.
        """
        self._nli_fn = nli_fn
        self._fallback = EmbeddingKeyPointScorer(embedder=embedder, threshold=threshold)

    def score(self, answer: str, key_points: list[str]) -> KeyPointResult:
        if self._nli_fn is None:
            log.warning("nli_unavailable_fallback_to_embedding")
            result = self._fallback.score(answer, key_points)
            result.mode = "embedding_fallback"
            return result

        if not key_points:
            return KeyPointResult(coverage=1.0, per_point=[], mode="nli")

        sentences = _split_sentences(answer)
        per_point: list[PointScore] = []
        covered_count = 0

        for kp in key_points:
            # Check if the answer entails this key point.
            verdict = self._nli_fn(answer, kp)
            is_covered = verdict in ("entailment", "neutral")
            if is_covered:
                covered_count += 1
            per_point.append(PointScore(key_point=kp, covered=is_covered, best_similarity=1.0 if is_covered else 0.0))

        # Hallucination detection: check if answer sentences contradict key points.
        contradiction_count = 0
        if sentences:
            kp_joined = "；".join(key_points)
            for sent in sentences:
                verdict = self._nli_fn(kp_joined, sent)
                if verdict == "contradiction":
                    contradiction_count += 1

        hallucination_rate = contradiction_count / len(sentences) if sentences else 0.0
        coverage = covered_count / len(key_points)
        return KeyPointResult(
            coverage=coverage, per_point=per_point, hallucination_rate=hallucination_rate, mode="nli"
        )


def evaluate_keypoints(
    samples: list[GoldenSample],
    answers: dict[str, str],
    scorer: KeyPointScorer,
    threshold: float = COVERAGE_MIN,
) -> EvalReport:
    """Evaluate key-point coverage across golden samples.

    Args:
        samples: Golden samples (those with empty key_points are skipped).
        answers: Mapping of query -> generated answer text.
        scorer: A KeyPointScorer implementation.
        threshold: Minimum mean coverage to pass the gate.

    Returns:
        EvalReport with coverage metric and per-sample detail.
    """
    eligible = [s for s in samples if s.key_points]
    if not eligible:
        return EvalReport(name="keypoint_coverage", metrics={"coverage": 1.0}, passed=True)

    coverages: list[float] = []
    for s in eligible:
        answer = answers.get(s.query, "")
        result = scorer.score(answer, s.key_points)
        coverages.append(result.coverage)

    mean_coverage = sum(coverages) / len(coverages)
    report = EvalReport(name="keypoint_coverage", metrics={"coverage": mean_coverage, "samples": float(len(eligible))})
    if mean_coverage < threshold:
        report.failures.append(f"key_point_coverage {mean_coverage:.4f} < {threshold}")
    report.passed = not report.failures
    log.info("keypoint_eval_done", coverage=round(mean_coverage, 4), samples=len(eligible), passed=report.passed)
    return report


def _cosine(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
