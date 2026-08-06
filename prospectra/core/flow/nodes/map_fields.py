# 2026-07-31 (P7): The Map Fields node — a MappingDoc living inside a flow.
#
# The doc goes into params AS A DICT, never a JSON string: a string would double-encode, be
# unreadable in a project diff, and turn a malformed doc into a compile-time crash. And the
# ParamField default is None, NOT {}: `Node.__init__` builds params from the schema's defaults by
# reference (`{f.name: f.default ...}`), so a mutable default would be SHARED across every node
# instance in the process — two mapping nodes on one canvas would edit each other. `__init__`
# normalizes None to a fresh dict per instance.
#
# `prepare()` materializes file-backed crosswalks into the run's connection (the same escape
# hatch a Database input uses), so `compile()` stays a pure projection.

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import duckdb

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.mapping.compile import compile_notes, compile_select
from prospectra.core.mapping.doc import MappingDoc
from prospectra.core.mapping.transforms import crosswalk_table
from prospectra.core.sqlutil import ident, path_lit

MAX_XWALK_ROWS = 50_000  # a crosswalk beyond this truncates — and says so in prepare_notes


@register
class MapFieldsNode(Node):
    type_name = "map_fields"
    display_name = "Map Fields"
    category = "transform"
    params_schema: ClassVar = (
        ParamField(
            "doc",
            "Field mapping",
            "mapping_doc",  # rendered by the dedicated full-panel editor, keyed on this kind
            default=None,  # NEVER a dict here — see the module note on shared references
            help="Drag source columns onto target fields; open the mapper to edit.",
        ),
    )

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        super().__init__(params)
        if not isinstance(self.params.get("doc"), dict):
            self.params["doc"] = MappingDoc().to_dict()  # a fresh dict PER INSTANCE
        # What prepare() had to confess (truncated crosswalks, deduped keys, blank keys skipped).
        # FlowRunner.run copies these onto the WriteReport, so they reach the Flow tab's status
        # line and `run-flow`'s output; `prospectra map` prints them directly.
        self.prepare_notes: list[str] = []

    def doc(self) -> MappingDoc:
        return MappingDoc.from_dict(self.params["doc"])

    def validate(self) -> None:
        doc = self.doc()
        doc.validate()
        if not doc.fields:
            raise ValueError("map at least one field (open the mapper and drag a column)")

    def compile(self, inputs: list[str]) -> str:
        return compile_select(self.doc(), inputs[0])

    def prepare(self, con: duckdb.DuckDBPyConnection) -> None:
        """Materialize every file-backed crosswalk as xwalk_<sha1> in this run's connection."""
        self.prepare_notes = list(compile_notes(self.doc()))
        for field_map in self.doc().fields:
            for step in field_map.steps:
                if step.key != "lookup":
                    continue
                file_path = str(step.args.get("file") or "").strip()
                if not file_path:
                    continue
                self._materialize(con, field_map.target, file_path)

    def _materialize(self, con: duckdb.DuckDBPyConnection, target: str, file_path: str) -> None:
        path = Path(file_path)
        if not path.is_file():
            raise ValueError(f"{target}: crosswalk file not found: {path}")
        reader = f"read_csv_auto({path_lit(path)}, all_varchar=true)"
        described = con.execute(f"DESCRIBE SELECT * FROM {reader} LIMIT 0").fetchall()
        if len(described) < 2:
            raise ValueError(
                f"{target}: a crosswalk file needs two columns (from, to); "
                f"{path.name} has {len(described)}"
            )
        key_col, value_col = ident(str(described[0][0])), ident(str(described[1][0]))
        count_row = con.execute(f"SELECT count(*) FROM {reader}").fetchone()
        total = int(count_row[0]) if count_row else 0
        if total > MAX_XWALK_ROWS:
            self.prepare_notes.append(
                f"{target}: the crosswalk {path.name} has {total:,} rows; only the first "
                f"{MAX_XWALK_ROWS:,} are used"
            )
        # min() per key: a duplicated key would make map() throw mid-run; deterministic dedup
        # plus a confession beats either a crash or a silent arbitrary pick.
        table = crosswalk_table(file_path)
        con.execute(
            f"CREATE OR REPLACE TABLE {table} AS "
            f"SELECT {key_col} AS map_key, min({value_col}) AS map_value FROM "
            f"(SELECT * FROM {reader} LIMIT {MAX_XWALK_ROWS}) "
            f"WHERE {key_col} IS NOT NULL GROUP BY {key_col}"
        )
        # 2026-08-05: count the rows that actually reached the GROUP BY, not "everything we read".
        # Subtracting kept from the read count blamed blank-key rows (dropped by the WHERE) on
        # duplication, so a crosswalk with one empty key reported a duplicate that did not exist.
        usable_row = con.execute(
            f"SELECT count(*) FROM (SELECT * FROM {reader} LIMIT {MAX_XWALK_ROWS}) "
            f"WHERE {key_col} IS NOT NULL"
        ).fetchone()
        usable = int(usable_row[0]) if usable_row else 0
        blank = min(total, MAX_XWALK_ROWS) - usable
        kept_row = con.execute(f"SELECT count(*) FROM {table}").fetchone()
        kept = int(kept_row[0]) if kept_row else 0
        if blank > 0:
            self.prepare_notes.append(
                f"{target}: {blank} row(s) in {path.name} have no key and were skipped"
            )
        deduped = usable - kept
        if deduped > 0:
            self.prepare_notes.append(
                f"{target}: {deduped} duplicate key(s) in {path.name} — one value per key "
                "is kept (alphabetically first)"
            )
