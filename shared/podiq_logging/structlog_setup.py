from __future__ import annotations

import logging
import os
import sys
from typing import Any

import structlog

_configured = False


def _service_name(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    event_dict.setdefault("service", os.environ.get("PODIQ_SERVICE_NAME", "unknown"))
    return event_dict


def _upper_level(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    lv = event_dict.get("level")
    if isinstance(lv, str):
        event_dict["level"] = lv.upper()
    return event_dict


def configure_podiq_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    raw_fmt = os.environ.get("LOG_FORMAT", "").strip().lower()
    if raw_fmt in ("json", "console"):
        log_format = raw_fmt
    elif os.environ.get("PODIQ_SERVICE_NAME"):
        log_format = "json"
    else:
        log_format = "console"

    lvl_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    root_level = getattr(logging, lvl_name, logging.INFO)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.format_exc_info,
        structlog.processors.TimeStamper(fmt="ISO", utc=True, key="timestamp"),
        _service_name,
        _upper_level,
    ]

    if log_format == "json":
        processors = [*shared, structlog.processors.JSONRenderer()]
    else:
        processors = [
            *shared,
            structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty()),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(root_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
    )
