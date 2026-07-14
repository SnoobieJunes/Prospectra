# 2026-07-13 (P4): SQL the model wrote is untrusted input. Before anything runs, it must be:
#   * exactly one statement (no "SELECT 1; DROP TABLE x" smuggling), and
#   * a SELECT — checked with DuckDB's own parser (`extract_statements`), not a regex, and
#   * wrapped in a row limit, so a runaway query cannot drag the whole table into the chat.
# The sandbox (sandbox.py) is the real security boundary; this is the second lock on the door.

from __future__ import annotations

import duckdb

MAX_ROWS = 200


class UnsafeSQLError(Exception):
    """The model's SQL is not a single read-only SELECT."""


def check_select(sql: str) -> str:
    """Validate and return the statement, or raise UnsafeSQLError."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise UnsafeSQLError("empty query")
    try:
        statements = duckdb.extract_statements(text)
    except duckdb.Error as exc:
        raise UnsafeSQLError(f"could not parse the SQL: {exc}") from exc
    if len(statements) != 1:
        raise UnsafeSQLError(f"only one statement is allowed, this has {len(statements)}")
    kind = statements[0].type
    if kind != duckdb.StatementType.SELECT:
        raise UnsafeSQLError(f"only SELECT is allowed here (this is a {kind.name} statement)")
    return text


def wrap_with_limit(sql: str, limit: int = MAX_ROWS) -> str:
    """A hard row cap the model cannot talk its way past."""
    return f"SELECT * FROM ({sql}) LIMIT {int(limit)}"
