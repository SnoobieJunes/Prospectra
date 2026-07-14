# 2026-07-13 (P2): Select/Rename/Cast — the "Fix Data Type" / "Rename States" style clean step.
# Comma lists keep the P2 param UI generic; a visual field picker layers on later.

from __future__ import annotations

from typing import ClassVar

from prospectra.core.flow.node import Node, ParamField, register
from prospectra.core.sqlutil import ident


def _csv(raw: object) -> list[str]:
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def _pairs(raw: object, what: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in _csv(raw):
        left, sep, right = part.partition(":")
        if not sep or not left.strip() or not right.strip():
            raise ValueError(f"{what} entries look like 'old:new' — got {part!r}")
        pairs.append((left.strip(), right.strip()))
    return pairs


@register
class SelectNode(Node):
    type_name = "select"
    display_name = "Select / Rename / Cast"
    category = "transform"
    params_schema: ClassVar = (
        ParamField("keep", "Keep only (comma list, empty = all)", "columns"),
        ParamField("drop", "Drop (comma list)", "columns"),
        ParamField("rename", "Rename (old:new, …)", "string"),
        ParamField("cast", "Cast (column:TYPE, …)", "string", help="e.g. order_date:DATE"),
    )

    def validate(self) -> None:
        _pairs(self.params.get("rename", ""), "Rename") if self.params.get("rename") else None
        _pairs(self.params.get("cast", ""), "Cast") if self.params.get("cast") else None
        if self.params.get("keep") and self.params.get("drop"):
            raise ValueError("use Keep or Drop, not both")

    def compile(self, inputs: list[str]) -> str:
        src = inputs[0]
        keep = _csv(self.params.get("keep", ""))
        drop = _csv(self.params.get("drop", ""))
        rename = dict(_pairs(self.params.get("rename", ""), "Rename"))
        casts = dict(_pairs(self.params.get("cast", ""), "Cast"))

        if keep:
            exprs = []
            for col in keep:
                expr = f"CAST({ident(col)} AS {casts[col]})" if col in casts else ident(col)
                alias = rename.get(col, col)
                exprs.append(f"{expr} AS {ident(alias)}")
            return f"SELECT {', '.join(exprs)} FROM {src}"

        star = "*"
        if drop:
            star += " EXCLUDE (" + ", ".join(ident(c) for c in drop) + ")"
        if casts:
            replacements = ", ".join(
                f"CAST({ident(c)} AS {t}) AS {ident(c)}" for c, t in casts.items()
            )
            star += f" REPLACE ({replacements})"
        inner = f"SELECT {star} FROM {src}"
        if rename:
            renames = ", ".join(f"{ident(o)} AS {ident(n)}" for o, n in rename.items())
            return f"SELECT * RENAME ({renames}) FROM ({inner})"
        return inner
