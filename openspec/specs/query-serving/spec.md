# query-serving Specification

## Purpose

Provide the online query-serving facade that orchestrates the end-to-end query path (embed, intent recognition, cache lookup, retrieval, generation) behind a single injected `QueryService`, along with a mock wiring mode and CLI entry point for running the full path without infrastructure.

## Requirements

### Requirement: End-to-end query orchestration

The system SHALL provide a `QueryService` facade exposing `async def query(tenant_id: str, text: str, bypass_cache: bool = False) -> Answer` that orchestrates the online path in order: embed the query, recognize intent, look up the cache, retrieve on miss, generate an answer, and return it. The facade SHALL construct none of its collaborators itself; all collaborators SHALL be injected via its constructor. When `bypass_cache` is `true`, the cache lookup SHALL be skipped so retrieval and generation always run.

#### Scenario: Full miss path produces an answer

- **WHEN** `query(tenant_id, text)` is called and the cache returns no hit
- **THEN** the service embeds the query once, recognizes intent, performs retrieval, builds a prompt, invokes the dispatcher, and returns an `Answer` whose `text` is the generated text
- **AND** `Answer.cached` is `false`

#### Scenario: Single embedding reused downstream

- **WHEN** a query is processed
- **THEN** the query embedding is computed exactly once and passed to both cache lookup and retrieval, not recomputed per stage

#### Scenario: Bypass forces retrieval and generation

- **WHEN** `query(tenant_id, text, bypass_cache=True)` is called
- **THEN** the cache lookup is skipped and the query always proceeds through retrieval and generation
- **AND** the returned `Answer` has `cached` set to `false`

### Requirement: Cache-hit fast path

The system SHALL return early with the cached answer when the cache reports a hit, skipping retrieval and generation. When the intent is marked time-sensitive, the cache lookup SHALL be bypassed.

#### Scenario: Cache hit short-circuits

- **WHEN** the cache lookup returns a `CacheHit`
- **THEN** the service returns an `Answer` with `cached` set to `true` and the hit's answer text
- **AND** retrieval and generation are not invoked

#### Scenario: Time-sensitive query bypasses cache

- **WHEN** the recognized intent has `time_sensitive` set to `true`
- **THEN** the cache lookup is skipped and the query proceeds to retrieval and generation

### Requirement: Intent-to-request mapping

The system SHALL map the recognized `Intent` enum to the `"Intent-1" | "Intent-2" | "Intent-3"` string form expected by `GenRequest` when constructing the generation request.

#### Scenario: Intent enum mapped for dispatcher

- **WHEN** a `GenRequest` is constructed from an `IntentResult`
- **THEN** the request's `intent` field holds the corresponding `"Intent-N"` string

### Requirement: Answer provenance

The system SHALL return an `Answer` result type that carries the answer text plus provenance: the recognized intent, whether the result came from cache, the degradation level, and the serving tier used. The `Answer` SHALL additionally carry a `QueryTrace` exposing the correlation `request_id`, per-hop latency, the retrieved document ids, the retrieved context strings, the cache level (when hit), the serving tier, and the degradation flags. Existing provenance fields SHALL be preserved.

#### Scenario: Answer exposes provenance fields

- **WHEN** an `Answer` is returned from a generated (non-cached) result
- **THEN** it exposes the recognized intent, `cached=false`, the dispatcher's degradation level, and the serving tier

#### Scenario: Answer carries a query trace

- **WHEN** any query completes, whether cache hit or miss
- **THEN** the `Answer` exposes a `QueryTrace` carrying the `request_id`, per-hop latency timings, retrieved document ids, retrieved contexts, and tier/degradation provenance
- **AND** on a cache hit the trace records the cache level and empty retrieval fields

### Requirement: Fire-and-forget cache store on miss

The system SHALL asynchronously store the generated answer into the cache on a miss without blocking the response to the caller.

#### Scenario: Store scheduled after generation

- **WHEN** an answer is generated on a cache miss
- **THEN** a cache store operation is scheduled with the query, answer, embedding, and retrieved document ids
- **AND** the service returns without awaiting the store to complete

### Requirement: Mock wiring mode

The system SHALL provide a `build_mock()` assembly that wires the facade with fakes at every infrastructure and GPU seam, so the full query path runs on a laptop with no databases and no GPU. The mock assembly SHALL exercise the real intent classification (rules path), the real retrieval routing branch selection, and the real dispatcher routing and degradation logic, while faking only embedding, vector/graph stores, cache backend, and LLM text generation.

#### Scenario: Mock run completes without infrastructure

- **WHEN** `build_mock()` assembles a `QueryService` and a query is executed
- **THEN** the query completes end-to-end and returns an `Answer` without connecting to Milvus, Elasticsearch, Neo4j, Redis, PostgreSQL, or any GPU/LLM endpoint

### Requirement: CLI entry point

The system SHALL provide a `python -m query "<question>" --tenant <id>` entry point that runs a single query in mock mode and prints the resulting answer. The entry point SHALL run under the flat root-relative import convention with `src/rag` on `PYTHONPATH`.

#### Scenario: CLI prints an answer

- **WHEN** `python -m query "<question>" --tenant <id>` is invoked
- **THEN** the process runs the full query path in mock mode and prints the answer text to standard output
- **AND** exits with status code 0
