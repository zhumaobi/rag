from __future__ import annotations

from dataclasses import dataclass, field

from raglog import get_logger
from serving.types import Instance, InstanceState, PoolTier

log = get_logger("model_pool")


@dataclass
class PoolConfig:
    tier: PoolTier
    model_name: str
    tensor_parallel: int
    min_instances: int
    max_instances: int


# Tiered pool defaults (task 7.1): OpenAI models — gpt-4o-mini for Intent-1 (cheap/fast),
# gpt-4o for Intent-2/3 (higher quality). tensor_parallel is a no-op for a hosted API.
DEFAULT_POOL_CONFIGS: dict[PoolTier, PoolConfig] = {
    PoolTier.SMALL: PoolConfig(PoolTier.SMALL, "gpt-4o-mini", 2, min_instances=2, max_instances=32),
    PoolTier.LARGE: PoolConfig(PoolTier.LARGE, "gpt-4o", 4, min_instances=2, max_instances=16),
}


class ModelPool:
    """A tier's set of vLLM replicas. Pools are independent so 14B saturation never
    starves the 7B (Intent-1) path (spec: resource isolation)."""

    def __init__(self, config: PoolConfig) -> None:
        self.config = config
        self._instances: dict[str, Instance] = {}

    @property
    def tier(self) -> PoolTier:
        return self.config.tier

    @property
    def model_name(self) -> str:
        return self.config.model_name

    def add(self, instance: Instance) -> None:
        self._instances[instance.instance_id] = instance

    def remove(self, instance_id: str) -> None:
        self._instances.pop(instance_id, None)

    def get(self, instance_id: str) -> Instance | None:
        return self._instances.get(instance_id)

    def all(self) -> list[Instance]:
        return list(self._instances.values())

    def healthy(self) -> list[Instance]:
        return [i for i in self._instances.values() if i.healthy]

    def size(self) -> int:
        return len(self._instances)

    def healthy_count(self) -> int:
        return len(self.healthy())

    def avg_gpu_util(self) -> float:
        healthy = self.healthy()
        return sum(i.gpu_mem_util for i in healthy) / len(healthy) if healthy else 0.0

    def mark(self, instance_id: str, state: InstanceState) -> None:
        inst = self._instances.get(instance_id)
        if inst:
            inst.state = state
            log.info("instance_state_changed", instance=instance_id, tier=self.tier.value, state=state.value)
