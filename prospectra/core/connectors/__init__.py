# 2026-07-14 (P6): dialect descriptors, the REST mapping tier, JDBC, and the document/stat file
# connectors join the public surface.
# 2026-07-13 (P1): Connector layer — everything that turns an external source into a DuckDB
# view/table lives here. Public surface re-exported for convenience.
from prospectra.core.connectors.base import (
    Connector,
    ConnectorError,
    ConnectorStatus,
    DatasetRef,
)
from prospectra.core.connectors.dialects import (
    DIALECTS,
    DIALECTS_BY_KEY,
    Dialect,
    Field,
    dialect_for_url,
)
from prospectra.core.connectors.documents import PDFTableConnector, StatFileConnector
from prospectra.core.connectors.jdbc import JDBCConnector, jdbc_available
from prospectra.core.connectors.registry import (
    SUPPORTED_FILE_SUFFIXES,
    UnsupportedFileError,
    external_connectors,
    file_connector_for,
)
from prospectra.core.connectors.rest import RestConnector, RestMapping

__all__ = [
    "DIALECTS",
    "DIALECTS_BY_KEY",
    "SUPPORTED_FILE_SUFFIXES",
    "Connector",
    "ConnectorError",
    "ConnectorStatus",
    "DatasetRef",
    "Dialect",
    "Field",
    "JDBCConnector",
    "PDFTableConnector",
    "RestConnector",
    "RestMapping",
    "StatFileConnector",
    "UnsupportedFileError",
    "dialect_for_url",
    "external_connectors",
    "file_connector_for",
    "jdbc_available",
]
