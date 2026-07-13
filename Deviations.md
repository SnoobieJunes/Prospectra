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
- Commit(s): this commit
