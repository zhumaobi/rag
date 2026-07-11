# Hybrid Retrieval (`retrieval/`)

[← Home](./Home.md) · [Architecture](./Architecture.md)

Routes a recognized query to the intent-appropriate retrieval strategy, combining dense (Milvus), sparse (Elasticsearch BM25), and graph (Neo4j) sources, fused with Reciprocal Rank Fusion and reranked with a cross-encoder.

## Entry point

`RetrievalRouter.route(tenant_id, query, intent_result)` — `retrieval/router.py:46`. Returns a `RetrievalResult`.

```python
if intent is PRECISE:  return _intent1(...)   # targeted hybrid + RRF + rerank → Top-5
if intent is COMPARE:  return _intent2(...)   # parallel per-product hybrid, grouped
else:                  return _intent3(...)   # graph traversal + vector supplement
```

Collaborators are injected (`retrieval/router.py:32`): `embed_fn`, `DenseRetriever`, `SparseRetriever`, `Reranker`, `Neo4jClient`.

## Shared hybrid primitive

`_hybrid(...)` (`retrieval/router.py:55`) is the reusable dense+sparse building block:

```
dense.retrieve  ─┐  (asyncio.to_thread — offloaded so fan-out is truly parallel)
                 ├─ asyncio.gather → RRF fusion → cross-encoder rerank → final_k
sparse.retrieve ─┘
```

Blocking client calls run via `asyncio.to_thread`, so Intent-2's multi-product fan-out is genuinely concurrent.

## Intent-1 — precise (`_intent1`, router.py:80)

- Picks the first entity with a resolved `collection_id` to narrow the search; else global.
- `recall_k=20`, `final_k=5`.
- `degraded=True` when no collection could be resolved.

## Intent-2 — compare (`_intent2`, router.py:91)

- Requires ≥2 product entities; otherwise degrades to a single hybrid pass (`degraded=True`).
- Runs one hybrid retrieval per product concurrently via `asyncio.gather` (`recall_k=10, final_k=3`).
- Returns `RetrievalResult(chunks=merged, groups={product_name: hits})` — the `groups` map drives comparison generation.

## Intent-3 — relation (`_intent3`, router.py:115)

1. Reads the tenant's active graph version (`neo4j.active_version`).
2. **Two entities:** `neo4j.find_paths(...)` up to `_GRAPH_MAX_HOPS = 3` → returns paths + associated `doc_ids`.
3. **One entity:** `neo4j.neighbor_doc_ids(...)` within 3 hops.
4. If graph doc_ids found: run vector supplementation constrained to those docs **plus** a global hybrid pass, fuse with RRF (`top_k=6`), return with `graph_paths`.
5. **Fallback** (no path/entity): pure-vector hybrid, `degraded=True`, no graph relations cited.

## Fusion — `retrieval/fusion.py`

`reciprocal_rank_fusion(ranked_lists, k=60, top_k=None)`:
- Score for a chunk = Σ `1 / (k + rank)` across every list it appears in.
- Deduplicates by `chunk_id`, returns a single sorted fused list.

## Types — `retrieval/types.py`

- `RetrievedChunk(chunk_id, doc_id, text, score, source)` — `source` ∈ `dense|sparse|graph|rrf|rerank`.
- `RetrievalResult(chunks, groups, graph_paths, degraded, to_dict())` — `groups` for Intent-2, `graph_paths` for Intent-3.

## Files

| File | Purpose |
|------|---------|
| `retrieval/router.py` | `RetrievalRouter` — intent routing + hybrid primitive |
| `retrieval/fusion.py` | `reciprocal_rank_fusion()` |
| `retrieval/types.py` | `RetrievedChunk`, `RetrievalResult` |
| `retrieval/dense.py` | `DenseRetriever` — Milvus per-tenant HNSW search |
| `retrieval/sparse.py` | `SparseRetriever` — Elasticsearch BM25 with tenant filter |
| `retrieval/rerank.py` | `Reranker` — cross-encoder reranking |
