## 1. Package scaffold

- [x] 1.1 Create `src/rag/query/__init__.py`
- [x] 1.2 Verify `RetrievedChunk` exposes a `doc_id` field (retrieval/types.py); note how to derive doc_ids for cache store

## 2. Result type

- [x] 2.1 Create `query/types.py` with an `Answer` dataclass: `text`, `intent`, `cached: bool`, `degraded_level: str`, `tier`
- [x] 2.2 Add an `Intent -> "Intent-N"` mapping helper (PRECISE→"Intent-1", COMPARE→"Intent-2", RELATION→"Intent-3")

## 3. QueryService facade

- [x] 3.1 Create `query/service.py` with `QueryService.__init__(embedder, intent, cache, router, dispatcher, system_prefix)` that constructs nothing
- [x] 3.2 Implement `async def query(tenant_id, text) -> Answer`: embed once, recognize intent, cache lookup (bypass if time_sensitive)
- [x] 3.3 Return early with `Answer(cached=True)` on cache hit; skip retrieval and generation
- [x] 3.4 On miss: await `router.route(...)`, build context from `RetrievalResult.chunks`, call `build_prompt(...)`
- [x] 3.5 Construct `GenRequest` with mapped intent string; await `dispatcher.generate(...)`; build `Answer` with provenance
- [x] 3.6 Schedule `cache.store_async(...)` fire-and-forget via `asyncio.create_task`; return without awaiting it

## 4. Mock collaborators

- [x] 4.1 Create `query/fakes.py` with `FakeEmbedder.embed_texts` returning deterministic hash-seeded normalized 1024-dim vectors
- [x] 4.2 Add fake dense/sparse/reranker/neo4j collaborators returning canned `RetrievedChunk`s for the `RetrievalRouter`
- [x] 4.3 Add a force-miss cache backend (fake L2 or lookup returning `None`) plus a no-op `store_async`
- [x] 4.4 Reuse the `_FakeVLLM` pattern (from serving/loadtest.py) as the injected dispatcher client

## 5. Wiring assembly

- [x] 5.1 Create `query/wiring.py` with `build_mock() -> QueryService` injecting all fakes; keep real `IntentService` (rules path) and real `Dispatcher`
- [x] 5.2 Build `ModelPool`s from `DEFAULT_POOL_CONFIGS` and add healthy fake `Instance`s per tier (mirror loadtest.py)
- [x] 5.3 Add `build_production()` stub raising `NotImplementedError` with a documented wiring shape

## 6. CLI entry point

- [x] 6.1 Create `query/__main__.py` with argparse: positional `text`, `--tenant` (default provided)
- [x] 6.2 Run `asyncio.run(build_mock().query(tenant, text))` and print `Answer.text`; exit 0

## 7. Verify end-to-end

- [x] 7.1 Run `python -m query "怎么对比A产品和B产品的售后政策?" --tenant t1` with `src/rag` on `PYTHONPATH`; confirm it prints an answer and exits 0
- [x] 7.2 Run a PRECISE-intent query and a RELATION-intent query; confirm the routing branch differs and each returns an `Answer`
- [x] 7.3 Confirm no network/DB/GPU connection is attempted during a mock run
