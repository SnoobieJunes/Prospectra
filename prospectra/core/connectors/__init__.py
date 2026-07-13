# 2026-07-13 (P1): Connector layer — everything that turns an external source into a DuckDB
# view/table lives here. Public surface re-exported for convenience.
from prospectra.core.connectors.base import Connector, ConnectorError, DatasetRef
from prospectra.core.connectors.registry import (
    SUPPORTED_FILE_SUFFIXES,
    UnsupportedFileError,
    file_connector_for,
)

__all__ = [
    "SUPPORTED_FILE_SUFFIXES",
    "Connector",
    "ConnectorError",
    "DatasetRef",
    "UnsupportedFileError",
    "file_connector_for",
]
