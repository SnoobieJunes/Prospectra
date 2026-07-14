# 2026-07-13 (P3): Charts for the Analyze workspace, embedded matplotlib (no pyplot — no global
# state, safe next to worker threads).
#
# Built to the dataviz method: form follows the data's job (ranked magnitudes -> horizontal bars;
# relationship -> scatter + fit; group distributions -> box; variance decomposition -> scree).
# One series means no legend (the title names it) and a single sequential hue from the validated
# reference palette; text always wears theme ink, never the series colour; grid and axes stay
# recessive; every chart has a hover layer. Status colours (the trust light) are reserved and
# always ship with a text label, never colour alone.

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from numpy.typing import NDArray
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QWidget

# Reference palette — sequential blue: step 450 on light surfaces, 400 on dark.
SERIES_LIGHT = "#2a78d6"
SERIES_DARK = "#3987e5"
# Reserved status colours (good / caution / poor). Never used for a data series.
STATUS = {"good": "#008300", "caution": "#eda100", "poor": "#e34948"}


class Chart(FigureCanvasQTAgg):
    """A theme-aware figure with one axes and a hover readout."""

    def __init__(self, parent: QWidget | None = None, height: float = 2.6) -> None:
        self._figure = Figure(figsize=(5.0, height), layout="constrained")
        super().__init__(self._figure)
        if parent is not None:
            self.setParent(parent)
        self.axes = self._figure.add_subplot(111)
        self._annotation: Any = None  # matplotlib Annotation; created lazily on first hover
        self._hover_points: list[tuple[float, float, str]] = []
        self.mpl_connect("motion_notify_event", self._on_hover)

    # -- theme ---------------------------------------------------------------------------

    def _theme(self) -> QPalette:
        """The palette to draw against.

        NOT self.palette(): matplotlib's Qt canvas forces its own all-white palette in its
        constructor, so asking the canvas would report "light theme" forever and every chart
        would render white-on-dark. Ask the parent widget (or the application) instead.
        """
        parent = self.parentWidget()
        if parent is not None:
            return parent.palette()
        app = QApplication.instance()
        return app.palette() if isinstance(app, QApplication) else self.palette()

    @property
    def _dark(self) -> bool:
        return self._theme().window().color().lightness() < 128

    @property
    def series_color(self) -> str:
        return SERIES_DARK if self._dark else SERIES_LIGHT

    def _style(self, title: str = "", xlabel: str = "", ylabel: str = "") -> None:
        ink = self._theme().text().color().name()
        surface = self._theme().base().color().name()
        self._figure.set_facecolor(surface)
        self.axes.set_facecolor(surface)
        self.axes.set_title(title, color=ink, fontsize=10, loc="left")
        self.axes.set_xlabel(xlabel, color=ink, fontsize=9)
        self.axes.set_ylabel(ylabel, color=ink, fontsize=9)
        self.axes.tick_params(colors=ink, labelsize=8)
        for side, spine in self.axes.spines.items():
            spine.set_visible(side in ("left", "bottom"))
            spine.set_color(ink)
            spine.set_alpha(0.3)
        self.axes.grid(True, color=ink, alpha=0.12, linewidth=0.8)  # recessive
        self.axes.set_axisbelow(True)

    def _reset(self) -> None:
        self.axes.clear()
        self._annotation = None
        self._hover_points = []

    # -- hover ---------------------------------------------------------------------------

    def _on_hover(self, event) -> None:
        if event.inaxes is not self.axes or not self._hover_points:
            if self._annotation is not None and self._annotation.get_visible():
                self._annotation.set_visible(False)
                self.draw_idle()
            return
        # nearest point in display coordinates, so the hit target is uniform on screen
        cursor = np.array([event.x, event.y])
        best, best_distance = None, 1e9
        for x, y, label in self._hover_points:
            px, py = self.axes.transData.transform((x, y))
            distance = float(np.hypot(px - cursor[0], py - cursor[1]))
            if distance < best_distance:
                best, best_distance = (x, y, label), distance
        if best is None or best_distance > 30:  # generous hit target
            if self._annotation is not None and self._annotation.get_visible():
                self._annotation.set_visible(False)
                self.draw_idle()
            return
        x, y, label = best
        ink = self._theme().text().color().name()
        surface = self._theme().base().color().name()
        if self._annotation is None:
            self._annotation = self.axes.annotate(
                "",
                xy=(0, 0),
                xytext=(10, 10),
                textcoords="offset points",
                fontsize=8,
                bbox={"boxstyle": "round,pad=0.4", "fc": surface, "ec": ink, "alpha": 0.95},
            )
        self._annotation.xy = (x, y)
        self._annotation.set_text(label)
        self._annotation.set_color(ink)
        self._annotation.set_visible(True)
        self.draw_idle()

    # -- forms ---------------------------------------------------------------------------

    def scatter_with_fit(
        self, x: Sequence[float], y: Sequence[float], xlabel: str, ylabel: str, fit_label: str = ""
    ) -> None:
        """Relationship between two numeric columns, with the fitted trend drawn over it."""
        self._reset()
        xs: NDArray[np.float64] = np.asarray(x, dtype=float)
        ys: NDArray[np.float64] = np.asarray(y, dtype=float)
        self.axes.scatter(xs, ys, s=18, color=self.series_color, alpha=0.55, linewidths=0, zorder=2)
        if len(xs) >= 2 and float(np.std(xs)) > 0:
            order = np.argsort(xs)
            slope, intercept = np.polyfit(xs, ys, 1)
            ink = self._theme().text().color().name()
            self.axes.plot(
                xs[order],
                slope * xs[order] + intercept,
                color=ink,
                linewidth=2,
                alpha=0.75,
                zorder=3,
                label=fit_label or None,
            )
        self._hover_points = [
            (float(a), float(b), f"{xlabel}: {a:.4g}\n{ylabel}: {b:.4g}")
            for a, b in zip(xs[:2000], ys[:2000], strict=False)
        ]
        self._style(title=f"{ylabel} vs {xlabel}", xlabel=xlabel, ylabel=ylabel)
        self.draw_idle()

    def ranked_bars(
        self, labels: Sequence[str], values: Sequence[float], title: str, xlabel: str
    ) -> None:
        """Ranked magnitudes -> horizontal bars, strongest at the top."""
        self._reset()
        y_positions = np.arange(len(labels))[::-1]
        bars = self.axes.barh(
            y_positions, list(values), height=0.68, color=self.series_color, zorder=2
        )
        self.axes.set_yticks(y_positions, list(labels), fontsize=8)
        ink = self._theme().text().color().name()
        for bar, value in zip(bars, values, strict=True):  # direct labels: no legend needed
            self.axes.annotate(
                f"{value:.2f}",
                (bar.get_width(), bar.get_y() + bar.get_height() / 2),
                xytext=(4, 0),
                textcoords="offset points",
                va="center",
                fontsize=8,
                color=ink,
            )
        self._hover_points = [
            (float(v), float(pos), f"{label}: {v:.3f}")
            for label, v, pos in zip(labels, values, y_positions, strict=True)
        ]
        self._style(title=title, xlabel=xlabel)
        self.draw_idle()

    def box_by_group(self, groups: dict[str, Sequence[float]], value: str, group: str) -> None:
        """Distribution of a numeric column across the levels of a category."""
        self._reset()
        names = list(groups)
        data: list[NDArray[np.float64]] = [np.asarray(groups[name], dtype=float) for name in names]
        ink = self._theme().text().color().name()
        boxes = self.axes.boxplot(
            data,
            tick_labels=names,
            patch_artist=True,
            widths=0.55,
            medianprops={"color": ink, "linewidth": 2},
            flierprops={
                "marker": "o",
                "markersize": 3,
                "alpha": 0.4,
                "markerfacecolor": self.series_color,
                "markeredgecolor": "none",
            },
        )
        for patch in boxes["boxes"]:
            patch.set_facecolor(self.series_color)
            patch.set_alpha(0.55)
            patch.set_edgecolor(self.series_color)
        self._hover_points = [
            (
                float(i + 1),
                float(np.median(values)),
                f"{name}\nmedian: {np.median(values):.4g}\nn = {len(values):,}",
            )
            for i, (name, values) in enumerate(zip(names, data, strict=True))
        ]
        self._style(title=f"{value} by {group}", xlabel=group, ylabel=value)
        self.axes.tick_params(axis="x", rotation=30 if len(names) > 4 else 0)
        self.draw_idle()

    def scree(self, explained: Sequence[float], cumulative: Sequence[float]) -> None:
        """PCA variance decomposition. Both series share one 0-100% scale — never a second axis."""
        self._reset()
        indices = np.arange(1, len(explained) + 1)
        ink = self._theme().text().color().name()
        self.axes.bar(
            indices,
            [v * 100 for v in explained],
            width=0.6,
            color=self.series_color,
            zorder=2,
            label="variance explained by this component",
        )
        self.axes.plot(
            indices,
            [v * 100 for v in cumulative],
            color=ink,
            linewidth=2,
            marker="o",
            markersize=5,
            alpha=0.8,
            zorder=3,
            label="running total",
        )
        self.axes.set_xticks(indices, [f"PC{i}" for i in indices], fontsize=8)
        self.axes.set_ylim(0, 105)
        self._hover_points = [
            (float(i), v * 100, f"PC{i}: {v:.1%} of variance\nrunning total {c:.0%}")
            for i, v, c in zip(indices, explained, cumulative, strict=True)
        ]
        self._style(title="How much variation each component captures", ylabel="% of variation")
        legend = self.axes.legend(fontsize=8, frameon=False, loc="center right")  # two series
        for text in legend.get_texts():
            text.set_color(ink)
        self.draw_idle()

    def residuals(self, fitted: Sequence[float], resid: Sequence[float]) -> None:
        """Residuals vs fitted — the shape here is what the trust light is reading."""
        self._reset()
        ink = self._theme().text().color().name()
        self.axes.axhline(0, color=ink, linewidth=1, alpha=0.4, zorder=1)
        self.axes.scatter(
            list(fitted),
            list(resid),
            s=14,
            color=self.series_color,
            alpha=0.5,
            linewidths=0,
            zorder=2,
        )
        self._hover_points = [
            (float(f), float(r), f"predicted: {f:.4g}\nerror: {r:+.4g}")
            for f, r in list(zip(fitted, resid, strict=True))[:2000]
        ]
        self._style(
            title="Errors should scatter evenly around zero",
            xlabel="predicted value",
            ylabel="error (actual minus predicted)",
        )
        self.draw_idle()
