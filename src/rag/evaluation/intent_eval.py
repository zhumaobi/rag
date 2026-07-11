from __future__ import annotations

from collections import defaultdict

from evaluation.types import EvalReport, IntentSample
from raglog import get_logger

log = get_logger("intent_eval")

_LABELS = ["Intent-1", "Intent-2", "Intent-3"]
_ACC_THRESHOLD = 0.92
_F1_THRESHOLD = 0.90


def _f1_per_class(y_true: list[str], y_pred: list[str]) -> dict[str, float]:
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    for t, p in zip(y_true, y_pred):
        if t == p:
            tp[t] += 1
        else:
            fp[p] += 1
            fn[t] += 1
    f1: dict[str, float] = {}
    for lbl in _LABELS:
        prec = tp[lbl] / (tp[lbl] + fp[lbl]) if (tp[lbl] + fp[lbl]) else 0.0
        rec = tp[lbl] / (tp[lbl] + fn[lbl]) if (tp[lbl] + fn[lbl]) else 0.0
        f1[lbl] = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return f1


def evaluate_intent(samples: list[IntentSample], predict_fn) -> EvalReport:
    """Task 8.1: run the intent classifier over the labeled Golden Set and gate on
    Accuracy >= 92% and per-class F1 >= 0.90. `predict_fn(query) -> label`."""
    if not samples:
        return EvalReport(name="intent", passed=False, failures=["empty eval set"])

    y_true = [s.label for s in samples]
    y_pred = [predict_fn(s.query) for s in samples]

    correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
    accuracy = correct / len(samples)
    f1 = _f1_per_class(y_true, y_pred)

    report = EvalReport(
        name="intent",
        metrics={"accuracy": accuracy, **{f"f1_{k}": v for k, v in f1.items()}},
        per_intent={k: {"f1": v} for k, v in f1.items()},
    )
    if accuracy < _ACC_THRESHOLD:
        report.failures.append(f"accuracy {accuracy:.4f} < {_ACC_THRESHOLD}")
    for lbl, v in f1.items():
        if v < _F1_THRESHOLD:
            report.failures.append(f"F1[{lbl}] {v:.4f} < {_F1_THRESHOLD}")
    report.passed = not report.failures
    log.info("intent_eval_done", accuracy=round(accuracy, 4), passed=report.passed)
    return report
