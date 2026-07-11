from __future__ import annotations

import enum
import threading
import time

from raglog import get_logger

log = get_logger("circuit_breaker")


class BreakerState(str, enum.Enum):
    CLOSED = "closed"      # normal
    OPEN = "open"          # tripped, reject fast
    HALF_OPEN = "half_open"  # probing recovery


class CircuitBreaker:
    """Per-instance circuit breaker (task 7.6, level L1).

    Trips OPEN after `fail_threshold` consecutive failures, removing the instance from
    routing. After `reset_timeout` it goes HALF_OPEN to probe; one success closes it,
    one failure re-opens it.
    """

    def __init__(self, fail_threshold: int = 5, reset_timeout: float = 30.0) -> None:
        self._fail_threshold = fail_threshold
        self._reset_timeout = reset_timeout
        self._failures = 0
        self._state = BreakerState.CLOSED
        self._opened_at = 0.0
        self._lock = threading.Lock()

    def allow(self, now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        with self._lock:
            if self._state is BreakerState.OPEN and ts - self._opened_at >= self._reset_timeout:
                self._state = BreakerState.HALF_OPEN
            return self._state is not BreakerState.OPEN

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._state = BreakerState.CLOSED

    def record_failure(self, now: float | None = None) -> None:
        ts = now if now is not None else time.time()
        with self._lock:
            self._failures += 1
            if self._state is BreakerState.HALF_OPEN or self._failures >= self._fail_threshold:
                self._state = BreakerState.OPEN
                self._opened_at = ts
                log.warning("circuit_opened", failures=self._failures)

    @property
    def state(self) -> BreakerState:
        return self._state
