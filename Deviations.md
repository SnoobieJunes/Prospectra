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

## 2026-08-05 — P7 hardening: ~40 review findings fixed; three project rules had been broken
- Phase: P7
- Deviation: P7 as first written violated three of this repo's own non-negotiable rules. Four
  adversarial reviews found ~40 defects; the significant ones are fixed in this commit and the
  fixes are locked by tests that fail against the previous code
  (`tests/test_mapping_injection.py`, `test_http_regressions.py`, `test_mapping_regressions.py`,
  `test_ui_regressions.py`).
  * **"No raw SQL is ever typed"** — `TargetColumn.type` was interpolated raw on the two compile
    paths that skip `validate()` (`field_exprs`, `coercion_check_sql`). Opening a *shared* project
    and pressing "Preview values" executed arbitrary statements, including writing a file
    (reproduced). The plan had explicitly said not to copy `select.py`'s unvalidated type
    interpolation; it was copied anyway. Now `check_type` is enforced in `_declared_type`, the one
    choke point every path passes through, and `_TYPE_PATTERN` is `\A…\Z` (Python's `$` also
    matched a trailing newline).
  * **"Nothing is silent"** — the mapper displayed one transform order and compiled another
    (`steps.remove()` matched by dataclass VALUE, so removing a repeated chip deleted the first);
    a case-collision between a target and a passthrough column served the wrong value downstream;
    `__lost` both undercounted (a `default()` after a cast re-filled the NULLs) and overcounted
    (all-NULL `concat_ws` rows counted as unreadable); and `MapFieldsNode.prepare_notes` was read
    by nothing despite a comment claiming the UI read it.
  * **"A live write cannot happen by accident"** — a write to a redirecting URL was rewritten
    POST→GET by httpx, dropping the body, and reported `written` (reproduced); "Run flow" had no
    re-entrancy guard, so a double-click could start two concurrent live write jobs.
  Also fixed: a circular import that made `import prospectra.core.http.write` crash on a cold
  interpreter (the suite hid it by importing `core.flow` first — report types now live in
  `core/report.py`, beneath both layers); a regression where moving auth into `send()` made
  `params` non-empty and httpx REPLACED the URL's query, so link pagination with query auth
  re-fetched page 1 forever; batch failures recording one key per chunk instead of per row;
  unbounded `Retry-After`; `to_curl` printing a credential typed into a query parameter; a typed
  token surviving a request switch and being sent to a different host; `WriteSpec.body_kind`
  persisted but ignored; the write editor offering auth kinds it could not configure; and
  `prospectra map` failing outright on file-backed crosswalks.
- Why: recorded rather than quietly repaired because the failure was one of verification, not just
  of code. The original P7 suite passed 388 tests while every defect above was present: the tests
  encoded the same assumptions as the code, and several source comments asserted behaviour that had
  never been exercised. The lesson is written into CLAUDE.md.
- Commit(s): this commit

## 2026-08-05 — Muse Spark: real, editable defaults; the advertised endpoint had never resolved
- Phase: P6 (provider), fixed in P7 hardening
- Deviation: the P6 provider instructed users to paste `https://api.musespark.ai/v1` — a hostname
  that does not resolve — in three places. It now defaults to `https://api.meta.ai/v1` with model
  `muse-spark-1.2`, both prefilled and editable, and the settings form reads the endpoint from the
  new `Provider.default_base_url` descriptor instead of `if cls.type_name == "muse_spark"`.
- Why: the app was documenting an endpoint that could never answer, and the name-based special case
  broke the project's own "a descriptor drives the form" rule (Ollama's hardcoded localhost URL
  moved to the same descriptor). Pointing Prospectra at any other OpenAI-compatible gateway is now
  a settings change with no code change, which is what the provider is for.
- Honesty: `verified` stays False. The request/response shape is proven against a scripted
  OpenAI-compatible server (observed working, 0.5s round trip, correct payload and Bearer header),
  and `api.meta.ai` resolves and answers `/v1/models` with HTTP 401 — reachable, wants a credential
  — but no authenticated call has been made from this build.
- Commit(s): this commit

## 2026-08-05 — P7 findings knowingly NOT fixed in this pass
- Phase: P7
- Deviation: these review findings are real and remain open rather than being silently dropped.
  * `output_dataset` writes a `.duckdb` file that Prospectra itself cannot re-open (`_READERS` has
    no `.duckdb`, `DIALECTS` has no DuckDB entry). The node's help text and module comment now say
    so; adding a DuckDB dialect is the fix.
  * Saved API sources and playground requests cannot be renamed or deleted from the UI
    (`delete_connection` exists with no caller), and saving twice under one name creates two rows.
  * `flow_with_mapping` still has no production caller — the guided "Map to…" action was never
    wired; the Map Fields node in the palette is the only route in.
  * The playground can save a request into a project but nothing exports the standalone `.json`
    that `prospectra api-send` reads, so replay means hand-writing the file.
  * `suggest_from_values` is CLI-only by design (a flow node's target is a declared column list,
    not a relation to sample) — the false claim in the mapper's header comment is corrected.
  * Response rendering is unbounded: a multi-megabyte body is formatted on the GUI thread.
