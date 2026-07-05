"""Structured logging via structlog.

Dev: colored, human-readable console lines.
Prod/Docker: one JSON object per line (grep-able, ship-able to anything later).

Usage anywhere in the app::

    from app.logging import get_logger
    log = get_logger(__name__)
    log.info("sync.started", days=30, endpoint="daily_metrics")
"""

from __future__ import annotations

import logging
import sys

import structlog

from app.config import get_app_config


def configure_logging() -> None:
    """Configure stdlib + structlog once, at application startup."""
    cfg = get_app_config()
    level = getattr(logging, cfg.log_level)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    renderer: structlog.types.Processor
    if cfg.log_json:
        renderer = structlog.processors.JSONRenderer()
        shared_processors.append(structlog.processors.format_exc_info)
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
