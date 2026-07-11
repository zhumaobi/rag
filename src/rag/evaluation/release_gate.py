from __future__ import annotations

import json
from pathlib import Path

from evaluation.types import EvalReport, GateResult
from raglog import get_logger

log = get_logger("release_gate")

_REGRESSION_TOLERANCE = 0.02  # any metric dropping > 2% vs baseline blocks release.
_E2E_ACCURACY_MIN = 0.85


def _flatten(report: EvalReport) -> dict[str, float]:
    flat = dict(report.metrics)
    for intent, metrics in report.per_intent.items():
        for m, v in metrics.items():
            flat[f"{intent}.{m}"] = v
    return flat


def load_baseline(path: str) -> dict[str, float]:
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_baseline(path: str, reports: list[EvalReport]) -> None:
    merged: dict[str, float] = {}
    for r in reports:
        for k, v in _flatten(r).items():
            merged[f"{r.name}.{k}"] = v
    Path(path).write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")


def evaluate_gate(
    reports: list[EvalReport], baseline: dict[str, float], e2e_accuracy: float | None = None
) -> GateResult:
    """Task 8.8: block release if any threshold fails, end-to-end accuracy < 85%, or any
    metric regresses > 2% vs the stored baseline."""
    regressions: list[str] = []
    passed = True

    for r in reports:
        if not r.passed:
            passed = False
        for k, v in _flatten(r).items():
            key = f"{r.name}.{k}"
            base = baseline.get(key)
            if base is not None and v < base - _REGRESSION_TOLERANCE:
                regressions.append(f"{key}: {v:.4f} < baseline {base:.4f} - {_REGRESSION_TOLERANCE}")

    if e2e_accuracy is not None and e2e_accuracy < _E2E_ACCURACY_MIN:
        passed = False
        regressions.append(f"e2e_accuracy {e2e_accuracy:.4f} < {_E2E_ACCURACY_MIN}")

    if regressions:
        passed = False

    result = GateResult(passed=passed, reports=reports, regressions=regressions)
    log.info("release_gate", passed=passed, regressions=len(regressions))
    return result
