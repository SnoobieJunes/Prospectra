# 2026-07-13 (P1): Column profile cards — the Tableau-Prep-style per-column summaries with mini
# histograms / top-value bars. Built to the dataviz method: single-hue sequential bars (validated
# reference palette, light/dark selected per theme), thin gapped marks, text in theme ink (never
# series color), per-bar hover tooltips, no legend for a single series.

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from prospectra.core.stats import Bin, ColumnProfile, TableProfile

# dataviz reference palette, sequential blue: step 450 on light surfaces, step 400 on dark.
_BAR_LIGHT = QColor("#2a78d6")
_BAR_DARK = QColor("#3987e5")


def _on_dark_surface(widget: QWidget) -> bool:
    return widget.palette().window().color().lightness() < 128


class _Bars(QWidget):
    """Mini bar chart for one column (histogram bins or top values)."""

    def __init__(self, bins: list[Bin]) -> None:
        super().__init__()
        self._bins = bins
        self._rects: list[tuple[QRect, Bin]] = []
        self.setMinimumHeight(48)
        self.setMouseTracking(True)

    def paintEvent(self, event: QPaintEvent) -> None:
        if not self._bins:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = _BAR_DARK if _on_dark_surface(self) else _BAR_LIGHT
        peak = max(b.count for b in self._bins) or 1
        gap = 2  # surface gap between adjacent marks
        w = self.width()
        h = self.height()
        bar_w = max(3, (w - gap * (len(self._bins) - 1)) // len(self._bins))
        self._rects = []
        x = 0
        for b in self._bins:
            bar_h = max(1, round((h - 2) * b.count / peak)) if b.count else 0
            rect = QRect(x, h - bar_h, bar_w, bar_h)
            if b.count:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, 2, 2)
            # hover target spans full height so empty bins are inspectable too
            self._rects.append((QRect(x, 0, bar_w + gap, h), b))
            x += bar_w + gap

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        for rect, b in self._rects:
            if rect.contains(pos):
                QToolTip.showText(
                    self.mapToGlobal(pos + QPoint(8, -8)), f"{b.label}: {b.count:,}", self
                )
                return
        QToolTip.hideText()


class _Card(QFrame):
    def __init__(self, profile: ColumnProfile, row_count: int) -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFixedWidth(190)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        name = QLabel(profile.name)
        name.setStyleSheet("font-weight: 600;")
        name.setToolTip(profile.name)
        layout.addWidget(name)
        dtype = QLabel(profile.dtype)
        dtype.setEnabled(False)  # muted secondary ink
        layout.addWidget(dtype)

        layout.addWidget(_Bars(profile.bins if profile.numeric else profile.top))

        if profile.numeric and profile.minimum is not None:
            span = QLabel(f"{profile.minimum:.4g} to {profile.maximum:.4g}")
            span.setEnabled(False)
            layout.addWidget(span)
        detail = f"{profile.distinct:,} distinct"
        if profile.null_count:
            pct = 100.0 * profile.null_count / row_count if row_count else 0.0
            detail += f" · {pct:.0f}% null"
        info = QLabel(detail)
        info.setEnabled(False)
        layout.addWidget(info)


class ProfileCardsPanel(QScrollArea):
    """Horizontal strip of column cards for a TableProfile."""

    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._body = QWidget()
        self._layout = QHBoxLayout(self._body)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self.setWidget(self._body)
        self.setMinimumHeight(170)

    def clear(self) -> None:
        while self._layout.count() > 1:  # keep the trailing stretch
            item = self._layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def set_profile(self, profile: TableProfile) -> None:
        self.clear()
        for column in profile.columns:
            self._layout.insertWidget(self._layout.count() - 1, _Card(column, profile.sample_size))