- Why: each is a bounded, non-corrupting limitation with an honest statement in the code or UI,
  whereas everything fixed above either lost data, leaked a credential, or executed arbitrary SQL.
  Shipping the safety fixes now beats holding them behind ergonomics.
- Commit(s): this commit

## 2026-07-31 — P7: `Auth` moved to core/http (re-exported from the old path)
- Phase: P7
- Deviation: the plan's reuse table kept `Auth` in `core/connectors/rest/mapping.py`; it now
  lives in `core/http/request.py`, with `mapping.py` re-exporting it unchanged.
- Why: core/http importing Auth from the REST tier would have made the import graph circular
  (`connectors.rest.client` imports `core.http.send`, whose package would import
  `connectors.rest.mapping` back). Auth is an HTTP-level concern shared by the playground, the
  paginator, and the write path; the layering is now strictly `connectors → http`. Every
  existing import path (`from prospectra.core.connectors.rest import Auth`) still works.
- Commit(s): this commit

## 2026-07-31 — P7: Output: Local Dataset writes a DuckDB *file*, not the session catalog
- Phase: P7
- Deviation: the plan said `CREATE OR REPLACE TABLE … AS <sql>` "into the catalog";
  `output_dataset` ATTACHes a `.duckdb` database file and creates the table there instead.
- Why: a flow run executes on its own isolated in-memory connection (the P2 reproducibility
  rule), so a table created "in the catalog" would either evaporate with the run's connection or
  require the runner to reach into the live UI session — which headless `run-flow` does not
  have. A database file is durable, re-openable, and identical in headless and GUI runs; the
  same reasoning that lands scraped tables as CSVs.
- Commit(s): this commit

## 2026-07-31 — P7: coercion counters measure base→final loss, not just the last TRY_CAST
- Phase: P7
- Deviation: the plan specified `<target>__lost` as rows where the pre-cast expression is
  NOT NULL and its TRY_CAST is NULL. The implementation counts rows where the field's *base*
  value (before any step) was NOT NULL and the *final* expression (after every step and the
  declared-type cast) is NULL, plus a separate `<target>__unmatched` counter per lookup step.
- Why: the plan's formulation misses losses inside the step chain — a mid-chain `parse_date`
  or `cast` step silently NULLing values would go uncounted. "Went in readable, came out NULL"
  subsumes the plan's check and is the honest number; crosswalk misses (which COALESCE back to
  the original, so they never look like losses) get their own stated count.
- Commit(s): this commit

## 2026-07-31 — P7: mappings and destinations persist inside flow docs, not as connection rows
- Phase: P7
- Deviation: the plan's data model listed connector_type discriminators `rest / rest_write /
  field_mapping` in the connections table. Shipped: `rest` (API sources) and `http_request`
  (saved playground requests) as connection rows; mapping documents and REST write specs
  persist as their node's params inside the flow document instead of as connection rows.
- Why: a mapping belongs to the flow that uses it — a second copy in the connections table
  would be a synchronization bug waiting to happen (edit the node, stale row survives). The
  no-new-tables constraint is still honoured, old builds still open P7 projects and ignore
  what they don't know, and nothing needed a standalone mapping row yet; if sharing mappings
  across flows becomes real, `field_mapping` rows can be added without a schema change.
- Commit(s): this commit

## 2026-07-31 — P7: the guided "Map to…" entry point is the canvas, not a separate command
- Phase: P7
- Deviation: the plan named a guided "Map to…" action generating the flow. Shipped as
  `flow_with_mapping()` (core, tested — Input → Map Fields → Output, refusing a broken doc
  before the flow exists) plus the Map Fields node in the palette with its full-panel mapper
  dialog; there is no additional toolbar command that wraps them.
- Why: the mapper lives where flows live. A second entry point would duplicate the canvas path
  without new capability; the load-bearing promise — the drop writes a *flow*, never hidden
  magic — is delivered and tested. If a one-click "map this dataset to that one" affordance is
  wanted later, it is a thin caller of `flow_with_mapping`.
- Commit(s): this commit

## 2026-07-31 — P7: POST acknowledgement is a WriteSpec field, enforced at validate
- Phase: P7
- Deviation: the plan required "explicit acknowledgement" for POST without locating the
  mechanism; it landed as `WriteSpec.post_acknowledged` — `validate()` refuses a POST spec
  without it, and the node editor surfaces it as a "may create duplicates on retry" checkbox.
- Why: putting the acknowledgement in the spec makes headless `run-flow` exactly as guarded as
  the GUI — a CLI user cannot POST without having stored the same explicit consent the
  checkbox records, and the caveat lives in the UI as required, not in a docstring.
- Commit(s): this commit

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
