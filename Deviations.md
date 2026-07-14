# Deviations Log

<!-- 2026-07-13 (P0): Required by CLAUDE.md — every departure from the approved build plan is
     recorded here with rationale, tagged to the commit(s) that contain it. -->

Entry format:

```
## YYYY-MM-DD — short title
- Phase: P#
- Deviation: what changed vs. the plan
- Why: rationale
- Commit(s): hash(es)
```

## 2026-07-13 — P1 file-connector subset (T0 not complete)
- Phase: P1
- Deviation: the plan lists PDF tables and SPSS/Stata/SAS statistical files in the T0 file tier;
  P1 ships CSV/TSV/text, JSON/JSONL, Parquet, and Excel (xlsx/xlsm/xls/ods) only.
- Why: P1 and P2 were built in a single pass at the user's request ("phase 1 and 2"); PDF/stat
  formats need extra dependencies (pdfplumber, pyreadstat) and their own extraction UX, and
  nothing downstream blocks on them. They move to the connector-breadth phase (P6).
- Commit(s): this commit

## 2026-07-13 — P1 SQL tier via generic SQLAlchemy only
- Phase: P1
- Deviation: the plan named DuckDB ATTACH for SQLite/Postgres/MySQL plus SQLAlchemy for
  SQL Server; P1 ships a single generic SQLAlchemy connector for all dialects instead.
- Why: one mechanism covers every dialect by URL (including warehouses) with one code path to
  test; DuckDB's postgres/mysql ATTACH extensions download at first use, which is a poor default
  for offline/partner machines. ATTACH remains an optimization candidate for large tables.
  Honesty note: only SQLite is exercised by tests (no server credentials in this environment) —
  every other dialect is flagged "experimental" in the UI until run against a real server.
- Commit(s): this commit

## 2026-07-13 — P2 canvas: OdenGraphQt rejected after evaluation
- Phase: P2
- Deviation: none from the letter of the plan (it prescribed "evaluate, then fall back"), recorded
  for traceability: OdenGraphQt 0.7.4 fails on import under Python ≥3.12 (`from distutils.version
  import LooseVersion`; distutils was removed from the stdlib), so the flow canvas is a custom
  QGraphicsScene editor owned by this repo.
- Why: a canvas dependency that cannot import on any supported interpreter is not adoptable.
- Commit(s): eee92ab

## 2026-07-13 — P2 built before the rest of P1's UI polish; scope trimmed to ship the canvas
- Phase: P2
- Deviation: the P2 node list in the plan is delivered in full, but three canvas conveniences the
  plan implies are not in this commit: dragging catalog datasets onto the canvas as inputs (flow
  inputs are file paths for now), an undo stack, and a visual column picker (params take comma
  lists / SQL expressions). Excel and database sources cannot yet feed a flow — only files DuckDB
  reads natively (CSV/TSV/text/JSON/Parquet).
- Why: the user asked for P1+P2 in one pass; these are additive UX layers over a working engine
  and none of them change the flow model, so they slot into P5 (drag-and-drop backbone) without
  rework. Called out explicitly so nobody assumes they exist.
- Commit(s): eee92ab

## 2026-07-13 — Python pinned to 3.12 (plan said "3.12 (floor 3.11)")
- Phase: P2
- Deviation: added `.python-version` pinning 3.12 exactly; `requires-python` still allows ≥3.11.
- Why: uv was resolving to 3.14 locally, so the maintainer's machine, CI, and the Windows testers
  could each run a different interpreter — the exact class of difference that makes "works on my
  machine" claims worthless. One pinned version across all three OSes.
- Commit(s): eee92ab

## 2026-07-13 — P3 multivariate selection uses BIC, not adjusted R²
- Phase: P3
- Deviation: the plan specified "multivariate via Lasso path + forward selection"; forward
  selection is scored on **BIC**, with LassoCV kept as a reported cross-check rather than as the
  selector.
