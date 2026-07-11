from __future__ import annotations

import argparse
import statistics
import time

from intent.rules import classify_rules
from intent.types import Intent

# Latency benchmark for the intent recognition path (task 4.8). The rule layer is the
# hot path (~60% of traffic short-circuits here). This isolates rule-layer latency and,
# when a trained model is available, measures the full two-stage path P99 (< 15ms target).

_RULE_QUERIES = [
    "订单中心和支付网关有什么区别",   # compare
    "幂等键这个概念是什么意思",         # relation
    "网关服务如何配置限流策略",         # precise (no rule hit -> model)
    "风控引擎 vs 对账系统 哪个更好",    # compare
    "库存服务依赖哪些下游服务",         # relation
]


def _percentile(values: list[float], p: float) -> float:
    idx = min(len(values) - 1, int(round(p / 100 * len(values))))
    return sorted(values)[idx]


def bench_rules(iterations: int = 20000) -> dict:
    latencies: list[float] = []
    for i in range(iterations):
        q = _RULE_QUERIES[i % len(_RULE_QUERIES)]
        t0 = time.perf_counter()
        classify_rules(q)
        latencies.append((time.perf_counter() - t0) * 1000)
    return {
        "layer": "rule",
        "iterations": iterations,
        "p50_ms": round(statistics.median(latencies), 4),
        "p95_ms": round(_percentile(latencies, 95), 4),
        "p99_ms": round(_percentile(latencies, 99), 4),
    }


def bench_full(iterations: int = 2000) -> dict:
    """Full two-stage path benchmark; requires a trained classifier under models/intent."""
    from intent.service import IntentService

    service = IntentService()
    latencies: list[float] = []
    for i in range(iterations):
        q = _RULE_QUERIES[i % len(_RULE_QUERIES)]
        t0 = time.perf_counter()
        service.recognize("bench_tenant", q)
        latencies.append((time.perf_counter() - t0) * 1000)
    return {
        "layer": "full",
        "iterations": iterations,
        "p50_ms": round(statistics.median(latencies), 4),
        "p95_ms": round(_percentile(latencies, 95), 4),
        "p99_ms": round(_percentile(latencies, 99), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Intent recognition latency benchmark")
    parser.add_argument("--mode", choices=["rule", "full"], default="rule")
    parser.add_argument("--iterations", type=int)
    args = parser.parse_args()

    if args.mode == "rule":
        report = bench_rules(args.iterations or 20000)
    else:
        report = bench_full(args.iterations or 2000)

    print(report)
    if report["p99_ms"] >= 15:
        print("WARNING: P99 exceeds 15ms budget")


if __name__ == "__main__":
    main()
