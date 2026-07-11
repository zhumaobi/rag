from __future__ import annotations

import time
from contextlib import contextmanager

from raglog import get_logger

log = get_logger("tracing")

try:
    from opentelemetry import trace as _otel_trace

    _HAS_OTEL = True
except ModuleNotFoundError:
    _HAS_OTEL = False


class _SpanShim:
    """Minimal span used when OpenTelemetry isn't installed; logs timing + attributes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._attrs: dict = {}
        self._start = time.perf_counter()

    def set_attribute(self, key: str, value) -> None:
        self._attrs[key] = value

    def end(self) -> None:
        dur_ms = round((time.perf_counter() - self._start) * 1000, 2)
        log.info("span", name=self.name, duration_ms=dur_ms, **self._attrs)


class Tracer:
    """Request-path tracing across intent -> retrieval -> LLM (task 9.2).

    Wraps OpenTelemetry when present; otherwise falls back to a logging span so the
    full-chain trace structure (nested spans, attributes) is preserved in logs.
    """

    def __init__(self, service_name: str = "rag") -> None:
        self._otel = _otel_trace.get_tracer(service_name) if _HAS_OTEL else None

    @contextmanager
    def span(self, name: str, **attributes):
        if self._otel is not None:
            with self._otel.start_as_current_span(name) as sp:
                for k, v in attributes.items():
                    sp.set_attribute(k, v)
                yield sp
        else:
            sp = _SpanShim(name)
            for k, v in attributes.items():
                sp.set_attribute(k, v)
            try:
                yield sp
            finally:
                sp.end()


_GLOBAL: Tracer | None = None
_EXPORT_CONFIGURED = False


def get_tracer() -> Tracer:
    global _GLOBAL
    if _GLOBAL is None:
        _GLOBAL = Tracer()
    return _GLOBAL


def setup_tracing(otlp_endpoint: str = "", service_name: str = "rag") -> bool:
    """Configure OTLP span export for production; no-op unless OTel + an endpoint exist.

    Idempotent: registers a TracerProvider + BatchSpanProcessor(OTLPSpanExporter) once,
    then resets the global Tracer so subsequent get_tracer() calls pick up the provider.
    The span() calls already in QueryService/RetrievalRouter then export unchanged.
    """
    global _GLOBAL, _EXPORT_CONFIGURED
    if _EXPORT_CONFIGURED or not _HAS_OTEL or not otlp_endpoint:
        return _EXPORT_CONFIGURED
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    except ModuleNotFoundError:
        log.warning("otlp_sdk_missing", detail="install opentelemetry-sdk + otlp exporter")
        return False

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    _otel_trace.set_tracer_provider(provider)
    _GLOBAL = None  # force rebuild so Tracer binds to the configured provider
    _EXPORT_CONFIGURED = True
    log.info("tracing_export_configured", endpoint=otlp_endpoint, service=service_name)
    return True