- Why: forced by a failing acceptance test, not by preference. Forward selection on adjusted R²
  admitted `competitor_promo` — a pure-noise decoy — into the model of the tutorial dataset
  (standardized β = -0.016), because with n≈1100 the adj-R² penalty (n-1)/(n-k-1) is far too weak
  to exclude noise. BIC penalises each parameter by ~ln(n) ≈ 7 and recovers exactly the three
  planted drivers. Reporting a noise variable as a driver is the worst failure this tool could
  have, so the criterion changed.
- Commit(s): this commit

## 2026-07-13 — P3 PCA ships scree + loadings + narrative; no biplot yet
- Phase: P3
- Deviation: the plan listed a biplot alongside the scree plot and loadings table.
- Why: the scree chart, the loadings table, and the plain-English narrative already answer "what
  are the components and what drives them" for a first-time PCA user, which was the point. The
  biplot needs the scores overlaid with loading vectors and a legend scheme that earns its
  complexity; it belongs with the dashboards work (P5) where the chart layer gets its real
  treatment. `PCAResult.scores` already carries the first two components' scores, so the biplot is
  a chart-only addition when it lands.
- Commit(s): this commit

## 2026-07-14 — P4: no provider was run against a live API; all four ship "experimental"
- Phase: P4
- Deviation: the plan's acceptance line ("'Why might temperature correlate with sales?' returns a
  grounded, cited answer") has NOT been demonstrated against a real model. There is no API key in
  this environment, so every provider carries `verified = False` and the UI badges it
  "experimental: the request format is implemented but has not been run against this provider's
  live API in this build".
- Why: no credentials. What *is* proven, against a scripted provider: the tool loop, the privacy
  gate (sentinel test), the SQL sandbox (attack tests), the audit log, keychain storage, and the
  hypothesis engine's prompt and citation handling. What is unproven is only the wire format of
  each vendor's API. Flipping a provider to `verified = True` requires making a real call and
  observing it — nothing else counts.
- Commit(s): this commit

## 2026-07-14 — P4: web search is Anthropic-only; no Tavily/Brave backend
- Phase: P4
- Deviation: the plan specified "web search (Anthropic server-side `web_search` tool when
  provider=Anthropic; pluggable Tavily/Brave key otherwise)". Only the Anthropic server-side tool
  is implemented. With any other provider the hypothesis engine still answers, but says plainly
  that nothing is cited and that the content is the model's prior knowledge rather than evidence.
- Why: a second search backend needs its own key to test, and shipping an untested search path
  that silently returns nothing would be worse than saying so. `Provider.supports_web_search` is
  the seam a Tavily/Brave backend plugs into.
- Commit(s): this commit

## 2026-07-14 — P4: privacy levels gate *which tools exist*, and the middle level uses a
## structured aggregate tool instead of free-form SQL
- Phase: P4
- Deviation: the plan described the model getting `run_sql` (read-only, enforced LIMIT) as a
  general tool. Instead `run_sql` exists **only** at the highest sharing level; the default level
  exposes a structured `aggregate` tool (the model names group-by columns and picks metrics from a
  fixed list; this code builds the SQL).
- Why: it makes the guarantee provable rather than promised. With free-form SQL there is no way to
  be certain a query cannot return an individual row; with a structured aggregate tool there is no
  query shape that can. The tools a level does not permit are not merely refused — they are absent
  from the request, so no prompt can talk the model into them. Additionally, `run_sql` runs inside
  a separate DuckDB with `enable_external_access=false` and a locked configuration, because a
  plain "SELECT-only" check is not a security boundary (`SELECT * FROM read_csv('/etc/passwd')` is
  a SELECT).
- Commit(s): this commit

## 2026-07-14 — P4: no drag-in context chips in the chat dock
- Phase: P4
- Deviation: the plan said "any column/finding can be dragged in as a context chip". Not built —
  the buddy sees all opened datasets, and the Analyze tab hands it the current findings
  automatically.
- Why: it depends on the drag-and-drop MIME backbone, which is P5's job. Deferred there rather
  than half-built here.
- Commit(s): this commit

