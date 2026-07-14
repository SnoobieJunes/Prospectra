# Prospectra

Your data buddy. A cross-platform (Windows / Linux / macOS) desktop app that connects to your
data sources, preps data on a Tableau-Prep-style flow canvas, auto-mines it for statistical
relationships (correlation scans with FDR correction, regressions ranked by R² / adjusted R²,
ANOVA, PCA), visualizes findings on dashboards, and uses LLMs plus web search to hypothesize —
with cited sources — *why* those relationships might exist.

**Status: pre-alpha (P2 done).** Working today: data connectors (CSV/TSV/text, JSON, Parquet,
Excel, and any SQL database by SQLAlchemy URL), a virtualized data grid with a column profiler,
and the **prep flow canvas** — a Tableau-Prep-style node editor with 12 prep steps that compiles a
whole pipeline into a single DuckDB query. The mining engine (regressions, ANOVA, PCA) is P3; the
LLM data buddy is P4. Anything not built yet says so in the UI rather than pretending.

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) — it provisions the right Python (3.12) automatically,
so you do **not** need Python preinstalled.

### Windows

```powershell
winget install --id=astral-sh.uv -e     # or: irm https://astral.sh/uv/install.ps1 | iex
git clone https://github.com/SnoobieJunes/Prospectra.git
cd Prospectra
uv sync                                  # install
uv run prospectra                        # launch the GUI
```

### macOS / Linux

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/SnoobieJunes/Prospectra.git && cd Prospectra
uv sync && uv run prospectra
```

Every commit is tested on Windows, Linux, and macOS in CI — the suite plus a real GUI launch on
each OS (see `.github/workflows/ci.yml`).

## Try the flow canvas in 60 seconds

1. `uv run prospectra generate-example` writes `examples/ice_cream_sales.csv` (a seeded synthetic
   dataset whose drivers are known: sales depend on temperature, school holidays, and ad spend).
2. Launch the app, go to the **Flow** tab.
3. Add an **Input: File** node, point it at that CSV; add **Aggregate** with group-by `school_out`
   and aggregation `avg(ice_cream_sales) AS avg_sales`; drag from the input's right port to the
   aggregate's left port.
4. Hit **Preview selected** — the profile cards and data preview below the canvas fill in.
5. Add an **Output** node, give it a `.csv` path, and hit **Run flow**.

## Headless CLI

The whole engine runs without a display (this is what CI exercises):

```sh
uv run prospectra generate-example                 # seeded tutorial dataset
uv run prospectra run-flow <project.prospectra> <flow-name>   # run a saved flow
uv run prospectra scan <file> --target <column>    # arrives in P3
```

## Architecture in one paragraph

`prospectra/core/` is a headless engine — no Qt imports, enforced by an import-linter contract —
covering connectors, prep flows, sampling, statistics/mining, LLM providers, and the scraper.
`prospectra/ui/` is a PySide6 shell over it. Everything extensible ships as plugins via entry
points (`prospectra.connectors`, `prospectra.flow_nodes`, `prospectra.analyses`,
`prospectra.llm_providers`, `prospectra.chart_types`) so features are easy to add — or strip out.

## License

Apache-2.0
