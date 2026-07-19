## Context

`QueryService.query` (`src/rag/query/service.py`) runs a single linear pass — embed → intent → cache → retrieve → generate → return — with exactly one LLM call and no verification that the answer is grounded or relevant. The offline `RagasEvaluator` (`src/rag/evaluation/ragas_eval.py`) already computes Faithfulness (≥ 0.90) and Answer Relevance (≥ 0.85), but it is never invoked on the hot path.

The serving layer is built around strict per-intent SLAs — queue timeouts of 2s / 5s / 8s for Intent-1/2/3 (`src/rag/serving/degradation.py`) — and a two-tier vLLM pool (SMALL/7B, LARGE/14B) with tenant-affinity load balancing. Any online self-correction loop fights that latency budget: a single failed-then-retried agentic request costs on the order of ~10 LLM calls (2 generations + 2 RAGAs evaluations that internally decompose claims + 1 HyDE generation). This forces the loop to be opt-in and run under its own relaxed deadline.

Retrieval is hybrid: `RetrievalRouter.route(tenant_id, text, ir)` fires dense (Milvus) and sparse (ES/BM25) retrievers in parallel, fuses with RRF (k=60), then reranks (`bge-reranker-v2-m3`). Embedding happens *inside* the leaf retrievers today.

## Goals / Non-Goals

**Goals:**
- Detect low-faithfulness / low-relevance answers online for opted-in `(tenant, intent)` pairs and attempt recovery via HyDE rewrite + re-retrieval.
- Guarantee the loop never returns a worse answer than today's single pass (best-so-far selection).
- Keep non-opted traffic on the exact current path with zero added latency or dependency.
- Reuse existing collaborators (`RagasEvaluator`, dense/sparse retrievers, RRF, reranker, `Dispatcher`) via dependency injection, matching the codebase's DI style.

**Non-Goals:**
- No query decomposition / multi-sub-query in v1 (HyDE only; decompose deferred).
- No feedback-driven or metric-aware branching rewrite in v1 (HyDE is applied uniformly on failure).
- No changes to `RetrievalRouter` internals — a separate agentic retrieval path is used instead.
- No online Context Utilization metric (needs ground truth; stays offline).
- No dynamic/per-request config (static env only); no API gateway / auth changes.
- No relaxation of the strict per-intent SLAs for non-opted traffic.

## Decisions

### D1: Opt-in via static env config, checked in `QueryService.query`
`RAG_AGENTIC_ENABLED_TENANTS` and `RAG_AGENTIC_ENABLED_INTENTS` gate the loop. `query()` checks the `(tenant_id, intent)` pair after intent recognition; if not enabled it runs the existing linear path unchanged, otherwise it delegates to `AgenticController.run(...)`.
- **Why:** simplest, zero cost for non-opted traffic, no new infra. Redeploy to change is acceptable for a controlled rollout.
- **Alternatives:** Redis per-tenant config (runtime toggle) — rejected for v1 as premature; can migrate later without changing the loop.

### D2: Full RAGAs online for the quality gate (Faithfulness + Answer Relevance only)
The loop reuses `RagasEvaluator.score_one(query, answer, contexts)` synchronously per candidate. Only the two reference-free metrics gate the result; Context Utilization (which behaves poorly without ground truth) is ignored online.
- **Why:** reuses existing, spec-aligned thresholds; the named metrics are reference-free so they work at query time.
- **Trade-off:** RAGAs decomposes the answer into claims and verifies each → multiple LLM calls → the dominant latency cost. Mitigated by D3 (separate deadline) and D5 (SMALL pool for the judge).
- **Alternatives:** lightweight single-call LLM judge (faster, less accurate) — rejected per product decision to reuse full RAGAs.

### D3: Separate relaxed deadline + bounded iterations
Agentic requests run under `RAG_AGENTIC_DEADLINE_S` (default ~20s) and `RAG_AGENTIC_MAX_ITERS`, independent of the 2s/5s/8s serving timeouts. The loop checks remaining wall-clock time before starting each iteration and before each expensive sub-step; it never starts an iteration it cannot plausibly finish.
- **Why:** full RAGAs + HyDE + re-retrieval cannot fit the strict SLAs; opted-in requests explicitly trade latency for quality.
- **Trade-off:** longer tail latency for opted-in traffic — acceptable and bounded by the hard deadline.

