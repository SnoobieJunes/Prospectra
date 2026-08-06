# 2026-08-05: Locks for the mapping defects an adversarial review found. Every test here failed
# against P7 as first written. The theme: the compiler was honest in the cases its own tests
# covered and quietly wrong just outside them.

from __future__ import annotations

import duckdb
import pytest

from prospectra.core.mapping import (
    FieldMap,
    MappingDoc,
    Step,
    TargetColumn,
    coercion_check_sql,
    compile_notes,
    compile_select,
)


@pytest.fixture
def con():
    connection = duckdb.connect()
    yield connection
    connection.close()


def _counts(con, sql):
    row = con.execute(sql).fetchone()
    names = [str(d[0]) for d in con.description or []]
    return dict(zip(names, row, strict=True))


# -- case collisions ---------------------------------------------------------------------------


def test_a_passthrough_column_cannot_shadow_a_mapped_target_by_case(con):
    """SQL identifiers are case-insensitive; Python sets are not. `SKU` passed through beside a
    mapped `sku`, and a downstream read of `sku` got the passthrough value."""
    con.execute("CREATE TABLE feed AS SELECT * FROM (VALUES ('foo','red')) t(\"SKU\",\"Colour\")")
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("sku")],
        fields=[FieldMap(target="sku", sources=["Colour"])],
        unmapped_policy="passthrough",
    )
    sql = compile_select(doc, "feed", available=["SKU", "Colour"])
    assert con.execute(f"SELECT sku FROM ({sql})").fetchall() == [("red",)]


def test_two_targets_differing_only_in_case_are_refused():
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("SKU"), TargetColumn("sku")],
        fields=[FieldMap(target="SKU", sources=["a"])],
    )
    with pytest.raises(ValueError, match="case-insensitive"):
        doc.validate()


def test_a_source_column_matches_case_insensitively(con):
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("out")],
        fields=[FieldMap(target="out", sources=["Colour"])],
    )
    compile_select(doc, "feed", available=["colour"])  # must not raise


# -- the declared type is a contract -----------------------------------------------------------


def test_a_declared_type_is_applied_even_to_an_untouched_single_source(con):
    con.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('7'),('x')) v(qty_raw)")
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("qty", "BIGINT")],
        fields=[FieldMap(target="qty", sources=["qty_raw"])],
    )
    sql = compile_select(doc, "t")
    dtype = con.execute(f"DESCRIBE {sql}").fetchall()[0][1]
    assert str(dtype).upper().startswith("BIGINT")  # was silently VARCHAR
    assert _counts(con, coercion_check_sql(doc, "t"))["qty__lost"] == 1  # and the loss is stated


# -- the counters tell the truth ---------------------------------------------------------------


def test_a_default_after_a_cast_does_not_hide_the_losses(con):
    """coalesce guarantees non-NULL, so an end-of-chain check reported zero losses."""
    con.execute(
        "CREATE TABLE p AS SELECT * FROM (VALUES ('12.5'),('abc'),('nope'),('3')) v(price_raw)"
    )
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("price", "DOUBLE")],
        fields=[
            FieldMap(
                target="price",
                sources=["price_raw"],
                steps=[Step("cast", {"type": "DOUBLE"}), Step("default", {"value": "0"})],
            )
        ],
    )
    counts = _counts(con, coercion_check_sql(doc, "p"))
    assert counts["price__lost_cast"] == 2  # 'abc' and 'nope' were replaced, and we say so


def test_an_all_null_multi_source_row_is_not_reported_as_unreadable(con):
    """concat_ws returns '' (not NULL) for all-NULL sources, so empty rows looked like losses."""
    con.execute("CREATE TABLE m AS SELECT * FROM (VALUES ('1','2'),(NULL,NULL),(NULL,NULL)) v(a,b)")
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("n", "BIGINT")],
        fields=[FieldMap(target="n", sources=["a", "b"], join_with="")],
    )
    assert _counts(con, coercion_check_sql(doc, "m"))["n__lost"] == 0


def test_two_lookups_on_one_field_get_distinct_counter_names(con):
    con.execute("CREATE TABLE c AS SELECT * FROM (VALUES ('red')) v(clr)")
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("out")],
        fields=[
            FieldMap(
                target="out",
                sources=["clr"],
                steps=[
                    Step("lookup", {"pairs": [["red", "R"]]}),
                    Step("lookup", {"pairs": [["R", "RED"]]}),
                ],
            )
        ],
    )
    names = list(_counts(con, coercion_check_sql(doc, "c")))
    assert names.count("out__unmatched") == 1 and "out__unmatched_2" in names


# -- crosswalk robustness ----------------------------------------------------------------------


def test_duplicate_inline_crosswalk_keys_do_not_crash_the_run(con):
    con.execute("CREATE TABLE c2 AS SELECT * FROM (VALUES ('red'),('blue')) v(clr)")
    doc = MappingDoc(
        name="m",
        target_columns=[TargetColumn("out")],
        fields=[
            FieldMap(
                target="out",
                sources=["clr"],
                steps=[Step("lookup", {"pairs": [["red", "R"], ["red", "RR"], ["blue", "B"]]})],
            )
        ],
    )
    sql = compile_select(doc, "c2")
    assert con.execute(sql).fetchall() == [("R",), ("B",)]  # first translation wins, no crash
    assert any("repeated key" in note for note in compile_notes(doc))


def test_raw_numeric_crosswalk_keys_do_not_reach_str_lit_uncoerced(con):
    """coercion_check_sql passed RAW args to lookup_probe — the one caller outside the boundary."""
    con.execute("CREATE TABLE c3 AS SELECT * FROM (VALUES ('100')) v(code)")
    doc = MappingDoc.from_dict(
        {
            "mapping_doc_schema": 1,
            "name": "m",
            "target_columns": [{"name": "out"}],
            "fields": [
                {
                    "target": "out",
                    "sources": ["code"],
                    "steps": [{"key": "lookup", "args": {"pairs": [[100, "A"]]}}],
                }
            ],
        }
    )
    counts = _counts(con, coercion_check_sql(doc, "c3"))  # used to raise AttributeError
    assert counts["out__unmatched"] == 0


# -- empty documents ---------------------------------------------------------------------------


def test_a_mapping_with_no_fields_is_refused_with_a_sentence():
    doc = MappingDoc(name="m", target_columns=[TargetColumn("out")])
    with pytest.raises(ValueError, match="no fields"):
        compile_select(doc, "t")


# -- crosswalk file accounting -----------------------------------------------------------------


def test_a_blank_key_row_is_reported_as_skipped_not_as_a_duplicate(tmp_path):
    from prospectra.core.flow.nodes.map_fields import MapFieldsNode

    xwalk = tmp_path / "x.csv"
    xwalk.write_text("from,to\nred,R\n,ORPHAN\nblue,B\n", encoding="utf-8")
    node = MapFieldsNode(
        {
            "doc": MappingDoc(
                name="m",
                target_columns=[TargetColumn("out")],
                fields=[
                    FieldMap(
                        target="out",
                        sources=["clr"],
                        steps=[Step("lookup", {"pairs": [], "file": str(xwalk)})],
                    )
                ],
            ).to_dict()
        }
    )
    connection = duckdb.connect()
    try:
        node.prepare(connection)
    finally:
        connection.close()
    assert any("no key and were skipped" in note for note in node.prepare_notes)
    assert not any("duplicate key" in note for note in node.prepare_notes)
