## Why

The online query path (`QueryService.query`) is a single linear pass: retrieve → generate → return, with no check that the generated answer is grounded in the retrieved context or actually addresses the question. Low-faithfulness (hallucinated) or low-relevance answers are returned to the user unchanged; the existing RAGAs faithfulness/relevance evaluation runs offline only and is never consulted on the hot path. We want an opt-in Agentic RAG self-correction loop that detects low-quality answers online and attempts to recover by rewriting the query (HyDE) and re-retrieving, returning the best answer it produced.

## What Changes

- Add an opt-in **Agentic RAG loop** that wraps the retrieve → generate cycle for enabled `(tenant, intent)` combinations. Non-opted requests keep today's exact linear path at zero added cost.
- Add an **online quality gate** using the existing `RagasEvaluator` to score each candidate answer on Faithfulness (≥ 0.90) and Answer Relevance (≥ 0.85). Context Utilization is excluded online (requires ground truth unavailable at query time).
- Add a **HyDE query rewrite** step: when a candidate fails the gate and budget remains, an LLM (SMALL/7B pool) generates a hypothetical answer document; its embedding feeds the dense retrieval arm while the sparse/BM25 arm keeps the original query terms.
- Add a **separate agentic retrieval path** that calls the dense and sparse retrievers directly (RRF + rerank) and accepts a precomputed dense-arm embedding override, leaving `RetrievalRouter` untouched.
- Enforce a **separate relaxed deadline** (`RAG_AGENTIC_DEADLINE_S`, default ~20s) and a bounded max-iteration count for agentic requests, decoupled from the strict 2s/5s/8s per-intent serving SLAs.
- On budget/deadline exhaustion, return the **best-scoring answer seen so far**, flagged `low_confidence` in `Answer.meta` and recorded in `QueryTrace` with per-iteration sub-scores. The loop can never return a worse result than the single-pass baseline.
- Add **static env configuration** (`RAG_AGENTIC_ENABLED_TENANTS`, `RAG_AGENTIC_ENABLED_INTENTS`, `RAG_AGENTIC_DEADLINE_S`, `RAG_AGENTIC_MAX_ITERS`) to control opt-in.

## Capabilities

### New Capabilities

- `agentic-rag`: The opt-in self-correction loop — online quality gating, HyDE query rewrite, iterative re-retrieval, deadline/iteration budgeting, and best-so-far selection with a low-confidence flag.

### Modified Capabilities

- `query-serving`: `QueryService.query` gains a conditional branch that delegates to the agentic controller when the `(tenant, intent)` pair is opted in; the returned `Answer`/`QueryTrace` carry agentic provenance (iteration count, per-iteration scores, low-confidence flag).
- `evaluation-framework`: The L3 RAGAs Faithfulness/Answer-Relevance evaluation is promoted from offline-only to an online, synchronous quality gate inside the agentic loop (Context Utilization remains offline-only).

## Impact

- **New code**: `query/agentic.py` (agentic controller), a separate agentic retrieval helper, a HyDE rewrite component.
- **Modified code**: `query/service.py` (opt-in delegation), `query/types.py` (`QueryTrace`/`Answer` agentic fields), `query/wiring.py` (inject controller + RAGAs evaluator into production/mock assemblies), `config.py` (new `RAG_AGENTIC_*` settings), `retrieval` (embedding-override path used by the agentic retriever).
- **Dependencies**: RAGAs becomes a hard runtime dependency for opted-in requests (previously lazy/optional). The judge and HyDE generation target the SMALL/7B vLLM pool to avoid starving the LARGE pool used for answer generation.
- **Latency**: Opted-in requests trade latency for quality and run under a separate relaxed deadline; strict per-intent SLAs are unaffected for non-opted traffic.
- **Specs**: modifies `query-serving` and `evaluation-framework`; adds `agentic-rag`.
