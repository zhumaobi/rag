from __future__ import annotations

from dataclasses import dataclass, field

from raglog import get_logger

log = get_logger("agentic_efficiency")


@dataclass
class AgenticEfficiencyReport:
    """Aggregated efficiency metrics for the agentic RAG loop."""

    first_pass_rate: float = 0.0
    loop_trigger_rate: float = 0.0
    improvement_delta: float = 0.0
    loop_success_rate: float = 0.0
    wasted_loop_rate: float = 0.0
    deadline_exhaustion_rate: float = 0.0
    low_confidence_rate: float = 0.0
    avg_iterations: float = 0.0
    cost_effectiveness: float | None = None
    per_group: dict[str, "AgenticEfficiencyReport"] = field(default_factory=dict)
    recommendations: dict[str, str] = field(default_factory=dict)
    total_queries: int = 0

    def to_dict(self) -> dict:
        d = {
            "first_pass_rate": self.first_pass_rate,
            "loop_trigger_rate": self.loop_trigger_rate,
            "improvement_delta": self.improvement_delta,
            "loop_success_rate": self.loop_success_rate,
            "wasted_loop_rate": self.wasted_loop_rate,
            "deadline_exhaustion_rate": self.deadline_exhaustion_rate,
            "low_confidence_rate": self.low_confidence_rate,
            "avg_iterations": self.avg_iterations,
            "cost_effectiveness": self.cost_effectiveness,
            "total_queries": self.total_queries,
        }
        if self.per_group:
            d["per_group"] = {k: v.to_dict() for k, v in self.per_group.items()}
        if self.recommendations:
            d["recommendations"] = self.recommendations
        return d


@dataclass
class IterationData:
    """Minimal iteration record for efficiency aggregation (mirrors query.agentic.IterationRecord)."""

    iteration: int
    rewritten: bool
    faithfulness: float
    answer_relevance: float
    passed: bool
    latency_ms: float = 0.0


def _rank(faithfulness: float, answer_relevance: float) -> float:
    return faithfulness + answer_relevance


def _compute_metrics(record_lists: list[list[IterationData]], max_iters: int = 2) -> AgenticEfficiencyReport:
    """Compute efficiency metrics from a list of per-query iteration records."""
    n = len(record_lists)
    if n == 0:
        return AgenticEfficiencyReport(total_queries=0)

    first_pass = 0
    loop_triggered = 0
    loop_succeeded = 0
    wasted = 0
    deadline_exhausted = 0
    low_confidence = 0
    total_iters = 0
    deltas: list[float] = []
    loop_latencies: list[float] = []

    for records in record_lists:
        if not records:
            continue
        total_iters += len(records)

        # First pass: passed at iteration 0.
        if records[0].passed:
            first_pass += 1
            continue

        # Loop was triggered (iteration 0 failed).
        loop_triggered += 1

        # Check if any subsequent iteration passed.
        any_passed = any(r.passed for r in records[1:])
        if any_passed:
            loop_succeeded += 1

        # Improvement delta: best rank improvement between consecutive iterations.
        for i in range(len(records) - 1):
            delta = _rank(records[i + 1].faithfulness, records[i + 1].answer_relevance) - _rank(
                records[i].faithfulness, records[i].answer_relevance
            )
            deltas.append(delta)

        # Wasted loop: last iteration rank <= first iteration rank.
        if len(records) >= 2:
            first_rank = _rank(records[0].faithfulness, records[0].answer_relevance)
            last_rank = _rank(records[-1].faithfulness, records[-1].answer_relevance)
            if last_rank <= first_rank:
                wasted += 1

        # Deadline exhaustion: used all iterations without passing.
        if len(records) >= max_iters and not any_passed:
            deadline_exhausted += 1

        # Low confidence: best candidate still below threshold.
        if not any_passed:
            low_confidence += 1

        # Latency for triggered loops (sum of iterations after the first).
        loop_lat = sum(r.latency_ms for r in records[1:])
        if loop_lat > 0:
            loop_latencies.append(loop_lat)

    improvement_delta = sum(deltas) / len(deltas) if deltas else 0.0
    mean_loop_latency_s = (sum(loop_latencies) / len(loop_latencies) / 1000.0) if loop_latencies else 0.0

    cost_eff: float | None = None
    if mean_loop_latency_s > 0 and improvement_delta > 0:
        cost_eff = improvement_delta / mean_loop_latency_s

    return AgenticEfficiencyReport(
        first_pass_rate=first_pass / n,
        loop_trigger_rate=loop_triggered / n,
        improvement_delta=improvement_delta,
        loop_success_rate=loop_succeeded / loop_triggered if loop_triggered else 0.0,
        wasted_loop_rate=wasted / loop_triggered if loop_triggered else 0.0,
        deadline_exhaustion_rate=deadline_exhausted / n,
        low_confidence_rate=low_confidence / n,
        avg_iterations=total_iters / n,
        cost_effectiveness=cost_eff,
        total_queries=n,
    )


def _recommend(report: AgenticEfficiencyReport) -> str:
    """Generate enablement recommendation from efficiency metrics."""
    if report.loop_trigger_rate < 0.2:
        return "skip"
    if report.wasted_loop_rate >= 0.5:
        return "tune"
    if report.loop_trigger_rate > 0.2 and report.improvement_delta > 0.05 and report.wasted_loop_rate < 0.5:
        return "enable"
    return "skip"


def aggregate_agentic_efficiency(
    records_by_query: list[list[IterationData]],
    groups: dict[str, list[list[IterationData]]] | None = None,
    max_iters: int = 2,
) -> AgenticEfficiencyReport:
    """Aggregate agentic loop iteration records into an efficiency report.

    Args:
        records_by_query: List of per-query iteration record lists (global).
        groups: Optional mapping of "{tenant}:{intent}" -> per-query records for that group.
        max_iters: Configured max iterations (for deadline exhaustion detection).

    Returns:
        AgenticEfficiencyReport with global metrics and per-group breakdown.
    """
    global_report = _compute_metrics(records_by_query, max_iters)

    if groups:
        for key, group_records in groups.items():
            group_report = _compute_metrics(group_records, max_iters)
            global_report.per_group[key] = group_report
            global_report.recommendations[key] = _recommend(group_report)
    else:
        # Single implicit group.
        global_report.recommendations["global"] = _recommend(global_report)

    log.info(
        "agentic_efficiency_done",
        total=global_report.total_queries,
        first_pass=round(global_report.first_pass_rate, 3),
        wasted=round(global_report.wasted_loop_rate, 3),
    )
    return global_report
