from __future__ import annotations

import asyncio
import time

from raglog import get_logger
from serving.circuit_breaker import CircuitBreaker
from serving.degradation import (
    DegradeAction,
    on_queue_timeout,
    tier_for_intent,
    timeout_for,
)
from serving.model_pool import ModelPool
from serving.prefix import build_prompt, record_prefix_lookup
from serving.router import LoadBalancer
from serving.types import GenRequest, GenResult, Instance, InstanceState, PoolTier
from serving.vllm_client import VLLMClient

log = get_logger("dispatcher")

# 14B pool considered saturated when the least-loaded instance still exceeds this.
_LARGE_POOL_SATURATION_TOKENS = 12288


class Dispatcher:
    """Orchestrates generation: tiered routing (7.4), queue-timeout degradation (7.5),
    and the L1->L4 circuit-breaker degradation chain (7.6).

    Degradation chain semantics:
      L1: unhealthy/tripped instance removed from routing (breaker + LB skip).
      L2: 14B pool saturated -> downgrade Intent-2/3 to the 7B pool.
      L3: queue/timeout -> skip LLM, hand back retrieved chunks (Intent-1) or pure-vector.
      L4: total failure -> return a cached approximate answer (provided by caller).
    """

    def __init__(
        self,
        pools: dict[PoolTier, ModelPool],
        client: VLLMClient | None = None,
        balancer: LoadBalancer | None = None,
    ) -> None:
        self._pools = pools
        self._client = client or VLLMClient()
        self._lb = balancer or LoadBalancer()
        self._breakers: dict[str, CircuitBreaker] = {}

    def _breaker(self, instance_id: str) -> CircuitBreaker:
        return self._breakers.setdefault(instance_id, CircuitBreaker())

    def _select_tier(self, intent: str) -> PoolTier:
        tier = tier_for_intent(intent)
        # L2: if the large pool is saturated, downgrade Intent-2/3 to the small pool.
        if tier is PoolTier.LARGE:
            large = self._pools[PoolTier.LARGE]
            healthy = large.healthy()
            least = min((i.pending_tokens for i in healthy), default=None)
            if not healthy or (least is not None and least > _LARGE_POOL_SATURATION_TOKENS):
                log.info("tier_downgraded", intent=intent, reason="large_pool_saturated")
                return PoolTier.SMALL
        return tier

    async def generate(
        self,
        req: GenRequest,
        context: str,
        fallback_chunks_text: str = "",
        cached_answer: str | None = None,
    ) -> GenResult:
        requested_tier = tier_for_intent(req.intent)
        tier = self._select_tier(req.intent)
        pool = self._pools[tier]
        self._lb.refresh(pool)

        instance = self._pick_allowed(pool, req.tenant_id)
        if instance is None:
            # L3/L4: no serving capacity at all.
            return self._degrade_no_capacity(req, tier, fallback_chunks_text, cached_answer)

        prompt = build_prompt(req.system_prefix, context, req.prompt)
        budget = timeout_for(req.intent)

        instance.inflight += 1
        instance.pending_tokens += req.est_prompt_tokens + req.max_tokens
        start = time.perf_counter()
        try:
            text = await asyncio.wait_for(
                self._client.generate(instance, pool.model_name, prompt, req.max_tokens),
                timeout=budget,
            )
            self._breaker(instance.instance_id).record_success()
            record_prefix_lookup(instance, hit=(instance.instance_id == self._lb._ring.get(req.tenant_id)))
            return GenResult(
                text=text,
                tier=tier,
                instance_id=instance.instance_id,
                downgraded=(tier != requested_tier),
                prefix_cache_hit=bool(req.system_prefix),
                meta={"latency_ms": round((time.perf_counter() - start) * 1000, 1)},
                prompt=prompt,
            )
        except asyncio.TimeoutError:
            # Task 7.5: queue/inference timeout -> intent-specific degradation.
            action = on_queue_timeout(req.intent)
            log.warning("queue_timeout", intent=req.intent, action=action.kind)
            return self._apply_timeout_action(req, tier, action, context, fallback_chunks_text, cached_answer)
        except Exception as exc:
            # L1: mark the failing instance so it drops out of routing.
            self._breaker(instance.instance_id).record_failure()
            pool.mark(instance.instance_id, InstanceState.UNHEALTHY)
            log.error("generation_failed", instance=instance.instance_id, error=str(exc))
            return self._degrade_no_capacity(req, tier, fallback_chunks_text, cached_answer)
        finally:
            instance.inflight = max(0, instance.inflight - 1)
            instance.pending_tokens = max(0, instance.pending_tokens - (req.est_prompt_tokens + req.max_tokens))

    def _pick_allowed(self, pool: ModelPool, tenant_id: str) -> Instance | None:
        # Try up to a few candidates so a tripped breaker (L1) doesn't dead-end routing.
        for _ in range(3):
            inst = self._lb.pick(pool, tenant_id)
            if inst is None:
                return None
            if self._breaker(inst.instance_id).allow():
                return inst
            pool.mark(inst.instance_id, InstanceState.UNHEALTHY)
            self._lb.refresh(pool)
        return None

    def _apply_timeout_action(
        self, req: GenRequest, tier: PoolTier, action: DegradeAction,
        context: str, fallback_chunks_text: str, cached_answer: str | None,
    ) -> GenResult:
        if action.kind == "return_chunks":  # L3
            return GenResult(text=fallback_chunks_text, tier=tier, instance_id="", degraded_level="L3", meta={"action": action.detail})
        if action.kind == "skip_graph":  # L3 (pure-vector context already in `context`)
            return GenResult(text=fallback_chunks_text or context, tier=tier, instance_id="", degraded_level="L3", meta={"action": action.detail})
        # downgrade_tier handled by retrying on small pool would recurse; keep simple: L3 fallback.
        return self._degrade_no_capacity(req, tier, fallback_chunks_text, cached_answer)

    def _degrade_no_capacity(
        self, req: GenRequest, tier: PoolTier, fallback_chunks_text: str, cached_answer: str | None
    ) -> GenResult:
        if fallback_chunks_text:  # L3
            return GenResult(text=fallback_chunks_text, tier=tier, instance_id="", degraded_level="L3")
        if cached_answer is not None:  # L4
            return GenResult(text=cached_answer, tier=tier, instance_id="", degraded_level="L4")
        return GenResult(text="", tier=tier, instance_id="", degraded_level="L4")