### D4: HyDE only, feeding the dense arm; BM25 keeps the original query
On a failed candidate, an LLM generates a hypothetical answer passage; its embedding overrides the dense arm's query vector while the sparse arm continues to use the original query terms. Results fuse via the same RRF + rerank.
- **Why:** HyDE widens dense recall when question wording differs from document wording, without corrupting BM25 (which needs real terms). Genuinely new capability, orthogonal to existing intent routing.
- **Alternatives:** decompose (defer to v2), blind rephrase (weaker), HyDE feeding both arms (BM25 on hallucinated text is usually worse) — all rejected for v1.

### D5: Separate agentic retrieval path with an embedding override
A dedicated agentic retriever calls the dense and sparse retrievers directly, accepting an optional precomputed dense-arm embedding, then applies RRF + rerank. `RetrievalRouter` is left untouched.
- **Why:** avoids destabilizing the SLA-critical shared router; isolates agentic behavior. Accepts minor duplication of the hybrid-fusion glue.
- **Alternatives:** extend `RetrievalRouter` with an embedding-override parameter — rejected to keep the hot shared path unchanged.
- **Pool routing:** RAGAs judge and HyDE generation target the SMALL/7B pool; answer generation continues to use the intent's normal tier, so the loop does not starve the LARGE/14B pool.

### D6: Best-so-far selection with low-confidence flag
Every iteration's candidate is scored; the controller retains the highest-scoring `(answer, contexts, score)`. On pass, it returns immediately. On deadline/iteration exhaustion it returns the retained best, setting `Answer.meta.low_confidence = true` when no candidate cleared the thresholds, and recording per-iteration scores in `QueryTrace`.
- **Why:** guarantees the loop is never worse than the baseline; surfaces uncertainty to callers/observability without failing the request.

### D7: `AgenticController` as an injected collaborator
New `query/agentic.py` holds `AgenticController`, constructed with the agentic retriever, `Dispatcher`, `RagasEvaluator`, a HyDE component, the embedder, and the deadline/iteration config. `QueryService` receives it via constructor injection; `build_production()` and `build_mock()` wire it (mock uses fake LLM + injected deterministic RAGAs scorer).
- **Why:** matches the codebase's strict DI pattern; keeps `query()` thin; lets the identical loop run against fakes in mock mode.

## Risks / Trade-offs

- **RAGAs latency dominates and is variable (claim decomposition)** → Cap with the hard deadline (D3); run the judge on the SMALL pool (D5); check remaining time before each RAGAs call and skip re-scoring if it cannot finish.
- **HyDE hallucinates the hypothetical doc → retrieves confidently wrong context** → BM25 arm still anchored on real query terms (D4); best-so-far means a bad HyDE iteration is simply discarded if it scores lower (D6).
- **RAGAs becomes a hard dependency for opted-in requests** → Only opted-in `(tenant, intent)` pairs require it; mock mode injects a deterministic scorer; if RAGAs import fails at runtime, the controller falls back to the single-pass baseline and logs.
- **LLM load amplification (~10 calls per retried request)** → Opt-in scope limits blast radius; judge/HyDE on SMALL pool; bounded max iterations.
- **Best-so-far still returns a low-quality answer when all iterations fail** → Explicit `low_confidence` flag in meta + trace so downstream/UX and L4 monitoring can react.

## Migration Plan

1. Ship all `RAG_AGENTIC_*` settings defaulting to disabled (empty tenant/intent lists) → no behavior change in production.
2. Land `AgenticController`, agentic retriever, and HyDE component; wire into `build_mock()` first and validate the full loop offline with the deterministic RAGAs scorer.
3. Wire into `build_production()`; verify RAGAs + HyDE route to the SMALL pool.
4. Enable for a single canary tenant + one intent (likely Intent-1 precise) via env; monitor tail latency, iteration counts, and `low_confidence` rate.
5. Expand opt-in list as confidence grows.
6. **Rollback:** clear `RAG_AGENTIC_ENABLED_TENANTS`/`_INTENTS` (or redeploy without the vars) → all traffic reverts to the linear path; no data migration involved.

## Open Questions

- Default value for `RAG_AGENTIC_DEADLINE_S` and `RAG_AGENTIC_MAX_ITERS` — start at ~20s / 2 iterations, tune from canary telemetry.
- Should `low_confidence` answers feed the existing L4 negative-feedback / low-quality sample store automatically? (Likely yes; confirm during implementation.)
- Which model backs HyDE generation on the SMALL pool, and what max-token budget for the hypothetical passage?