## 2026-07-14 — P6: warehouse dialects ship as descriptors, unverified, with no driver bundled
- Phase: P6
- Deviation: the plan said "warehouse dialect descriptors (Snowflake, BigQuery, Redshift,
  Databricks, Athena first — flipping experimental→verified needs your credentials)". Delivered as
  written, recorded for traceability: **all 12 dialects except SQLite are `experimental`**, and
  none of their driver packages is a dependency of Prospectra — the app detects whether the driver
  is importable and prints the exact `uv add …` command if not.
- Why: bundling a dozen warehouse drivers would add hundreds of megabytes and a pile of native
  build requirements for users who need one of them, or none. And no dialect can be called verified
  from here: there are no warehouse credentials in this environment, and per CLAUDE.md a badge flips
  only after a real connection is observed. `prospectra connectors` prints the whole matrix so the
  state is never a guess.
- Commit(s): 92a1a95

## 2026-07-14 — P6: a new flow node (`Input: Database`) and a new hook on the Node ABC
- Phase: P6
- Deviation: the plan's P6 acceptance line is "install a dialect, connect, run a flow end-to-end",
  but nothing in the plan's node list lets a flow *read a database*. Flow inputs were files only
  (a P2 limitation). Added `Node.prepare(con)` — an optional hook that materializes external data
  into the run's DuckDB connection before the graph is compiled — and an `Input: Database` node that
  uses it.
- Why: without it the acceptance line was unreachable, and "you can connect to Snowflake" and "you
  can prep data on a canvas" would have been two features that never met. The hook is a default
  no-op, the compiler is untouched (the graph still becomes one CTE query), and every existing node
  ignores it. It is also the seam an API-input node will use.
- Commit(s): 92a1a95

## 2026-07-14 — P6: packaged app cannot load user-installed plugins
- Phase: P6
- Deviation: the plugin API works in a source install, and in the packaged build for plugins that
  were installed **at build time** (the Jira plugin is bundled and CI asserts the frozen binary
  still lists it). A user cannot add a connector to the packaged app — there is no pip inside a
  PyInstaller bundle.
- Why: a fundamental property of freezing, not an oversight. Two findings are worth recording:
  (1) the first bundle built cleanly, launched, ran the whole stats engine — and had silently
  dropped **every** entry-point plugin, because PyInstaller ships no `.dist-info` and
  `importlib.metadata.entry_points()` therefore found nothing. `copy_metadata` fixes it, and CI now
  greps the packaged binary's `connectors` output so this cannot regress unnoticed. (2) A drop-in
  plugin *folder* (scanning a user directory at startup) would give the frozen app real
  extensibility; it is not built, and is the obvious next step for the plugin story.
- Commit(s): 92a1a95

## 2026-07-14 — P6: no code signing / notarization; no installers
- Phase: P6
- Deviation: the plan says "PyInstaller builds for all 3 OSes". The builds exist and CI produces
  artifacts for Windows, Linux, and macOS, but they are **unsigned**: no Apple notarization, no
  Windows Authenticode. There is no .msi/.dmg/.deb installer either — the artifact is a folder (or
  a .app).
- Why: signing needs certificates and paid developer accounts that do not exist for this project
  yet, and it is a distribution decision for the maintainer, not a build detail. Consequence, stated
  plainly so the Windows testers are not surprised: SmartScreen will warn on first launch, and macOS
  Gatekeeper will refuse a downloaded .app until it is opened via right-click ▸ Open. That is a real
  cost of shipping unsigned, not a bug.
- Commit(s): 92a1a95

## 2026-07-14 — P6: Muse Spark LLM provider added (not in the plan)
- Phase: P6
- Deviation: the plan's day-one provider list was Anthropic, OpenAI, Gemini, Ollama. A fifth
  provider, **Muse Spark**, was added at the user's request: a user-supplied OpenAI-compatible
  endpoint where the URL, API key, and model are all typed in by the user.
