# 2026-07-13 (P2): Flow execution — preview/profile any node, and run every Output node (COPY to
# CSV/Parquet). Each call opens a fresh in-memory DuckDB connection: flows read files directly,
# so runs are isolated, reproducible, and safe to fire from worker threads.

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb

from prospectra.core.flow.compiler import compile_sql
from prospectra.core.flow.errors import FlowRunError
from prospectra.core.flow.graph import FlowGraph
from prospectra.core.sqlutil import path_lit
from prospectra.core.stats import TableProfile, profile_relation


@dataclass(frozen=True)
class PreviewResult:
    columns: list[tuple[str, str]]  # (name, dtype)
    rows: list[tuple[Any, ...]]
    total_rows: int


@dataclass(frozen=True)
class OutputResult:
    node_id: str
    path: str
    rows: int


class FlowRunner:
    def preview(self, graph: FlowGraph, node_id: str, limit: int = 500) -> PreviewResult:
        sql = compile_sql(graph, node_id)
        con = duckdb.connect()
        try:
            described = con.execute(f"DESCRIBE {sql}").fetchall()
            columns = [(str(r[0]), str(r[1])) for r in described]
            count_row = con.execute(f"SELECT count(*) FROM ({sql})").fetchone()
            total = int(count_row[0]) if count_row else 0
            rows = con.execute(f"SELECT * FROM ({sql}) LIMIT {int(limit)}").fetchall()
        except duckdb.Error as exc:
            raise FlowRunError(node_id, str(exc)) from exc
        finally:
            con.close()
        return PreviewResult(columns=columns, rows=rows, total_rows=total)

    def profile(self, graph: FlowGraph, node_id: str, max_rows: int = 50_000) -> TableProfile:
        sql = compile_sql(graph, node_id)
        con = duckdb.connect()
        try:
            return profile_relation(con, f"({sql})", max_rows=max_rows)
        except duckdb.Error as exc:
            raise FlowRunError(node_id, str(exc)) from exc
        finally:
            con.close()

    def run(self, graph: FlowGraph) -> list[OutputResult]:
        """Execute every Output node; returns one result per output."""
        results: list[OutputResult] = []
        con = duckdb.connect()
        try:
            for node_id in graph.output_nodes():
                inst = graph.nodes[node_id]
                out_path = Path(str(inst.node.params.get("path", "")).strip())
                fmt = str(inst.node.params.get("format", "csv")).lower()
                sql = compile_sql(graph, node_id)
                options = "FORMAT PARQUET" if fmt == "parquet" else "FORMAT CSV, HEADER"
                out_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    row = con.execute(
                        f"COPY ({sql}) TO {path_lit(out_path)} ({options})"
                    ).fetchone()
                    # DuckDB 1.5 quirk: COPY normally returns the number of rows written, but
                    # returns an EMPTY result when the query contains a PIVOT (the file is still
                    # written correctly). Read the count back off the written file in that case —
                    # cheaper and more honest than re-running the whole pipeline to count it.
                    written = int(row[0]) if row else self._count_file(con, out_path, fmt)
                except duckdb.Error as exc:
                    raise FlowRunError(node_id, str(exc)) from exc
                results.append(OutputResult(node_id=node_id, path=str(out_path), rows=written))
        finally:
            con.close()
        return results

    @staticmethod
    def _count_file(con: duckdb.DuckDBPyConnection, path: Path, fmt: str) -> int:
        reader = "read_parquet" if fmt == "parquet" else "read_csv_auto"
        row = con.execute(f"SELECT count(*) FROM {reader}({path_lit(path)})").fetchone()
        return int(row[0]) if row else 0
