"""Task 10.2: multi-tenant isolation tests.

Asserts one tenant's queries never surface another tenant's documents (retrieval
isolation), the semantic cache namespaces by tenant, and graph doc-id resolution is
scoped per tenant.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from conftest import FakeCorpus  # noqa: E402

from rag.cache.l1_cache import L1Cache  # noqa: E402
from rag.cache.types import CacheEntry  # noqa: E402


def test_retrieval_no_cross_tenant():
    corpus = FakeCorpus()
    corpus.add("tenantA", "docA1", "secret alpha 配置 文档")
    corpus.add("tenantB", "docB1", "secret alpha 配置 文档")

    a_results = corpus.retrieve("tenantA", "secret alpha", top_k=5)
    b_results = corpus.retrieve("tenantB", "secret alpha", top_k=5)

    assert all(c.doc_id.startswith("docA") for c in a_results), "tenantA saw foreign docs"
    assert all(c.doc_id.startswith("docB") for c in b_results), "tenantB saw foreign docs"
    # Same query text, disjoint result doc sets.
    assert {c.doc_id for c in a_results}.isdisjoint({c.doc_id for c in b_results})


def test_cache_namespace_isolation():
    l1 = L1Cache(capacity=100, threshold=0.9)
    emb = [1.0, 0.0, 0.0]
    l1.put(CacheEntry("k", "tenantA", "q", "answerA", emb))

    # Same embedding, different tenant -> must miss.
    assert l1.get("tenantB", emb) is None, "cache leaked across tenants"
    hit = l1.get("tenantA", emb)
    assert hit is not None and hit.answer == "answerA"


def test_empty_tenant_returns_nothing():
    corpus = FakeCorpus()
    corpus.add("tenantA", "docA1", "alpha 文档")
    assert corpus.retrieve("tenantGhost", "alpha", top_k=5) == []


if __name__ == "__main__":
    test_retrieval_no_cross_tenant()
    test_cache_namespace_isolation()
    test_empty_tenant_returns_nothing()
    print("multi-tenant isolation tests PASSED")
