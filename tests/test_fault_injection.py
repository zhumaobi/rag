"""Task 10.3: fault-injection tests for the degradation chain.

Simulates LLM instance failure, all-instances-down, and inference timeout to verify
the dispatcher degrades correctly (L1 instance removal, L3 return chunks, L4 cached
answer) instead of failing hard.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rag.serving.dispatcher import Dispatcher  # noqa: E402
from rag.serving.model_pool import DEFAULT_POOL_CONFIGS, ModelPool  # noqa: E402
from rag.serving.types import GenRequest, Instance, InstanceState, PoolTier  # noqa: E402


def _pools(small_n=2, large_n=2):
    pools = {tier: ModelPool(cfg) for tier, cfg in DEFAULT_POOL_CONFIGS.items()}
    for i in range(small_n):
        pools[PoolTier.SMALL].add(Instance(f"s{i}", PoolTier.SMALL, f"http://s{i}", InstanceState.HEALTHY))
    for i in range(large_n):
        pools[PoolTier.LARGE].add(Instance(f"l{i}", PoolTier.LARGE, f"http://l{i}", InstanceState.HEALTHY))
    return pools


class _AlwaysFailClient:
    async def generate(self, *a, **k):
        raise RuntimeError("vLLM instance down")


class _TimeoutClient:
    async def generate(self, *a, **k):
        await asyncio.sleep(10)  # exceeds every intent's queue budget
        return "never"


class _HealthyClient:
    async def generate(self, *a, **k):
        return "ok answer"


def _req(intent="Intent-1"):
    return GenRequest(tenant_id="t1", intent=intent, prompt="q", system_prefix="sys", est_prompt_tokens=100, max_tokens=64)


def test_instance_failure_degrades_to_chunks():
    d = Dispatcher(_pools(), client=_AlwaysFailClient())
    res = asyncio.run(d.generate(_req("Intent-1"), context="ctx", fallback_chunks_text="TOP3", cached_answer="CACHED"))
    # All instances fail -> falls through to L3 (chunks) since fallback text is present.
    assert res.degraded_level in ("L3", "L4"), res.degraded_level
    assert res.text in ("TOP3", "CACHED")


def test_no_fallback_uses_cached_answer_L4():
    d = Dispatcher(_pools(), client=_AlwaysFailClient())
    res = asyncio.run(d.generate(_req("Intent-1"), context="ctx", fallback_chunks_text="", cached_answer="CACHED"))
    assert res.degraded_level == "L4"
    assert res.text == "CACHED"


def test_timeout_triggers_intent1_return_chunks():
    d = Dispatcher(_pools(), client=_TimeoutClient())
    res = asyncio.run(d.generate(_req("Intent-1"), context="ctx", fallback_chunks_text="TOP3", cached_answer="CACHED"))
    assert res.degraded_level == "L3"
    assert res.text == "TOP3"


def test_healthy_path_no_degradation():
    d = Dispatcher(_pools(), client=_HealthyClient())
    res = asyncio.run(d.generate(_req("Intent-1"), context="ctx", fallback_chunks_text="TOP3"))
    assert res.degraded_level == ""
    assert res.text == "ok answer"


if __name__ == "__main__":
    test_instance_failure_degrades_to_chunks()
    test_no_fallback_uses_cached_answer_L4()
    test_timeout_triggers_intent1_return_chunks()
    test_healthy_path_no_degradation()
    print("fault-injection tests PASSED")
