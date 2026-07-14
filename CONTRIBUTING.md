# Contributing to Prospectra

Prospectra is built to be extended, not just used — connectors, flow nodes, LLM providers, and
chart types are all entry-point plugins. If you want to add a data source or a node type, you
likely don't need to touch `prospectra/core/` at all.

## Setup

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh   # or winget install --id=astral-sh.uv -e
git clone https://github.com/SnoobieJunes/Prospectra.git && cd Prospectra
uv sync
uv run prospectra          # launch the GUI
uv run pytest -q           # run the test suite
```

`uv` provisions Python 3.12 automatically — you do not need Python preinstalled, and the project
is pinned to 3.12 everywhere (see `.python-version`) so CI, your machine, and everyone else's stay
identical.

## Before you open a PR

```sh
uv run ruff check .        # lint
uv run mypy prospectra     # types (strict in core)
uv run lint-imports        # architecture contract — see below
uv run pytest -q           # tests
```

All four run in CI on Windows, Linux, and macOS on every push — including a real (non-offscreen)
GUI launch on each OS. A change that isn't proven on all three isn't done; if you only have one OS
to test on, say so in the PR and let CI cover the rest.

## Architecture rules that are enforced, not just documented

- **`prospectra/core/` never imports Qt or `prospectra.ui`.** This is a hard contract, checked by
  `lint-imports` (see `pyproject.toml`) — the engine has to run headless, with no display, forever.
  UI imports core; core never imports UI.
- **One node / connector / analysis / provider / chart type per file, behind an ABC.** Extension
  points are entry-point groups: `prospectra.connectors`, `prospectra.flow_nodes`,
  `prospectra.analyses`, `prospectra.llm_providers`, `prospectra.chart_types`. Adding a feature
  should mean adding a file and an entry point, not editing a central registry by hand.
- **Secrets go in the OS keychain (`keyring`), never QSettings, never the project file, never a
  dotfile.** If your contribution touches credentials, route them through
  `prospectra/core/llm/secrets.py`'s pattern.
- **No claim of "verified" without a real call observed.** A new connector or provider ships
  badged `experimental` until someone runs it against the real service and watches it work —
  that's not a formality, it's how the whole project stays honest about what's actually been
  tested versus what's implemented but unproven. See `Deviations.md` for the running log of what
  falls into which bucket.

## Adding a connector

Start with `docs/writing-a-connector.md`. The contract is two methods
(`list_datasets` / `install`) and an entry point; `plugins/prospectra_jira/` is the reference
implementation at under 100 lines. A working connector plugin looks like:

```toml
# my_connector/pyproject.toml
[project.entry-points."prospectra.connectors"]
widgets = "prospectra_widgets.connector:WidgetConnector"
```

If your source is a REST/OData API, don't write a new HTTP client — describe it as a
`RestMapping` (auth, pagination, paths→columns) instead. See
`prospectra/core/connectors/rest/mapping.py` and the Jira plugin.

## Adding a flow node

Subclass the `Node` ABC in `prospectra/core/flow/node.py` and register it under
`prospectra.flow_nodes`. Every node compiles into a fragment of a single DuckDB query — if your
node needs to pull in data that isn't already in the graph (a database table, an API), use the
optional `Node.prepare(con)` hook (see `Input: Database` for the pattern) rather than special-
casing the compiler.

## Tests

- Put new tests in `tests/`, following the existing `test_<area>.py` naming.
- GUI tests run offscreen (`tests/conftest.py`) so they're deterministic without a real display.
- If you touch LLM privacy (`core/llm/privacy.py`) or the SQL sandbox (`core/llm/sandbox.py`),
  add or extend a sentinel-value test — see `tests/test_llm_privacy.py` for the pattern that
  proves data doesn't leak, rather than just asserting it shouldn't.
- Tests must never touch a real developer's settings: patch `settings_store._APP` to a unique
  name if your test writes to `QSettings`.

## Deviations

If your change departs from documented behavior or an existing acceptance line, add an entry to
`Deviations.md` (format is at the top of that file) explaining what changed and why, tagged to
your commit. This project's whole honesty model depends on that log being complete — half the
point of Prospectra is that it never claims something works without having watched it work, and
that standard applies to the codebase's own history too.

## Commit style

Small, focused commits with messages that explain *why*, not just *what* — see `git log` for the
existing style. Every non-trivial code change should carry a short dated comment at the point of
change explaining the reasoning, not a restatement of what the code does (see any file in
`prospectra/core/` for the pattern).

## Questions

Open an issue, or check `README.md` and `Deviations.md` first — between the two of them, most
"why does it work this way" questions are already answered.
