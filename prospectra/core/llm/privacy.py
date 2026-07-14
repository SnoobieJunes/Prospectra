# 2026-07-13 (P4): The privacy gate.
#
# The model never touches the data directly — it can only ask for it through tools, and this enum
# decides which tools exist at all. That makes the guarantee structural rather than a promise in a
# prompt: at SCHEMA_ONLY the tools that return values are not merely discouraged, they are absent
# from the request, so no amount of prompting can produce a row.
#
# The three levels, in the user's words:
#   SCHEMA_ONLY  — "tell it my column names, nothing else"
#   AGGREGATES   — "it may see summaries and my findings, never individual rows"  (default)
#   SAMPLE_ROWS  — "it may query and read actual rows from the sample"

from __future__ import annotations

from enum import Enum


class PrivacyLevel(Enum):
    SCHEMA_ONLY = "schema_only"
    AGGREGATES = "aggregates"
    SAMPLE_ROWS = "sample_rows"

    @property
    def label(self) -> str:
        return {
            PrivacyLevel.SCHEMA_ONLY: "Schema only",
            PrivacyLevel.AGGREGATES: "Schema + summaries (recommended)",
            PrivacyLevel.SAMPLE_ROWS: "Schema + summaries + sample rows",
        }[self]

    @property
    def explanation(self) -> str:
        return {
            PrivacyLevel.SCHEMA_ONLY: (
                "Only column names, types and row counts are sent. No values of any kind leave "
                "this machine."
            ),
            PrivacyLevel.AGGREGATES: (
                "Column names, types, summary statistics (counts, averages, ranges, group "
                "totals) and your findings may be sent. Individual rows never are."
            ),
            PrivacyLevel.SAMPLE_ROWS: (
                "As above, plus the assistant may run read-only queries that return actual rows "
                "from your sampled data."
            ),
        }[self]

    def allows(self, tool_name: str) -> bool:
        return tool_name in ALLOWED_TOOLS[self]


# The single source of truth for what each level exposes. Adding a tool means adding it here —
# a tool absent from this map is never offered to any model.
ALLOWED_TOOLS: dict[PrivacyLevel, frozenset[str]] = {
    PrivacyLevel.SCHEMA_ONLY: frozenset({"list_datasets", "describe_dataset"}),
    PrivacyLevel.AGGREGATES: frozenset(
        {
            "list_datasets",
            "describe_dataset",
            "column_stats",
            "aggregate",
            "list_findings",
            "get_finding",
        }
    ),
    PrivacyLevel.SAMPLE_ROWS: frozenset(
        {
            "list_datasets",
            "describe_dataset",
            "column_stats",
            "aggregate",
            "list_findings",
            "get_finding",
            "run_sql",
        }
    ),
}
