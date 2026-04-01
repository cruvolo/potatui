# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (c) 2026 MonkeybutlerCJH (https://github.com/MonkeybutlerCJH)

"""Logging setup for potatui — call setup_logging() once at startup."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_LOG_FILE = "potatui_debug.log"
_MAX_BYTES = 1_048_576  # 1 MB
_BACKUP_COUNT = 3
_FMT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FMT = "%H:%M:%S"


def setup_logging(log_dir: Path, enabled: bool = True, level: int = logging.DEBUG) -> None:
    """Enable or disable file-based debug logging. Safe to call multiple times.

    When *enabled* is False any existing handlers are removed so logging stops
    immediately without requiring a restart.
    """
    root = logging.getLogger("potatui")

    if not enabled:
        for h in list(root.handlers):
            h.close()
            root.removeHandler(h)
        return

    if root.handlers:
        return  # already configured

    log_dir.mkdir(parents=True, exist_ok=True)
    root.setLevel(level)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / _LOG_FILE,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger under the 'potatui' namespace."""
    return logging.getLogger(f"potatui.{name}")
