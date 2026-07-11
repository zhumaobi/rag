from __future__ import annotations

import threading
import time

from raglog import get_logger

log = get_logger("cache_metrics")


class HitRateMonitor:
    """Rolling 1-hour cache hit-rate tracker (task 6.6).

    Records (timestamp, hit) events in a ring and computes the hit rate over a sliding
    window. `check_alert` fires when the rate stays below `alert_threshold` for the whole
    window, so the online layer / a cron can surface an alert for investigation.
    """

    def __init__(self, window_seconds: int = 3600, alert_threshold: float = 0.40) -> None:
        self._window = window_seconds
        self._alert_threshold = alert_threshold
        self._events: list[tuple[float, bool]] = []
        self._lock = threading.Lock()

    def record(self, hit: bool, now: float | None = None) -> None:
        ts = now if now is not None else time.time()
        with self._lock:
            self._events.append((ts, hit))
            self._evict(ts)

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        idx = 0
        for idx, (ts, _) in enumerate(self._events):
            if ts >= cutoff:
                break
        if idx:
            del self._events[:idx]

    def hit_rate(self, now: float | None = None) -> float:
        ts = now if now is not None else time.time()
        with self._lock:
            self._evict(ts)
            if not self._events:
                return 0.0
            hits = sum(1 for _, h in self._events if h)
            return hits / len(self._events)

    def check_alert(self, now: float | None = None) -> bool:
        """Returns True (and logs) when the rolling hit rate is below the alert threshold."""
        rate = self.hit_rate(now)
        with self._lock:
            enough_samples = len(self._events) >= 100
        if enough_samples and rate < self._alert_threshold:
            log.warning("cache_hit_rate_low", hit_rate=round(rate, 4), threshold=self._alert_threshold)
            return True
        return False
