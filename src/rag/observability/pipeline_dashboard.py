from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from raglog import get_logger

log = get_logger("pipeline_dashboard")


@dataclass
class StageRun:
    stage: str
    duration_s: float
    success: bool
    failure_reason: str = ""


@dataclass
class _StageAgg:
    runs: int = 0
    successes: int = 0
    total_duration: float = 0.0
    failure_reasons: dict[str, int] = field(default_factory=lambda: defaultdict(int))


class PipelineDashboard:
    """Aggregates offline-index pipeline stage telemetry (task 9.4).

    Feeds a board showing per-stage duration, success rate, and a breakdown of failure
    reason classes so operators can see where and why a run stalled.
    """

    def __init__(self) -> None:
        self._stages: dict[str, _StageAgg] = defaultdict(_StageAgg)

    def record(self, run: StageRun) -> None:
        agg = self._stages[run.stage]
        agg.runs += 1
        agg.total_duration += run.duration_s
        if run.success:
            agg.successes += 1
        else:
            agg.failure_reasons[run.failure_reason or "unknown"] += 1
        log.info("stage_recorded", stage=run.stage, success=run.success, duration_s=round(run.duration_s, 3))

    def snapshot(self) -> dict:
        board: dict[str, dict] = {}
        for stage, agg in self._stages.items():
            board[stage] = {
                "runs": agg.runs,
                "success_rate": agg.successes / agg.runs if agg.runs else 0.0,
                "avg_duration_s": agg.total_duration / agg.runs if agg.runs else 0.0,
                "failure_reasons": dict(agg.failure_reasons),
            }
        return board
