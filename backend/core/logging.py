"""Structured logging with a per-request correlation id.

Every agent run, data fetch and report generation is logged with the request
id, so a research output can be traced back to the exact inputs that produced
it. Logs are written as JSON lines to ``var/logs/bti.log`` when
``BTI_LOG_FILE`` is set, otherwise to stderr.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Any

_log_context: ContextVar[dict[str, Any]] = ContextVar("bti_log_context", default={})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(_log_context.get())
        for key in ("agent", "provider", "symbol", "duration_ms", "status"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(extra)
        return json.dumps(payload, default=str)


_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler: logging.Handler
    log_file = os.getenv("BTI_LOG_FILE")
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path)
    else:
        handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger("bti")
    root.handlers = [handler]
    root.setLevel((level or os.getenv("BTI_LOG_LEVEL") or "INFO").upper())
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(f"bti.{name}")


def bind_context(**kwargs: Any) -> None:
    ctx = dict(_log_context.get())
    ctx.update({k: v for k, v in kwargs.items() if v is not None})
    _log_context.set(ctx)


def new_request_id() -> str:
    rid = uuid.uuid4().hex[:12]
    bind_context(request_id=rid)
    return rid


def reset_context() -> None:
    _log_context.set({})


class timed:
    """Context manager that records elapsed milliseconds for a log line."""

    def __init__(self) -> None:
        self.start = time.perf_counter()
        self.elapsed_ms = 0.0

    def __enter__(self) -> "timed":
        return self

    def __exit__(self, *exc: object) -> None:
        self.elapsed_ms = round((time.perf_counter() - self.start) * 1000, 2)
