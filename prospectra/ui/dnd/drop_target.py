# 2026-07-31 (P7): The drop-target mixin — one implementation of the dragEnter/dragLeave/drop
# dance and the shared active-border treatment. Before this, four widgets (NewDatasetZone,
# ColumnShelf, ChipBar, FlowView) each hand-rolled the same three event handlers and two of them
# duplicated the same #2a78d6 dashed-border styling; the mapper's FieldRow would have been copy
# number five.
#
# A subclass provides two hooks (decode + apply) and optionally a visual hook; the mixin owns the
# accept/ignore protocol, so "a payload we can't read is ignored, never crashes" is decided once.

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QMimeData

ACTIVE_DROP_COLOUR = "#2a78d6"


def drop_border_style(
    object_name: str, *, active: bool, width: int = 2, radius: int = 6, extra: str = ""
) -> str:
    """The dashed drop-zone border, blue while a compatible drag hovers."""
    colour = ACTIVE_DROP_COLOUR if active else "palette(mid)"
    return (
        f"#{object_name} {{ border: {width}px dashed {colour}; "
        f"border-radius: {radius}px; {extra} }}"
    )


class DropTargetMixin:
    """Mix in BEFORE the QWidget base (`class Zone(DropTargetMixin, QLabel)`), and call
    `setAcceptDrops(True)` in __init__. Hooks:

    - `_decode_drop(mime)` -> payload or None: what this target accepts.
    - `_payload_dropped(payload)`: what a successful drop does.
    - `_drop_active(active)`: optional visual treatment while a compatible drag hovers.
    """

    def _decode_drop(self, mime: QMimeData) -> Any:
        raise NotImplementedError

    def _payload_dropped(self, payload: Any) -> None:
        raise NotImplementedError

    def _drop_active(self, active: bool) -> None:
        pass

    # -- the protocol, decided once -----------------------------------------------------------

    def dragEnterEvent(self, event: Any) -> None:
        if self._decode_drop(event.mimeData()) is not None:
            event.acceptProposedAction()
            self._drop_active(True)
        else:
            event.ignore()

    def dragMoveEvent(self, event: Any) -> None:
        # QGraphicsView (and some containers) ignore moves unless re-accepted per event.
        if self._decode_drop(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: Any) -> None:
        self._drop_active(False)
        super().dragLeaveEvent(event)  # type: ignore[misc]

    def dropEvent(self, event: Any) -> None:
        payload = self._decode_drop(event.mimeData())
        self._drop_active(False)
        if payload is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self._payload_dropped(payload)
