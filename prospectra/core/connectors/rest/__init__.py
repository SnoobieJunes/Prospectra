# 2026-07-14 (P6): REST/OData tier — a saved mapping (auth + pagination + paths→columns) turns any
# JSON endpoint into an ordinary table. This is the plan's T3 escape hatch: the long tail of APIs
# without one line of bespoke code per vendor.

from prospectra.core.connectors.rest.client import FetchReport, RestClient
from prospectra.core.connectors.rest.connector import RestConnector
from prospectra.core.connectors.rest.flatten import (
    infer_columns,
    infer_mapping_fields,
    infer_records_path,
    records_to_frame,
)
from prospectra.core.connectors.rest.mapping import (
    AUTH_KINDS,
    PAGINATION_KINDS,
    Auth,
    Column,
    Pagination,
    RestMapping,
)

__all__ = [
    "AUTH_KINDS",
    "PAGINATION_KINDS",
    "Auth",
    "Column",
    "FetchReport",
    "Pagination",
    "RestClient",
    "RestConnector",
    "RestMapping",
    "infer_columns",
    "infer_mapping_fields",
    "infer_records_path",
    "records_to_frame",
]
