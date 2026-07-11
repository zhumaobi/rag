from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

import redis

from config import get_settings
from raglog import get_logger

log = get_logger("feedback")


@dataclass
class FeedbackEvent:
    tenant_id: str
    query: str
    doc_id: str | None
    event_type: str  # "click_source" | "copy_text" | "negative" | "follow_up"
    ts: float


class FeedbackCollector:
    """Collects implicit user feedback (task 8.6).

    Click-source and copy-text events on a cited document become weak-positive
    <query, doc_id> pairs pushed to a review list for periodic human spot-check before
    joining the retrieval eval set (spec: implicit feedback expands the eval set).
    Negative-feedback events feed the L4 negative-rate monitor.
    """

    def __init__(self, client: redis.Redis | None = None) -> None:
        self._r = client or redis.Redis.from_url(get_settings().redis_url, decode_responses=True)

    def _weak_positive_key(self, tenant_id: str) -> str:
        return f"feedback:weakpos:{tenant_id}"

    def record(
        self, tenant_id: str, query: str, event_type: str, doc_id: str | None = None,
        now: float | None = None,
    ) -> None:
        ts = now if now is not None else time.time()
        event = FeedbackEvent(tenant_id, query, doc_id, event_type, ts)
        # Append to a rolling event stream for the L4 monitor to aggregate.
        self._r.xadd(f"feedback:stream:{tenant_id}", {"data": json.dumps(asdict(event))}, maxlen=100000)
        if event_type in ("click_source", "copy_text") and doc_id:
            self._r.rpush(self._weak_positive_key(tenant_id), json.dumps({"query": query, "doc_id": doc_id}))
        log.info("feedback_recorded", tenant_id=tenant_id, event_type=event_type)

    def drain_weak_positives(self, tenant_id: str, limit: int = 1000) -> list[dict]:
        """Pop pending weak-positive pairs for human spot-check + eval-set expansion."""
        key = self._weak_positive_key(tenant_id)
        out: list[dict] = []
        for _ in range(limit):
            raw = self._r.lpop(key)
            if raw is None:
                break
            out.append(json.loads(raw))
        return out
