# 2026-07-13 (P3): The Analyze workspace — point it at a dataset, optionally name a target, scan.
# Three sub-tabs mirroring the three questions the engine answers:
#   Relationships   — what moves with what (FDR-controlled, so decoys stay out)
#   What drives X   — each variable's own explanatory power, ranked by adjusted R², plus the best
#                     combined model and its trust light
#   PCA             — how the columns vary together, with the plain-English narrative and the
#                     explicit warning that PCA is unsupervised and cannot answer "what drives X"
# The scan runs on the thread pool; the UI stays live.

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.catalog import Catalog
from prospectra.core.mining import Finding, ScanResult, scan_relation
from prospectra.ui.analysis.explain_panel import ExplainPanel
from prospectra.ui.analysis.findings_table import FindingsTable
from prospectra.ui.analysis.trust_light import TrustLight
from prospectra.ui.widgets.charts import Chart
from prospectra.ui.workers import run_in_pool

logger = logging.getLogger(__name__)

_NO_TARGET = "(no target — just find relationships)"

# Compact symbols keep the effect column narrow; the headline spells each one out in words.
_EFFECT_SYMBOL = {"|r|": "|r|", "eta-squared": "η²", "Cramer's V": "V"}


def _size_columns(table: QTableWidget) -> None:
    """First column takes the slack, the rest hug their content.

    Without this the numeric columns claim a fixed width each and squeeze the name column down to
    an ellipsis ("tem…", "sch…") — which was exactly what a real-display screenshot showed.
    """
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    for column in range(1, table.columnCount()):
        header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)


