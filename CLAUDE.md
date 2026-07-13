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
- Next: P1 — file/SQL connectors, catalog, virtualized data grid, column profiler, sampling.

### Commands
- `uv sync` — install (uv provisions Python ≥3.11 automatically; system python is 3.9)
- `uv run prospectra` — launch GUI (`--smoke` auto-quits after ~2.5 s, used for launch checks)
- `uv run prospectra generate-example` — regenerate `examples/ice_cream_sales.csv`
- `uv run pytest` · `uv run ruff check .` · `uv run mypy prospectra` · `uv run lint-imports`

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
