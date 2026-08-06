# 2026-07-31 (P7): The full-panel mapper — source columns (drag sources) on the left, one FieldRow
# per target column in the middle, live before/after on demand. Suggestions are PROPOSALS in a
# checkable list — accepting them is a click the user makes; nothing is ever applied silently.
#
# 2026-08-05: the suggestions here are NAME-based only. Value-based matching (`suggest_from_values`)
# needs two relations to sample, and a flow node's "target" is a declared column list rather than a
# dataset — so it belongs to `prospectra suggest-map`, which has both. The earlier claim in this
# header that it ran "when a preview connection exists" was simply untrue.
#
# On open the panel re-validates the saved doc against the LIVE upstream columns and paints broken
# rows red: an upstream rename silently kills a saved mapping, and doc.validate() cannot see it.

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.flow.graph import NodeInstance
from prospectra.core.flow.node import ParamField
from prospectra.core.mapping import (
    UNMAPPED_POLICIES,
    MappingDoc,
    Suggestion,
    TargetColumn,
    suggest_matches,
)
from prospectra.core.mapping.compile import field_exprs
from prospectra.ui.dnd.mime import ColumnPayload, column_mime
from prospectra.ui.mapping.field_row import FieldRow
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)

# Signature of the injected preview: select_sql (reading relation `upstream`) -> SelectPreview.
PreviewFn = Callable[[str], object]


class SourceColumnList(QListWidget):
    """The upstream columns, draggable one or many at a time (a real ColumnPayload drag)."""

    def __init__(self, columns: list[tuple[str, str]]) -> None:
        super().__init__()
        self.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.set_columns(columns)

    def set_columns(self, columns: list[tuple[str, str]]) -> None:
        self.clear()
        for name, dtype in columns:
            item = QListWidgetItem(f"{name}   {dtype}")
            item.setData(Qt.ItemDataRole.UserRole, (name, dtype))
            self.addItem(item)

    def mimeData(self, items):
        pairs = [item.data(Qt.ItemDataRole.UserRole) for item in items]
        if not pairs:
            return super().mimeData(items)
        return column_mime(
            ColumnPayload(
                dataset_id="upstream",
                dataset="upstream",
                origin="mapper",
                columns=[name for name, _dtype in pairs],
                dtypes=[dtype for _name, dtype in pairs],
            )
        )


