## ADDED Requirements

### Requirement: Chunk-level context precision scoring

The system SHALL provide a `ContextPrecisionEvaluator` that uses an LLM judge to assess each retrieved chunk's relevance given the query and reference answer. For each golden sample, it SHALL compute Context Precision@K as the weighted fraction of relevant chunks in the top-K retrieved results, with higher-ranked chunks weighted more.

#### Scenario: Per-chunk relevance judgment

- **WHEN** the evaluator processes a golden sample with K retrieved chunks
- **THEN** it SHALL invoke the LLM judge for each chunk with the prompt containing (query, reference_answer, chunk_text) and record a binary relevance judgment (relevant=1.0 / irrelevant=0.0)

#### Scenario: Context Precision@K computation

- **WHEN** all chunks for a sample have been judged
- **THEN** the system SHALL compute `CP@K = (1/K) × Σ(relevance_i × (1/i))` for i in 1..K, where relevance_i is the judged relevance of the chunk at rank i

#### Scenario: Empty contexts handled

- **WHEN** a golden sample produces zero retrieved chunks
- **THEN** the evaluator SHALL record CP@K = 0.0 for that sample without error

### Requirement: Per-intent context precision breakdown

The system SHALL compute and report Context Precision separately for each intent (Intent-1, Intent-2, Intent-3), not merged into a single aggregate.

#### Scenario: Per-intent reporting

- **WHEN** the context precision evaluation completes over a golden set covering multiple intents
- **THEN** the report SHALL contain a `per_intent` mapping with each intent's mean CP@K value

#### Scenario: Intent-specific threshold gating

- **WHEN** an intent's mean CP@K falls below its configured threshold
- **THEN** the report SHALL add a failure entry identifying the intent and metric value

### Requirement: Reranker training label export

The system SHALL export each chunk relevance judgment as a `RerankTrainingSample` record containing: `query`, `chunk_text`, `relevance` (LLM judgment), `reranker_score` (original cross-encoder score), `is_hard_negative` (True when reranker_score ≥ 0.7 AND relevance = 0.0), `intent`, `doc_id`, and `ts`.

#### Scenario: Labels written to dated JSONL

- **WHEN** a context precision evaluation run completes
- **THEN** the system SHALL write all `RerankTrainingSample` records to `data/eval/rerank_labels/<YYYY-MM-DD>.jsonl`

#### Scenario: Hard negatives flagged

- **WHEN** a chunk has reranker_score ≥ 0.7 but LLM relevance judgment = 0.0
- **THEN** the exported record SHALL have `is_hard_negative = True`

#### Scenario: Export directory created on demand

- **WHEN** the `data/eval/rerank_labels/` directory does not exist
- **THEN** the system SHALL create it before writing labels

### Requirement: LLM judge injection for testability

The system SHALL accept an injectable judge function `(query: str, reference: str, chunk: str) -> float` so that tests and offline mock runs can provide deterministic judgments without a live LLM endpoint.

#### Scenario: Mock judge in offline mode

- **WHEN** the offline runner executes context precision evaluation with a mock judge
- **THEN** the evaluator SHALL use the injected function instead of calling the LLM endpoint

#### Scenario: Default judge uses vLLM

- **WHEN** no judge function is injected and the system is in production mode
- **THEN** the evaluator SHALL call the vLLM serving layer to obtain relevance judgments
