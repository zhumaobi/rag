# offline-evaluation Specification

## Purpose

Provide an offline evaluation harness that scores a curated golden dataset against the real retrieval and generation pipeline, deriving per-level (L1/L2/L3) evaluation inputs from a single query pass and producing gated pass/fail reports against configured thresholds.

## Requirements

### Requirement: Curated golden dataset

The system SHALL ship a curated offline test set as JSONL fixtures under `data/eval/`: `intent_eval.jsonl` (`{query, label}`), `retrieval_eval.jsonl` (`{query, intent, ground_truth_doc_ids}`), and `golden_set.jsonl` (`{query, intent, reference_answer, ground_truth_doc_ids}`). The fixtures SHALL cover all three intents and include edge cases, with a small hand-curated seed on the order of tens of rows per file. The fixture schemas SHALL match the loaders in `evaluation/datasets.py`.

#### Scenario: Fixtures load without error

- **WHEN** the dataset loaders read the shipped `data/eval/*.jsonl` files
- **THEN** each loader returns a non-empty list of correctly typed samples

#### Scenario: All intents represented

- **WHEN** the retrieval and golden fixtures are inspected
- **THEN** each of Intent-1, Intent-2, and Intent-3 is represented by at least one sample

### Requirement: Evaluation runner over the real pipeline

The system SHALL provide an offline evaluation runner that scores the curated dataset against the real retrieval and generation pipeline by invoking `QueryService.query(..., bypass_cache=True)`. The runner SHALL derive L1 (intent), L2 (retrieved document ids), and L3 (answer text and contexts) evaluation inputs from the returned `QueryTrace` of a single query pass per sample.

#### Scenario: Single pass yields all eval inputs

- **WHEN** the runner evaluates a golden sample
- **THEN** it issues one `query(..., bypass_cache=True)` call and reads the intent, retrieved doc ids, contexts, and answer text from the resulting `QueryTrace`

#### Scenario: Cache is bypassed during evaluation

- **WHEN** the runner evaluates any sample
- **THEN** the query is executed with the cache bypassed so retrieval and generation are always scored

### Requirement: Gated evaluation reports

The system SHALL feed the derived inputs into the existing evaluation gates (L1 intent accuracy/F1, L2 MRR/Recall@K/NDCG@K, L3 RAGAs faithfulness/answer-relevance/context-utilization) and produce per-level reports plus an overall pass/fail outcome using the existing thresholds.

#### Scenario: Reports produced with pass/fail

- **WHEN** the runner completes over the curated dataset
- **THEN** it produces L1, L2, and L3 reports each carrying their metrics and a `passed` flag consistent with the configured thresholds
