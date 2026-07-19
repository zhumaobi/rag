## ADDED Requirements

### Requirement: AgenticEfficiencyReport aggregation

The system SHALL provide a function `aggregate_agentic_efficiency` that accepts a list of per-query iteration record lists and produces an `AgenticEfficiencyReport` containing: `first_pass_rate`, `loop_trigger_rate`, `improvement_delta`, `loop_success_rate`, `wasted_loop_rate`, `deadline_exhaustion_rate`, `low_confidence_rate`, `avg_iterations`.

#### Scenario: First-pass rate computed

- **WHEN** aggregation runs over N queries where M passed at iteration 0
- **THEN** `first_pass_rate` SHALL equal M/N

#### Scenario: Improvement delta computed for triggered loops

- **WHEN** a query triggered the loop (iteration 0 failed) and has ≥ 2 iterations
- **THEN** `improvement_delta` SHALL include the mean of `(faithfulness_i+1 + answer_relevance_i+1) - (faithfulness_i + answer_relevance_i)` across all such queries

#### Scenario: Wasted loop rate identified

- **WHEN** a query's iteration N+1 has a combined rank score ≤ iteration N's rank score
- **THEN** that query SHALL count toward `wasted_loop_rate` (loop ran but did not improve the answer)

#### Scenario: Empty input handled

- **WHEN** `aggregate_agentic_efficiency` receives an empty list
- **THEN** it SHALL return a report with all rates at 0.0 and `passed = True`

### Requirement: Per-(tenant, intent) breakdown

The system SHALL compute all efficiency metrics separately for each (tenant_id, intent) combination present in the input data, in addition to the global aggregate.

#### Scenario: Per-group reporting

- **WHEN** the input contains queries from multiple (tenant, intent) combinations
- **THEN** the report SHALL include a `per_group` mapping keyed by `"{tenant_id}:{intent}"` with each group's metric values

#### Scenario: Single-group input

- **WHEN** all input queries share the same (tenant, intent)
- **THEN** the `per_group` mapping SHALL contain exactly one entry matching the global metrics

### Requirement: IterationRecord latency extension

The system SHALL extend `IterationRecord` with a `latency_ms: float` field (default 0.0) capturing the wall-clock duration of that iteration (retrieval + generation + scoring).

#### Scenario: Latency recorded per iteration

- **WHEN** the agentic controller completes an iteration
- **THEN** the `IterationRecord` SHALL include the elapsed time in milliseconds for that iteration

#### Scenario: Backward compatibility with legacy traces

- **WHEN** an `IterationRecord` is deserialized from a trace that predates this field
- **THEN** `latency_ms` SHALL default to 0.0 and latency-dependent metrics SHALL be marked as unavailable

### Requirement: Latency-aware cost-effectiveness metric

The system SHALL compute `cost_effectiveness` as `improvement_delta / mean_iteration_latency_s` for queries where the loop was triggered and latency data is available, representing quality improvement per second of added latency.

#### Scenario: Cost-effectiveness with latency data

- **WHEN** latency_ms > 0 for triggered-loop queries
- **THEN** the report SHALL include `cost_effectiveness` as improvement_delta divided by mean total loop latency in seconds

#### Scenario: Cost-effectiveness unavailable without latency

- **WHEN** all triggered-loop queries have latency_ms = 0 (legacy data)
- **THEN** the report SHALL set `cost_effectiveness = None` and log a note that latency data is unavailable

### Requirement: Enablement recommendation output

The system SHALL produce a structured recommendation per (tenant, intent) indicating whether the agentic loop provides measurable value, based on: loop_trigger_rate > 0.2 AND improvement_delta > 0.05 AND wasted_loop_rate < 0.5.

#### Scenario: Recommend enable

- **WHEN** a (tenant, intent) group has loop_trigger_rate=0.4, improvement_delta=0.12, wasted_loop_rate=0.3
- **THEN** the recommendation SHALL be `"enable"` with rationale citing the metric values

#### Scenario: Recommend skip

- **WHEN** a (tenant, intent) group has loop_trigger_rate=0.05
- **THEN** the recommendation SHALL be `"skip"` with rationale that the loop rarely triggers

#### Scenario: Recommend tune

- **WHEN** a (tenant, intent) group has wasted_loop_rate=0.6
- **THEN** the recommendation SHALL be `"tune"` with rationale that the loop triggers but often fails to improve
