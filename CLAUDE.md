## Communication — no sycophancy, no placating

The user does **not** want a yes-man. This is a hard rule, not a style preference.

- **Banned:** flattery, validation openers ("You're right", "Great question",
  "Absolutely"), reflexive apologies, and agreeing just to be agreeable. Lead with the
  fact or the action, never with reassurance.
- **Tell the truth even when it's unwelcome.** If something is broken, can't be done,
  or was claimed done but wasn't, say so plainly and show the evidence.
- **Never report a build, test, or feature as working without having run it and seen it
  pass.** Distinguish what is *proven* (ran it, saw the output) from what is *inferred*
  or *compile-checked only*. Label every unverified claim as unverified.
- Don't soften bad news with hedges or padding. Disagree when the evidence warrants it.

## Engineering conventions
- Always timestamp every code change in the comments, followed by a clear explanation of what / why this code was written.
- No monolithic code
- Ensure modular codebase, so it can be opensourced and others can easily add to or widdle down various features and functionalities.
- Any deviation from the plan must be recorded in Deviations.md, with an explanation as to why the plan was not followed.  Tag it to the commits
- When unsure, present with a decision to the user
- Be efficient with token usage, use lesser models and cross reference with adversarial analysis.
- Build the project in python using QT.
- It must work on Windows, Linux and Mac

## Project: Prospectra

Cross-platform PySide6 desktop app — "your data buddy": data connectors → Tableau-Prep-style
flow canvas → statistical mining (correlation scan + BH-FDR, regression ladder ranked by
R²/adj-R², ANOVA, PCA) → dashboards → LLM chat with cited internet hypotheses for findings.
Approved build plan (phases P0–P6): `~/.claude/plans/i-want-you-to-immutable-blossom.md`.
Repo: https://github.com/SnoobieJunes/Prospectra

### Status
- P0 (skeleton: app shell, project store, headless CLI, example dataset, tooling) — done 2026-07-13.
- P1 (connectors, catalog, virtualized grid, column profiler, sampling) — done 2026-07-13.
- P2 (flow engine + node set + canvas UI + headless `run-flow` + cross-OS CI) — done 2026-07-13.
- P3 (mining engine: pair tests + BH-FDR, regression ladder, multivariate model, ANOVA, PCA,
  diagnostics, Analyze workspace, headless `scan`) — done 2026-07-13.
- P4 (data buddy: 4 providers, keychain, privacy gate, sandboxed SQL tools, chat dock, hypothesis
  engine with cited sources) — done 2026-07-14. **No provider has been run against a live API —
  all four are badged "experimental" until one is.**
- P5 (scraper + `scrape` CLI, ChartSpec dashboards, drag-and-drop backbone) — done 2026-07-14.
  Proven end to end against **live Wikipedia**: scraped the GDP table → 7-node prep flow →
  FDR-controlled finding → chart on a dashboard saved in the project file.
- Next: P6 — connector breadth (warehouse dialects, ODBC/JDBC, REST + mapping tool), Jira reference
  plugin, plugin docs, PyInstaller builds for all 3 OSes.

### Scraper rules (do not regress these)
- **robots.txt is obeyed, and the check happens *before* the request** (`core/scraper/fetcher.py`).
  A disallow raises `RobotsDisallowed` and nothing is fetched; a redirect's destination is re-checked.
  A missing robots.txt means allowed (that is what the standard says), but a refusal is never
  worked around. Rate limiting is **per host** (1 req/s default), and a site's `Crawl-delay` raises
  that interval, never lowers it.
- **Scraped tables are written as ordinary CSVs into the project's staging folder** and opened
  through the normal file connector. That is the whole design: a scraped table is just a dataset,
  so it feeds the catalog, flows, and the miner with no special-casing.
- **The scraper does not coerce types.** Wikipedia ships `—N/a`, `98,964 (2024)` and `China[n 1]`;
  cleaning those is the *flow's* job (TRY_CAST in a Calculated node), not a silent guess in the
  parser. Headers are cleaned (footnotes stripped, collisions made unique) because they become SQL
  identifiers; values are left alone.
- **Page furniture is not data.** Tables under 2 rows or 2 columns are dropped — a live scrape
  emitted the page's map *legend* as a dataset until that floor existed.

### Chart rules (do not regress these)
- **A dual-axis chart is unrepresentable, not merely discouraged**: `ChartSpec` has one `y` and one
  y-scale. Two measures of different scale = two charts.
- **Truncation and dropped points are always stated.** A top-N bar chart says "showing the top 10 of
  194"; a log scale that cannot show zero/negative rows counts them and says so. The note is drawn
  as the figure's `supxlabel`, so an exported PNG carries its caveats with it.
