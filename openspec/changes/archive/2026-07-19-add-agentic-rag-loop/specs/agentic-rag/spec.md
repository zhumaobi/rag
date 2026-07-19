## ADDED Requirements

### Requirement: Opt-in agentic self-correction loop

The system SHALL provide an opt-in Agentic RAG loop that, for an enabled `(tenant, intent)` pair, wraps the retrieve → generate cycle: it generates a candidate answer, scores it with an online quality gate, and — if the candidate fails the gate and budget remains — rewrites the query and re-retrieves before generating a new candidate. The loop SHALL be controlled by static environment configuration (`RAG_AGENTIC_ENABLED_TENANTS`, `RAG_AGENTIC_ENABLED_INTENTS`, `RAG_AGENTIC_DEADLINE_S`, `RAG_AGENTIC_MAX_ITERS`). When the `(tenant, intent)` pair is not enabled, the loop SHALL NOT run and the existing single-pass query path SHALL be used unchanged.

#### Scenario: Non-opted request uses the single-pass path

- **WHEN** a query is processed for a `(tenant, intent)` pair that is not present in the enabled configuration
- **THEN** the agentic loop is not entered and the query runs the existing linear retrieve → generate path with no added latency or dependency

#### Scenario: Opted-in request enters the loop

- **WHEN** a query is processed for a `(tenant, intent)` pair present in both `RAG_AGENTIC_ENABLED_TENANTS` and `RAG_AGENTIC_ENABLED_INTENTS`
- **THEN** the query is handled by the agentic controller under the agentic deadline and iteration budget

### Requirement: Online quality gate

The system SHALL score each candidate answer online using the RAGAs Faithfulness (≥ 0.90) and Answer Relevance (≥ 0.85) thresholds. Context Utilization SHALL NOT be evaluated online. A candidate SHALL be considered passing only when both scored metrics meet their thresholds.

#### Scenario: Candidate clears both thresholds

- **WHEN** a candidate answer scores Faithfulness ≥ 0.90 and Answer Relevance ≥ 0.85
- **THEN** the candidate passes the gate and the loop returns it immediately without further iterations

#### Scenario: Candidate fails a threshold

- **WHEN** a candidate answer scores below either the Faithfulness or the Answer Relevance threshold
- **THEN** the candidate fails the gate and, if budget remains, the loop proceeds to a rewrite iteration

#### Scenario: Context Utilization excluded online

- **WHEN** the online quality gate evaluates a candidate
- **THEN** only Faithfulness and Answer Relevance are used to decide pass/fail, and Context Utilization does not gate the result

### Requirement: HyDE query rewrite

On a failed candidate with remaining budget, the system SHALL rewrite the query using HyDE: an LLM SHALL generate a hypothetical answer passage whose embedding overrides the dense retrieval arm's query vector, while the sparse (BM25) arm SHALL continue to use the original query terms. HyDE generation SHALL target the SMALL (7B) serving pool.

#### Scenario: HyDE feeds the dense arm only

- **WHEN** a rewrite iteration runs
- **THEN** the hypothetical-document embedding is used as the dense arm's query vector
- **AND** the sparse/BM25 arm uses the original query terms

#### Scenario: HyDE generation uses the SMALL pool

- **WHEN** the hypothetical passage is generated
- **THEN** the generation request targets the SMALL (7B) pool so the LARGE (14B) pool used for answer generation is not starved

### Requirement: Separate agentic retrieval path

The system SHALL perform agentic re-retrieval through a dedicated path that calls the dense and sparse retrievers directly, fuses results with reciprocal rank fusion, and reranks, accepting an optional precomputed dense-arm embedding override. This path SHALL NOT modify the shared `RetrievalRouter`.

#### Scenario: Embedding override applied

- **WHEN** the agentic retrieval path is called with a precomputed dense-arm embedding
- **THEN** the dense retriever uses the provided embedding instead of re-embedding the original query
- **AND** results are fused via RRF and reranked

#### Scenario: Shared router untouched

- **WHEN** the agentic retrieval path executes
- **THEN** the shared `RetrievalRouter` used by the non-opted linear path is not invoked or modified

### Requirement: Agentic deadline and iteration budget

The system SHALL bound the loop by a wall-clock deadline (`RAG_AGENTIC_DEADLINE_S`) and a maximum iteration count (`RAG_AGENTIC_MAX_ITERS`), independent of the strict per-intent serving SLAs. The loop SHALL check remaining time before starting each iteration and SHALL NOT begin an iteration or expensive sub-step it cannot plausibly complete within the deadline.

#### Scenario: Iteration cap reached

- **WHEN** the loop has run `RAG_AGENTIC_MAX_ITERS` iterations without a passing candidate
- **THEN** the loop stops iterating and returns the best-so-far result

#### Scenario: Deadline reached mid-loop

- **WHEN** insufficient wall-clock time remains before the next iteration or expensive sub-step
- **THEN** the loop stops and returns the best-so-far result rather than starting work it cannot finish

### Requirement: Best-so-far selection with low-confidence flag

The system SHALL retain, across iterations, the highest-scoring candidate answer and its scores. On budget or deadline exhaustion without a passing candidate, the system SHALL return the retained best candidate, set a `low_confidence` flag in `Answer.meta`, and record the per-iteration scores and iteration count in the `QueryTrace`. The loop SHALL NEVER return an answer that scored lower than the best candidate it produced.

#### Scenario: Return best-so-far on exhaustion

- **WHEN** the loop exhausts its deadline or iteration budget and no candidate cleared the thresholds
- **THEN** the highest-scoring candidate is returned
- **AND** `Answer.meta.low_confidence` is `true`
- **AND** the `QueryTrace` records the iteration count and per-iteration scores

#### Scenario: Passing candidate is not flagged

- **WHEN** a candidate passes the gate and is returned
- **THEN** `Answer.meta.low_confidence` is `false` (or absent)

### Requirement: Graceful fallback when RAGAs is unavailable

When the RAGAs backend cannot be loaded or invoked at runtime for an opted-in request, the system SHALL fall back to the single-pass query path, return the generated answer, and log the fallback, rather than failing the request.

#### Scenario: RAGAs import failure falls back

- **WHEN** the RAGAs backend fails to load for an opted-in request
- **THEN** the controller returns the single-pass generated answer and logs the fallback
- **AND** the request does not error
