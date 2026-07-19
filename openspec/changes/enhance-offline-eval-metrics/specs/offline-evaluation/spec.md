## MODIFIED Requirements

### Requirement: Evaluation runner over the real pipeline

The system SHALL provide an offline evaluation runner that scores the curated dataset against the real retrieval and generation pipeline by invoking `QueryService.query(..., bypass_cache=True)`. The runner SHALL derive L1 (intent), L2 (retrieved document ids), and L3 (answer text and contexts) evaluation inputs from the returned `QueryTrace` of a single query pass per sample. The runner SHALL additionally derive L3 answer-correctness inputs (key-point coverage, answer similarity) and, in nightly tier, L2 context-precision inputs (per-chunk relevance judgments) from the same query pass.

#### Scenario: Single pass yields all eval inputs

- **WHEN** the runner evaluates a golden sample
- **THEN** it SHALL issue one `query(..., bypass_cache=True)` call and read the intent, retrieved doc ids, contexts, answer text, and retrieved chunk scores from the resulting `QueryTrace`

#### Scenario: Cache is bypassed during evaluation

- **WHEN** the runner evaluates any sample
- **THEN** the query SHALL be executed with the cache bypassed so retrieval and generation are always scored

#### Scenario: Key-point coverage derived from golden sample

- **WHEN** the runner evaluates a golden sample with non-empty `key_points`
- **THEN** it SHALL compute key-point coverage by comparing the generated answer against the sample's `key_points` field

#### Scenario: Context precision derived in nightly tier

- **WHEN** the runner operates in nightly tier and evaluates a golden sample with a non-empty `reference_answer`
- **THEN** it SHALL invoke the context precision evaluator on the retrieved chunks using the sample's `reference_answer` as the reference

## ADDED Requirements

### Requirement: Golden set schema includes key_points

The system SHALL ship golden set fixtures where each row MAY include a `key_points` field (list of atomic factual claims). The loader SHALL default to an empty list when the field is absent.

#### Scenario: Fixtures with key_points load correctly

- **WHEN** the dataset loader reads a golden set JSONL containing `key_points` arrays
- **THEN** each `GoldenSample` SHALL carry the parsed `key_points` list

#### Scenario: Legacy fixtures without key_points remain valid

- **WHEN** the dataset loader reads a golden set JSONL without `key_points` fields
- **THEN** each `GoldenSample` SHALL load with `key_points = []` and all existing evaluations SHALL continue to function

### Requirement: Offline runner supports tier parameter

The system SHALL accept a `tier` parameter (`"ci"` or `"nightly"`, default `"ci"`) controlling which metrics are computed during the offline run.

#### Scenario: CI tier runs fast metrics only

- **WHEN** `run_offline` is invoked with `tier="ci"`
- **THEN** it SHALL compute L1 intent, L2 retrieval (MRR/Recall/NDCG), key-point coverage (embedding mode), and answer_similarity — without any LLM judge calls

#### Scenario: Nightly tier runs all metrics

- **WHEN** `run_offline` is invoked with `tier="nightly"`
- **THEN** it SHALL additionally compute RAGAs full suite, answer_correctness, context precision, NLI key-point mode (if available), and agentic efficiency report
