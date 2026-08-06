# 2026-07-13 (P2): Flow execution — preview/profile any node, and run every Output node (COPY to
# CSV/Parquet). Each call opens a fresh in-memory DuckDB connection: flows read files directly,
# so runs are isolated, reproducible, and safe to fire from worker threads.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb

from prospectra.core.flow.compiler import compile_sql
from prospectra.core.flow.errors import FlowRunError
from prospectra.core.flow.graph import FlowGraph
from prospectra.core.flow.write import WriteReport
from prospectra.core.stats import TableProfile, profile_relation


@dataclass(frozen=True)
class PreviewResult:
    columns: list[tuple[str, str]]  # (name, dtype)
    rows: list[tuple[Any, ...]]
    total_rows: int


@dataclass(frozen=True)
class SelectPreview:
    """2026-07-31 (P7): a small ad-hoc SELECT over one node's output (the mapper's live pane)."""

    columns: list[str]
    rows: list[tuple[Any, ...]]


# 2026-07-31 (P7): every output now reports through WriteReport; the P2 name stays as an alias
# (`.path` and `.rows` keep cli.py's "wrote {path} ({rows} rows)" and its tests working verbatim).
OutputResult = WriteReport


class FlowRunner:
    # 2026-07-31 (P7): `columns()` results are cached per compiled-SQL string — keying on node_id
    # would go stale on ANY upstream edit, and the SQL string already IS the full recipe.
    def __init__(self) -> None:
        self._columns_cache: dict[str, list[tuple[str, str]]] = {}

    # 2026-08-05: the cache cannot notice a source file being rewritten on disk — the compiled SQL
    # is identical, so `columns()` kept serving the old schema for the life of the flow tab while
    # `preview()` showed the new one (the same tab disagreeing with itself). Callers that know
    # something changed clear it.
    def clear_caches(self) -> None:
        self._columns_cache.clear()

    @staticmethod
    def _prepare_notes(graph: FlowGraph, target: str) -> list[str]:
        """Confessions any ancestor recorded while materializing its external data."""
        notes: list[str] = []
        for node_id in graph.topo_order(target):
            notes.extend(getattr(graph.nodes[node_id].node, "prepare_notes", []))
        return notes

    # 2026-07-14 (P6): every node in the target's ancestry gets a chance to materialize external
    # data into this run's connection first (Node.prepare). File nodes ignore it; a Database input
    # uses it to pull its table in. Only then is the graph compiled and executed as one query.
    # 2026-07-31 (P7): `prepared` de-duplicates across targets — run() visits every output node,
    # and without the guard a shared ancestor (a live API fetch!) would prepare once PER OUTPUT.
    @staticmethod
    def _prepare(
        graph: FlowGraph,
        con: duckdb.DuckDBPyConnection,
        target: str | None = None,
        prepared: set[str] | None = None,
    ) -> None:
        for node_id in graph.topo_order(target):
            if prepared is not None:
                if node_id in prepared:
                    continue
                prepared.add(node_id)
            inst = graph.nodes[node_id]
            try:
                inst.node.prepare(con)
            except duckdb.Error as exc:
                raise FlowRunError(node_id, str(exc)) from exc
            except Exception as exc:  # a driver/network failure belongs to the node that caused it
                raise FlowRunError(node_id, str(exc)) from exc

    # 2026-07-31 (P7): the cheap schema call — DESCRIBE … LIMIT 0 (catalog.py's idiom), so the
    # mapper can know a node's columns without fetching a row. Cached on the compiled SQL string.
    # NOTE: prepare() still runs (a Database/API input must exist for DESCRIBE to bind), which is
    # why the cache matters — a hit skips the connection entirely.
    def columns(self, graph: FlowGraph, node_id: str) -> list[tuple[str, str]]:
        sql = compile_sql(graph, node_id)
        cached = self._columns_cache.get(sql)
        if cached is not None:
            return list(cached)
        con = duckdb.connect()
        try:
            self._prepare(graph, con, node_id)
            described = con.execute(f"DESCRIBE SELECT * FROM ({sql}) LIMIT 0").fetchall()
            columns = [(str(r[0]), str(r[1])) for r in described]
        except duckdb.Error as exc:
            raise FlowRunError(node_id, str(exc)) from exc
        finally:
            con.close()
        self._columns_cache[sql] = columns
        return list(columns)

    # 2026-07-31 (P7): the mapper's live before/after pane. `select_sql` reads the node's output
    # as a relation named `upstream` — e.g. SELECT upper("sku_raw") AS after FROM upstream.
    def preview_select(
        self, graph: FlowGraph, upstream_id: str, select_sql: str, limit: int = 20
    ) -> SelectPreview:
        sql = compile_sql(graph, upstream_id)
        con = duckdb.connect()
        try:
            self._prepare(graph, con, upstream_id)
            full = f"WITH upstream AS ({sql}) SELECT * FROM ({select_sql}) LIMIT {int(limit)}"
            cursor = con.execute(full)
            rows = cursor.fetchall()
            names = [str(d[0]) for d in cursor.description or []]
        except duckdb.Error as exc:
            raise FlowRunError(upstream_id, str(exc)) from exc
        finally:
            con.close()
        return SelectPreview(columns=names, rows=rows)

    def preview(self, graph: FlowGraph, node_id: str, limit: int = 500) -> PreviewResult:
        sql = compile_sql(graph, node_id)
        con = duckdb.connect()
        try:
            self._prepare(graph, con, node_id)
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
            self._prepare(graph, con, node_id)
            return profile_relation(con, f"({sql})", max_rows=max_rows)
        except duckdb.Error as exc:
            raise FlowRunError(node_id, str(exc)) from exc
        finally:
            con.close()

    # 2026-07-31 (P7): the write-back guards. `run()` used to hard-code COPY here; each output
    # node now owns its own `write()`. A `destructive` node (a live REST write) is refused UP
    # FRONT — before ANY output executes — unless `allow_writes=True`: "Run flow" must never
    # fire live PUTs at a production API by accident. `dry_run` rehearses every write.
    def run(
        self,
        graph: FlowGraph,
        *,
        only: list[str] | None = None,
        allow_writes: bool = False,
        dry_run: bool = False,
    ) -> list[OutputResult]:
        """Execute the Output nodes (all of them, or the `only` subset); one report each."""
        targets = list(only) if only is not None else graph.output_nodes()
        for node_id in targets:
            inst = graph.nodes.get(node_id)
            if inst is None:
                raise FlowRunError(node_id, "no such node")
            if inst.node.category != "output":
                raise FlowRunError(node_id, f"{inst.node.display_name} is not an output node")
            if inst.node.destructive and not allow_writes and not dry_run:
                raise FlowRunError(
                    node_id,
                    f"{inst.node.display_name} sends live writes to an external system. "
                    "Nothing was run. Pass allow_writes=True (CLI: --allow-writes) to mean it, "
                    "or dry_run=True to rehearse.",
                )
        results: list[OutputResult] = []
        con = duckdb.connect()
        prepared: set[str] = set()  # each ancestor prepares ONCE across outputs
        try:
            for node_id in targets:
                self._prepare(graph, con, node_id, prepared)
                inst = graph.nodes[node_id]
                sql = compile_sql(graph, node_id)
                try:
                    report = inst.node.write(con, sql, dry_run=dry_run)
                except FlowRunError:
                    raise
                except duckdb.Error as exc:
                    raise FlowRunError(node_id, str(exc)) from exc
                report.node_id = node_id
                # 2026-08-05: whatever the ancestry confessed during prepare() (a truncated or
                # deduplicated crosswalk, blank keys skipped) rides out on the report. Those notes
                # previously lived on the node and were read by nothing — a silent cap, which is
                # exactly what this project forbids.
                report.notes.extend(self._prepare_notes(graph, node_id))
                results.append(report)
        finally:
            con.close()
        return results
