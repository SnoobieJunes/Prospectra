# 2026-07-13 (P2): Built-in node set — importing this package registers every node type.
# One node per file (CLAUDE.md: no monoliths; contributors add a file, not edit a switch).
from prospectra.core.flow.nodes import (  # noqa: F401  (import = registration)
    aggregate,
    calculated,
    clean_nulls,
    filter_rows,
    input_file,
    join,
    outliers,
    output,
    pivot,
    sample,
    select,
    union,
    unpivot,
)
