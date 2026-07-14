# 2026-07-14 (P5): A dashboard is a saved grid of ChartSpecs — nothing more. Because the spec is
# JSON, the whole dashboard is JSON, which is what lets it live in the project file's `dashboards`
# table (a P0 schema table, finally used) and reopen months later against the same datasets.
#
# Tiles carry their grid position so a reopened dashboard has the layout the user arranged, not an
# arbitrary reflow.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from prospectra.core.viz.spec import ChartSpec

DASHBOARD_SCHEMA = 1
COLUMNS = 2  # tiles per row


@dataclass
class Tile:
    spec: ChartSpec
    row: int = 0
    column: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"row": self.row, "column": self.column, "spec": self.spec.to_dict()}

    @classmethod
    def from_dict(cls, doc: dict[str, Any]) -> Tile:
        return cls(
            spec=ChartSpec.from_dict(doc["spec"]),
            row=int(doc.get("row", 0)),
            column=int(doc.get("column", 0)),
        )


@dataclass
class Dashboard:
    name: str = "Dashboard"
    tiles: list[Tile] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def add(self, spec: ChartSpec) -> Tile:
        """Append a chart, filling the grid left to right, top to bottom."""
        position = len(self.tiles)
        tile = Tile(spec=spec, row=position // COLUMNS, column=position % COLUMNS)
        self.tiles.append(tile)
        return tile

    def remove(self, spec_id: str) -> None:
        self.tiles = [t for t in self.tiles if t.spec.id != spec_id]
        for position, tile in enumerate(self.tiles):  # close the gap the removal left
            tile.row, tile.column = position // COLUMNS, position % COLUMNS

    def datasets(self) -> list[str]:
        """Every dataset this dashboard needs open to render fully."""
        names: list[str] = []
        for tile in self.tiles:
            if tile.spec.dataset and tile.spec.dataset not in names:
                names.append(tile.spec.dataset)
        return names

    # -- persistence --------------------------------------------------------------------------

    def to_doc(self) -> dict[str, Any]:
        return {
            "dashboard_schema": DASHBOARD_SCHEMA,
            "id": self.id,
            "name": self.name,
            "tiles": [tile.to_dict() for tile in self.tiles],
        }

    @classmethod
    def from_doc(cls, doc: dict[str, Any]) -> Dashboard:
        version = int(doc.get("dashboard_schema", DASHBOARD_SCHEMA))
        if version > DASHBOARD_SCHEMA:
            raise ValueError(
                f"Dashboard schema v{version} is newer than this app supports (v{DASHBOARD_SCHEMA})"
            )
        return cls(
            name=str(doc.get("name", "Dashboard")),
            tiles=[Tile.from_dict(t) for t in doc.get("tiles", [])],
            id=str(doc.get("id", uuid.uuid4().hex)),
        )