class MapperPanel(QWidget):
    """Edits one MappingDoc. `doc()` reads the current state; `drop_columns` is the test seam."""

    changed = Signal()

    def __init__(
        self,
        doc: MappingDoc,
        source_columns: list[tuple[str, str]],
        preview_fn: PreviewFn | None = None,
    ) -> None:
        super().__init__()
        self._source_columns = list(source_columns)
        self._preview_fn = preview_fn
        self._name = doc.name
        self._source_label = doc.source
        self._target_label = doc.target
        self._rows: list[FieldRow] = []

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self._target_name = QLineEdit(doc.target)
        self._target_name.setPlaceholderText("target system (for the record)")
        toolbar.addWidget(QLabel("Mapping to:"))
        toolbar.addWidget(self._target_name)
        self._policy = QComboBox()
        for policy in UNMAPPED_POLICIES:
            self._policy.addItem(policy, policy)
        self._policy.setCurrentIndex(max(0, self._policy.findData(doc.unmapped_policy)))
        self._policy.setToolTip(
            "What happens to target columns nothing is mapped to:\n"
            "drop = they are absent · passthrough = unconsumed input columns ride along · "
            "null = they exist, empty"
        )
        toolbar.addWidget(QLabel("Unmapped:"))
        toolbar.addWidget(self._policy)
        suggest = QPushButton("Suggest matches…")
        suggest.setToolTip("Propose source→target matches — you accept or ignore each one")
        suggest.clicked.connect(self._suggest_clicked)
        toolbar.addWidget(suggest)
        self._refresh_preview = QPushButton("Preview values")
        self._refresh_preview.clicked.connect(self.refresh_previews)
        self._refresh_preview.setEnabled(preview_fn is not None)
        toolbar.addWidget(self._refresh_preview)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        layout.addWidget(self._banner)

        split = QSplitter()
        left = QWidget()
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.addWidget(QLabel("Source columns (drag onto a field)"))
        self._source_list = SourceColumnList(source_columns)
        left_col.addWidget(self._source_list, 1)
        split.addWidget(left)

        rows_host = QWidget()
        self._rows_layout = QVBoxLayout(rows_host)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        by_target = {f.target: f for f in doc.fields}
        for column in doc.target_columns:
            row = FieldRow(column, by_target.get(column.name))
            row.changed.connect(self._row_changed)
            self._rows.append(row)
            self._rows_layout.addWidget(row)
        self._rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(rows_host)
        split.addWidget(scroll)
        split.setSizes([220, 620])
        layout.addWidget(split, 1)

        self._policy.currentIndexChanged.connect(lambda _i: self._row_changed())
        self._revalidate()

    # -- state ---------------------------------------------------------------------------------

    def doc(self) -> MappingDoc:
        return MappingDoc(
            name=self._name,
            source=self._source_label,
            target=self._target_name.text().strip(),
            target_columns=[row.column for row in self._rows],
            fields=[row.field_map for row in self._rows if row.mapped],
            unmapped_policy=str(self._policy.currentData()),
        )

    def _row_changed(self) -> None:
        self._revalidate()
        self.changed.emit()

    def _revalidate(self) -> None:
        available = {name for name, _dtype in self._source_columns}
        any_broken = False
        for row in self._rows:
            missing = [s for s in row.field_map.sources if s not in available]
            row.set_broken(missing)
            any_broken = any_broken or bool(missing)
        try:
            self.doc().validate()
            problem = ""
        except ValueError as exc:
            problem = str(exc)
        if any_broken:
            problem = (problem + " · " if problem else "") + (
                "some mapped columns no longer exist upstream (the red rows)"
            )
        if problem:
            self._banner.setText(f"✗ {problem}")
            self._banner.setStyleSheet("color: #b71c1c;")
        else:
            self._banner.setText("✓ the mapping is valid")
            self._banner.setStyleSheet("color: #2e7d32;")

    def set_available_columns(self, columns: list[tuple[str, str]]) -> None:
        """The live upstream schema changed (or was just fetched) — re-validate against it."""
        self._source_columns = list(columns)
        self._source_list.set_columns(columns)
        self._revalidate()

    # -- test seam (mirrors SourcesDock.drop_columns) ------------------------------------------

    def drop_columns(self, target: str, payload: ColumnPayload) -> None:
        """Same effect as dropping `payload` on the row for `target`, minus the Qt drag."""
        for row in self._rows:
            if row.column.name == target:
                row.add_sources(payload.columns)
                return
        raise ValueError(f"no target column {target!r}")

    # -- suggestions ---------------------------------------------------------------------------

    def _suggest_clicked(self) -> None:
        unmapped_targets = [
            (row.column.name, row.column.type) for row in self._rows if not row.mapped
        ]
        # 2026-08-05: off the GUI thread — suggest_matches is O(sources x targets) SequenceMatcher
        # and measured 7.5s frozen at 600x600 columns.
        self._banner.setText("Looking for matches…")
        run_in_pool(
            suggest_matches,
            self._source_columns,
            unmapped_targets,
            on_result=self._suggestions_ready,
            on_error=lambda msg: self._banner.setText(f"✗ {msg}"),
        )

    def _suggestions_ready(self, suggestions: list[Suggestion]) -> None:
        if not suggestions:
            self._banner.setText("No matches cleared the confidence bar — map by hand.")
            return
        dialog = _SuggestionDialog(suggestions, self)
        if dialog.exec():
            self.apply_suggestions(dialog.accepted_suggestions())
        else:
            self._revalidate()

    def apply_suggestions(self, suggestions: list[Suggestion]) -> None:
        """Fill only empty rows, only with what the user accepted."""
        for suggestion in suggestions:
            for row in self._rows:
                if row.column.name == suggestion.target and not row.mapped:
                    row.add_sources([suggestion.source])
        self._revalidate()

    # -- live values ---------------------------------------------------------------------------

    def refresh_previews(self) -> None:
        """Fetch one before/after sample for every mapped field — in ONE query, off-thread.

        2026-08-05: this used to issue one `preview_select` per mapped field, synchronously on
        the GUI thread. Each call re-ran the upstream node's `prepare()`, so a database-backed
        input downloaded its whole table once per field while the window sat frozen. Now a single
        SELECT carries every field's pair, and it runs through the thread pool.
        """
        if self._preview_fn is None:
            return
        doc = self.doc()
        targets: list[str] = []
        projections: list[str] = []
        for row in self._rows:
            if not row.mapped:
                continue
            try:
                base, final = field_exprs(doc, row.column.name)
            except ValueError as exc:
                row.set_preview("✗", str(exc)[:60])
                continue
            index = len(targets)
            targets.append(row.column.name)
            projections.append(f"{base} AS before_{index}, {final} AS after_{index}")
        if not projections:
            return

        sql = "SELECT " + ", ".join(projections) + " FROM upstream"
        self._refresh_preview.setEnabled(False)
        self._banner.setText("Sampling values…")
        run_in_pool(
            self._preview_fn,
            sql,
            on_result=lambda preview: self._previews_ready(targets, preview),
            on_error=self._previews_failed,
            on_finished=lambda: self._refresh_preview.setEnabled(True),
        )

    def _previews_ready(self, targets: list[str], preview: object) -> None:
        rows = getattr(preview, "rows", [])
        by_target = {row.column.name: row for row in self._rows}
        if not rows:
            self._banner.setText("The input has no rows to sample.")
            return
        first = rows[0]
        for index, target in enumerate(targets):
            row = by_target.get(target)
            if row is None:
                continue
            before, after = first[index * 2], first[index * 2 + 1]
            row.set_preview(
                "∅" if before is None else str(before)[:28],
                "∅" if after is None else str(after)[:28],
            )
        self._revalidate()

    def _previews_failed(self, message: str) -> None:
        self._banner.setText(f"✗ could not sample values: {message}")
        self._banner.setStyleSheet("color: #b71c1c;")


