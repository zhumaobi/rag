from __future__ import annotations

from raglog import get_logger

log = get_logger("metrics")

try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

    _HAS_PROM = True
except ModuleNotFoundError:  # graceful fallback: in-memory no-op metrics
    _HAS_PROM = False


# Latency buckets tuned around the SLA (P50<800ms, P95<2s, P99<3s).
_LATENCY_BUCKETS = (0.05, 0.1, 0.2, 0.4, 0.8, 1.2, 2.0, 3.0, 5.0, 10.0)


class _NoopMetric:
    def labels(self, *a, **k):
        return self

    def inc(self, *a, **k):
        pass

    def observe(self, *a, **k):
        pass

    def set(self, *a, **k):
        pass


class Metrics:
    """Prometheus metric registry for the RAG system (task 9.1).

    Exposes GPU memory utilization and KV-cache hit rate gauges plus request/latency
    counters. When prometheus_client isn't installed, every metric is a no-op so the
    rest of the system runs unchanged.
    """

    def __init__(self, registry=None) -> None:
        if _HAS_PROM:
            self.registry = registry or CollectorRegistry()
            self.gpu_mem_util = Gauge(
                "rag_gpu_mem_util", "GPU memory utilization (0-1)", ["tier", "instance"], registry=self.registry
            )
            self.kv_cache_hit_rate = Gauge(
                "rag_kv_cache_hit_rate", "Prefix KV cache hit rate", ["tier", "instance"], registry=self.registry
            )
            self.semantic_cache_hit_rate = Gauge(
                "rag_semantic_cache_hit_rate", "Semantic cache rolling hit rate", registry=self.registry
            )
            self.requests_total = Counter(
                "rag_requests_total", "Total requests", ["intent", "outcome"], registry=self.registry
            )
            self.request_latency = Histogram(
                "rag_request_latency_seconds", "End-to-end latency", ["intent"],
                buckets=_LATENCY_BUCKETS, registry=self.registry,
            )
            self.degradations_total = Counter(
                "rag_degradations_total", "Degradation events", ["level"], registry=self.registry
            )
            self.stage_latency = Histogram(
                "rag_stage_latency_seconds", "Per-stage latency", ["stage"],
                buckets=_LATENCY_BUCKETS, registry=self.registry,
            )
            self.agentic_iterations = Histogram(
                "rag_agentic_iterations", "Agentic loop iterations per request", ["intent"],
                buckets=(1, 2, 3, 4, 5), registry=self.registry,
            )
            self.agentic_low_confidence_total = Counter(
                "rag_agentic_low_confidence_total", "Agentic answers returned low-confidence",
                ["intent"], registry=self.registry,
            )
        else:
            self.registry = None
            noop = _NoopMetric()
            self.gpu_mem_util = noop
            self.kv_cache_hit_rate = noop
            self.semantic_cache_hit_rate = noop
            self.requests_total = noop
            self.request_latency = noop
            self.degradations_total = noop
            self.stage_latency = noop
            self.agentic_iterations = noop
            self.agentic_low_confidence_total = noop
            log.warning("prometheus_unavailable_noop_metrics")

    def observe_request(self, intent: str, latency_s: float, outcome: str = "ok") -> None:
        self.requests_total.labels(intent=intent, outcome=outcome).inc()
        self.request_latency.labels(intent=intent).observe(latency_s)

    def observe_degradation(self, level: str) -> None:
        if level:
            self.degradations_total.labels(level=level).inc()

    def observe_stages(self, hop_latency_ms: dict[str, float]) -> None:
        """Record per-stage latencies (ms map from QueryTrace.hop_latency_ms)."""
        for stage, ms in hop_latency_ms.items():
            self.stage_latency.labels(stage=stage).observe(ms / 1000.0)

    def observe_agentic(self, intent: str, iterations: int, low_confidence: bool) -> None:
        """Record agentic loop iteration count and low-confidence outcomes."""
        self.agentic_iterations.labels(intent=intent).observe(iterations)
        if low_confidence:
            self.agentic_low_confidence_total.labels(intent=intent).inc()


_GLOBAL: Metrics | None = None
_SERVER_STARTED = False


def get_metrics() -> Metrics:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = Metrics()
    return _GLOBAL


def start_metrics_server(port: int = 9090) -> bool:
    """Expose the metrics registry over HTTP via a standalone server thread.

    No-ops (and never raises) when prometheus_client is absent, and starts at most once
    per process. Returns True if a server is running after the call.
    """
    global _SERVER_STARTED
    if not _HAS_PROM:
        return False
    if _SERVER_STARTED:
        return True
    from prometheus_client import start_http_server

    start_http_server(port, registry=get_metrics().registry)
    _SERVER_STARTED = True
    log.info("metrics_server_started", port=port)
    return True
