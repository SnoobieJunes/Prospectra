# 2026-07-13 (P2): Canvas graphics items — node boxes with typed ports, and the bezier edges
# between them. Kept separate from the scene so the scene file stays about interaction, not
# painting (CLAUDE.md: no monoliths).

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsSceneMouseEvent,
    QStyleOptionGraphicsItem,
    QWidget,
)

if TYPE_CHECKING:
    from prospectra.core.flow.graph import NodeInstance

NODE_W = 150.0
NODE_H = 54.0
PORT_R = 5.0

# Category hues from the dataviz reference palette (categorical slots, fixed order — never cycled).
_CATEGORY_COLOR = {
    "input": QColor("#2a78d6"),  # blue
    "transform": QColor("#1baf7a"),  # aqua
    "combine": QColor("#4a3aa7"),  # violet
    "output": QColor("#eb6834"),  # orange
}
_INVALID = QColor("#e34948")  # red — reserved status color, used only for error state


class NodeItem(QGraphicsItem):
    """A node box: title, category stripe, input port(s) on the left, output port on the right."""

    def __init__(self, instance: NodeInstance) -> None:
        super().__init__()
        self.instance = instance
        self.node_id = instance.id
        self.error: str | None = None
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setPos(instance.x, instance.y)
        self.setToolTip(type(instance.node).display_name)

    # -- geometry ---------------------------------------------------------------------

    def boundingRect(self) -> QRectF:
        return QRectF(-PORT_R, 0, NODE_W + 2 * PORT_R, NODE_H)

    @property
    def n_input_ports(self) -> int:
        node = self.instance.node
        if node.max_inputs == 0:
            return 0
        return 2 if node.max_inputs == 2 else 1

    def input_port_pos(self, port: int) -> QPointF:
        ports = max(self.n_input_ports, 1)
        step = NODE_H / (ports + 1)
        return self.mapToScene(QPointF(0.0, step * (port + 1)))

    def output_port_pos(self) -> QPointF:
        return self.mapToScene(QPointF(NODE_W, NODE_H / 2))

    def port_at(self, scene_pos: QPointF) -> tuple[str, int] | None:
        """Return ('in', port) / ('out', 0) if scene_pos is on a port, else None."""
        for port in range(self.n_input_ports):
            if (scene_pos - self.input_port_pos(port)).manhattanLength() <= PORT_R * 2.5:
                return ("in", port)
        if self.instance.node.category != "output" and (
            (scene_pos - self.output_port_pos()).manhattanLength() <= PORT_R * 2.5
        ):
            return ("out", 0)
        return None

    # -- painting ---------------------------------------------------------------------

    def paint(
        self, painter: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None
    ) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        node = self.instance.node
        accent = _CATEGORY_COLOR.get(node.category, QColor("#2a78d6"))
        surface = self.scene().palette().base().color() if self.scene() else QColor("#ffffff")
        ink = self.scene().palette().text().color() if self.scene() else QColor("#000000")

        body = QRectF(0, 0, NODE_W, NODE_H)
        painter.setBrush(QBrush(surface))
        border = _INVALID if self.error else accent
        width = 2 if self.isSelected() or self.error else 1
        painter.setPen(QPen(border, width))
        painter.drawRoundedRect(body, 6, 6)

        # category stripe along the top edge
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        stripe = QPainterPath()
        stripe.addRoundedRect(QRectF(1, 1, NODE_W - 2, 5), 2, 2)
        painter.drawPath(stripe)

        painter.setPen(QPen(ink))
        title = type(node).display_name
        painter.drawText(QRectF(8, 10, NODE_W - 16, 18), Qt.AlignmentFlag.AlignLeft, title)
        subtitle = self._subtitle()
        if subtitle:
            faded = QColor(ink)
            faded.setAlpha(150)
            painter.setPen(QPen(faded))
            metrics = painter.fontMetrics()
            elided = metrics.elidedText(subtitle, Qt.TextElideMode.ElideRight, int(NODE_W - 16))
            painter.drawText(QRectF(8, 30, NODE_W - 16, 16), Qt.AlignmentFlag.AlignLeft, elided)

        painter.setPen(QPen(accent))
        painter.setBrush(QBrush(surface))
        for port in range(self.n_input_ports):
            local = self.mapFromScene(self.input_port_pos(port))
            painter.drawEllipse(local, PORT_R, PORT_R)
        if node.category != "output":
            painter.setBrush(QBrush(accent))
            painter.drawEllipse(self.mapFromScene(self.output_port_pos()), PORT_R, PORT_R)

    def _subtitle(self) -> str:
        """One-line hint of what the node does — the canvas 'change badge'."""
        params = self.instance.node.params
        for key in ("path", "expression", "aggregations", "columns", "left_on", "on", "column"):
            value = str(params.get(key, "")).strip()
            if value:
                return value.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return ""

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: object) -> object:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            pos = self.pos()
            self.instance.x, self.instance.y = pos.x(), pos.y()
            scene = self.scene()
            if scene is not None:
                scene.refresh_edges()  # type: ignore[attr-defined]
        return super().itemChange(change, value)

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        scene = self.scene()
        if scene is not None:
            scene.node_double_clicked.emit(self.node_id)  # type: ignore[attr-defined]
        super().mouseDoubleClickEvent(event)


class EdgeItem(QGraphicsPathItem):
    """A bezier connection from one node's output to another node's input port."""

    def __init__(self, src: NodeItem, dst: NodeItem, port: int) -> None:
        super().__init__()
        self.src = src
        self.dst = dst
        self.port = port
        self.setZValue(-1)  # edges paint behind nodes
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.refresh()

    def refresh(self) -> None:
        start = self.src.output_port_pos()
        end = self.dst.input_port_pos(self.port)
        dx = max(40.0, abs(end.x() - start.x()) * 0.5)
        path = QPainterPath(start)
        path.cubicTo(start + QPointF(dx, 0), end - QPointF(dx, 0), end)
        self.setPath(path)
        color = self.scene().palette().text().color() if self.scene() else QColor("#666666")
        color.setAlpha(200 if self.isSelected() else 120)  # recessive unless selected
        self.setPen(QPen(color, 2.5 if self.isSelected() else 2))
