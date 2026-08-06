# 2026-07-31 (P7): Injection locks for the mapping compiler.
#
# These exist because the P7 review found a real hole: `_TYPE_PATTERN` guarded only
# `MappingDoc.validate()`, but `field_exprs` and `coercion_check_sql` reach `_folded_expr`
# WITHOUT calling validate() — and the mapper's "Preview values" button uses `field_exprs`.
# A `TargetColumn.type` carrying `VARCHAR) AS x FROM t); COPY (...) TO '/tmp/x'; --` therefore
# executed arbitrary statements (DuckDB's execute() runs `;`-separated statements) the moment a
# user opened a SHARED project and previewed a field. The plan warned about exactly this
# ("cast is choice-constrained … do not copy select.py's unvalidated type interpolation").
#
# Every compile entry point must now refuse a malformed declared type, so the guard cannot be
# bypassed by reaching the compiler through a different door.

from __future__ import annotations

from pathlib import Path

import pytest

from prospectra.core.mapping import MappingDoc, coercion_check_sql, compile_select
from prospectra.core.mapping.compile import field_exprs

EVIL_TYPE = "VARCHAR) AS after FROM upstream); COPY (SELECT 'pwned' AS x) TO '{path}'; --"


def evil_doc(path: Path) -> MappingDoc:
    """A mapping document as it would arrive inside a shared/downloaded .prospectra project."""
    return MappingDoc.from_dict(
        {
            "mapping_doc_schema": 1,
            "name": "m",
            "target_columns": [{"name": "out", "type": EVIL_TYPE.format(path=path.as_posix())}],
            # a step is what makes _folded_expr emit the TRY_CAST that carries the type into SQL
            "fields": [{"target": "out", "sources": ["a"], "steps": [{"key": "trim", "args": {}}]}],
        }
    )


@pytest.mark.parametrize(
    "entry_point",
    [
        pytest.param(lambda doc: compile_select(doc, "upstream"), id="compile_select"),
        pytest.param(lambda doc: field_exprs(doc, "out"), id="field_exprs"),
        pytest.param(lambda doc: coercion_check_sql(doc, "upstream"), id="coercion_check_sql"),
    ],
)
def test_no_compile_entry_point_accepts_an_unusable_declared_type(tmp_path, entry_point):
    victim = tmp_path / "pwned.csv"
    doc = evil_doc(victim)
    with pytest.raises(ValueError, match="unusable type"):
        entry_point(doc)
    assert not victim.exists()


def test_the_preview_path_cannot_execute_a_planted_type(tmp_path):
    """The full user-facing path: shared project -> Open Mapper -> Preview values."""
    from prospectra.core.flow import FlowGraph, FlowRunner

    source = tmp_path / "src.csv"
    source.write_text("a\nx\n", encoding="utf-8")
    victim = tmp_path / "pwned.csv"
    doc = evil_doc(victim)

    graph = FlowGraph()
    node_id = graph.add_node("input_file", {"path": str(source)})
    with pytest.raises(ValueError, match="unusable type"):
        base, final = field_exprs(doc, "out")
        FlowRunner().preview_select(
            graph, node_id, f"SELECT {base} AS before, {final} AS after FROM upstream"
        )
    assert not victim.exists()


def test_a_legitimate_declared_type_still_compiles(tmp_path):
    doc = MappingDoc.from_dict(
        {
            "mapping_doc_schema": 1,
            "name": "m",
            "target_columns": [{"name": "price", "type": "DECIMAL(18,4)"}],
            "fields": [
                {"target": "price", "sources": ["a"], "steps": [{"key": "trim", "args": {}}]}
            ],
        }
    )
    assert "DECIMAL(18,4)" in compile_select(doc, "upstream")
    assert "DECIMAL(18,4)" in field_exprs(doc, "price")[1]
    assert coercion_check_sql(doc, "upstream") != ""
