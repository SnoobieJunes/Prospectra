# 2026-07-31 (P7): Field mapping — the Qt-free heart of "everyone calls it something different".
# A MappingDoc (spec → validate → persist) compiles to one SELECT through a closed, descriptor-
# driven transform vocabulary; suggest.py proposes matches by name AND by sampled values.

from prospectra.core.mapping.compile import coercion_check_sql, compile_notes, compile_select
from prospectra.core.mapping.doc import (
    MAPPING_DOC_SCHEMA,
    UNMAPPED_POLICIES,
    FieldMap,
    MappingDoc,
    Step,
    TargetColumn,
)
from prospectra.core.mapping.suggest import Suggestion, suggest_from_values, suggest_matches
from prospectra.core.mapping.transforms import (
    CAST_TYPES,
    TRANSFORMS,
    TRANSFORMS_BY_KEY,
    ArgSpec,
    Transform,
    coerce_args,
)

__all__ = [
    "CAST_TYPES",
    "MAPPING_DOC_SCHEMA",
    "TRANSFORMS",
    "TRANSFORMS_BY_KEY",
    "UNMAPPED_POLICIES",
    "ArgSpec",
    "FieldMap",
    "MappingDoc",
    "Step",
    "Suggestion",
    "TargetColumn",
    "Transform",
    "coerce_args",
    "coercion_check_sql",
    "compile_notes",
    "compile_select",
    "suggest_from_values",
    "suggest_matches",
]
