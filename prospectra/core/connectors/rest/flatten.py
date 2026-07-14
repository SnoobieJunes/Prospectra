# 2026-07-14 (P6): Records -> a table, and a sample response -> a suggested mapping.
#
# `infer_mapping_fields` is the "mapping tool" doing its actual work: point it at one response and
# it proposes the records path and the columns, so the common case needs no JSONPath knowledge at
# all. The user can then edit what it guessed — a suggestion the user can correct beats a wizard
# that pretends there is nothing to correct.
#
# Nested values that are still dict/list after flattening are stored as JSON text rather than
# dropped: a column of JSON is honest and queryable in DuckDB, an absent column is a silent loss.

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from prospectra.core.connectors.rest import paths
from prospectra.core.connectors.rest.mapping import Column, RestMapping

MAX_INFERRED_COLUMNS = 60
# Response keys that hold the rows, in the order APIs actually use them.
_RECORD_KEYS = ("data", "items", "results", "records", "values", "issues", "rows", "elements")


def _scalarize(value: Any) -> Any:
    """A cell must be a scalar. Anything still structured becomes JSON text, never nothing."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _flatten_record(record: Any, prefix: str = "", depth: int = 0) -> dict[str, Any]:
    """One nested record -> flat {dotted_key: scalar}. Lists stay whole (as JSON)."""
    if not isinstance(record, dict):
        return {prefix or "value": _scalarize(record)}
    flat: dict[str, Any] = {}
    for key, value in record.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict) and depth < 3:
            flat.update(_flatten_record(value, name, depth + 1))
        else:
            flat[name] = _scalarize(value)
    return flat


def records_to_frame(records: list[Any], mapping: RestMapping) -> pd.DataFrame:
    """Apply the mapping's columns; with no columns declared, flatten everything."""
    if not records:
        return pd.DataFrame()
    if mapping.columns:
        rows = [
            {
                column.name: _scalarize(paths.resolve(record, column.path))
                for column in mapping.columns
            }
            for record in records
        ]
        return pd.DataFrame(rows, columns=[c.name for c in mapping.columns])
    rows = [_flatten_record(record) for record in records]
    return pd.DataFrame(rows)


def infer_records_path(body: Any) -> str:
    """Where do the rows live in this response? "" means the response IS the list."""
    if isinstance(body, list):
        return ""
    if not isinstance(body, dict):
        return ""
    for key in _RECORD_KEYS:  # the conventional names first
        if isinstance(body.get(key), list):
            return key
    # otherwise: the longest list of objects anywhere at the top level
    best, best_length = "", 0
    for key, value in body.items():
        if not (isinstance(value, list) and value and isinstance(value[0], dict)):
            continue
        if len(value) > best_length:
            best, best_length = str(key), len(value)
    return best


def infer_columns(records: list[Any]) -> list[Column]:
    """Suggest one column per leaf key, in first-seen order, from a sample of records."""
    seen: list[str] = []
    for record in records[:50]:  # a sample is enough, and ragged records add keys as they go
        for key in _flatten_record(record):
            if key not in seen:
                seen.append(key)
        if len(seen) >= MAX_INFERRED_COLUMNS:
            break
    return [Column(name=key.replace(".", "_"), path=key) for key in seen[:MAX_INFERRED_COLUMNS]]


def infer_mapping_fields(body: Any) -> tuple[str, list[Column]]:
    """The mapping tool's suggestion for a sample response: (records_path, columns)."""
    records_path = infer_records_path(body)
    records = paths.records_at(body, records_path)
    return records_path, infer_columns(records)
