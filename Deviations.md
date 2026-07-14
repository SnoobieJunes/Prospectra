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

## 2026-07-13 — Linux GUI launch runs under Xvfb, not the bare runner
- Phase: P2
- Deviation: CI's GUI-launch step uses the native platform plugin on Windows/macOS but `xvfb-run`
  on Linux.
- Why: proven by the first CI run — the Linux runner has no X display (`qt.qpa.xcb: could not
  connect to display`), while Windows and macOS runners do. Xvfb supplies a real X display, which
  is a stronger check than falling back to the offscreen plugin. Windows and macOS passed the
  native-plugin launch on run #1.
- Commit(s): (this commit)
