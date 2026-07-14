# 2026-07-14 (P5): Export a chart's *data* (not its picture) to CSV — "show me the numbers behind
# this bar" is the first question anyone asks of a dashboard, and the dataviz method requires a
# table view to exist wherever colour carries meaning.
#
# Windows rule (CLAUDE.md): the handle is opened with newline="" so csv never writes \r\r\n.
# PNG export lives in the UI (ui/dashboards/chart_tile.py) because only the UI owns a figure.

from __future__ import annotations

import csv
from pathlib import Path

from prospectra.core.viz.query import ChartData


def data_to_csv(data: ChartData, path: Path | str) -> Path:
    """Write the chart's rows, with the notes (truncation, dropped points) as leading comments."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for note in data.notes:  # the caveats travel with the numbers, not just on screen
            writer.writerow([f"# {note}"])
        if data.spec.mark == "histogram":
            writer.writerow([data.spec.x])
            writer.writerows([[value] for value in data.x])
        else:
            writer.writerow(data.header())
            writer.writerows(data.rows())
    return out