- **Colour follows the entity, never its rank** — hues come from the validated categorical order in
  `ui/widgets/spec_chart.py`, keyed by series name; the 9th series folds into "Other" rather than
  inventing a hue. One series gets the sequential blue and no legend (the title names it).
- Before touching any chart code: load the `dataviz` skill.

### Statistical rules (do not regress these)
- **Never rank R² across different response transforms.** A log-y model's R² describes ln(y), not
  y. `core/stats/regression.py` back-transforms predictions and scores every form on the original
  target scale (`Fit.r2`); the model's own value is kept separately as `Fit.native_r2`.
- **Every scan of many pairs gets Benjamini-Hochberg FDR** (`core/stats/fdr.py`). Without it a
  26-column scan reports ~16 false trends. Driver fits are their own FDR family.
- **Model selection uses BIC, not adjusted R².** With n≈1100 the adj-R² penalty is weak enough
  that a pure-noise column got into the model; BIC (~ln(n) per parameter) keeps it out.
- **Findings are associational, never causal.** No "causes"/"drives"/"because" in headlines — a
  test in `tests/test_mining.py` enforces this.
- PCA is unsupervised and cannot answer "what drives X"; the narrative and UI say so explicitly.

### Data-buddy rules (do not regress these)
- **The privacy level decides which tools exist**, not just which are refused. A tool a level does
  not permit is absent from the request (`core/llm/privacy.py` → `ALLOWED_TOOLS`), so no prompt can
  talk the model into it. Default is AGGREGATES: summaries and findings, never rows.
- **Every outbound payload goes through `AuditLog.record` before the call leaves the process.**
  That is what makes the privacy claim testable — `tests/test_llm_privacy.py` plants a sentinel
  value and asserts it never appears in anything sent. Any new provider must record its payload.
- **The model's SQL runs in `core/llm/sandbox.py`, never on the main catalog connection.** It is a
  separate DuckDB with `enable_external_access=false` and a locked config, holding only the copied
  datasets. "SELECT-only" alone is NOT a boundary — `SELECT * FROM read_csv('/etc/passwd')` is a
  SELECT.
- **API keys go to the OS keychain via `core/llm/secrets.py`.** Never QSettings, never the project
  file, never a dotfile.
- A provider is `verified = True` only after a real call to its API was made and observed. Anything
  else is `False` and the UI says "experimental".
- Tests must never touch real user preferences: patch `settings_store._APP` to a unique name (a
  broken fixture once wrote a test's privacy level into the developer's real QSettings).

### Commands
- `uv sync` — install (uv provisions Python 3.12 per `.python-version`; system python is 3.9)
- `uv run prospectra` — launch GUI (`--smoke` auto-quits after ~2.5 s, used for launch checks)
- `uv run prospectra generate-example` — regenerate `examples/ice_cream_sales.csv`
- `uv run prospectra run-flow <project> <flow>` — run a saved flow headless
- `uv run prospectra scrape <url> --out <dir>` — scrape a page's tables to CSV (robots.txt obeyed;
  accepts a local .html path or `file://`, which is how CI exercises it without a network)
- `uv run pytest` · `uv run ruff check .` · `uv run mypy prospectra` · `uv run lint-imports`

### Cross-OS rule (non-negotiable)
The testers run **Windows only**; the maintainer develops on macOS. Never claim Windows works from
a macOS run — CI (`.github/workflows/ci.yml`) runs the suite **and a real GUI launch** on
windows/ubuntu/macos, and that is the only acceptable evidence. Windows gotchas already handled:
build SQL paths through `prospectra.core.sqlutil.path_lit` (POSIX separators; never interpolate a
raw `str(Path)` with backslashes into SQL), and write CSVs with `newline=""`.

### Architecture rules
- `prospectra/core/` is the headless engine: it must NEVER import Qt or `prospectra.ui`.
  The import-linter contract in pyproject.toml enforces this — keep it green.
- UI imports core, never the reverse. Engine features land in core with headless CLI coverage.
- One node/connector/analysis per file behind ABCs; extension points are the entry-point groups
  `prospectra.{connectors,flow_nodes,analyses,llm_providers,chart_types}`.
- Secrets go in the OS keychain via `keyring` (P4+); project files store secret *references* only.
- CLI stubs for unbuilt features must exit 2 with an honest "arrives in phase Px" message.
- `examples/ice_cream_sales.csv` is generated (seed 42) with planted ground truth
  (sales ← temperature, school_out, ad_spend; decoys: lottery_numbers, competitor_promo).
  Mining golden tests depend on it — regenerate only via the CLI, never change the seed casually.
- Before writing any chart code: load the `dataviz` skill.
- `sampleflow.png` (repo root) is the UI reference for the P2 flow canvas + profile pane.
