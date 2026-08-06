# 2026-07-31 (P7): Match suggestions. The two named acceptance cases from the plan:
#   * `prod_nm` -> `productName` must clear the bar — the case difflib ALONE fails, which is why
#     token splitting + abbreviation expansion carries half the weight;
#   * `suggest_from_values` must match `c1` -> `colour_code` when the names share nothing,
#     because the values do. Names lie; values don't.

from __future__ import annotations

from difflib import SequenceMatcher

import duckdb
import pytest

from prospectra.core.mapping import suggest_from_values, suggest_matches


def test_prod_nm_matches_product_name_where_difflib_alone_fails():
    raw_difflib = SequenceMatcher(None, "prod_nm", "productname").ratio()
    assert raw_difflib < 0.75  # the reason the blend exists

    suggestions = suggest_matches(
        [("prod_nm", "VARCHAR"), ("retail_px", "DOUBLE")],
        [("productName", "VARCHAR"), ("retailPrice", "DOUBLE")],
    )
    by_target = {s.target: s for s in suggestions}
    assert by_target["productName"].source == "prod_nm"
    assert by_target["productName"].confidence >= 0.45
    assert "name" in by_target["productName"].reason


def test_abbreviations_carry_the_match_and_the_reason_says_why():
    suggestions = suggest_matches([("qty", "BIGINT")], [("quantity", "BIGINT")])
    assert suggestions and suggestions[0].source == "qty"
    assert "quantity" in suggestions[0].reason


def test_a_dtype_clash_costs_confidence():
    same = suggest_matches([("price", "DOUBLE")], [("price", "DOUBLE")], min_confidence=0.0)
    clash = suggest_matches([("price", "DOUBLE")], [("price", "VARCHAR")], min_confidence=0.0)
    assert same[0].confidence > clash[0].confidence


def test_nothing_clears_an_impossible_bar():
    assert suggest_matches([("a", "VARCHAR")], [("zzz", "VARCHAR")]) == []


def test_suggestions_come_sorted_by_confidence():
    suggestions = suggest_matches(
        [("product_name", "VARCHAR"), ("clr", "VARCHAR")],
        [("productName", "VARCHAR"), ("color", "VARCHAR")],
        min_confidence=0.2,
    )
    confidences = [s.confidence for s in suggestions]
    assert confidences == sorted(confidences, reverse=True)


# -- value-based -------------------------------------------------------------------------------


@pytest.fixture
def con():
    connection = duckdb.connect()
    connection.execute(
        "CREATE TABLE vendor AS SELECT * FROM (VALUES ('NVY'), ('BLK'), ('WHT'), ('OLV')) t(c1)"
    )
    connection.execute(
        "CREATE TABLE pim AS SELECT * FROM (VALUES "
        "('nvy'), ('blk'), ('wht'), ('red')) t(colour_code)"
    )
    yield connection
    connection.close()


def test_values_match_c1_to_colour_code_when_names_share_nothing(con):
    assert suggest_matches([("c1", "VARCHAR")], [("colour_code", "VARCHAR")]) == []  # names fail

    suggestions = suggest_from_values(con, "vendor", "pim", [("c1", "colour_code")])
    assert len(suggestions) == 1
    assert suggestions[0].confidence == 0.75  # 3 of min(4, 4) sampled values overlap
    assert "overlap" in suggestions[0].reason


def test_disjoint_values_yield_no_suggestion(con):
    con.execute("CREATE TABLE other AS SELECT * FROM (VALUES ('xxl'), ('sm')) t(size_cd)")
    assert suggest_from_values(con, "vendor", "other", [("c1", "size_cd")]) == []
