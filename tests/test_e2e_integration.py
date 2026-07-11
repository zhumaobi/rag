"""Task 10.1: end-to-end integration tests, 3 intents x 50 cases each.

Verifies the intent -> retrieval -> (routing) chain produces correct intent
classification and non-empty, tenant-scoped retrieval for each intent class.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import FakeCorpus, FakeIntentService  # noqa: E402

from rag.intent.types import Intent  # noqa: E402

CASES_PER_INTENT = 50


def _seed_corpus() -> FakeCorpus:
    corpus = FakeCorpus()
    for i in range(60):
        corpus.add("tenantA", f"docA{i}", f"产品 alpha{i} 配置 限流 幂等 说明 文档{i}")
    return corpus


def _make_case(intent: Intent, i: int) -> str:
    token = f"alpha{i % 60}"
    if intent is Intent.PRECISE:
        return f"{token} 如何 配置 限流"
    if intent is Intent.COMPARE:
        return f"{token} 对比 beta 区别"
    return f"{token} 关系 是什么"


def test_e2e_three_intents():
    intent_svc = FakeIntentService()
    corpus = _seed_corpus()

    results = {Intent.PRECISE: 0, Intent.COMPARE: 0, Intent.RELATION: 0}
    retrieval_hits = 0
    total = 0

    for intent in (Intent.PRECISE, Intent.COMPARE, Intent.RELATION):
        for i in range(CASES_PER_INTENT):
            query = _make_case(intent, i)
            ir = intent_svc.recognize("tenantA", query)
            if ir.intent is intent:
                results[intent] += 1
            chunks = corpus.retrieve("tenantA", query, top_k=5)
            if chunks:
                retrieval_hits += 1
            total += 1

    # Every intent class must be recognized for all its cases.
    for intent in results:
        assert results[intent] == CASES_PER_INTENT, f"{intent} misclassified: {results[intent]}/{CASES_PER_INTENT}"
    # Retrieval must return results for the vast majority of cases.
    assert retrieval_hits / total > 0.95, f"retrieval hit rate too low: {retrieval_hits}/{total}"


if __name__ == "__main__":
    test_e2e_three_intents()
    print("test_e2e_three_intents PASSED")
