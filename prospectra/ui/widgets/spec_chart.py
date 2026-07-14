# 2026-07-14 (P5): Renders a ChartSpec + ChartData. The dashboard's only renderer.
#
# Built to the dataviz method (loaded before writing this file, per CLAUDE.md):
#   * Form follows the data's job — the spec's mark IS the form choice, and the shelf UI only
#     offers marks that fit what was dropped.
#   * ONE axis, always. `ChartSpec` cannot express a second y-scale, so a dual-axis chart is
#     unrepresentable rather than merely discouraged — the single most common chart mistake is
#     designed out of the model.
#   * Colour by job: one series -> the sequential blue (no legend; the title names it). Several
#     series -> the validated categorical order, assigned in fixed slot order and keyed to the
#     series *name*, so filtering out a series never repaints the survivors. Past 8 series the 9th+
#     fold into "Other" instead of inventing hues.
#   * Text wears theme ink, never the series colour. Grid and axes stay recessive. Every mark has a
#     hover readout (inherited from Chart).
#   * Notes (top-N truncation, points a log scale cannot show) are rendered as a caption *on the
#     figure*, so an exported PNG carries its caveats with it.

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtWidgets import QWidget

from prospectra.core.viz.query import ChartData
from prospectra.core.viz.spec import ChartSpec
from prospectra.ui.widgets.charts import Chart

# The validated categorical order from the dataviz reference palette (light / dark steps).
# The ORDER is the colourblind-safety mechanism — do not reorder or cycle it.
CATEGORICAL_LIGHT = (
    "#2a78d6",  # blue
    "#1baf7a",  # aqua
    "#eda100",  # yellow
    "#008300",  # green
    "#4a3aa7",  # violet
    "#e34948",  # red
    "#e87ba4",  # magenta
    "#eb6834",  # orange
)
CATEGORICAL_DARK = (
    "#3987e5",
    "#199e70",
    "#c98500",
    "#008300",
    "#9085e9",
    "#e66767",
    "#d55181",
    "#d95926",
)
MAX_SERIES = len(CATEGORICAL_LIGHT)
OTHER = "Other"


