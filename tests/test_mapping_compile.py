# 2026-07-31 (P7): The compiler, against the plan's worked example — a vendor feed into a PIM.
# The SQL is asserted EXACTLY (a compiler that drifts silently is a compiler nobody can trust in
# a saved document), then executed, because SQL that only looks right proves nothing.

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

EXPECTED_SQL = (
    "SELECT\n"
    '  TRY_CAST(substr(concat_ws(\' - \', "prod_nm", "colorway"), 1, 40) AS VARCHAR) '
    'AS "styleDescription",\n'
    '  TRY_CAST(upper(split_part("sku_raw", \'-\', 1)) AS VARCHAR) AS "styleCode",\n'
    '  CAST(NULL AS DECIMAL(18,4)) AS "retailPrice"\n'
    "FROM n0"
)


def worked_example() -> MappingDoc:
    return MappingDoc(
        name="vendor_feed_to_pim",
        source="vendor_csv",
        target="pim_products",
        target_columns=[
            TargetColumn("styleCode", "VARCHAR", required=True),
            TargetColumn("styleDescription", "VARCHAR", required=True),
            TargetColumn("retailPrice", "DECIMAL(18,4)"),
        ],
        fields=[
            FieldMap(
                target="styleDescription",
                sources=["prod_nm", "colorway"],
                join_with=" - ",
                steps=[Step("truncate", {"length": 40})],
                note="vendor splits name and colourway; PIM wants one 40-char line",
            ),
            FieldMap(
                target="styleCode",
                sources=["sku_raw"],
                steps=[Step("split_part", {"sep": "-", "index": 1}), Step("upper", {})],
                note="vendor SKU is STYLE-COLOR-SIZE; PIM wants the style segment",
            ),
        ],
        unmapped_policy="null",
    )


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE n0 AS SELECT * FROM (VALUES "
        "('Oxford Shirt', 'Navy', 'ab1234-NVY-M'), "
        "('Chore Coat', NULL, 'cc9-OLV-L')"
        ") t(prod_nm, colorway, sku_raw)"
    )
    yield connection
    connection.close()


def test_the_worked_example_compiles_to_the_exact_sql(con):
    sql = compile_select(worked_example(), "n0")
    assert sql == EXPECTED_SQL
    assert sql.count("WITH") == 0  # stays a projection; the flow compiler's single-CTE shape holds

    rows = con.execute(sql).fetchall()
    assert rows[0] == ("Oxford Shirt - Navy", "AB1234", None)


def test_a_null_colourway_does_not_erase_the_product(con):
    """concat_ws SKIPS NULLs; '||' would have nulled the whole description."""
    rows = con.execute(compile_select(worked_example(), "n0")).fetchall()
    assert rows[1][0] == "Chore Coat"  # not NULL, not "Chore Coat - "


def test_round_trip_through_the_document(con):
    doc = MappingDoc.from_dict(worked_example().to_dict())
    assert compile_select(doc, "n0") == EXPECTED_SQL
    with pytest.raises(ValueError, match="newer"):
        MappingDoc.from_dict({"mapping_doc_schema": 99})


# -- the three unmapped policies --------------------------------------------------------------


def test_policy_null_emits_typed_nulls(con):
    described = con.execute(f"DESCRIBE {compile_select(worked_example(), 'n0')}").fetchall()
    by_name = {str(r[0]): str(r[1]) for r in described}
    assert by_name["retailPrice"].startswith("DECIMAL")


def test_policy_drop_emits_nothing_for_unmapped(con):
    doc = worked_example()
    doc.unmapped_policy = "drop"
    described = con.execute(f"DESCRIBE {compile_select(doc, 'n0')}").fetchall()
    assert [str(r[0]) for r in described] == ["styleDescription", "styleCode"]


