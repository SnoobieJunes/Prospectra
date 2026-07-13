# 2026-07-13 (P1): File connectors — the T0 tier. Text-ish formats (CSV/TSV/JSON/Parquet) become
# DuckDB *views* over the file (zero-copy, re-read per query); Excel-family files are read via
# pandas+calamine and materialized as *tables* (DataFrames are per-cursor, tables are shared).
# Deferred from T0 to a later phase: PDF tables, SPSS/Stata/SAS (see Deviations.md).

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import duckdb

from prospectra.core.connectors.base import Connector, ConnectorError, DatasetRef
from prospectra.core.sqlutil import path_lit

# suffix -> DuckDB table function
_READERS: dict[str, str] = {
    ".csv": "read_csv_auto",
    ".tsv": "read_csv_auto",
    ".txt": "read_csv_auto",
    ".json": "read_json_auto",
    ".jsonl": "read_json_auto",
    ".ndjson": "read_json_auto",
    ".parquet": "read_parquet",
}

_EXCEL_SUFFIXES = (".xlsx", ".xlsm", ".xls", ".ods")


class TextFileConnector(Connector):
    """CSV/TSV/text/JSON/Parquet files via DuckDB's native readers."""

    type_name = "file"
    display_name = "Data file"
    status: ClassVar = "verified"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.suffix.lower() not in _READERS:
            raise ConnectorError(f"Unsupported file type: {self.path.name}")
        if not self.path.is_file():
            raise ConnectorError(f"No such file: {self.path}")

    def list_datasets(self) -> list[DatasetRef]:
        return [DatasetRef(name=self.path.stem, kind="file")]

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        reader = _READERS[self.path.suffix.lower()]
        cursor.execute(
            f"CREATE OR REPLACE VIEW {view_name} AS SELECT * FROM {reader}({path_lit(self.path)})"
        )


class ExcelConnector(Connector):
    """xlsx/xlsm/xls/ods workbooks; each sheet is a dataset."""

    type_name = "excel"
    display_name = "Excel workbook"
    status: ClassVar = "verified"

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.suffix.lower() not in _EXCEL_SUFFIXES:
            raise ConnectorError(f"Not an Excel-family file: {self.path.name}")
        if not self.path.is_file():
            raise ConnectorError(f"No such file: {self.path}")

    def list_datasets(self) -> list[DatasetRef]:
        from python_calamine import CalamineWorkbook  # deferred: import cost only when used

        try:
            sheets = CalamineWorkbook.from_path(str(self.path)).sheet_names
        except Exception as exc:  # calamine raises library-specific errors
            raise ConnectorError(f"Could not read workbook {self.path.name}: {exc}") from exc
        return [DatasetRef(name=s, kind="sheet") for s in sheets]

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        import pandas as pd

        try:
            frame = pd.read_excel(self.path, sheet_name=ref.name, engine="calamine")
        except Exception as exc:
            raise ConnectorError(
                f"Could not read sheet {ref.name!r} of {self.path.name}: {exc}"
            ) from exc
        cursor.register("_prospectra_tmp_frame", frame)
        try:
            cursor.execute(
                f"CREATE OR REPLACE TABLE {view_name} AS SELECT * FROM _prospectra_tmp_frame"
            )
        finally:
            cursor.unregister("_prospectra_tmp_frame")
