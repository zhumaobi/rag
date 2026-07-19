from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from intent.types import Intent, IntentResult
from serving.types import PoolTier


@dataclass
class QueryTrace:
    """Per-query observability record. Captured once inside QueryService.query() and
    surfaced on Answer so it feeds both live observability and offline evaluation."""

    request_id: str
    hop_latency_ms: dict[str, float] = field(default_factory=dict)
    intent: IntentResult | None = None
    cache_level: str = ""
    retrieved_doc_ids: list[str] = field(default_factory=list)
    contexts: list[str] = field(default_factory=list)
    prompt: str = ""
    tier: PoolTier | None = None
    degraded_level: str = ""
    retrieval_degraded: bool = False
    agentic: bool = False
    agentic_iterations: int = 0
    agentic_scores: list[dict] = field(default_factory=list)

    @contextmanager
    def hop(self, name: str):
        """Time a hop and record its duration (ms) into hop_latency_ms under `name`."""
        start = time.perf_counter()
        try:
            yield
        finally:
            self.hop_latency_ms[name] = round((time.perf_counter() - start) * 1000, 2)


@dataclass
class Answer:
    """Final online query result plus provenance for observability/debugging."""

    text: str
    intent: IntentResult | None = None
    cached: bool = False
    degraded_level: str = ""
    tier: PoolTier | None = None
    meta: dict = field(default_factory=dict)
    trace: QueryTrace | None = None


def intent_to_request_str(intent: Intent) -> str:
    """Map the Intent enum to the "Intent-N" string GenRequest expects.

    The enum values already are "Intent-1|2|3"; this indirection keeps the impedance
    match explicit at the facade boundary rather than relying on that coincidence.
    """
    return intent.value
