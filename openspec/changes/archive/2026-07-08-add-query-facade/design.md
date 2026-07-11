## Context

The online query path is fully implemented as independent modules, each with constructor-injectable collaborators, but no code wires them into a runnable whole. There is no `main`, `__main__`, or query facade. The subagent survey confirmed the public entry points:

- `IntentService.recognize(tenant_id, query) -> IntentResult` (rules path short-circuits at confidence ≥ 0.85 with no model load)
- `SemanticCache.lookup(tenant_id, query, embedding, time_sensitive) -> CacheHit | None` and `store_async(...)`
- `RetrievalRouter(embed_fn, ...).route(tenant_id, query, intent) -> RetrievalResult` (async)
- `Dispatcher(pools, client, balancer).generate(req, context, ...) -> GenResult` (async)
- `serving.prefix.build_prompt(system_prefix, context, query)`
- `pipeline.embed.Embedder.embed_texts(texts) -> list[list[float]]`

Constraints: flat root-relative imports (`from config import ...`), so the package is not importable as `rag.*`; the CLI runs as `python -m query` with `src/rag` on `PYTHONPATH`. `serving/loadtest.py` already demonstrates the fake-injection pattern (`_FakeVLLM`) used across this codebase.

## Goals / Non-Goals

**Goals:**
- A single async facade `QueryService.query(tenant_id, text)` that orchestrates all five stages with correct data hand-offs.
- A mock assembly that runs the full path on a laptop with no infra or GPU, while keeping real intent classification, real retrieval routing, and real dispatcher degradation logic exercised.
- A `python -m query` CLI that runs one query and prints the answer.
- The facade is pure orchestration: it constructs nothing, so mock and production assemblies share identical service code.

**Non-Goals:**
- No HTTP/FastAPI server (deferred to a follow-up).
- No real `build_production()` implementation beyond a stub signature.
- No changes to the existing modules' public APIs.
- No performance/SLA validation (that is `serving/loadtest.py`'s job).

## Decisions

**Decision 1: Dependency-injected facade, constructs nothing.**
`QueryService.__init__` takes `embedder`, `intent`, `cache`, `router`, `dispatcher`, and `system_prefix`. Rationale: the same orchestration logic must run against fakes and real clients; injection is already the codebase idiom (`Dispatcher(pools, client=...)`). Alternative — facade builds its own clients keyed by a mode flag — rejected because it couples orchestration to infra and blocks laptop runs.

**Decision 2: Two assembly functions in `wiring.py`.**
`build_mock()` injects fakes at the infra/GPU seams; `build_production()` is a stub raising `NotImplementedError` with a documented shape. Rationale: keeps the wiring decision in one place, separate from orchestration.

**Decision 3: Fake only three seams; keep two stages real.**
Fake the embedder (avoids loading bge-m3), the retrieval leaf clients (dense/sparse/reranker/neo4j → canned `RetrievedChunk`s), the cache L2 backend (force miss), and the LLM (`_FakeVLLM` pattern). Keep the real `IntentService` (rules path, no model) and the real `Dispatcher` + `ModelPool` with healthy fake `Instance`s. Rationale: a mock run then genuinely proves intent routing and dispatcher tier-selection/degradation, not just plumbing. Alternative — fake everything including intent and dispatcher — rejected as a hollow smoke test.

**Decision 4: Reuse `pipeline.embed.Embedder` as the single query embed_fn; fake it in mock mode.**
Both cache and retrieval need one 1024-dim `embed_fn`. `FakeEmbedder.embed_texts` returns deterministic hash-seeded normalized 1024-vectors. Rationale: one embedding concept for the retrieval/cache side (distinct from IntentClassifier's internal MiniLM, which stays encapsulated).

**Decision 5: Intent enum → `"Intent-N"` mapping at the facade boundary.**
`GenRequest.intent` expects `"Intent-1|2|3"`. A small map (`Intent.PRECISE→"Intent-1"`, `COMPARE→"Intent-2"`, `RELATION→"Intent-3"`) lives in the facade. Rationale: localize the impedance mismatch rather than change either module.

**Decision 6: CLI as `src/rag/query/__main__.py`, invoked `python -m query`.**
Consistent with the flat-import decision already made. `argparse` for `text` positional + `--tenant`; `asyncio.run(build_mock().query(...))`; print `Answer.text`.

## Risks / Trade-offs

- **Import shadowing / packaging** → The package runs only with `src/rag` on `PYTHONPATH` as root; `python -m query` (not `python -m rag.query`). Mitigation: document the run command; keep `__main__.py` inside `query/`.
- **`RetrievedChunk` may lack `doc_id` for cache store** → step 8 needs document ids. Mitigation: verify the field during implementation; if absent, derive ids from the canned chunks or pass an empty list in mock mode.
- **Mock fidelity gap** → faked retrieval/embedding means semantic correctness is not tested, only wiring and routing. Mitigation: explicitly scoped as a wiring proof; real-infra validation is a separate change.
- **Dispatcher pool construction** → needs at least one healthy `Instance` per tier or routing fails. Mitigation: mock assembly adds healthy fake instances per `DEFAULT_POOL_CONFIGS`, mirroring `loadtest.py`.

## Migration Plan

Additive only — new `query/` package, no edits to existing modules. No rollback concerns beyond deleting the new package. No data migration.

## Open Questions

- Should `build_production()` be fleshed out in this change or left as a documented stub? (Current plan: documented stub.)
- Does `Answer` need to expose retrieval groups/graph paths for COMPARE/RELATION intents, or is flat text sufficient for the first integration? (Current plan: flat text + provenance; extend later if needed.)
