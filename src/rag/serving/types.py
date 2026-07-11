from __future__ import annotations

import enum
from dataclasses import dataclass, field


class PoolTier(str, enum.Enum):
    SMALL = "7B"   # Qwen2.5-7B, TP=2 — Intent-1
    LARGE = "14B"  # Qwen2.5-14B, TP=4 — Intent-2/3


class InstanceState(str, enum.Enum):
    STARTING = "starting"   # model loading, not yet in LB
    HEALTHY = "healthy"
    DRAINING = "draining"   # no new requests, finishing in-flight
    UNHEALTHY = "unhealthy"
    STOPPED = "stopped"


@dataclass
class Instance:
    instance_id: str
    tier: PoolTier
    endpoint: str
    state: InstanceState = InstanceState.STARTING
    pending_tokens: int = 0          # queued + in-flight token estimate
    inflight: int = 0                # in-flight request count
    gpu_mem_util: float = 0.0        # 0..1
    prefix_hits: int = 0
    prefix_lookups: int = 0

    @property
    def healthy(self) -> bool:
        return self.state is InstanceState.HEALTHY

    @property
    def prefix_hit_rate(self) -> float:
        return self.prefix_hits / self.prefix_lookups if self.prefix_lookups else 0.0


@dataclass
class GenRequest:
    tenant_id: str
    intent: str                      # "Intent-1" | "Intent-2" | "Intent-3"
    prompt: str
    system_prefix: str = ""          # shared system prompt + tenant instruction (~300 tok)
    max_tokens: int = 512
    est_prompt_tokens: int = 0


@dataclass
class GenResult:
    text: str
    tier: PoolTier
    instance_id: str
    downgraded: bool = False         # 14B -> 7B tier downgrade occurred
    degraded_level: str = ""         # "" | "L1" | "L2" | "L3" | "L4"
    prefix_cache_hit: bool = False
    meta: dict = field(default_factory=dict)
    prompt: str = ""                 # exact prompt sent to the LLM ("" if LLM was skipped)
