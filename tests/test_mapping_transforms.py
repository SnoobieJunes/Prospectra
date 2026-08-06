# 2026-07-31 (P7): The transform vocabulary. Two things are load-bearing here:
#   1. every `build` EXECUTES in a real DuckDB — a transform that only renders plausible SQL is
#      a transform that fails at preview time in front of a non-technical user;
#   2. `coerce_args` is the injection boundary — "40; DROP TABLE" must die at coercion with a
#      readable message, never reach an f-string.
# The DuckDB edge semantics called out in the plan are asserted explicitly, so an engine upgrade
# that changes them fails loudly.

from __future__ import annotations

import duckdb
import pytest

from prospectra.core.mapping.transforms import (
    CAST_TYPES,
    TRANSFORMS,
    TRANSFORMS_BY_KEY,
    build_step,
    coerce_args,
)

# Args that make every transform buildable (defaults suffice for the rest).
_SAMPLE_ARGS: dict[str, dict] = {
    "lookup": {"pairs": [["Navy", "NVY"], ["Black", "BLK"]]},
    "expression": {"sql": "upper({value})"},
}


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect()
    yield connection
    connection.close()


@pytest.mark.parametrize("transform", TRANSFORMS, ids=lambda t: t.key)
def test_every_build_executes_in_duckdb(con, transform):
    args = _SAMPLE_ARGS.get(transform.key, {})
    expr = build_step(transform.key, args, "'Oxford Shirt - Navy'")
    row = con.execute(f"SELECT {expr}").fetchone()
    assert row is not None  # it ran; the value depends on the transform


def test_the_worked_transforms_produce_the_expected_values(con):
    cases = [
        ("trim", {}, "'  x  '", "x"),
        ("upper", {}, "'ab'", "AB"),
        ("title", {}, "'oxford SHIRT'", "Oxford Shirt"),
        ("truncate", {"length": 4}, "'longtext'", "long"),
        ("prepend", {"text": "S-"}, "'1'", "S-1"),
        ("append", {"text": "-M"}, "'1'", "1-M"),
        ("replace", {"find": "-", "with": "_"}, "'a-b'", "a_b"),
        ("split_part", {"sep": "-", "index": 1}, "'AB1234-NVY-M'", "AB1234"),
        ("regex_extract", {"pattern": "(\\d+)", "group": 1}, "'ab123'", "123"),
        ("regex_replace", {"pattern": "\\d", "with": "#"}, "'a1b2'", "a#b#"),
        ("pad", {"length": 5, "char": "0", "side": "left"}, "'42'", "00042"),
        ("default", {"value": "n/a"}, "NULL", "n/a"),
        ("lookup", {"pairs": [["Navy", "NVY"]]}, "'Navy'", "NVY"),
        ("date_format", {"format": "%d.%m.%Y"}, "'2024-01-31'", "31.01.2024"),
    ]
    for key, args, literal, expected in cases:
        expr = build_step(key, args, literal)
        assert con.execute(f"SELECT {expr}").fetchone()[0] == expected, key


def test_lookup_miss_keeps_the_original_value_and_a_prepend_of_null_stays_null(con):
    miss = build_step("lookup", {"pairs": [["Navy", "NVY"]]}, "'Teal'")
    assert con.execute(f"SELECT {miss}").fetchone()[0] == "Teal"  # a miss never blanks a value
    null_prepend = build_step("prepend", {"text": "S-"}, "NULL")
    assert con.execute(f"SELECT {null_prepend}").fetchone()[0] is None  # || propagates NULL


# -- the injection boundary ------------------------------------------------------------------


def test_a_sql_payload_in_an_int_arg_dies_at_coercion():
    with pytest.raises(ValueError, match="whole number"):
        coerce_args(TRANSFORMS_BY_KEY["truncate"], {"length": "40; DROP TABLE users"})


def test_cast_rejects_a_type_outside_the_closed_list():
    with pytest.raises(ValueError, match="must be one of"):
        coerce_args(TRANSFORMS_BY_KEY["cast"], {"type": "VARCHAR); DROP TABLE users; --"})
    assert "VARCHAR" in CAST_TYPES  # the closed list itself stays usable


def test_an_unknown_arg_name_is_rejected_not_ignored():
    with pytest.raises(ValueError, match="unknown argument"):
        coerce_args(TRANSFORMS_BY_KEY["trim"], {"lenght": 4})


def test_split_part_index_must_be_at_least_one():
    with pytest.raises(ValueError, match="≥ 1"):
        coerce_args(TRANSFORMS_BY_KEY["split_part"], {"sep": "-", "index": 0})


def test_a_quote_in_a_string_arg_is_escaped_not_executed(con):
    expr = build_step("append", {"text": "'; DROP TABLE users; --"}, "'x'")
    value = con.execute(f"SELECT {expr}").fetchone()[0]
    assert value == "x'; DROP TABLE users; --"  # the payload is DATA, not SQL


def test_an_empty_lookup_is_refused_with_a_fixable_message():
    with pytest.raises(ValueError, match="at least one pair"):
        build_step("lookup", {"pairs": []}, "'x'")


def test_the_expression_hatch_is_marked_advanced_and_requires_the_placeholder():
    assert TRANSFORMS_BY_KEY["expression"].status == "advanced"
    with pytest.raises(ValueError, match=r"\{value\}"):
        build_step("expression", {"sql": "upper(name)"}, "'x'")


# -- DuckDB edge semantics the plan warned about (locked so an upgrade fails loudly) ----------


def test_duckdb_edge_semantics_are_what_the_compiler_assumes(con):
    assert con.execute("SELECT concat_ws(' - ', NULL, NULL)").fetchone()[0] == ""  # not NULL!
    assert con.execute("SELECT regexp_extract('abc', '(x)', 1)").fetchone()[0] == ""
    assert con.execute("SELECT split_part('a-b', '-', 9)").fetchone()[0] == ""
