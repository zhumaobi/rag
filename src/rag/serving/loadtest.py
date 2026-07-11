from __future__ import annotations

import argparse
import asyncio
import statistics
import time

from raglog import get_logger
from serving.dispatcher import Dispatcher
from serving.model_pool import DEFAULT_POOL_CONFIGS, ModelPool
from serving.types import GenRequest, Instance, InstanceState, PoolTier

log = get_logger("loadtest")


class _FakeVLLM:
    """Stand-in for VLLMClient that simulates per-request latency, so the harness can
    exercise routing/degradation logic without a live GPU cluster (task 7.10)."""

    def __init__(self, base_latency_s: float = 0.4) -> None:
        self._base = base_latency_s

    async def generate(self, instance, model, prompt, max_tokens):
        # Latency grows with instance load to model queueing under contention.
        load_penalty = min(1.5, instance.inflight * 0.05)
        await asyncio.sleep(self._base + load_penalty)
        return "simulated answer"


def _build_pools(small_n: int, large_n: int) -> dict[PoolTier, ModelPool]:
    pools = {tier: ModelPool(cfg) for tier, cfg in DEFAULT_POOL_CONFIGS.items()}
    for i in range(small_n):
        pools[PoolTier.SMALL].add(Instance(f"s{i}", PoolTier.SMALL, f"http://s{i}", InstanceState.HEALTHY))
    for i in range(large_n):
        pools[PoolTier.LARGE].add(Instance(f"l{i}", PoolTier.LARGE, f"http://l{i}", InstanceState.HEALTHY))
    return pools


def _percentile(values: list[float], p: float) -> float:
    idx = min(len(values) - 1, int(round(p / 100 * len(values))))
    return sorted(values)[idx]


async def run_load(qps: int, duration_s: int, small_n: int, large_n: int) -> dict:
    pools = _build_pools(small_n, large_n)
    dispatcher = Dispatcher(pools, client=_FakeVLLM())
    latencies: list[float] = []
    degraded = 0

    # 60% Intent-1, 25% Intent-2, 15% Intent-3 traffic mix.
    intents = ["Intent-1"] * 60 + ["Intent-2"] * 25 + ["Intent-3"] * 15

    async def one(i: int):
        nonlocal degraded
        intent = intents[i % len(intents)]
        req = GenRequest(
            tenant_id=f"t{i % 50}", intent=intent, prompt="q", system_prefix="sys",
            est_prompt_tokens=300, max_tokens=256,
        )
        t0 = time.perf_counter()
        res = await dispatcher.generate(req, context="ctx", fallback_chunks_text="chunks", cached_answer="cached")
        latencies.append((time.perf_counter() - t0) * 1000)
        if res.degraded_level:
            degraded += 1

    tasks: list[asyncio.Task] = []
    interval = 1.0 / qps
    start = time.perf_counter()
    i = 0
    while time.perf_counter() - start < duration_s:
        tasks.append(asyncio.create_task(one(i)))
        i += 1
        await asyncio.sleep(interval)
    await asyncio.gather(*tasks)

    report = {
        "requests": len(latencies),
        "qps_target": qps,
        "p50_ms": round(statistics.median(latencies), 1),
        "p95_ms": round(_percentile(latencies, 95), 1),
        "p99_ms": round(_percentile(latencies, 99), 1),
        "degraded_pct": round(100 * degraded / max(1, len(latencies)), 2),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM serving load-test harness")
    parser.add_argument("--qps", type=int, default=5000)
    parser.add_argument("--duration", type=int, default=10)
    parser.add_argument("--small", type=int, default=40)
    parser.add_argument("--large", type=int, default=16)
    args = parser.parse_args()
    report = asyncio.run(run_load(args.qps, args.duration, args.small, args.large))
    print(report)
    if report["p99_ms"] >= 3000:
        print("WARNING: P99 exceeds 3s SLA")


if __name__ == "__main__":
    main()
