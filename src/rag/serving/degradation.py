from __future__ import annotations

from dataclasses import dataclass

from serving.types import PoolTier

# Per-intent queue-timeout budgets (task 7.5). Exceeding the budget triggers the
# intent-specific degradation action rather than waiting on the LLM.
QUEUE_TIMEOUTS_S: dict[str, float] = {
    "Intent-1": 2.0,
    "Intent-2": 5.0,
    "Intent-3": 8.0,
}


@dataclass
class DegradeAction:
    kind: str          # "return_chunks" | "skip_graph" | "downgrade_tier" | "cached_answer"
    detail: str = ""


def timeout_for(intent: str) -> float:
    return QUEUE_TIMEOUTS_S.get(intent, 5.0)


def on_queue_timeout(intent: str) -> DegradeAction:
    """Map an intent's queue timeout to its degradation action (task 7.5).

    Intent-1: skip LLM, return Top-3 retrieved chunks directly.
    Intent-3: drop the graph stage, feed pure-vector context to the LLM.
    Intent-2: downgrade to the 7B tier to clear the backlog faster.
    """
    if intent == "Intent-1":
        return DegradeAction("return_chunks", "queue>2s: return top-3 retrieval")
    if intent == "Intent-3":
        return DegradeAction("skip_graph", "queue>8s: pure-vector context")
    return DegradeAction("downgrade_tier", "queue>5s: 14B->7B")


def tier_for_intent(intent: str) -> PoolTier:
    """Task 7.4 routing table: Intent-1 -> 7B pool, Intent-2/3 -> 14B pool."""
    return PoolTier.SMALL if intent == "Intent-1" else PoolTier.LARGE
