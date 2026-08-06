# 2026-07-31 (P7): The mapping document — spec → validate → persist, exactly like ChartSpec.
#
# `target_columns` is the piece that makes this safe for a non-technical user: it is what lets
# `validate()` say "styleCode is required and nothing is mapped to it" BEFORE anything runs. It is
# populated from Catalog.describe() for a local target, FlowRunner.columns() for a flow node, or
# infer_mapping_fields() over a sample response for an API target.
#
# Every FieldMap carries a `note` — why this mapping exists. When there are 50 names for "product
# name", the note is the audit trail that says which one this system uses and why.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from prospectra.core.mapping.transforms import TRANSFORMS_BY_KEY, build_step

MAPPING_DOC_SCHEMA = 1
UNMAPPED_POLICIES = ("drop", "passthrough", "null")

# The closed shape a declared column type may take ("VARCHAR", "DECIMAL(18,4)", …). Types are
# interpolated into CAST expressions, so this pattern is a safety boundary, not cosmetics.
# 2026-07-31 (P7): anchored with \Z, not $ — Python's `$` also matches before a trailing newline,
# so "VARCHAR\n" passed the pattern. Nothing can follow the type, newline included.
_TYPE_PATTERN = re.compile(r"\A[A-Za-z][A-Za-z0-9_ ]*(\(\d+(,\s*\d+)?\))?\Z")


def check_type(declared: str, column_name: str) -> None:
    """Raise unless `declared` is a usable SQL type. Called by validate() AND by the compiler.

    Lives here beside the pattern, but is enforced at every compile entry point (compile.py's
    `_declared_type`) — a check that only one caller remembers to run is not a boundary.
    """
    if not _TYPE_PATTERN.match(declared):
        raise ValueError(f"target column {column_name!r} has an unusable type {declared!r}")


@dataclass
class Step:
    key: str
    args: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "args": dict(self.args)}

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Step:
        return cls(key=str(doc.get("key", "")), args=dict(doc.get("args", {})))


@dataclass
class FieldMap:
    target: str
    sources: list[str] = field(default_factory=list)  # 0 = constant/NULL; >1 = concat_ws join
    join_with: str = " "
    steps: list[Step] = field(default_factory=list)
    constant: str = ""
    note: str = ""  # why this mapping exists — the audit trail for "50 names for product name"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "sources": list(self.sources),
            "join_with": self.join_with,
            "steps": [s.to_dict() for s in self.steps],
            "constant": self.constant,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> FieldMap:
        return cls(
            target=str(doc.get("target", "")),
            sources=[str(s) for s in doc.get("sources", [])],
            join_with=str(doc.get("join_with", " ")),
            steps=[Step.from_dict(s) for s in doc.get("steps", [])],
            constant=str(doc.get("constant", "")),
            note=str(doc.get("note", "")),
        )


@dataclass
class TargetColumn:
    name: str
    type: str = "VARCHAR"
    required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.type, "required": self.required}

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> TargetColumn:
        return cls(
            name=str(doc.get("name", "")),
            type=str(doc.get("type", "VARCHAR")),
            required=bool(doc.get("required", False)),
        )


@dataclass
class MappingDoc:
    name: str = "mapping"
    source: str = ""  # where the rows come from (display/lineage, not an address)
    target: str = ""  # where they are going
    target_columns: list[TargetColumn] = field(default_factory=list)
    fields: list[FieldMap] = field(default_factory=list)
    unmapped_policy: str = "drop"

    def validate(self) -> None:
        """Everything that can be wrong *within the document* — said in a fixable sentence.

        (Whether the sources still exist upstream needs the live column list; `compile_select`
        checks that when given `available`, and the mapper UI re-validates on open.)
        """
        if self.unmapped_policy not in UNMAPPED_POLICIES:
            raise ValueError(
                f"unknown unmapped-column policy {self.unmapped_policy!r} "
                f"(have: {', '.join(UNMAPPED_POLICIES)})"
            )
        known_targets = {c.name for c in self.target_columns}
        declared_seen: set[str] = set()
        for column in self.target_columns:
            if not column.name.strip():
                raise ValueError("a target column has no name")
            check_type(column.type, column.name)
            if column.name.casefold() in declared_seen:
                raise ValueError(
                    f"two target columns are named {column.name!r} (names are case-insensitive "
                    "in SQL, so they would collide)"
                )
            declared_seen.add(column.name.casefold())

        # 2026-08-05: case-folded — SQL identifiers are case-insensitive, so two targets differing
        # only in case ("SKU" and "sku") collide in the emitted SELECT and a downstream step reads
        # whichever DuckDB kept. That has to be a refusal, not a silent pick.
        known_targets_folded = {c.casefold() for c in known_targets}
        seen: set[str] = set()
        for field_map in self.fields:
            if not field_map.target.strip():
                raise ValueError("a field mapping has no target column")
            if field_map.target.casefold() in seen:
                raise ValueError(f"two mappings write to {field_map.target!r}")
            seen.add(field_map.target.casefold())
            if known_targets and field_map.target.casefold() not in known_targets_folded:
                raise ValueError(
                    f"{field_map.target!r} is not a column of the target "
                    f"({', '.join(sorted(known_targets))})"
                )
            if field_map.sources and field_map.constant:
                raise ValueError(f"{field_map.target}: use source columns or a constant, not both")
            for step in field_map.steps:
                if step.key not in TRANSFORMS_BY_KEY:
                    raise ValueError(f"{field_map.target}: unknown transform {step.key!r}")
                # Coerce AND build against a placeholder — the same path compile takes, so a bad
                # arg ("40; DROP") or an empty lookup dies here, before any SQL touches data.
                build_step(step.key, step.args, "placeholder_value")

        mapped = {f.target for f in self.fields}
        missing = [c.name for c in self.target_columns if c.required and c.name not in mapped]
        if missing:
            raise ValueError(
                f"{missing[0]!r} is required and nothing is mapped to it"
                if len(missing) == 1
                else f"required columns with nothing mapped to them: {', '.join(missing)}"
            )

    # -- persistence --------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapping_doc_schema": MAPPING_DOC_SCHEMA,
            "name": self.name,
            "source": self.source,
            "target": self.target,
            "target_columns": [c.to_dict() for c in self.target_columns],
            "fields": [f.to_dict() for f in self.fields],
            "unmapped_policy": self.unmapped_policy,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> MappingDoc:
        version = int(doc.get("mapping_doc_schema", MAPPING_DOC_SCHEMA))
        if version > MAPPING_DOC_SCHEMA:
            raise ValueError(
                f"Mapping schema v{version} is newer than this app supports (v{MAPPING_DOC_SCHEMA})"
            )
        return cls(
            name=str(doc.get("name", "mapping")),
            source=str(doc.get("source", "")),
            target=str(doc.get("target", "")),
            target_columns=[TargetColumn.from_dict(c) for c in doc.get("target_columns", [])],
            fields=[FieldMap.from_dict(f) for f in doc.get("fields", [])],
            unmapped_policy=str(doc.get("unmapped_policy", "drop")),
        )
