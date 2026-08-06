# 2026-07-31 (P7): The drag-and-drop field mapper. Importing this package registers the
# `mapping_doc` custom editor with the generic params form — keyed on the ParamField KIND, never
# the node type, so any node (or plugin) declaring a mapping_doc param gets the full mapper.

from prospectra.ui.api.write_spec_editor import WriteSpecEditor
from prospectra.ui.flow.params_editor import CUSTOM_EDITORS
from prospectra.ui.mapping.field_row import FieldRow
from prospectra.ui.mapping.mapper_panel import MapperDialog, MapperPanel, MappingDocEditor
from prospectra.ui.mapping.transform_chip import TransformArgsDialog, TransformChip

CUSTOM_EDITORS.setdefault(
    "mapping_doc", lambda editor, instance, field: MappingDocEditor(editor, instance, field)
)
CUSTOM_EDITORS.setdefault(
    "write_spec", lambda editor, instance, field: WriteSpecEditor(editor, instance, field)
)

__all__ = [
    "FieldRow",
    "MapperDialog",
    "MapperPanel",
    "MappingDocEditor",
    "TransformArgsDialog",
    "TransformChip",
]
