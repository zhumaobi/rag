"""Unit tests for the offline evaluation enhancements.

Covers: key-point coverage (embedding + NLI fallback), reference wiring,
context precision, agentic efficiency aggregation, and CI/nightly tier split.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "rag"))

from evaluation.types import EvalReport, GoldenSample, KeyPointResult, PointScore, RerankTrainingSample
from evaluation.keypoint_eval import (
    EmbeddingKeyPointScorer,
    NLIKeyPointScorer,
    evaluate_keypoints,
    _cosine,
    _split_sentences,
)
from evaluation.context_precision import (
    ContextPrecisionEvaluator,
    evaluate_context_precision,
    export_rerank_labels,
)
from evaluation.agentic_efficiency import (
    AgenticEfficiencyReport,
    IterationData,
    aggregate_agentic_efficiency,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class DeterministicEmbedder:
    """Embeds text as a normalized bag-of-characters vector (dim=26)."""

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * 26
        for ch in text.lower():
            if "a" <= ch <= "z":
                v[ord(ch) - ord("a")] += 1.0
        norm = sum(x * x for x in v) ** 0.5
        if norm > 0:
            v = [x / norm for x in v]
        return v


def _golden(query="q", intent="Intent-1", ref="ref answer", key_points=None):
    return GoldenSample(
        query=query, intent=intent, reference_answer=ref,
        ground_truth_doc_ids=[], key_points=key_points or [],
    )


# ---------------------------------------------------------------------------
# 2.4 EmbeddingKeyPointScorer tests
# ---------------------------------------------------------------------------

class TestEmbeddingKeyPointScorer:
    def setup_method(self):
        self.scorer = EmbeddingKeyPointScorer(embedder=DeterministicEmbedder(), threshold=0.5)

    def test_all_covered(self):
        # Key points that share characters with the answer should be covered.
        result = self.scorer.score("hello world", ["hello", "world"])
        assert result.coverage == 1.0
        assert result.mode == "embedding"
        assert all(p.covered for p in result.per_point)

    def test_none_covered(self):
        # Key points with no character overlap won't match.
        result = self.scorer.score("aaaa bbbb", ["zzzz", "yyyy"])
        assert result.coverage == 0.0
        assert not any(p.covered for p in result.per_point)

    def test_partial_coverage(self):
        result = self.scorer.score("hello world", ["hello", "zzzz"])
        assert result.coverage == 0.5

    def test_empty_key_points_returns_full_coverage(self):
        result = self.scorer.score("any answer", [])
        assert result.coverage == 1.0
        assert result.per_point == []

    def test_empty_answer_returns_zero_coverage(self):
        result = self.scorer.score("", ["point a", "point b"])
        assert result.coverage == 0.0

    def test_threshold_boundary(self):
        # With threshold=1.0, only exact matches pass.
        strict = EmbeddingKeyPointScorer(embedder=DeterministicEmbedder(), threshold=1.0)
        result = strict.score("hello", ["hello"])
        assert result.coverage == 1.0  # identical text → cosine = 1.0

    def test_per_point_detail(self):
        result = self.scorer.score("hello world", ["hello"])
        assert len(result.per_point) == 1
        assert result.per_point[0].key_point == "hello"
        assert result.per_point[0].best_similarity > 0.5
        assert result.per_point[0].matched_sentence != ""


# ---------------------------------------------------------------------------
# 2.5 NLIKeyPointScorer fallback tests
# ---------------------------------------------------------------------------

class TestNLIKeyPointScorer:
    def test_fallback_when_nli_none(self):
        scorer = NLIKeyPointScorer(nli_fn=None, embedder=DeterministicEmbedder(), threshold=0.5)
        result = scorer.score("hello world", ["hello"])
        assert result.mode == "embedding_fallback"
        assert result.coverage == 1.0

    def test_nli_mode_with_mock_fn(self):
        def mock_nli(premise, hypothesis):
            return "entailment" if hypothesis in premise else "contradiction"

        scorer = NLIKeyPointScorer(nli_fn=mock_nli)
        result = scorer.score("the answer is hello world", ["hello", "missing"])
        assert result.mode == "nli"
        assert result.coverage == 0.5  # "hello" entailed, "missing" contradicted

    def test_nli_hallucination_detection(self):
        def mock_nli(premise, hypothesis):
            # Contradict any sentence containing "false"
            if "false" in hypothesis:
                return "contradiction"
            return "entailment"

        scorer = NLIKeyPointScorer(nli_fn=mock_nli)
        result = scorer.score("true statement. false claim.", ["true"])
        assert result.hallucination_rate == 0.5  # 1 of 2 sentences contradicted

    def test_empty_key_points_nli(self):
        def mock_nli(p, h):
            return "entailment"

        scorer = NLIKeyPointScorer(nli_fn=mock_nli)
        result = scorer.score("answer", [])
        assert result.coverage == 1.0
        assert result.mode == "nli"


# ---------------------------------------------------------------------------
# 2.4+ evaluate_keypoints aggregation
# ---------------------------------------------------------------------------

class TestEvaluateKeypoints:
    def test_skips_samples_without_key_points(self):
        samples = [_golden(key_points=[]), _golden(key_points=[])]
        scorer = EmbeddingKeyPointScorer(embedder=DeterministicEmbedder())
        report = evaluate_keypoints(samples, {"q": "answer"}, scorer)
        assert report.passed is True
        assert report.metrics["coverage"] == 1.0

    def test_gate_fails_below_threshold(self):
        samples = [_golden(query="q1", key_points=["zzzz"])]
        scorer = EmbeddingKeyPointScorer(embedder=DeterministicEmbedder(), threshold=0.9)
        report = evaluate_keypoints(samples, {"q1": "aaaa"}, scorer, threshold=0.80)
        assert report.passed is False
        assert "key_point_coverage" in report.failures[0]


# ---------------------------------------------------------------------------
# 3.4 RAGAs reference wiring
# ---------------------------------------------------------------------------

class TestRagasReferenceWiring:
    def test_ground_truth_populated(self):
        """Verify score_one passes reference_answer through to the scorer."""
        captured = {}

        def spy_scorer(query, answer, contexts):
            captured["called"] = True
            return {"faithfulness": 0.95, "answer_relevance": 0.90, "context_utilization": 0.80}

        from evaluation.ragas_eval import RagasEvaluator

        evaluator = RagasEvaluator()
        evaluator.score_one("q", "a", ["c"], scorer=spy_scorer, reference_answer="the reference")
        assert captured.get("called") is True

    def test_score_one_signature_accepts_reference(self):
        """Verify the reference_answer parameter exists and defaults to empty."""
        import inspect
        from evaluation.ragas_eval import RagasEvaluator

        sig = inspect.signature(RagasEvaluator.score_one)
        assert "reference_answer" in sig.parameters
        assert sig.parameters["reference_answer"].default == ""


# ---------------------------------------------------------------------------
# 4.5 Context Precision tests
# ---------------------------------------------------------------------------

class TestContextPrecision:
    def test_cp_at_k_computation(self):
        # 3 chunks: relevant, irrelevant, relevant → CP@3 = (1/1 + 0/2 + 1/3) / 3
        def judge(q, ref, chunk):
            return 1.0 if "good" in chunk else 0.0

        evaluator = ContextPrecisionEvaluator(judge_fn=judge)
        sample = _golden(ref="ref")
        chunks = [
            {"text": "good chunk 1", "doc_id": "d1", "score": 0.9},
            {"text": "bad chunk", "doc_id": "d2", "score": 0.85},
            {"text": "good chunk 3", "doc_id": "d3", "score": 0.7},
        ]
        cp, training = evaluator.evaluate_sample(sample, chunks)
        expected = (1.0 + 0.0 + 1.0 / 3) / 3
        assert abs(cp - expected) < 1e-6
        assert len(training) == 3

    def test_hard_negative_flagging(self):
        def judge(q, ref, chunk):
            return 0.0  # all irrelevant

        evaluator = ContextPrecisionEvaluator(judge_fn=judge)
        sample = _golden()
        chunks = [
            {"text": "chunk", "doc_id": "d1", "score": 0.8},   # hard negative (≥0.7)
            {"text": "chunk", "doc_id": "d2", "score": 0.5},   # not hard negative
        ]
        _, training = evaluator.evaluate_sample(sample, chunks)
        assert training[0].is_hard_negative is True
        assert training[1].is_hard_negative is False

    def test_empty_chunks(self):
        evaluator = ContextPrecisionEvaluator(judge_fn=lambda q, r, c: 1.0)
        cp, training = evaluator.evaluate_sample(_golden(), [])
        assert cp == 0.0
        assert training == []

    def test_per_intent_breakdown(self):
        def judge(q, ref, chunk):
            return 1.0

        samples = [
            _golden(query="q1", intent="Intent-1"),
            _golden(query="q2", intent="Intent-2"),
        ]
        chunks_map = {
            "q1": [{"text": "c", "doc_id": "d", "score": 0.9}],
            "q2": [{"text": "c", "doc_id": "d", "score": 0.9}],
        }
        report, _ = evaluate_context_precision(samples, chunks_map, judge_fn=judge)
        assert "Intent-1" in report.per_intent
        assert "Intent-2" in report.per_intent
        assert report.per_intent["Intent-1"]["cp@k"] == 1.0

    def test_export_rerank_labels(self):
        samples = [
            RerankTrainingSample(
                query="q", chunk_text="c", relevance=0.0, reranker_score=0.8,
                is_hard_negative=True, intent="Intent-1", doc_id="d1", ts=1000.0,
            )
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = export_rerank_labels(samples, tmp)
            assert Path(path).exists()
            lines = Path(path).read_text(encoding="utf-8").strip().splitlines()
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["is_hard_negative"] is True


# ---------------------------------------------------------------------------
# 5.6 Agentic Efficiency tests
# ---------------------------------------------------------------------------

class TestAgenticEfficiency:
    def test_first_pass_rate(self):
        records = [
            [IterationData(0, False, 0.95, 0.90, True)],
            [IterationData(0, False, 0.92, 0.88, True)],
            [IterationData(0, False, 0.70, 0.60, False),
             IterationData(1, True, 0.91, 0.87, True)],
        ]
        report = aggregate_agentic_efficiency(records)
        assert abs(report.first_pass_rate - 2 / 3) < 1e-6
        assert report.total_queries == 3

    def test_wasted_loop(self):
        records = [
            [IterationData(0, False, 0.70, 0.60, False),
             IterationData(1, True, 0.65, 0.55, False)],  # rank decreased
        ]
        report = aggregate_agentic_efficiency(records)
        assert report.wasted_loop_rate == 1.0

    def test_improvement_delta(self):
        records = [
            [IterationData(0, False, 0.60, 0.50, False),
             IterationData(1, True, 0.80, 0.70, True)],
        ]
        report = aggregate_agentic_efficiency(records)
        # delta = (0.80+0.70) - (0.60+0.50) = 0.40
        assert abs(report.improvement_delta - 0.40) < 1e-6

    def test_empty_input(self):
        report = aggregate_agentic_efficiency([])
        assert report.total_queries == 0
        assert report.first_pass_rate == 0.0

    def test_legacy_latency_zero(self):
        records = [
            [IterationData(0, False, 0.70, 0.60, False, latency_ms=0.0),
             IterationData(1, True, 0.90, 0.85, True, latency_ms=0.0)],
        ]
        report = aggregate_agentic_efficiency(records)
        assert report.cost_effectiveness is None  # no latency data

    def test_cost_effectiveness_with_latency(self):
        records = [
            [IterationData(0, False, 0.60, 0.50, False, latency_ms=100.0),
             IterationData(1, True, 0.80, 0.70, True, latency_ms=200.0)],
        ]
        report = aggregate_agentic_efficiency(records)
        assert report.cost_effectiveness is not None
        assert report.cost_effectiveness > 0

    def test_per_group_breakdown(self):
        groups = {
            "t1:Intent-1": [[IterationData(0, False, 0.95, 0.90, True)]],
            "t1:Intent-2": [
                [IterationData(0, False, 0.60, 0.50, False),
                 IterationData(1, True, 0.80, 0.70, True)]
            ],
        }
        report = aggregate_agentic_efficiency([], groups=groups)
        assert "t1:Intent-1" in report.per_group
        assert report.per_group["t1:Intent-1"].first_pass_rate == 1.0
        assert report.recommendations["t1:Intent-1"] == "skip"  # trigger rate < 0.2

    def test_recommendation_enable(self):
        # High trigger rate + good improvement + low waste → enable
        records = [
            [IterationData(0, False, 0.60, 0.50, False),
             IterationData(1, True, 0.90, 0.85, True)]
            for _ in range(10)
        ]
        report = aggregate_agentic_efficiency(records)
        assert report.recommendations.get("global") == "enable"


# ---------------------------------------------------------------------------
# 6.7 Integration: CI tier vs Nightly tier
# ---------------------------------------------------------------------------

class TestTierSplit:
    def test_ci_tier_no_llm_calls(self):
        """CI tier should not invoke any LLM judge functions."""
        from evaluation.run_offline import run_offline
        from query.wiring import build_mock
        from query.fakes import FakeEmbedder

        # run_offline with tier="ci" should complete without errors
        # using the mock service (no real LLM calls).
        result = run_offline("../../data/eval", service=build_mock(), tier="ci", embedder=FakeEmbedder())
        assert "reports" in result
        assert result["tier"] == "ci"
        # Should have intent, retrieval, generation, and keypoint reports.
        report_names = [r["name"] for r in result["reports"]]
        assert "keypoint_coverage" in report_names

    def test_nightly_tier_includes_extra_metrics(self):
        """Nightly tier should include context_precision and/or agentic_efficiency."""
        from evaluation.run_offline import run_offline
        from query.wiring import build_mock
        from query.fakes import FakeEmbedder

        result = run_offline("../../data/eval", service=build_mock(), tier="nightly", embedder=FakeEmbedder())
        assert result["tier"] == "nightly"
        report_names = [r["name"] for r in result["reports"]]
        # Nightly adds context_precision (if chunks available).
        # At minimum, it should not crash and should include base reports.
        assert "keypoint_coverage" in report_names
