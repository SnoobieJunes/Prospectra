# 2026-07-14 (P6): A deliberately small JSONPath — dots for keys, [n] for an index, [*] for "every
# element". `issues[*].fields.summary` is the whole vocabulary, and it is enough for every REST
# payload the mapping tool has to flatten.
#
# Why not a JSONPath library: the full spec (filters, recursive descent, script expressions) is a
# query language, and a query language in a saved mapping is a thing users have to debug. This is
# the subset that maps a response to columns, it has no evaluation surface, and it fits in a file
# somebody can read in a minute — which is the point of the plugin-first design.

from __future__ import annotations

import re
from typing import Any

_SEGMENT = re.compile(r"([^.\[\]]+)|\[(\*|-?\d+)\]")


class PathError(ValueError):
    """A malformed path expression."""


def parse(path: str) -> list[str | int]:
    """ "a.b[0].c" -> ["a", "b", 0, "c"];  "[*]" -> ["*"]."""
    if not path.strip():
        return []
    steps: list[str | int] = []
    position = 0
    for match in _SEGMENT.finditer(path):
        if match.start() > position and path[position : match.start()] not in (".",):
            raise PathError(f"Cannot read path {path!r} near {path[position : match.start()]!r}")
        key, index = match.group(1), match.group(2)
        if key is not None:
            steps.append(key)
        elif index == "*":
            steps.append("*")
        else:
            steps.append(int(index))
        position = match.end()
    if not steps:
        raise PathError(f"Cannot read path {path!r}")
    return steps


def resolve(data: Any, path: str) -> Any:
    """Follow `path` into `data`. A `[*]` yields a list; a missing key yields None, never an error.

    Missing-is-None is deliberate: REST payloads are ragged (an issue with no assignee simply has
    no `assignee` key), and a mapping that raised on the first ragged row would be useless.
    """
    steps = parse(path)
    return _walk(data, steps)


def _walk(node: Any, steps: list[str | int]) -> Any:
    if not steps:
        return node
    step, rest = steps[0], steps[1:]

    if step == "*":
        if not isinstance(node, list):
            return None
        return [_walk(item, rest) for item in node]

    if isinstance(step, int):
        if not isinstance(node, list) or not -len(node) <= step < len(node):
            return None
        return _walk(node[step], rest)

    if isinstance(node, list):  # a key after a [*] applies to every element
        return [_walk(item, [step, *rest]) for item in node]
    if not isinstance(node, dict):
        return None
    return _walk(node.get(step), rest)


def records_at(data: Any, path: str) -> list[Any]:
    """The list of records a mapping's `records_path` points at. An empty path means the root."""
    node = data if not path.strip() else resolve(data, path)
    if node is None:
        return []
    if isinstance(node, list):
        return node
    return [node]  # a single-object response is one row, not an error
