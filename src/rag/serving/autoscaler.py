from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol

from raglog import get_logger
from serving.model_pool import ModelPool
from serving.types import Instance, InstanceState, PoolTier

log = get_logger("autoscaler")


class InstanceProvider(Protocol):
    """Provisioning backend (K8s/Ray/etc.). Implemented outside this module."""

    def launch(self, tier: PoolTier) -> Instance: ...
    def terminate(self, instance_id: str) -> None: ...


# Reactive thresholds (task 7.8).
_SCALE_UP_UTIL = 0.85
_SCALE_UP_HOLD_S = 60.0
_SCALE_DOWN_UTIL = 0.30
_SCALE_DOWN_HOLD_S = 600.0
# In-flight poll interval while draining (task 7.9).
_DRAIN_POLL_S = 2.0


@dataclass
class _Trend:
    """Tracks how long a condition has held to enforce the hold-duration thresholds."""

    since: float | None = None

    def update(self, active: bool, now: float) -> float:
        if active:
            if self.since is None:
                self.since = now
            return now - self.since
        self.since = None
        return 0.0


@dataclass
class Autoscaler:
    """Predictive + reactive autoscaling with graceful drain (tasks 7.7 - 7.9)."""

    pool: ModelPool
    provider: InstanceProvider
    peak_hours: set[int] = field(default_factory=set)   # local hours of historical peaks
    prewarm_lead_min: int = 30
    _up_trend: _Trend = field(default_factory=_Trend)
    _down_trend: _Trend = field(default_factory=_Trend)
    _prewarmed_hours: set[int] = field(default_factory=set)

    # ---- 7.7 predictive ----------------------------------------------------------

    def predictive_tick(self, current_hour: int, current_minute: int) -> int:
        """Pre-warm before a historical peak. Call from a per-minute cron. `current_hour`
        must be supplied by the caller (no wall-clock reads here). Returns launched count."""
        launched = 0
        # 30 min before a peak hour means the previous hour at minute >= (60 - lead).
        target_hour = (current_hour + 1) % 24
        if target_hour in self.peak_hours and current_minute >= (60 - self.prewarm_lead_min):
            if target_hour not in self._prewarmed_hours and self.pool.size() < self.pool.config.max_instances:
                inst = self.provider.launch(self.pool.tier)
                self.pool.add(inst)
                self._prewarmed_hours.add(target_hour)
                launched += 1
                log.info("prewarm_launched", tier=self.pool.tier.value, for_hour=target_hour, instance=inst.instance_id)
        if current_hour not in self.peak_hours:
            self._prewarmed_hours.discard(current_hour)
        return launched

    # ---- 7.8 reactive ------------------------------------------------------------

    def reactive_tick(self, now: float | None = None) -> str:
        """Evaluate GPU-utilization trends and scale. Returns the action taken."""
        ts = now if now is not None else time.time()
        util = self.pool.avg_gpu_util()

        up_held = self._up_trend.update(util > _SCALE_UP_UTIL, ts)
        down_held = self._down_trend.update(util < _SCALE_DOWN_UTIL, ts)

        if up_held >= _SCALE_UP_HOLD_S and self.pool.size() < self.pool.config.max_instances:
            inst = self.provider.launch(self.pool.tier)
            self.pool.add(inst)
            self._up_trend.since = None
            log.info("scaled_up", tier=self.pool.tier.value, util=round(util, 3), instance=inst.instance_id)
            return "scaled_up"

        if down_held >= _SCALE_DOWN_HOLD_S and self.pool.healthy_count() > self.pool.config.min_instances:
            victim = self._pick_drain_victim()
            if victim is not None:
                self.pool.mark(victim.instance_id, InstanceState.DRAINING)
                self._down_trend.since = None
                log.info("scale_down_initiated", tier=self.pool.tier.value, util=round(util, 3), instance=victim.instance_id)
                return "draining"
        return "noop"

    def _pick_drain_victim(self) -> Instance | None:
        healthy = self.pool.healthy()
        return min(healthy, key=lambda i: i.inflight) if healthy else None

    # ---- 7.9 graceful drain ------------------------------------------------------

    async def drain_and_terminate(self, instance_id: str, sleep=None) -> None:
        """Stop routing to the instance (already DRAINING), wait for in-flight requests to
        finish, then terminate. `sleep` is injectable for testing."""
        import asyncio

        sleep = sleep or asyncio.sleep
        inst = self.pool.get(instance_id)
        if inst is None:
            return
        inst.state = InstanceState.DRAINING
        while inst.inflight > 0:
            await sleep(_DRAIN_POLL_S)
        self.pool.mark(instance_id, InstanceState.STOPPED)
        self.pool.remove(instance_id)
        self.provider.terminate(instance_id)
        log.info("instance_terminated", tier=self.pool.tier.value, instance=instance_id)
