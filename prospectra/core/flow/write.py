# 2026-08-05: the report types moved to `prospectra.core.report` — a module beneath both the HTTP
# layer and the flow engine — because defining them here made `import prospectra.core.http.write`
# a circular import that crashed on a cold interpreter. This module stays as the flow engine's
# door to them so every existing `from prospectra.core.flow.write import WriteReport` keeps working.
# 2026-07-31 (P7): What every write reports — file COPY, catalog table, or live HTTP.
#
# One report shape for all destinations, because the questions are always the same: how many rows
# did you attempt, how many actually landed, which ones failed and WHY, did you stop early, and
# was this a rehearsal? `notes` carries the confessions (caps hit, rows skipped) — and per the
# project rule they must reach the UI/CLI, never die in a logger.

from prospectra.core.report import RowFailure, WriteReport

__all__ = ["RowFailure", "WriteReport"]
