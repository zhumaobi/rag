from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from raglog import get_logger

log = get_logger("alerts")


@dataclass
class AlertRule:
    name: str
    predicate: Callable[[dict], bool]  # (metrics_snapshot) -> firing?
    message: str
    hold_seconds: float = 0.0
    _firing_since: float | None = field(default=None, repr=False)


@dataclass
class Alert:
    name: str
    message: str
    value: dict


class AlertManager:
    """Threshold alerting (task 9.3) covering the four spec alerts:
    P99 > 3s (30s hold), semantic cache hit rate < 40% (1h context), negative feedback
    rate > 5%, and KG extraction quality below threshold. Hold durations prevent flapping."""

    def __init__(self) -> None:
        self._rules: list[AlertRule] = []
        self._install_defaults()

    def _install_defaults(self) -> None:
        self.add(AlertRule(
            "p99_latency_high",
            lambda m: m.get("p99_latency_s", 0.0) > 3.0,
            "P99 端到端延迟 > 3s",
            hold_seconds=30.0,
        ))
        self.add(AlertRule(
            "semantic_cache_low",
            lambda m: m.get("semantic_cache_hit_rate", 1.0) < 0.40,
            "语义缓存命中率 < 40%",
            hold_seconds=3600.0,
        ))
        self.add(AlertRule(
            "negative_feedback_high",
            lambda m: m.get("negative_feedback_rate", 0.0) > 0.05,
            "否定反馈率 > 5%",
            hold_seconds=3600.0,
        ))
        self.add(AlertRule(
            "kg_quality_low",
            lambda m: m.get("kg_entity_precision", 1.0) < 0.90 or m.get("kg_entity_recall", 1.0) < 0.85,
            "图谱抽取质量低于阈值",
            hold_seconds=0.0,
        ))

    def add(self, rule: AlertRule) -> None:
        self._rules.append(rule)

    def evaluate(self, snapshot: dict, now: float) -> list[Alert]:
        """Return alerts whose predicate has held true for at least hold_seconds."""
        firing: list[Alert] = []
        for rule in self._rules:
            if rule.predicate(snapshot):
                if rule._firing_since is None:
                    rule._firing_since = now
                if now - rule._firing_since >= rule.hold_seconds:
                    firing.append(Alert(rule.name, rule.message, snapshot))
                    log.warning("alert_firing", rule=rule.name, message=rule.message)
            else:
                rule._firing_since = None
        return firing
