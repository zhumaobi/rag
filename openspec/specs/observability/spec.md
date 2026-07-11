# observability Specification

## Purpose

Provide correlation, tracing, and metrics for the online query path so every query is attributable end-to-end, each hop is traceable, and hot-path metrics are exposed for scraping. Instrumentation SHALL degrade gracefully when optional dependencies (`structlog`, OpenTelemetry, `prometheus_client`) are absent.

## Requirements

### Requirement: Request correlation identifier

The system SHALL mint a unique `request_id` at the entry of `QueryService.query()` and bind it to a context-local scope so that every log line, span, and metric emitted during that query is attributable to it. The `request_id` SHALL be exposed on the query's `QueryTrace`.

#### Scenario: Request id minted and propagated

- **WHEN** a query begins
- **THEN** a unique `request_id` is generated and bound to the context for the duration of the query
- **AND** the same `request_id` appears in the returned `QueryTrace`

#### Scenario: Logs carry the request id

- **WHEN** any downstream component logs during a query
- **THEN** the emitted structured log line carries the current `request_id` field automatically

### Requirement: Structured log correlation

The system SHALL configure the logging layer so that context-local fields (including `request_id`) are merged into every structured log record. When `structlog` is available it SHALL use a context-var merge processor; when absent the fallback logger SHALL still function without error.

#### Scenario: Correlation without structlog installed

- **WHEN** `structlog` is not installed
- **THEN** logging continues to operate through the fallback logger without raising

### Requirement: Hop-level tracing

The system SHALL wrap each stage of the query path — embed, intent, cache lookup, retrieval (including dense, sparse, rerank, and graph sub-stages), generation, and cache store — in a tracing span. Spans SHALL be exported via OpenTelemetry when it is installed and configured, and SHALL degrade to structured log spans otherwise.

#### Scenario: Each hop produces a span

- **WHEN** a query runs to completion on a cache miss
- **THEN** a span is recorded for each of embed, intent, cache lookup, retrieval, generation, and cache store
- **AND** each span carries the current `request_id`

#### Scenario: Tracing degrades without OpenTelemetry

- **WHEN** OpenTelemetry is not installed
- **THEN** span boundaries are emitted as structured log events instead, without raising

### Requirement: Hot-path metric emission

The system SHALL emit request metrics on the online query path: a request counter labeled by intent and outcome, a request latency histogram labeled by intent, and a degradation counter labeled by level. Metric emission SHALL use the existing metrics module and SHALL degrade to no-ops when `prometheus_client` is absent.

#### Scenario: Successful request observed

- **WHEN** a query completes successfully
- **THEN** the request counter is incremented with the recognized intent and an `ok` outcome
- **AND** the request latency is observed in the latency histogram for that intent

#### Scenario: Degradation observed

- **WHEN** the dispatcher reports a degradation level for a query
- **THEN** the degradation counter is incremented for that level

### Requirement: Metrics exposition endpoint

The system SHALL expose Prometheus metrics over HTTP via a standalone exposition server started from wiring, without requiring a web framework. When `prometheus_client` is absent the wiring SHALL start no server and SHALL not raise.

#### Scenario: Metrics served on a port

- **WHEN** the observability wiring is initialized with `prometheus_client` installed
- **THEN** a standalone HTTP server exposes the metrics registry on the configured port

#### Scenario: No server without prometheus_client

- **WHEN** `prometheus_client` is not installed
- **THEN** wiring initialization completes without starting a server and without raising
