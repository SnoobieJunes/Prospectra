# 2026-07-31 (P7): Identifier tokenizing + abbreviation expansion for match suggestions.
#
# "prod_nm" and "productName" are the same words wearing different clothes. Splitting camelCase
# and snake_case into tokens and expanding the abbreviations data people actually use is what
# lets token-overlap scoring see it — difflib alone rates "prod_nm" vs "productName" poorly.
# The table is deliberately boring and additive; a wrong expansion only costs a suggestion.

from __future__ import annotations

import re

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")

ABBREVIATIONS: dict[str, str] = {
    "nm": "name",
    "clr": "color",
    "col": "color",
    "colour": "color",
    "qty": "quantity",
    "desc": "description",
    "descr": "description",
    "prod": "product",
    "cust": "customer",
    "cat": "category",
    "num": "number",
    "no": "number",
    "nbr": "number",
    "amt": "amount",
    "prc": "price",
    "px": "price",
    "cd": "code",
    "dt": "date",
    "tm": "time",
    "addr": "address",
    "tel": "phone",
    "img": "image",
    "pic": "image",
    "mfr": "manufacturer",
    "vend": "vendor",
    "sz": "size",
    "wt": "weight",
    "ht": "height",
    "len": "length",
    "pct": "percent",
    "avg": "average",
    "min": "minimum",
    "max": "maximum",
    "uom": "unit",
    "curr": "currency",
    "ccy": "currency",
    "lang": "language",
    "ctry": "country",
    "st": "state",
    "id": "identifier",
    "ref": "reference",
    "sku": "sku",  # a domain word, not an abbreviation — kept as itself on purpose
}


def split_identifier(name: str) -> list[str]:
    """ "prod_nm" -> ["prod", "nm"]; "productName" -> ["product", "name"]; lower-cased."""
    spaced = _NON_ALNUM.sub(" ", name)
    spaced = _CAMEL_BOUNDARY.sub(" ", spaced)
    return [token.lower() for token in spaced.split() if token]


def expand_tokens(tokens: list[str]) -> list[str]:
    """Each token replaced by its expansion when one is known ("nm" -> "name")."""
    return [ABBREVIATIONS.get(token, token) for token in tokens]


def normalized_tokens(name: str) -> list[str]:
    return expand_tokens(split_identifier(name))
