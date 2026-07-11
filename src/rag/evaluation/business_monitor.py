from __future__ import annotations

import threading
import time

from raglog import get_logger

log = get_logger("business_metrics")

_NEGATIVE_RATE_ALERT = 0.05  # 5% rolling negative feedback triggers manual intervention.
_WINDOW_S = 3600


class BusinessMonitor:
    """L4 end-to-end business metrics (spec: resolution rate, negative feedback rate,
    follow-up rate, citation click-through).

    Tracks rolling 1-hour rates. When negative feedback exceeds 5% for the window, it
    signals an alert and the caller should sample low-scoring answers for root-cause.
    """

    def __init__(self, window_seconds: int = _WINDOW_S) -> None:
        self._window = window_seconds
        # each event: (ts, kind) where kind in {resolved, negative, follow_up, citation_click, total}
        self._events: list[tuple[float, str]] = []
        self._lock = threading.Lock()

    def record(self, kind: str, now: float | None = None) -> None:
        ts = now if now is not None else time.time()
        with self._lock:
            self._events.append((ts, kind))
            self._evict(ts)

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        idx = 0
        for idx, (ts, _) in enumerate(self._events):
            if ts >= cutoff:
                break
        if idx:
            del self._events[:idx]

    def _rate(self, kind: str, now: float) -> float:
        self._evict(now)
        total = sum(1 for _, k in self._events if k == "total")
        if not total:
            return 0.0
        count = sum(1 for _, k in self._events if k == kind)
        return count / total

    def rates(self, now: float | None = None) -> dict[str, float]:
        ts = now if now is not None else time.time()
        with self._lock:
            return {
                "resolution_rate": self._rate("resolved", ts),
                "negative_rate": self._rate("negative", ts),
                "follow_up_rate": self._rate("follow_up", ts),
                "citation_click_rate": self._rate("citation_click", ts),
            }

    def check_negative_alert(self, now: float | None = None) -> bool:
        ts = now if now is not None else time.time()
        with self._lock:
            total = sum(1 for _, k in self._events if k == "total")
            rate = self._rate("negative", ts)
        if total >= 100 and rate > _NEGATIVE_RATE_ALERT:
            log.warning("negative_feedback_high", rate=round(rate, 4), threshold=_NEGATIVE_RATE_ALERT)
            return True
        return False