- Why: requested directly. It reuses the OpenAI chat-completions implementation (as Ollama does),
  so it adds a provider without adding a protocol. The one non-obvious piece: it refuses to run
  with no base URL rather than defaulting — the OpenAI SDK's default is `api.openai.com`, so a
  silent fallback would send the user's data to a vendor they never named. `verified = False` like
  the rest: the request shape is tested against a scripted OpenAI-standard server, but no live Muse
  Spark endpoint has been called from this build.
- Commit(s): 92a1a95

## 2026-07-14 — P5: no Playwright/JS-rendering extra; no LLM-assisted extraction
- Phase: P5
- Deviation: the plan listed an optional `[scraper-js]` Playwright extra for JS-rendered pages, and
  "LLM-assisted extraction for messy pages". Neither is built. The scraper fetches with httpx and
  parses server-rendered HTML only; a page whose tables are drawn by JavaScript yields nothing.
- Why: Playwright pulls a browser download per OS — a heavy, cross-platform-fragile dependency for
  a case nothing downstream needs (Wikipedia, statistical agencies, and most reference tables are
  server-rendered). LLM-assisted extraction would route page content to a provider, and no provider
  has been run against a live API yet (see the P4 entry) — building an unverified extraction path on
  top of an unverified provider path would produce a feature nobody could trust. Both are additive
  behind the existing `Fetcher` Protocol and `parse` seam, so neither needs rework to land in P6.
- Commit(s): 090e665

## 2026-07-14 — P5: dashboards are a fixed 2-column grid, not a free-form canvas
- Phase: P5
- Deviation: the plan says "dashboards are saved grids of specs". They are — but the grid is
  2 columns, filled left-to-right, with no drag-to-reposition or resize of tiles.
- Why: the tile's *position* is already persisted (`Tile.row`/`Tile.column`), so a free-form layout
  is a UI affordance over an unchanged model, not a data-model change. The chart layer's real work
  in P5 was the honesty of what a chart says (truncation notes, log-scale drops, the one-axis rule)
  and the drop-shelf builder; free layout is polish that can land any time without migration.
- Commit(s): 090e665

## 2026-07-14 — P5: PCA biplot still not built (promised here by the P3 deviation)
- Phase: P5
- Deviation: the P3 entry below deferred the PCA biplot to P5 ("it belongs with the dashboards work
  where the chart layer gets its real treatment"). It is still not built.
- Why: honest accounting rather than a quiet drop. P5's chart budget went to the ChartSpec model,
  the shelf-driven builder, and the two chart-honesty rules (stated truncation, stated log-scale
  drops) — those are the things that stop a dashboard from lying. The biplot remains a chart-only
  addition: `PCAResult.scores` still carries the first two components, and `SpecChart` is now the
  place it plugs into. Deferred to P6, and it will keep being deferred honestly until it is drawn.
- Commit(s): 090e665

## 2026-07-14 — P5: P2's canvas conveniences — one built, two still open
- Phase: P5
- Deviation: the P2 entry below deferred three canvas conveniences to P5. Status: **dragging catalog
  datasets onto the canvas as inputs is now built** (a dataset drop becomes an Input node wired to
  its file; a dataset a flow cannot read — an Excel sheet, a database table — is refused with the
  reason instead of dropping a node that fails on run). The **undo stack** and the **visual column
  picker** are still not built; flow params still take comma lists and SQL expressions.
- Why: the dataset-drop was the one that the drag-and-drop backbone made nearly free and that the
  P2 entry named explicitly. Undo and the column picker are editor ergonomics with no bearing on
  what a flow can express or on any acceptance line; they are not silently dropped, they are here.
- Commit(s): 090e665

## 2026-07-13 — Linux GUI launch runs under Xvfb, not the bare runner
- Phase: P2
- Deviation: CI's GUI-launch step uses the native platform plugin on Windows/macOS but `xvfb-run`
  on Linux.
- Why: proven by the first CI run — the Linux runner has no X display (`qt.qpa.xcb: could not
  connect to display`), while Windows and macOS runners do. Xvfb supplies a real X display, which
  is a stronger check than falling back to the offscreen plugin. Windows and macOS passed the
  native-plugin launch on run #1.
- Commit(s): (this commit)
