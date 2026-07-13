# 2026-07-13 (P0): Central logging setup — rotating file in the platform log directory plus any
# extra handlers a front end wants to attach (the UI's Log dock passes one in).
# Why: one configuration point that works identically headless (CLI/CI) and in the GUI.

from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Sequence
from pathlib import Path

import platformdirs

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured = False


def log_file_path() -> Path:
    return Path(platformdirs.user_log_dir("prospectra", appauthor=False)) / "prospectra.log"


def configure(extra_handlers: Sequence[logging.Handler] = ()) -> logging.Logger:
    """Configure the root logger once; subsequent calls only attach new extra handlers."""
    global _configured
    root = logging.getLogger()
    formatter = logging.Formatter(_FORMAT)
    if not _configured:
        root.setLevel(logging.INFO)
        log_path = log_file_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        _configured = True
    for handler in extra_handlers:
        if handler not in root.handlers:
            if handler.formatter is None:
                handler.setFormatter(formatter)
            root.addHandler(handler)
    return root
