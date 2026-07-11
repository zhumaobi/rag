from __future__ import annotations

import bisect
import hashlib

from raglog import get_logger
from serving.model_pool import ModelPool
from serving.types import Instance

log = get_logger("router")

_VNODES = 128  # virtual nodes per instance for balanced consistent hashing


class ConsistentHashRing:
    """Consistent-hash ring for tenant affinity (task 7.3).

    Each healthy instance is placed at `_VNODES` positions. A tenant maps to the first
    instance clockwise from hash(tenant_id), so the same tenant reuses one instance and
    its Prefix KV Cache. Adding/removing an instance only remaps a small key fraction.
    """

    def __init__(self) -> None:
        self._ring: list[int] = []
        self._slot_to_instance: dict[int, str] = {}

    @staticmethod
    def _hash(key: str) -> int:
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def rebuild(self, instances: list[Instance]) -> None:
        self._ring = []
        self._slot_to_instance = {}
        for inst in instances:
            for v in range(_VNODES):
                slot = self._hash(f"{inst.instance_id}#{v}")
                self._ring.append(slot)
                self._slot_to_instance[slot] = inst.instance_id
        self._ring.sort()

    def get(self, tenant_id: str) -> str | None:
        if not self._ring:
            return None
        h = self._hash(tenant_id)
        idx = bisect.bisect(self._ring, h) % len(self._ring)
        return self._slot_to_instance[self._ring[idx]]


class LoadBalancer:
    """Routes a request to an instance within a pool: tenant-affinity first, then load.

    Affinity is honored only if the target instance is healthy and not overloaded; on
    failure or overload it falls back to the least-loaded healthy instance by
    pending_tokens (spec: reroute on unhealthy affinity target).
    """

    def __init__(self, overload_pending_tokens: int = 8192) -> None:
        self._ring = ConsistentHashRing()
        self._overload = overload_pending_tokens

    def refresh(self, pool: ModelPool) -> None:
        self._ring.rebuild(pool.healthy())

    def pick(self, pool: ModelPool, tenant_id: str) -> Instance | None:
        healthy = pool.healthy()
        if not healthy:
            return None

        affinity_id = self._ring.get(tenant_id)
        affinity = pool.get(affinity_id) if affinity_id else None
        if affinity and affinity.healthy and affinity.pending_tokens < self._overload:
            return affinity

        # Fallback: least pending_tokens, ties broken by fewest in-flight.
        chosen = min(healthy, key=lambda i: (i.pending_tokens, i.inflight))
        if affinity is not None:
            log.info("affinity_bypassed", tenant=tenant_id, chosen=chosen.instance_id)
        return chosen
