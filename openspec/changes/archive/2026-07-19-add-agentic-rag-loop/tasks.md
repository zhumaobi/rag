# Tasks: add-agentic-rag-loop

## 1. Configuration

- [x] 1.1 Add `RAG_AGENTIC_ENABLED_TENANTS`, `RAG_AGENTIC_ENABLED_INTENTS`, `RAG_AGENTIC_DEADLINE_S`, `RAG_AGENTIC_MAX_ITERS` to `src/rag/config.py` (defaults: empty lists, ~20s, 2 iters)
- [x] 1.2 Add a helper to resolve whether a `(tenant_id, intent)` pair is agentic-enabled

## 2. Agentic retrieval path

- [x] 2.1 Add a dedicated agentic retrieval helper that calls dense + sparse retrievers directly, fuses via RRF, and reranks (reusing `retrieval/fusion.py` and `retrieval/rerank.py`)
- [x] 2.2 Support an optional precomputed dense-arm embedding override so HyDE can inject a hypothetical-doc vector; sparse arm keeps original query terms
- [x] 2.3 Ensure `RetrievalRouter` is left unmodified

## 3. HyDE rewrite component

- [x] 3.1 Implement a HyDE component that generates a hypothetical answer passage via the SMALL (7B) pool
- [x] 3.2 Embed the hypothetical passage with the existing embedder to produce the dense-arm override vector
- [x] 3.3 Bound the hypothetical passage max tokens

## 4. Online quality gate

- [x] 4.1 Wire `RagasEvaluator.score_one` into the loop for synchronous Faithfulness + Answer Relevance scoring
- [x] 4.2 Gate pass/fail on Faithfulness ≥ 0.90 AND Answer Relevance ≥ 0.85; exclude Context Utilization online
- [x] 4.3 Route RAGAs judge calls to the SMALL pool; add graceful fallback to single-pass when RAGAs is unavailable

## 5. Agentic controller

- [x] 5.1 Create `src/rag/query/agentic.py` with `AgenticController` (injected: agentic retriever, dispatcher, RagasEvaluator, HyDE component, embedder, config)
- [x] 5.2 Implement the loop: retrieve → generate → score → (fail & budget) rewrite → re-retrieve
- [x] 5.3 Enforce wall-clock deadline + max-iteration budget; skip work that cannot finish in time
- [x] 5.4 Track best-so-far candidate; return best on exhaustion with `low_confidence` flag
- [x] 5.5 Record per-iteration scores and iteration count into `QueryTrace`

## 6. Integrate into QueryService

- [x] 6.1 Extend `QueryTrace` / `Answer` in `src/rag/query/types.py` with agentic fields (iteration count, per-iteration scores, `low_confidence`)
- [x] 6.2 In `src/rag/query/service.py`, delegate to `AgenticController` on cache miss when the `(tenant, intent)` pair is enabled; keep the linear path otherwise
- [x] 6.3 Preserve fire-and-forget cache store and existing provenance on the agentic path

## 7. Wiring

- [x] 7.1 Wire `AgenticController` into `build_production()` with real RagasEvaluator, SMALL-pool HyDE/judge, and agentic retriever
- [x] 7.2 Wire `AgenticController` into `build_mock()` with fake LLM and an injected deterministic RAGAs scorer

## 8. Tests

- [x] 8.1 Test non-opted `(tenant, intent)` runs the unchanged single-pass path
- [x] 8.2 Test opted-in passing candidate returns immediately (no rewrite)
- [x] 8.3 Test failing candidate triggers HyDE rewrite + re-retrieval and dense-arm embedding override
- [x] 8.4 Test deadline/iteration exhaustion returns best-so-far with `low_confidence=true` and trace scores
- [x] 8.5 Test RAGAs-unavailable fallback returns single-pass answer without erroring
- [x] 8.6 Test end-to-end agentic loop via `build_mock()` with deterministic scorer

## 9. Observability & validation

- [x] 9.1 Emit metrics for agentic iterations, low-confidence rate, and per-stage latency
- [x] 9.2 Confirm `low_confidence` answers feed the low-quality sample store (per open question)
- [x] 9.3 Run `openspec validate add-agentic-rag-loop --strict` and resolve any issues
