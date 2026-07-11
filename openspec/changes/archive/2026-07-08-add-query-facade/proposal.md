## Why

Every stage of the online query path exists as an independent module (`IntentService`, `SemanticCache`, `RetrievalRouter`, `Dispatcher`), but nothing wires them together. There is no `main`, no `__main__`, no query facade, and no way to run a single user query end-to-end to LLM answer. Without a runnable integration point, the system cannot be smoke-tested as a whole, and the correctness of the hand-offs between stages is unverified.

## What Changes

- Add a `QueryService` facade (`query/service.py`) exposing `async def query(tenant_id, text) -> Answer` that orchestrates the five online stages: embed → intent → cache lookup → retrieval → generation, with fire-and-forget cache store on miss.
- Add an `Answer` result type (`query/types.py`) carrying the answer text plus provenance (intent, cache hit, degradation level, serving tier).
- Add wiring assembly (`query/wiring.py`) with `build_mock()` (fakes at the infra/GPU seams) and a `build_production()` stub for later real-client assembly.
- Add mock collaborators (`query/fakes.py`): a deterministic `FakeEmbedder`, force-miss cache backend, canned retrievers, and reuse of the existing `_FakeVLLM` pattern from `serving/loadtest.py`.
- Add a CLI entry point (`query/__main__.py`) so `python -m query "<question>" --tenant <id>` runs the full path in mock mode and prints the answer.
- The facade constructs nothing itself; all collaborators are injected, so the same code runs in mock and production assembly.

## Capabilities

### New Capabilities
- `query-serving`: End-to-end online orchestration of a user query into an LLM-generated answer, including a runnable mock mode and CLI entry point for laptop-only execution without databases or GPUs.

### Modified Capabilities
<!-- None. Existing modules are consumed as-is via their current public APIs. -->

## Impact

- New package `src/rag/query/` (`__init__.py`, `types.py`, `service.py`, `wiring.py`, `fakes.py`, `__main__.py`).
- Consumes existing public APIs unchanged: `intent.service.IntentService`, `cache.service.SemanticCache`, `retrieval.router.RetrievalRouter`, `serving.dispatcher.Dispatcher`, `serving.prefix.build_prompt`, `pipeline.embed.Embedder`.
- Entry point runs as `python -m query` with `src/rag` on `PYTHONPATH`, consistent with the existing flat root-relative import convention (`from config import ...`).
- A small `Intent` enum → `"Intent-1/2/3"` string mapping is needed at the facade boundary for `GenRequest`.
- No changes to infra clients, no new third-party dependencies for mock mode.
