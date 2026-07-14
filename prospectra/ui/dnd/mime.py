# 2026-07-14 (P5): The drag-and-drop contract — three MIME types and their payloads.
#
# This is the "interactive and abstract" glue from the build plan. Every draggable thing in the app
# (a grid column, a dataset in the Sources tree, a finding in the Analyze table) encodes itself
# here, and every drop target (chart shelves, the chat dock, the New-dataset zone) decodes here.
# Because the payload is JSON in a named MIME type, a plugin's panel can join in without either
# side knowing about the other — which is the whole reason to have a backbone rather than ad-hoc
# signals between widgets.
#
# Every payload also carries a text/plain rendering, so dragging a column into any plain text field
# (or another app) does something sensible instead of nothing.

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QMimeData

MIME_COLUMN = "application/x-prospectra-column"
MIME_DATASET = "application/x-prospectra-dataset"
MIME_FINDING = "application/x-prospectra-finding"

ALL_MIME_TYPES = (MIME_COLUMN, MIME_DATASET, MIME_FINDING)


@dataclass(frozen=True)
class ColumnPayload:
    """One or more columns of one dataset. A multi-column drag is still a single payload."""

    dataset_id: str
    dataset: str
    origin: str
    columns: list[str] = field(default_factory=list)
    dtypes: list[str] = field(default_factory=list)

    @property
    def column(self) -> str:
        """The lead column — what a single-slot target (a chart shelf) uses."""
        return self.columns[0] if self.columns else ""

    @property
    def dtype(self) -> str:
        return self.dtypes[0] if self.dtypes else ""

    def as_text(self) -> str:
        return ", ".join(self.columns)


@dataclass(frozen=True)
class DatasetPayload:
    dataset_id: str
    dataset: str
    origin: str

    def as_text(self) -> str:
        return self.dataset


@dataclass(frozen=True)
class FindingPayload:
    kind: str
    title: str
    headline: str
    columns: list[str] = field(default_factory=list)
    effect: float = 0.0
    effect_name: str = ""
    q_value: float = 1.0

    def as_text(self) -> str:
        return f"{self.title} — {self.headline}"


def _pack(mime_type: str, payload: dict[str, Any], text: str) -> QMimeData:
    mime = QMimeData()
    mime.setData(mime_type, json.dumps(payload).encode("utf-8"))
    mime.setText(text)  # fallback: dropping into any text field still says something useful
    return mime


def _unpack(mime: QMimeData, mime_type: str) -> dict[str, Any] | None:
    if not mime.hasFormat(mime_type):
        return None
    try:
        loaded = json.loads(bytes(mime.data(mime_type).data()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


# -- columns ------------------------------------------------------------------------------------


def column_mime(payload: ColumnPayload) -> QMimeData:
    return _pack(
        MIME_COLUMN,
        {
            "dataset_id": payload.dataset_id,
            "dataset": payload.dataset,
            "origin": payload.origin,
            "columns": payload.columns,
            "dtypes": payload.dtypes,
        },
        payload.as_text(),
    )


def read_column(mime: QMimeData) -> ColumnPayload | None:
    doc = _unpack(mime, MIME_COLUMN)
    if doc is None or not doc.get("columns"):
        return None
    return ColumnPayload(
        dataset_id=str(doc.get("dataset_id", "")),
        dataset=str(doc.get("dataset", "")),
        origin=str(doc.get("origin", "")),
        columns=[str(c) for c in doc["columns"]],
        dtypes=[str(d) for d in doc.get("dtypes", [])],
    )


# -- datasets -----------------------------------------------------------------------------------


def dataset_mime(payload: DatasetPayload) -> QMimeData:
    return _pack(
        MIME_DATASET,
        {
            "dataset_id": payload.dataset_id,
            "dataset": payload.dataset,
            "origin": payload.origin,
        },
        payload.as_text(),
    )


def read_dataset(mime: QMimeData) -> DatasetPayload | None:
    doc = _unpack(mime, MIME_DATASET)
    if doc is None or not doc.get("dataset_id"):
        return None
    return DatasetPayload(
        dataset_id=str(doc["dataset_id"]),
        dataset=str(doc.get("dataset", "")),
        origin=str(doc.get("origin", "")),
    )


# -- findings -----------------------------------------------------------------------------------


def finding_mime(payload: FindingPayload) -> QMimeData:
    return _pack(
        MIME_FINDING,
        {
            "kind": payload.kind,
            "title": payload.title,
            "headline": payload.headline,
            "columns": payload.columns,
            "effect": payload.effect,
            "effect_name": payload.effect_name,
            "q_value": payload.q_value,
        },
        payload.as_text(),
    )


def read_finding(mime: QMimeData) -> FindingPayload | None:
    doc = _unpack(mime, MIME_FINDING)
    if doc is None or not doc.get("title"):
        return None
    return FindingPayload(
        kind=str(doc.get("kind", "")),
        title=str(doc["title"]),
        headline=str(doc.get("headline", "")),
        columns=[str(c) for c in doc.get("columns", [])],
        effect=float(doc.get("effect", 0.0)),
        effect_name=str(doc.get("effect_name", "")),
        q_value=float(doc.get("q_value", 1.0)),
    )


def accepts(mime: QMimeData, *types: str) -> bool:
    """True when the drag carries any of the given Prospectra payloads."""
    return any(mime.hasFormat(t) for t in types)
