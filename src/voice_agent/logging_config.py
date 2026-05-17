"""Structlog configuration — JSON to stdout and a persistent log file."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TextIO

import structlog


_LOG_FILE_HANDLE: TextIO | None = None


class _Tee:
    def __init__(self, *streams: TextIO) -> None:
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog for JSON output and set stdlib root level."""
    global _LOG_FILE_HANDLE

    log_level = getattr(logging, level.upper(), logging.INFO)
    log_path = Path(os.getenv("VOICE_AGENT_LOG_FILE", "logs/voice-agent.jsonl"))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if _LOG_FILE_HANDLE:
        _LOG_FILE_HANDLE.close()
    _LOG_FILE_HANDLE = open(log_path, "a", encoding="utf-8", buffering=1)
    output = _Tee(sys.stdout, _LOG_FILE_HANDLE)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=output),
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.handlers.clear()
    logging.basicConfig(
        format="%(message)s",
        stream=output,
        level=log_level,
    )

    structlog.get_logger(__name__).info(
        "logging_configured",
        level=level.upper(),
        log_file=str(log_path),
    )