class MapperDialog(QDialog):
    """The dedicated full-panel editor a Map Fields node opens."""

    def __init__(
        self,
        doc: MappingDoc,
        source_columns: list[tuple[str, str]],
        preview_fn: PreviewFn | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Field mapper")
        self.setMinimumSize(920, 560)
        layout = QVBoxLayout(self)
        if not doc.target_columns and source_columns:
            # A brand-new mapping: offer the upstream schema as the starting target list — the
            # user edits from something rather than typing every column by hand.
            doc.target_columns = [TargetColumn(name, dtype) for name, dtype in source_columns]
        self.panel = MapperPanel(doc, source_columns, preview_fn)
        layout.addWidget(self.panel, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._problem = QLabel("")
        self._problem.setWordWrap(True)
        self._problem.setStyleSheet("color: #b71c1c;")
        layout.addWidget(self._problem)

    # 2026-08-05: OK is gated on the doc being valid. It used to accept anything and write it into
    # the node's params, so an invalid mapping was only discovered at run pre-flight — the project
    # states problems where they are made, not three screens later.
    def _accept_if_valid(self) -> None:
        try:
            self.panel.doc().validate()
        except ValueError as exc:
            self._problem.setText(f"Cannot save yet — {exc}")
            return
        self.accept()


class MappingDocEditor(QWidget):
    """What the generic params form shows for a `mapping_doc` param: a summary + the door in."""

    def __init__(self, editor, instance: NodeInstance, field: ParamField) -> None:
        super().__init__()
        self._editor = editor
        self._instance = instance
        self._field = field
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._summary = QLabel("")
        layout.addWidget(self._summary, 1)
        open_button = QPushButton("Open Mapper…")
        open_button.clicked.connect(self._open)
        layout.addWidget(open_button)
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        try:
            doc = MappingDoc.from_dict(self._instance.node.params.get(self._field.name) or {})
            self._summary.setText(
                f"{len(doc.fields)} field(s) mapped, {len(doc.target_columns)} target(s)"
            )
        except ValueError:
            self._summary.setText("(unreadable mapping)")

    def _open(self) -> None:
        """Fetch the upstream schema OFF the GUI thread, then open the mapper.

        2026-08-05: `upstream_columns_for` was called inline here. It runs the upstream node's
        `prepare()`, which for a database input downloads the whole table — so the window froze
        (unrepaintable, uncancellable) before the dialog even appeared.
        """
        host = getattr(self._editor, "host", None)
        if host is None:
            self._show_mapper([], None)
            return
        self._summary.setText("Reading the input's columns…")
        run_in_pool(
            host.upstream_columns_for,
            self._instance.id,
            on_result=lambda cols: self._show_mapper(cols, host),
            on_error=self._columns_failed,
        )

    def _columns_failed(self, message: str) -> None:
        # No upstream yet (or a source that cannot be read) is a state, not a crash — open the
        # mapper anyway so the target list can still be edited, and say why there is nothing
        # to drag.
        logger.info("Mapper opened without upstream columns: %s", message)
        self._refresh_summary()
        self._show_mapper([], None)

    def _show_mapper(self, source_columns: list[tuple[str, str]], host: Any) -> None:
        self._refresh_summary()
        preview_fn: PreviewFn | None = None
        if host is not None and source_columns:
            node_id = self._instance.id

            def preview_fn(sql: str) -> object:
                return host.preview_select_for(node_id, sql)

        try:
            doc = MappingDoc.from_dict(self._instance.node.params.get(self._field.name) or {})
        except ValueError:
            doc = MappingDoc()
        dialog = MapperDialog(doc, source_columns, preview_fn, self)
        if dialog.exec():
            self._instance.node.params[self._field.name] = dialog.panel.doc().to_dict()
            self._refresh_summary()
            self._editor.changed.emit()


class _SuggestionDialog(QDialog):
    """The proposals list — checked by hand, applied on OK, never silently."""

    def __init__(self, suggestions: list[Suggestion], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Suggested matches")
        self._boxes: list[tuple[QCheckBox, Suggestion]] = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Accept the matches that look right — nothing applies itself:"))
        for suggestion in suggestions:
            box = QCheckBox(
                f"{suggestion.source}  →  {suggestion.target}   "
                f"({suggestion.confidence:.0%} — {suggestion.reason})"
            )
            self._boxes.append((box, suggestion))
            layout.addWidget(box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accepted_suggestions(self) -> list[Suggestion]:
        return [suggestion for box, suggestion in self._boxes if box.isChecked()]
