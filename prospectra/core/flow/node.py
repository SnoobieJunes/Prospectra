# 2026-07-13 (P2): The node contract — one small ABC per prep operation, compiled to a DuckDB SQL
# SELECT over named inputs. Each node declares a params schema the UI renders generically, so
# adding a node type means one file and zero bespoke dialogs (CLAUDE.md modularity rule).
# Third-party nodes register via the `prospectra.flow_nodes` entry-point group.

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.metadata import entry_points
from typing import Any, ClassVar, TypeVar

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "prospectra.flow_nodes"


@dataclass(frozen=True)
class ParamField:
    name: str
    label: str
    kind: str  # string | int | float | bool | choice | path | expression | columns
    default: Any = ""
    choices: tuple[str, ...] = ()
    help: str = ""


class Node(ABC):
    type_name: ClassVar[str]
    display_name: ClassVar[str]
    category: ClassVar[str]  # input | transform | combine | output
    min_inputs: ClassVar[int] = 1
    max_inputs: ClassVar[int] = 1  # -1 = unlimited (union)
    params_schema: ClassVar[tuple[ParamField, ...]] = ()

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params: dict[str, Any] = {f.name: f.default for f in self.params_schema}
        if params:
            self.params.update(params)

    def validate(self) -> None:  # noqa: B027 - optional hook, deliberately not abstract
        """Raise ValueError for unusable params; called before compiling.

        Default is a no-op: nodes without required params (e.g. Union) need no validation.
        """

    @abstractmethod
    def compile(self, inputs: list[str]) -> str:
        """Return a SQL SELECT statement reading from the given input relation names."""


NODE_TYPES: dict[str, type[Node]] = {}

_N = TypeVar("_N", bound=type[Node])


def register(cls: _N) -> _N:
    NODE_TYPES[cls.type_name] = cls
    return cls


def load_external_nodes() -> None:
    """Bring in third-party node plugins; failures are logged, never fatal."""
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
        except Exception:
            logger.warning("Could not load flow-node plugin %r", ep.name, exc_info=True)
            continue
        if isinstance(cls, type) and issubclass(cls, Node):
            NODE_TYPES.setdefault(cls.type_name, cls)
        else:
            logger.warning("Flow-node plugin %r is not a Node subclass; skipped", ep.name)
