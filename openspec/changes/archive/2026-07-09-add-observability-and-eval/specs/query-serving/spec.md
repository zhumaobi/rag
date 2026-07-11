## MODIFIED Requirements

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

### Requirement: Answer provenance

The system SHALL return an `Answer` result type that carries the answer text plus provenance: the recognized intent, whether the result came from cache, the degradation level, and the serving tier used. The `Answer` SHALL additionally carry a `QueryTrace` exposing the correlation `request_id`, per-hop latency, the retrieved document ids, the retrieved context strings, the cache level (when hit), the serving tier, and the degradation flags. Existing provenance fields SHALL be preserved.

#### Scenario: Answer exposes provenance fields

- **WHEN** an `Answer` is returned from a generated (non-cached) result
- **THEN** it exposes the recognized intent, `cached=false`, the dispatcher's degradation level, and the serving tier

#### Scenario: Answer carries a query trace

- **WHEN** any query completes, whether cache hit or miss
- **THEN** the `Answer` exposes a `QueryTrace` carrying the `request_id`, per-hop latency timings, retrieved document ids, retrieved contexts, and tier/degradation provenance
- **AND** on a cache hit the trace records the cache level and empty retrieval fields
