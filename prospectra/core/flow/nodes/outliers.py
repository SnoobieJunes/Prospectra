# 2026-07-13 (P2): Outliers — flag or remove by IQR fences or z-score. The stats subquery runs on
# the node's own input, so fences reflect the data as prepped up to this point. NULL-safe: a
# degenerate spread (stddev 0 / equal quartiles) flags nothing rather than dropping everything.

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import ident


@register
class OutlierNode(Node):
    type_name = "outliers"
    display_name = "Outliers"
    category = "transform"
    params_schema: ClassVar = (
        ParamField("column", "Column", "columns"),
        ParamField("method", "Method", "choice", "iqr", ("iqr", "zscore")),
        ParamField("factor", "Factor (IQR fence / z threshold)", "float", 1.5),
        ParamField("action", "Action", "choice", "flag", ("flag", "remove")),
    )

    def validate(self) -> None:
        if not str(self.params.get("column", "")).strip():
            raise ValueError("choose the column to test")
        try:
            float(self.params.get("factor", 1.5))
        except (TypeError, ValueError) as exc:
            raise ValueError("factor must be a number") from exc

    def compile(self, inputs: list[str]) -> str:
        src = inputs[0]
        col = ident(str(self.params["column"]).strip())
        factor = float(self.params.get("factor", 1.5))
        if str(self.params.get("method", "iqr")) == "iqr":
            stats = (
                f"SELECT quantile_cont({col}, 0.25) AS lo_q, "
                f"quantile_cont({col}, 0.75) AS hi_q FROM {src}"
            )
            test = (
                f"(t.{col} < s.lo_q - {factor} * (s.hi_q - s.lo_q) "
                f"OR t.{col} > s.hi_q + {factor} * (s.hi_q - s.lo_q))"
            )
        else:
            stats = f"SELECT avg({col}) AS mu, stddev({col}) AS sigma FROM {src}"
            test = f"(abs(t.{col} - s.mu) > {factor} * s.sigma)"
        flagged = f"COALESCE({test}, FALSE)"
        if str(self.params.get("action", "flag")) == "flag":
            return f"SELECT t.*, {flagged} AS is_outlier FROM {src} t CROSS JOIN ({stats}) s"
        return f"SELECT t.* FROM {src} t CROSS JOIN ({stats}) s WHERE NOT {flagged}"
