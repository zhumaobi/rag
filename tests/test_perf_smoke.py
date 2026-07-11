"""Task 10.4: peak performance smoke test using the serving load-test harness.

Runs a short burst and asserts the P99 stays within the SLA and no crashes occur.
A full 10k-QPS soak requires a real cluster; this validates the harness + routing.
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rag.serving.loadtest import run_load  # noqa: E402


def test_perf_smoke_within_sla():
    report = asyncio.run(run_load(qps=1000, duration_s=2, small_n=40, large_n=16))
    assert report["requests"] > 0
    assert report["p99_ms"] < 3000, f"P99 {report['p99_ms']}ms exceeds 3s SLA"


if __name__ == "__main__":
    test_perf_smoke_within_sla()
    print("perf smoke test PASSED")