class AnalyzeTab(QWidget):
    # 2026-07-14 (P4): emitted after every scan so the Data Buddy dock can discuss the findings.
    scan_finished = Signal(list)

    def __init__(self, catalog: Catalog) -> None:
        super().__init__()
        self._catalog = catalog
        self._scan: ScanResult | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.addLayout(self._build_toolbar())
        self._status = QLabel("Open a dataset, pick what you want explained, then Run scan.")
        self._status.setEnabled(False)
        root.addWidget(self._status)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)
        self._tabs.addTab(self._build_relationships(), "Relationships")
        self._tabs.addTab(self._build_drivers(), "What drives…")
        self._tabs.addTab(self._build_pca(), "PCA")
        root.addWidget(self._tabs, 1)

    # -- construction ---------------------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        self._dataset_picker = QComboBox()
        self._dataset_picker.setMinimumWidth(200)
        self._dataset_picker.currentIndexChanged.connect(self._dataset_changed)
        self._target_picker = QComboBox()
        self._target_picker.setMinimumWidth(220)
        self._run = QPushButton("Run scan")
        self._run.clicked.connect(self._run_scan)
        bar.addWidget(QLabel("Dataset"))
        bar.addWidget(self._dataset_picker)
        bar.addWidget(QLabel("Explain"))
        bar.addWidget(self._target_picker)
        bar.addWidget(self._run)
        bar.addStretch(1)
        return bar

    def _build_relationships(self) -> QWidget:
        page = QSplitter(Qt.Orientation.Horizontal)
        # 2026-07-14 (P5): a FindingsTable, so a row can be dragged into the chat dock as a chip.
        self._findings = FindingsTable(0, 4)
        self._findings.setHorizontalHeaderLabels(["Relationship", "Strength", "Effect", "q-value"])
        self._findings.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._findings.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        _size_columns(self._findings)
        self._findings.itemSelectionChanged.connect(self._finding_selected)
        page.addWidget(self._findings)

        detail = QWidget()
        layout = QVBoxLayout(detail)
        layout.setContentsMargins(6, 0, 0, 0)
        self._headline = QLabel(
            "Select a relationship to see it plotted.\n\n"
            "These are associations, not causes: two columns moving together can share a hidden "
            "third cause, or be pure coincidence. Only findings that survive false-discovery-rate "
            "control are listed."
        )
        self._headline.setWordWrap(True)
        layout.addWidget(self._headline)
        self._pair_chart = Chart(height=3.0)
        layout.addWidget(self._pair_chart, 1)
        # 2026-07-14 (P4): ask the LLM why this relationship might exist, with cited sources.
        self._explain = ExplainPanel()
        layout.addWidget(self._explain, 1)
        page.addWidget(detail)
        page.setSizes([620, 560])
        return page

    def _build_drivers(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 4, 0, 0)
        split = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 6, 0)
        self._drivers_table = QTableWidget(0, 5)
        self._drivers_table.setHorizontalHeaderLabels(
            ["Variable", "adj R²", "R²", "Best form", "p"]
        )
        self._drivers_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._drivers_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        _size_columns(self._drivers_table)
        left_layout.addWidget(QLabel("Each variable on its own (best-fitting shape):"))
        left_layout.addWidget(self._drivers_table, 1)
        self._model_summary = QPlainTextEdit()
        self._model_summary.setReadOnly(True)
        self._model_summary.setMaximumHeight(150)
        left_layout.addWidget(QLabel("Best combined model:"))
        left_layout.addWidget(self._model_summary)
        split.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(6, 0, 0, 0)
        self._drivers_chart = Chart(height=2.6)
        right_layout.addWidget(self._drivers_chart, 1)
        self._trust = TrustLight()
        right_layout.addWidget(self._trust)
        self._residual_chart = Chart(height=2.4)
        right_layout.addWidget(self._residual_chart, 1)
        split.addWidget(right)
        split.setSizes([520, 560])
        layout.addWidget(split, 1)
        return page

    def _build_pca(self) -> QWidget:
        page = QSplitter(Qt.Orientation.Horizontal)
        self._pca_chart = Chart(height=3.0)
        page.addWidget(self._pca_chart)
        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(6, 0, 0, 0)
        self._pca_text = QPlainTextEdit()
        self._pca_text.setReadOnly(True)
        self._pca_text.setPlainText(
            "PCA finds the directions your columns vary in together — a way to summarize many "
            "columns with a few numbers.\n\nIt is unsupervised: it never looks at your target, so "
            "it cannot tell you what drives an outcome. Use 'What drives…' for that.\n\n"
            "Run a scan to see this dataset's components."
        )
        layout.addWidget(self._pca_text, 1)
        self._loadings = QTableWidget(0, 0)
        self._loadings.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(QLabel("Loadings (how much each column contributes):"))
        layout.addWidget(self._loadings, 1)
        page.addWidget(right)
        page.setSizes([520, 560])
        return page

    # -- dataset / target wiring ------------------------------------------------------------

    def refresh_datasets(self) -> None:
        current = self._dataset_picker.currentData()
        self._dataset_picker.blockSignals(True)
        self._dataset_picker.clear()
        for dataset in self._catalog.datasets.values():
            self._dataset_picker.addItem(dataset.name, dataset.id)
        self._dataset_picker.blockSignals(False)
        if current is not None:
            index = self._dataset_picker.findData(current)
            if index >= 0:
                self._dataset_picker.setCurrentIndex(index)
        self._dataset_changed()

    def _dataset_changed(self) -> None:
        dataset_id = self._dataset_picker.currentData()
        self._target_picker.clear()
        self._target_picker.addItem(_NO_TARGET, None)
        if not dataset_id:
            return
        for name, _dtype in self._catalog.describe(dataset_id):
            self._target_picker.addItem(name, name)

    # -- running -----------------------------------------------------------------------------

    def _run_scan(self) -> None:
        dataset_id = self._dataset_picker.currentData()
        if not dataset_id:
            self._status.setText("Open a dataset first (Sources ▸ Open File…).")
            return
        dataset = self._catalog.datasets[dataset_id]
        target = self._target_picker.currentData()
        self._run.setEnabled(False)
        self._status.setText("Scanning…")

        def work() -> ScanResult:
            return scan_relation(
                self._catalog.cursor(),
                dataset.view_name,
                target=target,
                dataset_name=dataset.name,
            )

        run_in_pool(
            work,
            on_result=self._scan_ready,
            on_error=self._scan_failed,
            on_finished=lambda: self._run.setEnabled(True),
        )

    def _scan_failed(self, message: str) -> None:
        self._status.setText(f"Scan failed: {message}")
        logger.error("Scan failed: %s", message)

    def _scan_ready(self, scan: ScanResult) -> None:
        self._scan = scan
        skipped = (
            "  ·  skipped: "
            + ", ".join(f"{c} ({reason})" for c, reason in scan.roles.excluded.items())
            if scan.roles.excluded
            else ""
        )
        self._status.setText(scan.summary + skipped)
        self._fill_findings(scan)
        self._fill_drivers(scan)
        self._fill_pca(scan)
        self.scan_finished.emit(list(scan.findings))

    # -- population --------------------------------------------------------------------------

    def _fill_findings(self, scan: ScanResult) -> None:
        pairs = [f for f in scan.findings if f.kind in ("correlation", "group-difference")]
        self._findings.set_findings(pairs)  # the rows are now draggable payloads
        self._findings.setRowCount(len(pairs))
        for row, finding in enumerate(pairs):
            cells = [
                QTableWidgetItem(finding.title),
                QTableWidgetItem(finding.strength),
                QTableWidgetItem(f"{finding.effect:.2f} {_EFFECT_SYMBOL[finding.effect_name]}"),
                QTableWidgetItem(f"{finding.q_value:.1e}"),
            ]
            for column, cell in enumerate(cells):
                # the plain-English headline is always one hover away, so a narrow column never
                # hides the meaning
                cell.setToolTip(f"{finding.title}\n\n{finding.headline}")
                self._findings.setItem(row, column, cell)
        if pairs:
            self._findings.selectRow(0)
        else:
            self._headline.setText(
                "No relationship survived false-discovery-rate control — on this data, anything "
                "that looked like a trend is within what chance alone would produce."
            )

    def _finding_selected(self) -> None:
        if self._scan is None or self._scan.frame is None:
            return
        row = self._findings.currentRow()
        pairs = [f for f in self._scan.findings if f.kind in ("correlation", "group-difference")]
        if not (0 <= row < len(pairs)):
            return
        finding = pairs[row]
        self._headline.setText(finding.headline + "\n\nAssociation, not proof of cause.")
        self._plot_finding(finding)
        self._explain.set_finding(finding, self._scan.dataset)

    def _plot_finding(self, finding: Finding) -> None:
        frame = self._scan.frame if self._scan else None
        if frame is None:
            return
        a, b = finding.columns
        kind = finding.payload.get("kind")
        if kind == "num-num":
            data = frame[[a, b]].dropna()
            self._pair_chart.scatter_with_fit(data[a], data[b], a, b)
        elif kind == "num-cat":
            data = frame[[a, b]].dropna()
            groups = {str(name): g[a].tolist() for name, g in data.groupby(b)}
            self._pair_chart.box_by_group(groups, value=a, group=b)
        else:  # cat-cat: counts per level of the first column
            counts = frame[a].astype(str).value_counts().head(10)
            self._pair_chart.ranked_bars(
                list(counts.index), [float(v) for v in counts], f"{a} (counts)", "rows"
            )

    def _fill_drivers(self, scan: ScanResult) -> None:
        self._drivers_table.setRowCount(len(scan.drivers))
        for row, fit in enumerate(scan.drivers):
            self._drivers_table.setItem(row, 0, QTableWidgetItem(fit.predictor))
            self._drivers_table.setItem(row, 1, QTableWidgetItem(f"{fit.adj_r2:.3f}"))
            self._drivers_table.setItem(row, 2, QTableWidgetItem(f"{fit.r2:.3f}"))
            self._drivers_table.setItem(row, 3, QTableWidgetItem(fit.form))
            self._drivers_table.setItem(row, 4, QTableWidgetItem(f"{fit.p_value:.1e}"))

        if scan.drivers:
            top = scan.drivers[:10]
            self._drivers_chart.ranked_bars(
                [f.predictor for f in top],
                [max(0.0, f.adj_r2) for f in top],
                f"What explains {scan.target}?",
                "adjusted R² (one variable at a time)",
            )
        if scan.model is not None:
            model = scan.model
            lines = [
                f"{len(model.predictors)} variable(s) explain {model.adj_r2:.1%} of "
                f"{model.target} (adjusted R² = {model.adj_r2:.3f}, n = {model.n:,}).",
                "",
                "Standardized coefficients (comparable across units — bigger means more pull):",
            ]
            ranked = sorted(model.std_coefficients.items(), key=lambda kv: abs(kv[1]), reverse=True)
            for name, beta in ranked:
                vif = model.vif.get(name)
                suffix = f"   VIF {vif:.1f}" if vif is not None else ""
                lines.append(f"  {name:<22} {beta:+.3f}{suffix}")
            lines.extend(["", *model.notes])
            self._model_summary.setPlainText("\n".join(lines))
        elif scan.target:
            self._model_summary.setPlainText("No combined model — no variable earned its place.")
        else:
            self._model_summary.setPlainText(
                "Pick a target in 'Explain' to rank what accounts for it."
            )

        self._trust.set_diagnostics(scan.diagnostics)
        if scan.diagnostics is not None:
            self._residual_chart.residuals(scan.diagnostics.fitted, scan.diagnostics.residuals)

    def _fill_pca(self, scan: ScanResult) -> None:
        pca = scan.pca
        if pca is None:
            self._pca_text.setPlainText(
                "PCA needs at least three numeric columns with variation — this dataset does not "
                "have enough."
            )
            return
        self._pca_chart.scree(
            [c.explained for c in pca.components], [c.cumulative for c in pca.components]
        )
        self._pca_text.setPlainText(pca.narrative)

        shown = pca.components[:4]
        self._loadings.setColumnCount(len(shown) + 1)
        self._loadings.setHorizontalHeaderLabels(["Column", *[c.label for c in shown]])
        self._loadings.setRowCount(len(pca.columns))
        for row, column in enumerate(pca.columns):
            self._loadings.setItem(row, 0, QTableWidgetItem(column))
            for col, component in enumerate(shown, start=1):
                self._loadings.setItem(
                    row, col, QTableWidgetItem(f"{component.loadings[column]:+.2f}")
                )
        _size_columns(self._loadings)