def test_policy_passthrough_carries_unconsumed_input_columns(con):
    doc = worked_example()
    doc.unmapped_policy = "passthrough"
    available = ["prod_nm", "colorway", "sku_raw", "vendor_note"]
    sql = compile_select(doc, "n0_plus", available=available)
    con.execute("CREATE TABLE n0_plus AS SELECT *, 'fragile' AS vendor_note FROM n0")
    described = con.execute(f"DESCRIBE {sql}").fetchall()
    names = [str(r[0]) for r in described]
    assert "vendor_note" in names  # unconsumed input columns survive
    assert names.count("styleCode") == 1  # and nothing is duplicated
    assert "prod_nm" not in names  # consumed sources do not ride along


def test_policy_passthrough_without_available_says_why_it_cannot(con):
    doc = worked_example()
    doc.unmapped_policy = "passthrough"
    with pytest.raises(ValueError, match="pass-through policy needs"):
        compile_select(doc, "n0")


# -- validation sentences ---------------------------------------------------------------------


def test_an_unmapped_required_target_is_named():
    doc = worked_example()
    doc.fields = [f for f in doc.fields if f.target != "styleCode"]
    with pytest.raises(ValueError, match="'styleCode' is required and nothing is mapped to it"):
        doc.validate()


def test_a_renamed_upstream_source_is_named_not_a_binder_error():
    message = "styleCode: source column\\(s\\) not in the input: sku_raw"
    with pytest.raises(ValueError, match=message):
        compile_select(worked_example(), "n0", available=["prod_nm", "colorway", "sku"])


def test_an_evil_target_type_is_refused():
    doc = worked_example()
    doc.target_columns[2] = TargetColumn("retailPrice", "DECIMAL(18,4)); DROP TABLE x; --")
    with pytest.raises(ValueError, match="unusable type"):
        doc.validate()


def test_two_mappings_to_one_target_are_refused():
    doc = worked_example()
    doc.fields.append(FieldMap(target="styleCode", sources=["prod_nm"]))
    with pytest.raises(ValueError, match="two mappings write to"):
        doc.validate()


def test_constant_fields_and_source_fields_are_mutually_exclusive():
    doc = worked_example()
    doc.fields[0].constant = "oops"
    with pytest.raises(ValueError, match="not both"):
        doc.validate()


# -- nothing is silent ------------------------------------------------------------------------


def test_coercion_check_counts_unreadable_prices(con):
    con.execute(
        "CREATE TABLE feed AS SELECT * FROM (VALUES "
        "('12.50'), ('n/a'), ('call for price'), ('99')"
        ") t(price_raw)"
    )
    doc = MappingDoc(
        name="prices",
        target_columns=[TargetColumn("retailPrice", "DECIMAL(18,4)")],
        fields=[
            FieldMap(
                target="retailPrice",
                sources=["price_raw"],
                steps=[Step("trim", {})],  # steps present -> the declared-type TRY_CAST applies
            )
        ],
    )
    check = coercion_check_sql(doc, "feed")
    row = con.execute(check).fetchone()
    assert row[0] == 2  # 'n/a' and 'call for price' went in readable, came out NULL — and we say so


def test_coercion_check_counts_crosswalk_misses(con):
    con.execute("CREATE TABLE feed2 AS SELECT * FROM (VALUES ('Navy'), ('Black'), ('Teal')) t(clr)")
    doc = MappingDoc(
        name="colours",
        target_columns=[TargetColumn("colorCode")],
        fields=[
            FieldMap(
                target="colorCode",
                sources=["clr"],
                steps=[Step("lookup", {"pairs": [["Navy", "NVY"], ["Black", "BLK"]]})],
            )
        ],
    )
    sql = coercion_check_sql(doc, "feed2")
    row = con.execute(sql).fetchone()
    names = [str(d[0]) for d in con.description or []]
    assert row[names.index("colorCode__unmatched")] == 1  # Teal had no translation — stated


def test_an_oversized_inline_crosswalk_confesses_its_truncation():
    pairs = [[f"v{i}", f"t{i}"] for i in range(60)]
    doc = MappingDoc(
        name="big",
        target_columns=[TargetColumn("c")],
        fields=[FieldMap(target="c", sources=["c1"], steps=[Step("lookup", {"pairs": pairs})])],
    )
    notes = compile_notes(doc)
    assert any("first 50 of 60" in note for note in notes)
