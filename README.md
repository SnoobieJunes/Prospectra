# Prospectra

Your data buddy. A cross-platform (Windows / Linux / macOS) desktop app that connects to your
data sources, preps data on a Tableau-Prep-style flow canvas, auto-mines it for statistical
relationships (correlation scans with FDR correction, regressions ranked by R² / adjusted R²,
ANOVA, PCA), visualizes findings on dashboards, and uses LLMs plus web search to hypothesize —
with cited sources — *why* those relationships might exist.

**Status: pre-alpha (P0 — skeleton).** The app shell, project file format, headless CLI, and the
synthetic tutorial dataset exist. Connectors, the flow canvas, and the mining engine arrive in
phases P1–P3 (see the build plan referenced in `CLAUDE.md`).

## Quickstart

Requires [uv](https://docs.astral.sh/uv/) (it provisions Python ≥ 3.11 automatically):

```sh
uv sync                 # install
uv run prospectra       # launch the GUI
uv run pytest           # run tests
```

Headless CLI (the whole engine will always be drivable without a display):

```sh
uv run prospectra generate-example   # regenerate examples/ice_cream_sales.csv (seeded)
uv run prospectra scan <file> --target <column>   # arrives in P3
uv run prospectra run-flow <project> <flow>       # arrives in P2
```

## Architecture in one paragraph

`prospectra/core/` is a headless engine — no Qt imports, enforced by an import-linter contract —
covering connectors, prep flows, sampling, statistics/mining, LLM providers, and the scraper.
`prospectra/ui/` is a PySide6 shell over it. Everything extensible ships as plugins via entry
points (`prospectra.connectors`, `prospectra.flow_nodes`, `prospectra.analyses`,
`prospectra.llm_providers`, `prospectra.chart_types`) so features are easy to add — or strip out.

## License

Apache-2.0
