"""Tasks 10.5 / 10.6: canary + full rollout controller tests.

Verifies healthy metrics advance the rollout through the ramp steps to 100%, and that
a health-gate breach at any step triggers immediate rollback to 0%.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rag.deploy.rollout import RolloutController, RolloutPhase  # noqa: E402

_HEALTHY = {"p99_latency_s": 1.2, "semantic_cache_hit_rate": 0.55, "negative_feedback_rate": 0.02, "error_rate": 0.001}
_BREACH = {"p99_latency_s": 4.0, "semantic_cache_hit_rate": 0.55, "negative_feedback_rate": 0.02, "error_rate": 0.001}


def test_healthy_ramps_to_full():
    rc = RolloutController()
    rc.start_canary()
    assert rc.percent == 10 and rc.phase is RolloutPhase.CANARY
    seen = [rc.percent]
    for _ in range(5):
        rc.observe(_HEALTHY)
        seen.append(rc.percent)
    assert rc.phase is RolloutPhase.FULL
    assert rc.percent == 100
    assert seen[:4] == [10, 25, 50, 100]


def test_breach_triggers_rollback():
    rc = RolloutController()
    rc.start_canary()
    rc.observe(_HEALTHY)  # -> 25%
    action = rc.observe(_BREACH)
    assert action == "rolled_back"
    assert rc.phase is RolloutPhase.ROLLED_BACK
    assert rc.percent == 0


def test_traffic_split_deterministic():
    rc = RolloutController()
    rc.start_canary()  # 10%
    routed = sum(1 for h in range(1000) if rc.route_to_new(h))
    assert routed == 100  # exactly 10% of 1000 buckets


if __name__ == "__main__":
    test_healthy_ramps_to_full()
    test_breach_triggers_rollback()
    test_traffic_split_deterministic()
    print("rollout tests PASSED")
