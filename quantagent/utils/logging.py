"""File-based logging and unhandled exception capture."""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


def init_file_logging(max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5) -> None:
    """Install a rotating file handler on the root logger at ~/.quantagent/logs/errors.log.

    All loggers in the project use ``logging.getLogger(__name__)``, so a handler
    on the root logger captures everything at once — no per-module setup needed.
    """
    log_dir = Path.home() / ".quantagent" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "errors.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s:%(funcName)s:%(lineno)d\n"
            "  %(message)s"
        )
    )
    handler.setLevel(logging.DEBUG)
    logging.root.addHandler(handler)

    # Ensure DEBUG messages reach the file handler (root default is WARNING).
    if logging.root.level == logging.WARNING:
        logging.root.setLevel(logging.DEBUG)


def install_excepthook() -> None:
    """Log truly unhandled exceptions via the logging system before crashing."""
    original = sys.excepthook

    def _hook(exc_type: type[BaseException], exc_value: BaseException, tb: Any) -> None:
        logging.critical("Unhandled exception", exc_info=(exc_type, exc_value, tb))
        original(exc_type, exc_value, tb)

    sys.excepthook = _hook
