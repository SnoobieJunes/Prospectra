# 2026-07-14 (P5): The viz layer — charts described as serializable specs, queried in DuckDB, and
# grouped into dashboards that live in the project file. No Qt here: the renderer is the UI's job.

from prospectra.core.viz.dashboard import COLUMNS, Dashboard, Tile
from prospectra.core.viz.export import data_to_csv
from prospectra.core.viz.query import ChartData, build_sql, fetch_chart_data
from prospectra.core.viz.spec import (
    AGGREGATIONS,
    MARKS,
    SCALES,
    ChartSpec,
)

__all__ = [
    "AGGREGATIONS",
    "COLUMNS",
    "MARKS",
    "SCALES",
    "ChartData",
    "ChartSpec",
    "Dashboard",
    "Tile",
    "build_sql",
    "data_to_csv",
    "fetch_chart_data",
]
