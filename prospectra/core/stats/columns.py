# 2026-07-13 (P3): Column classification for the scan — decides what is a usable *variable*.
# Why: an ID or a timestamp is not a variable, and a 1000-level categorical is not a category.
# Feeding those into the tests produces nonsense with tiny p-values. Every exclusion is recorded
# with a reason so the UI can say what it skipped and why, instead of silently dropping columns.

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
from pandas.api import types as ptypes

MAX_CATEGORY_LEVELS = 30


@dataclass(frozen=True)
class ColumnRoles:
    numeric: list[str] = field(default_factory=list)
    categorical: list[str] = field(default_factory=list)
    excluded: dict[str, str] = field(default_factory=dict)  # column -> reason


def classify(frame: pd.DataFrame) -> ColumnRoles:
    numeric: list[str] = []
    categorical: list[str] = []
    excluded: dict[str, str] = {}

    for name in frame.columns:
        series = frame[name]
        non_null = series.dropna()
        if non_null.empty:
            excluded[name] = "all values are null"
            continue
        distinct = int(non_null.nunique())
        if distinct <= 1:
            excluded[name] = "constant (only one value)"
            continue

        if ptypes.is_bool_dtype(series):
            numeric.append(name)  # booleans work as 0/1 numerics
        elif ptypes.is_numeric_dtype(series):
            numeric.append(name)
        elif ptypes.is_datetime64_any_dtype(series):
            excluded[name] = "date/time column (not yet used as a variable)"
        else:
            # An identifier is an identifier at any size: check uniqueness before the level cap,
            # or a 4-row table's unique key sneaks through as a 4-level "category".
            share = distinct / len(non_null) if len(non_null) else 1.0
            if share >= 0.9:
                excluded[name] = "looks like an identifier (nearly every row is unique)"
            elif distinct > MAX_CATEGORY_LEVELS:
                excluded[name] = f"too many categories ({distinct:,}; limit {MAX_CATEGORY_LEVELS})"
            else:
                categorical.append(name)

    return ColumnRoles(numeric=numeric, categorical=categorical, excluded=excluded)
