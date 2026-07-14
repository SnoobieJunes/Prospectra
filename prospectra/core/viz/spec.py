# 2026-07-14 (P5): ChartSpec — a chart described as data, not as code.
#
# Why a spec and not a chart object: dashboards are *saved*, so a chart must survive a JSON
# round-trip into the project file and be re-renderable months later; and the drag-and-drop shelves
# need something to mutate that isn't a matplotlib figure. The renderer (ui/widgets/spec_chart.py)
# is one consumer of this model; the CSV exporter is another; a future chart-type plugin registered
# under `prospectra.chart_types` is a third.
#
# The spec deliberately refuses the two things the dataviz method forbids by construction:
# there is no second y-axis (one `y`, one scale), and there is no per-series colour override — the
# `color` field names a *column*, and hues are assigned from a fixed categorical order by the
# renderer, so a filter that removes a series never repaints the survivors.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

SPEC_SCHEMA = 1

MARKS: tuple[str, ...] = ("bar", "line", "scatter", "box", "histogram")
AGGREGATIONS: tuple[str, ...] = ("sum", "mean", "median", "count", "min", "max")
SCALES: tuple[str, ...] = ("linear", "log")

# Marks whose y value is computed by grouping x (and colour); the others plot raw rows.
AGGREGATING_MARKS: tuple[str, ...] = ("bar", "line")
DEFAULT_LIMIT = 30  # top-N categories on a bar chart; beyond this a bar chart is unreadable
MAX_POINTS = 5000  # scatter/box: enough to see the shape, few enough to stay responsive


@dataclass
class ChartSpec:
    """One chart: a mark, the columns it reads, and the scales it reads them on."""

    mark: str = "bar"
    x: str = ""
    y: str = ""
    color: str = ""  # a *column* name — series identity, never a hue
    agg: str = "sum"
    x_scale: str = "linear"
    y_scale: str = "linear"
    limit: int = DEFAULT_LIMIT
    title: str = ""
    # Lineage: which dataset this chart reads. `dataset` is the catalog display name (how a tile
    # finds its data again after a restart); `origin` is the human provenance, kept so a dashboard
    # can say *which* file it wanted when that dataset is not open.
    dataset: str = ""
    origin: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    # -- validation ---------------------------------------------------------------------------

    def validate(self) -> None:
        """Raise ValueError with a fixable message; called before any SQL is built."""
        if self.mark not in MARKS:
            raise ValueError(f"unknown mark {self.mark!r} (have: {', '.join(MARKS)})")
        if self.agg not in AGGREGATIONS:
            raise ValueError(f"unknown aggregation {self.agg!r}")
        if self.x_scale not in SCALES or self.y_scale not in SCALES:
            raise ValueError("scales must be 'linear' or 'log'")
        if not self.x:
            raise ValueError("drop a column on the X shelf")
        if self.mark == "histogram":
            return  # a histogram needs x alone — it counts rows itself
        if self.aggregating and self.agg == "count":
            return  # count needs no y column either
        if not self.y:
            raise ValueError("drop a column on the Y shelf")

    @property
    def aggregating(self) -> bool:
        return self.mark in AGGREGATING_MARKS

    @property
    def y_label(self) -> str:
        if self.mark == "histogram":
            return "rows"
        if self.aggregating:
            return "rows" if self.agg == "count" else f"{self.agg} of {self.y}"
        return self.y

    @property
    def display_title(self) -> str:
        if self.title:
            return self.title
        if self.mark == "histogram":
            return f"Distribution of {self.x}"
        base = f"{self.y_label} by {self.x}"
        return f"{base}, split by {self.color}" if self.color else base

    # -- persistence --------------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_schema": SPEC_SCHEMA,
            "id": self.id,
            "mark": self.mark,
            "x": self.x,
            "y": self.y,
            "color": self.color,
            "agg": self.agg,
            "x_scale": self.x_scale,
            "y_scale": self.y_scale,
            "limit": self.limit,
            "title": self.title,
            "dataset": self.dataset,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> ChartSpec:
        version = int(doc.get("spec_schema", SPEC_SCHEMA))
        if version > SPEC_SCHEMA:
            raise ValueError(
                f"Chart schema v{version} is newer than this app supports (v{SPEC_SCHEMA})"
            )
        return cls(
            mark=str(doc.get("mark", "bar")),
            x=str(doc.get("x", "")),
            y=str(doc.get("y", "")),
            color=str(doc.get("color", "")),
            agg=str(doc.get("agg", "sum")),
            x_scale=str(doc.get("x_scale", "linear")),
            y_scale=str(doc.get("y_scale", "linear")),
            limit=int(doc.get("limit", DEFAULT_LIMIT)),
            title=str(doc.get("title", "")),
            dataset=str(doc.get("dataset", "")),
            origin=str(doc.get("origin", "")),
            id=str(doc.get("id", uuid.uuid4().hex)),
        )
