## ADDED Requirements

### Requirement: Dual-mode key-point coverage scoring

The system SHALL provide a `KeyPointScorer` interface with two implementations: `EmbeddingKeyPointScorer` (fast, deterministic, no LLM) and `NLIKeyPointScorer` (precise, LLM/NLI-based). Both SHALL accept `(answer: str, key_points: list[str])` and produce a `KeyPointResult` containing `coverage: float`, `per_point: list[PointScore]`, and `mode: str`.

#### Scenario: Embedding scorer computes coverage

- **WHEN** `EmbeddingKeyPointScorer` is given an answer and a list of key points
- **THEN** it SHALL compute max cosine similarity between each key point embedding and all answer sentence embeddings, mark a key point as covered when similarity ≥ configured threshold (default 0.65), and return `coverage = covered_count / total_key_points`

#### Scenario: NLI scorer detects hallucination

- **WHEN** `NLIKeyPointScorer` is given an answer and a list of key points
- **THEN** it SHALL use entailment checking to determine coverage AND identify answer claims that contradict key points, returning `hallucination_rate` in addition to `coverage`

#### Scenario: Graceful fallback when NLI unavailable

- **WHEN** `NLIKeyPointScorer` is requested but no NLI model or LLM endpoint is available
- **THEN** the system SHALL fall back to `EmbeddingKeyPointScorer` with a logged warning and set `mode = "embedding_fallback"`

### Requirement: Key-point coverage CI gate

The system SHALL include key-point coverage (embedding mode) as a gated metric in the CI evaluation tier, with a configurable threshold (default ≥ 0.80).

#### Scenario: Coverage below threshold fails CI gate

- **WHEN** the mean key-point coverage across the golden set is below the configured threshold
- **THEN** the evaluation report SHALL include a failure entry and set `passed = False`

#### Scenario: Golden samples without key_points are skipped

- **WHEN** a `GoldenSample` has an empty `key_points` list
- **THEN** the key-point scorer SHALL skip that sample without error and exclude it from the coverage average

### Requirement: Answer similarity metric

The system SHALL compute `answer_similarity` as the cosine similarity between the embedding of the generated answer and the embedding of `reference_answer`, using the existing sentence embedding model.

#### Scenario: Answer similarity computed per golden sample

- **WHEN** the offline evaluation processes a golden sample with a non-empty `reference_answer`
- **THEN** it SHALL compute and record `answer_similarity` for that sample

#### Scenario: Aggregate answer similarity in report

- **WHEN** the evaluation run completes over the golden set
- **THEN** the generation report SHALL include mean `answer_similarity` as a metric

### Requirement: Reference answer wired into RAGAs ground_truth

The system SHALL pass `GoldenSample.reference_answer` as the `ground_truth` field when invoking RAGAs scoring, replacing the current hardcoded empty string.

#### Scenario: RAGAs receives actual reference

- **WHEN** the RAGAs evaluator scores a golden sample
- **THEN** the `ground_truth` field in the RAGAs dataset SHALL contain the sample's `reference_answer` value

#### Scenario: Empty reference handled gracefully

- **WHEN** a golden sample has an empty `reference_answer`
- **THEN** the system SHALL pass an empty string to RAGAs (preserving current behavior) and skip `answer_correctness` for that sample

### Requirement: GoldenSample schema extension

The system SHALL extend `GoldenSample` with an optional `key_points: list[str]` field (default empty list). The dataset loader SHALL parse `key_points` from JSONL when present and default to `[]` when absent.

#### Scenario: Backward-compatible loading

- **WHEN** the dataset loader reads a golden set JSONL file without `key_points` fields
- **THEN** each sample SHALL load successfully with `key_points = []`

#### Scenario: Key points parsed when present

- **WHEN** the dataset loader reads a JSONL row containing `"key_points": ["point A", "point B"]`
- **THEN** the resulting `GoldenSample` SHALL have `key_points == ["point A", "point B"]`
