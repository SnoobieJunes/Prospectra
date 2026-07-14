# 2026-07-13 (P1): Connector registry — maps file suffixes to built-in connectors and discovers
# third-party connectors via the `prospectra.connectors` entry-point group.
# Why: the plan's plugin mechanism. Built-ins are wired directly (no self-referential entry
# points); external packages just expose a Connector subclass and appear here automatically.

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from pathlib import Path

from prospectra.core.connectors.base import Connector
from prospectra.core.connectors.documents import (
    PDF_SUFFIXES,
    STAT_SUFFIXES,
    PDFTableConnector,
    StatFileConnector,
)
from prospectra.core.connectors.files import (
    _EXCEL_SUFFIXES,
    _READERS,
    ExcelConnector,
    TextFileConnector,
)

logger = logging.getLogger(__name__)

# 2026-07-14 (P6): PDF and the statistical formats join the file tier, completing T0 (their
# libraries are optional extras — the connector says what to install if one is missing).
SUPPORTED_FILE_SUFFIXES: tuple[str, ...] = (
    tuple(_READERS) + _EXCEL_SUFFIXES + PDF_SUFFIXES + STAT_SUFFIXES
)

ENTRY_POINT_GROUP = "prospectra.connectors"


class UnsupportedFileError(Exception):
    pass


def file_connector_for(path: Path | str) -> Connector:
    suffix = Path(path).suffix.lower()
    if suffix in _READERS:
        return TextFileConnector(path)
    if suffix in _EXCEL_SUFFIXES:
        return ExcelConnector(path)
    if suffix in PDF_SUFFIXES:
        return PDFTableConnector(path)
    if suffix in STAT_SUFFIXES:
        return StatFileConnector(path)
    raise UnsupportedFileError(
        f"Unsupported file type {suffix!r}. Supported: {', '.join(SUPPORTED_FILE_SUFFIXES)}"
    )


def external_connectors() -> dict[str, type[Connector]]:
    """Third-party connectors from installed packages; failures are logged, never fatal."""
    found: dict[str, type[Connector]] = {}
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
        except Exception:  # a broken plugin must not take the app down
            logger.warning("Could not load connector plugin %r", ep.name, exc_info=True)
            continue
        if isinstance(cls, type) and issubclass(cls, Connector):
            found[ep.name] = cls
        else:
            logger.warning("Connector plugin %r is not a Connector subclass; skipped", ep.name)
    return found
