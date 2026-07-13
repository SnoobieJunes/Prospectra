# 2026-07-13 (P1): SQL quoting helpers used by every module that builds DuckDB SQL.
# Why: centralised, tested escaping — including Windows paths, where backslashes must not reach
# SQL string literals (DuckDB accepts POSIX-style separators on all OSes; single quotes are
# doubled per the SQL standard).

from __future__ import annotations

from pathlib import Path


def str_lit(value: str) -> str:
    """A single-quoted SQL string literal."""
    return "'" + value.replace("'", "''") + "'"


def ident(name: str) -> str:
    """A double-quoted SQL identifier."""
    return '"' + name.replace('"', '""') + '"'


def path_lit(path: Path | str) -> str:
    """A file path as a SQL literal, POSIX separators so it is Windows-safe."""
    return str_lit(Path(path).as_posix())
