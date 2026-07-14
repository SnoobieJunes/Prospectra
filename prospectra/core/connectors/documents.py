# 2026-07-14 (P6): The rest of the T0 file tier — PDF tables and the statistical formats
# (SPSS .sav, Stata .dta, SAS .sas7bdat/.xpt). Deferred from P1 (see Deviations.md) because both
# need extra dependencies and their own extraction behaviour; this closes that entry.
#
# Both are optional extras, so a default install stays light and a missing extra produces a
# sentence telling you what to run — never an ImportError traceback:
#   uv sync --extra pdf            (pdfplumber)
#   uv sync --extra stats-files    (pyreadstat)
#
# PDF honesty: a PDF has no schema. `pdfplumber` finds table-shaped things, and the first row is
# *assumed* to be a header — that assumption is right most of the time and wrong often enough that
# the profiler will show it. Each table on each page becomes its own dataset, named by page.

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, ClassVar

import duckdb

from prospectra.core.connectors.base import Connector, ConnectorError, DatasetRef

logger = logging.getLogger(__name__)

PDF_SUFFIXES = (".pdf",)
STAT_SUFFIXES = (".sav", ".zsav", ".por", ".dta", ".sas7bdat", ".xpt")

MIN_PDF_ROWS = 2  # a one-row "table" in a PDF is a caption or a form field, not data


def _register(cursor: duckdb.DuckDBPyConnection, frame: object, view_name: str) -> None:
    cursor.register("_prospectra_tmp_doc", frame)
    try:
        cursor.execute(f"CREATE OR REPLACE TABLE {view_name} AS SELECT * FROM _prospectra_tmp_doc")
    finally:
        cursor.unregister("_prospectra_tmp_doc")


class PDFTableConnector(Connector):
    """Tables inside a PDF. Each table on each page is a dataset."""

    type_name = "pdf"
    display_name = "PDF tables"
    status: ClassVar = "experimental"  # extraction quality depends entirely on the PDF

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.suffix.lower() not in PDF_SUFFIXES:
            raise ConnectorError(f"Not a PDF: {self.path.name}")
        if not self.path.is_file():
            raise ConnectorError(f"No such file: {self.path}")

    def _open(self) -> Any:  # pdfplumber.PDF — an optional dependency, so it stays untyped here
        try:
            import pdfplumber
        except ImportError as exc:
            raise ConnectorError(
                "Reading PDF tables needs the optional extra:  uv sync --extra pdf"
            ) from exc
        try:
            return pdfplumber.open(str(self.path))
        except Exception as exc:
            raise ConnectorError(f"Could not open {self.path.name}: {exc}") from exc

    def list_datasets(self) -> list[DatasetRef]:
        refs: list[DatasetRef] = []
        with self._open() as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                for table_number, table in enumerate(page.extract_tables(), start=1):
                    if len(table) < MIN_PDF_ROWS or not table[0]:
                        continue
                    refs.append(
                        DatasetRef(
                            name=f"page{page_number}_table{table_number}",
                            kind="table",
                            detail={"page": page_number, "table": table_number},
                        )
                    )
        if not refs:
            raise ConnectorError(
                f"No tables found in {self.path.name}. A scanned PDF holds pictures of tables, "
                "not tables — those need OCR, which Prospectra does not do."
            )
        return refs

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        import pandas as pd

        page_number = int(ref.detail.get("page", 1))
        table_number = int(ref.detail.get("table", 1))
        with self._open() as pdf:
            tables = pdf.pages[page_number - 1].extract_tables()
            if not 0 < table_number <= len(tables):
                raise ConnectorError(f"{ref.name} is no longer in {self.path.name}")
            rows = tables[table_number - 1]

        header = [
            (str(cell).strip() if cell else f"column_{i + 1}") for i, cell in enumerate(rows[0])
        ]
        seen: dict[str, int] = {}
        columns: list[str] = []
        for name in header:  # PDF headers repeat and collide; they become SQL identifiers
            count = seen.get(name, 0)
            seen[name] = count + 1
            columns.append(name if count == 0 else f"{name}_{count + 1}")
        frame = pd.DataFrame(rows[1:], columns=columns)
        _register(cursor, frame, view_name)


class StatFileConnector(Connector):
    """SPSS / Stata / SAS files — read with their value labels applied."""

    type_name = "statfile"
    display_name = "SPSS / Stata / SAS file"
    status: ClassVar = "experimental"  # not exercised against real-world files from vendors

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.suffix.lower() not in STAT_SUFFIXES:
            raise ConnectorError(f"Not an SPSS/Stata/SAS file: {self.path.name}")
        if not self.path.is_file():
            raise ConnectorError(f"No such file: {self.path}")

    def list_datasets(self) -> list[DatasetRef]:
        return [DatasetRef(name=self.path.stem, kind="file")]

    def install(self, cursor: duckdb.DuckDBPyConnection, ref: DatasetRef, view_name: str) -> None:
        try:
            import pyreadstat
        except ImportError as exc:
            raise ConnectorError(
                "Reading SPSS/Stata/SAS files needs the optional extra:  "
                "uv sync --extra stats-files"
            ) from exc

        readers = {
            ".sav": pyreadstat.read_sav,
            ".zsav": pyreadstat.read_sav,
            ".por": pyreadstat.read_por,
            ".dta": pyreadstat.read_dta,
            ".sas7bdat": pyreadstat.read_sas7bdat,
            ".xpt": pyreadstat.read_xport,
        }
        reader = readers[self.path.suffix.lower()]
        try:
            # apply_value_formats: an SPSS file stores 1/2 with labels "Male"/"Female"; the labels
            # are the data a human meant, and the miner classifies them correctly as categories.
            frame, _meta = reader(str(self.path), apply_value_formats=True)
        except TypeError:  # read_sas7bdat/read_xport take no apply_value_formats
            frame, _meta = reader(str(self.path))
        except Exception as exc:
            raise ConnectorError(f"Could not read {self.path.name}: {exc}") from exc
        _register(cursor, frame, view_name)
