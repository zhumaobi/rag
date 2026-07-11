from __future__ import annotations

import contextvars
import logging
import uuid

try:
    import structlog

    _HAS_STRUCTLOG = True
except ModuleNotFoundError:  # graceful fallback when structlog isn't installed
    structlog = None  # type: ignore[assignment]
    _HAS_STRUCTLOG = False


# Context-local correlation id, merged into every structured log record.
_REQUEST_ID: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")


def bind_request_id(request_id: str | None = None) -> str:
    """Bind a request_id to the current context (generating one if not given).

    When structlog is present the id is also bound into its contextvars so every log
    line during the request carries it automatically. Returns the bound id.
    """
    rid = request_id or uuid.uuid4().hex
    _REQUEST_ID.set(rid)
    if _HAS_STRUCTLOG:
        structlog.contextvars.bind_contextvars(request_id=rid)
    return rid


def get_request_id() -> str:
    return _REQUEST_ID.get()


def clear_request_id() -> None:
    _REQUEST_ID.set("")
    if _HAS_STRUCTLOG:
        structlog.contextvars.unbind_contextvars("request_id")


class _StdlibLogger:
    """Minimal structlog-compatible shim over the stdlib logger.

    Supports keyword event fields (log.info("event", key=val)) so call sites work whether
    or not structlog is present.
    """

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def _emit(self, level: int, event: str, **kw) -> None:
        if kw:
            fields = " ".join(f"{k}={v}" for k, v in kw.items())
            self._log.log(level, "%s %s", event, fields)
        else:
            self._log.log(level, "%s", event)

    def debug(self, event: str, **kw) -> None:
        self._emit(logging.DEBUG, event, **kw)

    def info(self, event: str, **kw) -> None:
        self._emit(logging.INFO, event, **kw)

    def warning(self, event: str, **kw) -> None:
        self._emit(logging.WARNING, event, **kw)

    def error(self, event: str, **kw) -> None:
        self._emit(logging.ERROR, event, **kw)


def get_logger(name: str):
    if _HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        )
        return structlog.get_logger(name)
    return _StdlibLogger(name)
