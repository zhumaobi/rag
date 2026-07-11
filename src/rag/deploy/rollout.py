from __future__ import annotations

import enum
from dataclasses import dataclass, field

from raglog import get_logger

log = get_logger("rollout")


class RolloutPhase(str, enum.Enum):
    IDLE = "idle"
    CANARY = "canary"        # 10.5: small % traffic under observation
    RAMPING = "ramping"      # 10.6: stepping up
    FULL = "full"            # 100%
    ROLLED_BACK = "rolled_back"


# Health gate: any breach rolls the release back to the previous version.
@dataclass
class HealthGate:
    max_p99_s: float = 3.0
    min_cache_hit_rate: float = 0.40
    max_negative_rate: float = 0.05
    max_error_rate: float = 0.01

    def breaches(self, m: dict) -> list[str]:
        out = []
        if m.get("p99_latency_s", 0.0) > self.max_p99_s:
            out.append("p99>3s")
        if m.get("semantic_cache_hit_rate", 1.0) < self.min_cache_hit_rate:
            out.append("cache<40%")
        if m.get("negative_feedback_rate", 0.0) > self.max_negative_rate:
            out.append("negative>5%")
        if m.get("error_rate", 0.0) > self.max_error_rate:
            out.append("error>1%")
        return out


@dataclass
class RolloutController:
    """Canary -> ramp -> full rollout with automatic rollback (tasks 10.5 / 10.6).

    Traffic is split by routing `percent` of requests to the new version. `observe`
    checks the health gate each evaluation window; a breach triggers immediate rollback
    to 0% (previous version), preserving the fast-rollback capability the spec requires.
    """

    gate: HealthGate = field(default_factory=HealthGate)
    ramp_steps: tuple[int, ...] = (10, 25, 50, 100)
    phase: RolloutPhase = RolloutPhase.IDLE
    percent: int = 0
    _step_idx: int = 0

    def start_canary(self) -> None:
        self.phase = RolloutPhase.CANARY
        self._step_idx = 0
        self.percent = self.ramp_steps[0]
        log.info("rollout_canary_started", percent=self.percent)

    def route_to_new(self, request_hash: int) -> bool:
        """Deterministic traffic split: hash bucket < percent goes to the new version."""
        return (request_hash % 100) < self.percent

    def observe(self, metrics: dict) -> str:
        """Evaluate the health gate and advance/hold/rollback. Returns the action taken."""
        breaches = self.gate.breaches(metrics)
        if breaches:
            self.rollback(reason=",".join(breaches))
            return "rolled_back"

        if self.phase in (RolloutPhase.CANARY, RolloutPhase.RAMPING):
            if self._step_idx + 1 < len(self.ramp_steps):
                self._step_idx += 1
                self.percent = self.ramp_steps[self._step_idx]
                self.phase = RolloutPhase.RAMPING if self.percent < 100 else RolloutPhase.FULL
                log.info("rollout_advanced", percent=self.percent, phase=self.phase.value)
                return "advanced"
            self.phase = RolloutPhase.FULL
            self.percent = 100
            return "full"
        return "hold"

    def rollback(self, reason: str) -> None:
        self.phase = RolloutPhase.ROLLED_BACK
        self.percent = 0
        log.warning("rollout_rolled_back", reason=reason)
