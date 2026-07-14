# Prospectra

Your data buddy. A cross-platform (Windows / Linux / macOS) desktop app that connects to your
data sources, preps data on a Tableau-Prep-style flow canvas, auto-mines it for statistical
relationships (correlation scans with FDR correction, regressions ranked by R² / adjusted R²,
ANOVA, PCA), visualizes findings on dashboards, and uses LLMs plus web search to hypothesize —
with cited sources — *why* those relationships might exist.

**Status: pre-alpha (P3 done).** Working today:

- **Connect** — CSV/TSV/text, JSON, Parquet, Excel, and any SQL database by SQLAlchemy URL.
- **Prep** — a Tableau-Prep-style flow canvas with 12 node types that compiles an entire pipeline
  into a single DuckDB query.
- **Mine** — point it at data and it finds what's interesting: every pair of columns tested with
  the right test for its types, false-discovery-rate control so noise columns don't masquerade as
  trends, a regression ladder (linear / log / exponential / power / quadratic) ranked by adjusted
  R², a BIC-selected combined model with standardized coefficients and VIF, a plain-English trust
  light on the model's assumptions, and PCA with a narrative that explains what it does and does
  not tell you.

- **Ask** — a data buddy you can chat with (Anthropic, OpenAI, Gemini, or a local Ollama model),
  and a "why might this be?" button on every finding that answers with cited sources.

Dashboards and the web scraper are P5. Anything not built yet says so in the UI rather than
pretending.

> **The four LLM providers are badged "experimental."** Their request formats are implemented and
> the whole pipeline around them is tested, but no provider has been run against its live API in
> this build (there are no keys here). Nothing claims to work that hasn't been observed working.

## Your data stays yours

The assistant never gets your data handed to it. It can only ask for things through tools, and
**the sharing level decides which tools exist at all** — not merely which ones get refused:

| Level | What can leave your machine |
|---|---|
| Schema only | Column names, types, row counts. No values, ever. |
| **Schema + summaries** (default) | Also counts, averages, ranges, group totals, and your findings. **Never an individual row.** |
| + sample rows | Also actual rows, via read-only queries you have explicitly allowed. |

Three things make that a guarantee rather than a promise:

- **Tools that a level forbids are absent from the request**, so no prompt can talk the model into
  them. At the default level there is no free-form SQL at all — only a structured aggregate tool,
  which has no query shape that can return a single row.
- **Every outbound request is logged locally before it is sent**, so you can read byte-for-byte
  what was shared. A test plants a sentinel value in the data, holds a whole conversation in
  schema-only mode, and asserts the sentinel appears in nothing that left the machine.
- **The model's SQL runs in a sealed DuckDB** containing only the datasets you shared, with file
  access disabled and the configuration locked — because "SELECT-only" is not a security boundary
  (`SELECT * FROM read_csv('/etc/passwd')` is a SELECT).

API keys go to your OS keychain — never the project file. Choosing **Ollama** keeps everything on
your machine.

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
uv run prospectra scan examples/ice_cream_sales.csv --target ice_cream_sales --pca
```

That last command mines the tutorial dataset, whose answer is known by construction: sales were
generated from temperature, school holidays, and ad spend, plus two decoy columns of pure noise.
The scan ranks the three real drivers at the top, rejects both decoys via FDR control, and
recovers the planted equation in its combined model (adjusted R² = 0.90).

## A word on what this tool will and won't tell you

It reports **associations, never causes.** Two columns can move together because one drives the
other, because something else drives both, or by coincidence — and no statistic can tell those
apart. In the tutorial dataset, humidity looks like it explains a third of ice cream sales; it
explains none of it, and is simply anti-correlated with temperature. Prospectra surfaces the
association, ranks it below the real drivers, and leaves the interpretation to you (with P4's
hypothesis engine offering cited leads).

## Architecture in one paragraph

`prospectra/core/` is a headless engine — no Qt imports, enforced by an import-linter contract —
covering connectors, prep flows, sampling, statistics/mining, LLM providers, and the scraper.
`prospectra/ui/` is a PySide6 shell over it. Everything extensible ships as plugins via entry
points (`prospectra.connectors`, `prospectra.flow_nodes`, `prospectra.analyses`,
`prospectra.llm_providers`, `prospectra.chart_types`) so features are easy to add — or strip out.

## License

Apache-2.0
