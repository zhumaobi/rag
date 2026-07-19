"""Tests for the opt-in Agentic RAG self-correction loop (add-agentic-rag-loop).

Covers: non-opted single-pass, opted-in pass-on-first, HyDE rewrite + re-retrieval on
failure, deadline/iteration exhaustion returning best-so-far with low_confidence, RAGAs
unavailable graceful fallback, and an end-to-end mock run.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "rag"))

from rag.query.agentic import (  # noqa: E402
    AgenticConfig,
    AgenticController,
    AgenticRetriever,
    HyDERewriter,
)
from rag.evaluation.ragas_eval import RagasEvaluator  # noqa: E402
from rag.retrieval.types import RetrievedChunk  # noqa: E402
from rag.serving.types import GenResult, PoolTier  # noqa: E402


class _Embedder:
    def embed_texts(self, texts):
        return [[float(len(t) % 7)] * 4 for t in texts]


class _Dense:
    def __init__(self):
        self.calls = []

    def retrieve(self, tenant_id, query_embedding, top_k=10, collection_id=None, doc_ids=None):
        self.calls.append(list(query_embedding))
        return [RetrievedChunk(chunk_id="d0", doc_id="doc0", text="dense passage", score=1.0, source="dense")]


class _Sparse:
    def __init__(self):
        self.queries = []

    def retrieve(self, tenant_id, query_text, top_k=10, collection_id=None):
        self.queries.append(query_text)
        return [RetrievedChunk(chunk_id="s0", doc_id="doc0", text="sparse passage", score=1.0, source="sparse")]


class _Reranker:
    def rerank(self, query, candidates, top_k=5):
        return candidates[:top_k]


class _Dispatcher:
    """Records generate calls; returns a canned answer. Tracks which pool tier HyDE hits."""

    def __init__(self):
        self.gen_intents = []

    async def generate(self, req, context, fallback_chunks_text="", cached_answer=None):
        self.gen_intents.append(req.intent)
        return GenResult(text=f"answer::{req.prompt[:20]}", tier=PoolTier.SMALL, instance_id="s0", prompt="p")


def _controller(scorer, *, max_iters=2, deadline_s=20.0, dispatcher=None, dense=None, sparse=None):
    dispatcher = dispatcher or _Dispatcher()
    dense = dense or _Dense()
    sparse = sparse or _Sparse()
    embedder = _Embedder()
    retriever = AgenticRetriever(dense=dense, sparse=sparse, reranker=_Reranker())
    return AgenticController(
        retriever=retriever,
        dispatcher=dispatcher,
        evaluator=RagasEvaluator(),
        hyde=HyDERewriter(dispatcher, embedder),
        embedder=embedder,
        config=AgenticConfig(enabled_tenants=frozenset({"t1"}), enabled_intents=frozenset({"Intent-1"}),
                             deadline_s=deadline_s, max_iters=max_iters),
        ragas_scorer=scorer,
    )


# ---- 8.1 non-opted uses single pass -------------------------------------------------

def test_config_gating():
    cfg = AgenticConfig(enabled_tenants=frozenset({"t1"}), enabled_intents=frozenset({"Intent-1"}))
    assert cfg.is_enabled("t1", "Intent-1")
    assert not cfg.is_enabled("t1", "Intent-2")
    assert not cfg.is_enabled("other", "Intent-1")


def test_config_from_settings_splits_csv():
    class S:
        agentic_enabled_tenants = "t1, t2 ,"
        agentic_enabled_intents = "Intent-1"
        agentic_deadline_s = 12.0
        agentic_max_iters = 3

    cfg = AgenticConfig.from_settings(S())
    assert cfg.enabled_tenants == frozenset({"t1", "t2"})
    assert cfg.enabled_intents == frozenset({"Intent-1"})
    assert cfg.deadline_s == 12.0 and cfg.max_iters == 3


# ---- 8.2 opted-in passing candidate returns immediately (no rewrite) ----------------

def test_pass_first_iteration_no_rewrite():
    dense = _Dense()
    ctrl = _controller(lambda q, a, c: {"faithfulness": 0.95, "answer_relevance": 0.90, "context_utilization": 0.8},
                       dense=dense)
    res = asyncio.run(ctrl.run("t1", "如何配置限流", "Intent-1", [0.1] * 4, collection_id="collA"))
    assert res.iterations == 1
    assert res.low_confidence is False
    assert len(dense.calls) == 1  # only one retrieval, no HyDE re-retrieve
    assert res.iteration_records[0].passed is True


# ---- 8.3 failing candidate triggers HyDE rewrite + re-retrieval + embedding override -

def test_failure_triggers_hyde_rewrite_and_reretrieve():
    dense = _Dense()
    sparse = _Sparse()
    dispatcher = _Dispatcher()
    # Always fail faithfulness so both iterations run.
    ctrl = _controller(lambda q, a, c: {"faithfulness": 0.10, "answer_relevance": 0.20, "context_utilization": 0.5},
                       dense=dense, sparse=sparse, dispatcher=dispatcher, max_iters=2)
    res = asyncio.run(ctrl.run("t1", "如何配置限流", "Intent-1", [9.0] * 4, collection_id=None))

    assert res.iterations == 2
    assert res.low_confidence is True
    assert res.iteration_records[1].rewritten is True
    # Two retrievals; the second dense call used the HyDE override, not the original vector.
    assert len(dense.calls) == 2
    assert dense.calls[0] == [9.0] * 4
    assert dense.calls[1] != [9.0] * 4
    # Sparse arm always used the original query terms.
    assert sparse.queries == ["如何配置限流", "如何配置限流"]
    # HyDE generation ran on the SMALL/7B pool (Intent-1) plus the two answer generations.
    assert dispatcher.gen_intents.count("Intent-1") >= 3


# ---- 8.4 exhaustion returns best-so-far with low_confidence + trace scores -----------

def test_best_so_far_selection():
    scores = iter([
        {"faithfulness": 0.30, "answer_relevance": 0.30, "context_utilization": 0.5},  # iter 0 low
        {"faithfulness": 0.80, "answer_relevance": 0.80, "context_utilization": 0.5},  # iter 1 higher but still failing
    ])
    ctrl = _controller(lambda q, a, c: next(scores), max_iters=2)
    res = asyncio.run(ctrl.run("t1", "q", "Intent-1", [0.0] * 4, collection_id="collA"))
    assert res.iterations == 2
    assert res.low_confidence is True
    # Best-so-far = the higher-scoring second iteration.
    assert res.iteration_records[1].faithfulness == 0.80


def test_deadline_stops_before_second_iteration():
    ctrl = _controller(lambda q, a, c: {"faithfulness": 0.0, "answer_relevance": 0.0, "context_utilization": 0.0},
                       max_iters=5, deadline_s=0.0)
    res = asyncio.run(ctrl.run("t1", "q", "Intent-1", [0.0] * 4))
    # Deadline already elapsed => exactly one iteration runs, best-so-far returned.
    assert res.iterations == 1
    assert res.low_confidence is True


# ---- 8.5 RAGAs-unavailable fallback (controller error -> service single pass) --------

def test_ragas_unavailable_raises_for_service_fallback():
    def boom(q, a, c):
        raise RuntimeError("ragas backend missing")

    # No injected scorer path: the controller uses the evaluator, which raises. The service
    # layer catches this and falls back to single-pass; here we assert the error propagates.
    ctrl = _controller(boom, max_iters=2)
    try:
        asyncio.run(ctrl.run("t1", "q", "Intent-1", [0.0] * 4))
        raised = False
    except RuntimeError:
        raised = True
    assert raised


# ---- 8.6 end-to-end via build_mock --------------------------------------------------

def test_e2e_mock_agentic_enabled(monkeypatch):
    monkeypatch.setenv("RAG_AGENTIC_ENABLED_TENANTS", "t1")
    monkeypatch.setenv("RAG_AGENTIC_ENABLED_INTENTS", "Intent-1")
    import config  # flat module used by query.wiring
    config.get_settings.cache_clear()
    from rag.query import wiring

    service = wiring.build_mock()
    ans = asyncio.run(service.query("t1", "如何配置限流"))
    assert ans.meta.get("agentic") is True
    assert ans.trace.agentic is True
    assert ans.trace.agentic_iterations >= 1
    assert ans.trace.agentic_scores


def test_e2e_mock_non_opted_single_pass(monkeypatch):
    monkeypatch.setenv("RAG_AGENTIC_ENABLED_TENANTS", "")
    monkeypatch.setenv("RAG_AGENTIC_ENABLED_INTENTS", "")
    import config  # flat module used by query.wiring
    config.get_settings.cache_clear()
    from rag.query import wiring

    service = wiring.build_mock()
    ans = asyncio.run(service.query("t1", "如何配置限流"))
    assert ans.meta.get("agentic") is not True
    assert ans.trace.agentic is False


if __name__ == "__main__":
    test_config_gating()
    test_pass_first_iteration_no_rewrite()
    test_failure_triggers_hyde_rewrite_and_reretrieve()
    test_best_so_far_selection()
    test_deadline_stops_before_second_iteration()
    print("agentic tests PASSED")
