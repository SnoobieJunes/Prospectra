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
- P6 (connector breadth: 12 dialect descriptors, REST/OData mapping tool, JDBC, PDF + SPSS/Stata/SAS,
  Jira reference plugin, `Input: Database` flow node, PyInstaller packaging) — done 2026-07-14.
  Proven: SQLite dialect form -> connection -> flow over a **database table** -> headless rerun; the
  macOS bundle was built and launched. Everything except SQLite is badged experimental.
- Also P6: **Muse Spark** LLM provider — a user-supplied OpenAI-compatible endpoint (URL + key +
  model, all three required).
- P7 (API playground + field mapper + destinations: `core/http` with one `send()` for the whole
  app, playground tab + `api-send` CLI, descriptor-driven transform vocabulary + `MappingDoc` +
  compiler with loss counters, `map`/`suggest-map` CLI, Map Fields flow node with full-panel
  drag-and-drop mapper, generalized `Node.write()` with `WriteReport`, local DuckDB-file
  destination, REST write behind four guards) — done 2026-07-31, **hardened 2026-08-05** after four
  adversarial reviews found ~40 defects including an arbitrary-SQL hole reachable from a shared
  project file. All significant findings are fixed and locked by tests that fail against the
  previous code; the open ones are listed in Deviations.md. Proven end to end: a mapped vendor CSV
  was PUT row-by-row at a **scripted local endpoint** (refusal → dry run → live run, the 400
  attributed to its row, failures CSV written), and `api-send` got a live 200 from the **real
  GitHub API**. Plan: `docs/i-want-to-add-purrfect-reddy.md`.
- All phases P0-P7 delivered. Remaining known gaps are in Deviations.md (JS-rendered scraping,
  LLM-assisted extraction, PCA biplot, flow undo stack, free-form dashboard layout).

### Connector rules (do not regress these)
- **A dialect is a descriptor, not a class.** `core/connectors/dialects.py` declares fields, URL
  template, and driver package; the UI renders the form from it. Adding a warehouse is one entry.
- **A path is not a credential.** `Field.path_like` decides the quoting: paths keep their separators,
  everything else is fully escaped. Escaping a SQLite path's slashes made SQLAlchemy *silently create
  an empty database* and report a good connection — found by running the acceptance path, not a test.
- **A missing SQLite file is an error**, because SQLite would otherwise create an empty one and the
  user would see a healthy connection with no tables.
- **Passwords never reach the project file.** `redact_url()` strips them; the real secret goes to the
  OS keychain and the connection record holds a `secret_ref`.
- **Don't reimplement HTTP for a SaaS source** — describe it as a `RestMapping` (auth + pagination +
  paths->columns). The Jira plugin is the reference: ~60 lines, and it is a real installed
  distribution loaded through the `prospectra.connectors` entry point.
- **A paginator must have caps and must confess when it hits one.** An API that always returns a
  "next" cursor exists; `FetchReport.notes` says "there may be more" rather than implying completeness.
- **The packaged app needs `copy_metadata` for every bundled plugin.** PyInstaller ships no
  `.dist-info`, so `entry_points()` finds nothing and plugins silently vanish from a build that
  otherwise looks perfect. CI asserts the bundled binary still lists the Jira plugin.

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

### Verification rules (learned the hard way, P7)
- **A green suite is not evidence.** P7 shipped 388 passing tests with a critical injection hole, a
  paginator regression, and two silent-data-corruption bugs in it. Tests written by the same pass
  that wrote the code encode its assumptions. Attack the code from outside it before claiming it
  works.
- **A regression test must fail against the old code first.** The P7 lock for "empty params must
  not strip the query string" passed while the real bug (NON-empty params) shipped.
- **Never write a comment asserting behaviour you have not exercised.** P7 comments claimed the UI
  read notes it never read, that runs never block the GUI thread while the mapper blocked it, and
  that value-based suggestions ran where they did not. Those comments then became the "evidence"
  in a status report. Describe what you ran, not what you intended.
- **Import each new module on a cold interpreter.** A circular import in `core/http/write.py` was
  invisible to the suite because the tests imported `core.flow` first.
- **Exercise the CLI path, not just the library call.** `prospectra map` was broken for file-backed
  crosswalks for as long as the feature existed, because only the flow node was tested.

### HTTP & write rules (do not regress these)
- **One `send()` for the whole app** (`core/http/send.py`): playground, REST paginator, and the
  write path. It NEVER raises — a 404 with a helpful body is a result to display; transport
  failure is an `HttpResponse.error`. `params or None` is load-bearing: `params={}` tells httpx
  to strip a URL's own query string, which once made the Link paginator re-fetch page 1 forever.
- **A live write cannot happen by accident.** Four guards ship together and none suffices alone:
  `Node.destructive`, `FlowRunner.run(allow_writes=…, dry_run=…)` refusing up front (before ANY
  output runs), `run-flow` exiting 2 and NAMING the node without `--allow-writes`, and the UI's
  dry-run-first + typed-WRITE confirmation. `push_rows` dry_run default is True and issues ZERO
  requests.
- **Retry only on 429/5xx, honouring Retry-After — never on other 4xx.** A wrong request
  re-sent is hammering. Circuit breaker: 5 consecutive failures stop the run and say so; the
  1,000-row cap confesses what it did not attempt. per_row is the default mode because a 400
  attributable to a SPECIFIC row is the product for a non-technical user.
- **`WriteReport.notes` (and every report's notes) must reach the UI/CLI** — a note that dies
  in a logger violates this file's own rule.
- **No raw SQL is ever typed in the mapper.** `coerce_args` is the injection boundary — every
  int is coerced, every choice is closed, every string goes through `str_lit`, and the ONE
  escape hatch (`expression`) is status="advanced", behind a disclosure, never suggested.
  `ParamsEditor` must never fall through to QLineEdit for unknown param kinds (it once
  `str(dict)`'d structured params and wrote the repr back — data loss).
- **`ParamField.default` must never be mutable** — `Node.__init__` shares defaults by
  reference; two nodes on one canvas would edit each other. Use `None` and normalize in
  `__init__` (see MapFieldsNode).
- **Nothing the mapper loses is silent**: `coercion_check_sql` counts rows that went in
  readable and came out NULL per field, and crosswalk misses per lookup step; truncated inline
  crosswalks are stated in `compile_notes`.

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
- `uv run prospectra connectors` — every connector, dialect, plugin, and LLM provider with its
  honest status and whether its driver is installed on this machine
- `uv run pyinstaller packaging/prospectra.spec --noconfirm` — build the desktop app
- Optional extras: `uv sync --extra pdf|stats-files|odbc|jdbc` (jdbc also needs a JVM)
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