class SpecChart(Chart):
    """One ChartSpec, drawn. Reuses Chart's theme handling, styling, and hover layer."""

    def __init__(self, parent: QWidget | None = None, height: float = 3.0) -> None:
        super().__init__(parent=parent, height=height)
        self.spec: ChartSpec | None = None

    # -- colour ---------------------------------------------------------------------------------

    def _palette(self) -> tuple[str, ...]:
        return CATEGORICAL_DARK if self._dark else CATEGORICAL_LIGHT

    def _series_colors(self, names: list[str]) -> dict[str, str]:
        """Fixed-order slot assignment, keyed by series name (identity, never rank)."""
        palette = self._palette()
        return {name: palette[i % len(palette)] for i, name in enumerate(names)}

    @staticmethod
    def _fold_others(names: list[str]) -> dict[str, str]:
        """Series past the 8th become 'Other' — a 9th hue would not be colourblind-safe."""
        keep = names[:MAX_SERIES]
        return {name: (name if name in keep else OTHER) for name in names}

    # -- rendering ------------------------------------------------------------------------------

    def render(self, data: ChartData) -> None:
        """Draw the spec. Each mark reports the axes it actually used — a single-series bar is
        horizontal (ranked magnitudes read better that way), which swaps x and y, and the log
        scale has to follow the *value* axis wherever it ended up."""
        spec = data.spec
        self.spec = spec
        self._reset()

        if spec.mark == "histogram":
            self._histogram(data)
            xlabel, ylabel, value_axis = spec.x, "rows", "y"
        elif spec.mark == "scatter":
            self._scatter(data)
            xlabel, ylabel, value_axis = spec.x, spec.y, "y"
        elif spec.mark == "box":
            self._box(data)
            xlabel, ylabel, value_axis = spec.x, spec.y, "y"
        elif spec.mark == "line":
            self._series_plot(data, line=True)
            xlabel, ylabel, value_axis = spec.x, spec.y_label, "y"
        elif spec.color:
            self._series_plot(data, line=False)
            xlabel, ylabel, value_axis = spec.x, spec.y_label, "y"
        else:
            self._horizontal_bars(data)
            xlabel, ylabel, value_axis = spec.y_label, spec.x, "x"

        self._style(title=spec.display_title, xlabel=xlabel, ylabel=ylabel)
        if spec.x_scale == "log" and spec.mark in ("scatter", "histogram"):
            self.axes.set_xscale("log")
        if spec.y_scale == "log" and spec.mark != "histogram":
            self.axes.set_xscale("log") if value_axis == "x" else self.axes.set_yscale("log")
        self._caption(data)
        self.draw_idle()

    def _caption(self, data: ChartData) -> None:
        """Truncation and dropped-point notes ride on the figure, so a PNG never loses them.

        Drawn as the figure's supxlabel rather than free-floating figure text: constrained layout
        *reserves space* for a supxlabel, and a plain figure.text is not accounted for — in a
        rendered PNG the note landed on top of the x-axis label. Always set (empty when there are
        no notes), so a re-render never leaves a stale caption from the previous spec behind.
        """
        ink = self._theme().text().color().name()
        self._figure.supxlabel(
            "  ".join(data.notes),
            fontsize=7,
            color=ink,
            alpha=0.75,
            x=0.01,
            ha="left",
        )

    @staticmethod
    def _compact(value: float) -> str:
        """32383920 -> "32.4M". A bar labelled 3.2e7 is a bar nobody can read."""
        magnitude = abs(value)
        for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
            if magnitude >= cutoff:
                return f"{value / cutoff:,.1f}{suffix}"
        return f"{value:,.3g}"

    def _legend(self, names: list[str]) -> None:
        if len(names) < 2:  # one series needs no legend — the title names it
            return
        ink = self._theme().text().color().name()
        legend = self.axes.legend(fontsize=8, frameon=False, loc="best")
        for text in legend.get_texts():
            text.set_color(ink)

    # -- marks ----------------------------------------------------------------------------------

    def _grouped(self, data: ChartData) -> tuple[list[str], dict[str, list[tuple[Any, float]]]]:
        folded = self._fold_others(data.series_names)
        grouped: dict[str, list[tuple[Any, float]]] = {}
        for x, series, y in zip(data.x, data.series, data.y, strict=True):
            grouped.setdefault(folded.get(series, series), []).append((x, y))
        return list(grouped), grouped

    def _horizontal_bars(self, data: ChartData) -> None:
        """Single-series bar: ranked magnitudes, strongest at the top, directly labelled."""
        spec = data.spec
        labels = [str(x) for x in data.x]
        positions = np.arange(len(labels))[::-1]
        bars = self.axes.barh(positions, data.y, height=0.68, color=self.series_color, zorder=2)
        self.axes.set_yticks(positions, labels, fontsize=8)
        if len(labels) <= 15 and spec.y_scale != "log":  # selective direct labels, not every point
            ink = self._theme().text().color().name()
            for bar, value in zip(bars, data.y, strict=True):
                self.axes.annotate(
                    self._compact(value),
                    (bar.get_width(), bar.get_y() + bar.get_height() / 2),
                    xytext=(4, 0),
                    textcoords="offset points",
                    va="center",
                    fontsize=8,
                    color=ink,  # text wears theme ink, never the series colour
                )
            self.axes.margins(x=0.12)  # room for the labels, so the longest one is not clipped
        self._hover_points = [
            (float(y), float(pos), f"{label}\n{spec.y_label}: {y:,.4g}")
            for label, y, pos in zip(labels, data.y, positions, strict=True)
        ]

    def _series_plot(self, data: ChartData, *, line: bool) -> None:
        spec = data.spec
        names, grouped = self._grouped(data)
        colors = self._series_colors(names) if spec.color else {}
        hover: list[tuple[float, float, str]] = []

        if line:
            for name in names:
                points = sorted(grouped[name], key=lambda p: str(p[0]))
                xs = [str(p[0]) for p in points]
                ys = [p[1] for p in points]
                colour = colors.get(name, self.series_color)
                self.axes.plot(
                    xs, ys, color=colour, linewidth=2, marker="o", markersize=4, label=name or None
                )
                hover += [
                    (float(i), y, f"{name + ': ' if name else ''}{x}\n{spec.y_label}: {y:,.4g}")
                    for i, (x, y) in enumerate(zip(xs, ys, strict=True))
                ]
            self.axes.tick_params(axis="x", rotation=30 if len(data.x) > 6 else 0)
        else:  # grouped bars: one cluster per x value, one bar per series
            categories = list(dict.fromkeys(str(x) for x in data.x))
            index = {name: i for i, name in enumerate(categories)}
            width = 0.8 / max(1, len(names))
            for slot, name in enumerate(names):
                values = dict.fromkeys(categories, 0.0)
                for x, y in grouped[name]:
                    values[str(x)] = y
                positions = [index[c] + slot * width - 0.4 + width / 2 for c in categories]
                self.axes.bar(
                    positions,
                    [values[c] for c in categories],
                    width=width * 0.9,  # 2px-equivalent gap between adjacent fills
                    color=colors[name],
                    label=name,
                    zorder=2,
                )
                hover += [
                    (p, values[c], f"{name}\n{c}\n{spec.y_label}: {values[c]:,.4g}")
                    for p, c in zip(positions, categories, strict=True)
                ]
            self.axes.set_xticks(range(len(categories)), categories, fontsize=8)
            self.axes.tick_params(axis="x", rotation=30 if len(categories) > 5 else 0)

        self._hover_points = hover
        self._legend(names if spec.color else [])

    def _scatter(self, data: ChartData) -> None:
        spec = data.spec
        names, grouped = self._grouped(data)
        colors = self._series_colors(names) if spec.color else {}
        hover: list[tuple[float, float, str]] = []
        for name in names:
            points = grouped[name]
            xs = [float(p[0]) for p in points]
            ys = [float(p[1]) for p in points]
            self.axes.scatter(
                xs,
                ys,
                s=18,
                color=colors.get(name, self.series_color),
                alpha=0.6,
                linewidths=0,
                zorder=2,
                label=name or None,
            )
            hover += [
                (x, y, f"{name + chr(10) if name else ''}{spec.x}: {x:,.4g}\n{spec.y}: {y:,.4g}")
                for x, y in list(zip(xs, ys, strict=True))[:1500]
            ]
        self._hover_points = hover
        self._legend(names if spec.color else [])

    def _box(self, data: ChartData) -> None:
        spec = data.spec
        groups: dict[str, list[float]] = {}
        for x, y in zip(data.x, data.y, strict=True):
            groups.setdefault(str(x), []).append(float(y))
        names = list(groups)[: MAX_SERIES * 2]  # a box plot past ~16 groups is unreadable
        ink = self._theme().text().color().name()
        boxes = self.axes.boxplot(
            [groups[name] for name in names],
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
                float(np.median(groups[name])),
                f"{name}\nmedian {spec.y}: {np.median(groups[name]):,.4g}\n"
                f"n = {len(groups[name]):,}",
            )
            for i, name in enumerate(names)
        ]
        self.axes.tick_params(axis="x", rotation=30 if len(names) > 4 else 0)

    def _histogram(self, data: ChartData) -> None:
        values = np.asarray(data.x, dtype=float)
        if values.size == 0:
            return
        bins = int(np.clip(np.sqrt(values.size), 8, 40))
        counts, edges, _patches = self.axes.hist(
            values, bins=bins, color=self.series_color, zorder=2
        )
        centres = (edges[:-1] + edges[1:]) / 2
        self._hover_points = [
            (
                float(c),
                float(n),
                f"{data.spec.x}: {edges[i]:,.4g} to {edges[i + 1]:,.4g}\n{n:,.0f} rows",
            )
            for i, (c, n) in enumerate(zip(centres, counts, strict=True))
        ]
