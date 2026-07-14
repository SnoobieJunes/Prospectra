# 2026-07-13 (P2): Join — two ported inputs (0 = left, 1 = right), USING when key names match on
# both sides (dedupes the key column, Tableau-style), explicit ON otherwise.

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import ident


@register
class JoinNode(Node):
    type_name = "join"
    display_name = "Join"
    category = "combine"
    min_inputs = 2
    max_inputs = 2
    params_schema: ClassVar = (
        ParamField("how", "Join type", "choice", "inner", ("inner", "left", "right", "full")),
        ParamField("left_on", "Left key column(s)", "columns"),
        ParamField("right_on", "Right key column(s) (empty = same as left)", "columns", default=""),
    )

    def validate(self) -> None:
        if not str(self.params.get("left_on", "")).strip():
            raise ValueError("set the join key column(s)")

    def compile(self, inputs: list[str]) -> str:
        left, right = inputs
        how = str(self.params["how"]).upper()
        left_keys = [c.strip() for c in str(self.params["left_on"]).split(",") if c.strip()]
        right_raw = str(self.params.get("right_on", "")).strip()
        right_keys = (
            [c.strip() for c in right_raw.split(",") if c.strip()] if right_raw else left_keys
        )
        if len(left_keys) != len(right_keys):
            raise ValueError("left and right key lists differ in length")
        if left_keys == right_keys:
            using = ", ".join(ident(c) for c in left_keys)
            return f"SELECT * FROM {left} {how} JOIN {right} USING ({using})"
        conditions = " AND ".join(
            f"{left}.{ident(a)} = {right}.{ident(b)}"
            for a, b in zip(left_keys, right_keys, strict=True)
        )
        return f"SELECT * FROM {left} {how} JOIN {right} ON {conditions}"
