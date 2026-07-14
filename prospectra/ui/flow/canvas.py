# 2026-07-13 (P2): The flow canvas — a QGraphicsScene/View over a core FlowGraph. Owns interaction
# (drag nodes, drag port→port to connect, delete, rubber-band select) and keeps the scene in sync
# with the model; it never runs SQL itself, it emits signals the Flow tab acts on.

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QKeyEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QGraphicsPathItem,
    QGraphicsScene,
    QGraphicsSceneMouseEvent,
    QGraphicsView,
)

from prospectra.core.flow import FlowGraph, FlowGraphError
from prospectra.ui.flow.canvas_items import EdgeItem, NodeItem


class FlowScene(QGraphicsScene):
    node_double_clicked = Signal(str)
    selection_changed_id = Signal(str)  # node id, or "" when nothing is selected
    graph_changed = Signal()
    edge_rejected = Signal(str)  # human-readable reason (cycle, port taken, …)

    def __init__(self, graph: FlowGraph) -> None:
        super().__init__()
        self.graph = graph
        self._nodes: dict[str, NodeItem] = {}
        self._edges: list[EdgeItem] = []
        self._pending: tuple[str, str, int] | None = None  # (node_id, kind, port) while dragging
        self._rubber: QGraphicsPathItem | None = None
        self.selectionChanged.connect(self._emit_selection)
        self.rebuild()

    # -- model <-> scene ----------------------------------------------------------------

    def rebuild(self) -> None:
        self.clear()
        self._nodes.clear()
        self._edges.clear()
        self._rubber = None
        for instance in self.graph.nodes.values():
            node_item = NodeItem(instance)
            self.addItem(node_item)
            self._nodes[instance.id] = node_item
        for edge in self.graph.edges:
            src, dst = self._nodes.get(edge.src), self._nodes.get(edge.dst)
            if src and dst:
                edge_item = EdgeItem(src, dst, edge.port)
                self.addItem(edge_item)
                self._edges.append(edge_item)

    def refresh_edges(self) -> None:
        for edge in self._edges:
            edge.refresh()

    def add_node(self, type_name: str, pos: QPointF) -> str:
        node_id = self.graph.add_node(type_name, pos=(pos.x(), pos.y()))
        item = NodeItem(self.graph.nodes[node_id])
        self.addItem(item)
        self._nodes[node_id] = item
        self.graph_changed.emit()
        return node_id

    def mark_error(self, node_id: str | None, message: str | None) -> None:
        for nid, item in self._nodes.items():
            item.error = message if nid == node_id else None
            item.update()

    def selected_node_id(self) -> str | None:
        for item in self.selectedItems():
            if isinstance(item, NodeItem):
                return item.node_id
        return None

    def _emit_selection(self) -> None:
        self.selection_changed_id.emit(self.selected_node_id() or "")

    # -- interaction ---------------------------------------------------------------------

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        item = self._node_at(event.scenePos())
        if item is not None:
            hit = item.port_at(event.scenePos())
            if hit is not None:
                kind, port = hit
                self._pending = (item.node_id, kind, port)
                self._rubber = QGraphicsPathItem()
                self._rubber.setPen(QPen(self.palette().text().color(), 2, Qt.PenStyle.DashLine))
                self.addItem(self._rubber)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._pending is not None and self._rubber is not None:
            node_id, kind, port = self._pending
            item = self._nodes[node_id]
            anchor = item.output_port_pos() if kind == "out" else item.input_port_pos(port)
            path = QPainterPath(anchor)
            path.lineTo(event.scenePos())
            self._rubber.setPath(path)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._pending is not None:
            if self._rubber is not None:
                self.removeItem(self._rubber)
                self._rubber = None
            source_id, kind, port = self._pending
            self._pending = None
            target = self._node_at(event.scenePos())
            if target is not None and target.node_id != source_id:
                hit = target.port_at(event.scenePos())
                # Accept either drag direction: output→input or input→output.
                if kind == "out":
                    dst_port = hit[1] if hit and hit[0] == "in" else 0
                    self._connect(source_id, target.node_id, dst_port)
                elif hit is None or hit[0] == "out":
                    self._connect(target.node_id, source_id, port)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _connect(self, src: str, dst: str, port: int) -> None:
        try:
            self.graph.add_edge(src, dst, port)
        except FlowGraphError as exc:
            self.edge_rejected.emit(str(exc))
            return
        item = EdgeItem(self._nodes[src], self._nodes[dst], port)
        self.addItem(item)
        self._edges.append(item)
        self.graph_changed.emit()

    def _node_at(self, pos: QPointF) -> NodeItem | None:
        for item in self.items(pos):
            if isinstance(item, NodeItem):
                return item
        # Ports stick out past the node body; catch near-misses on the port circles.
        for node in self._nodes.values():
            if node.port_at(pos) is not None:
                return node
        return None

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            removed = False
            for item in list(self.selectedItems()):
                if isinstance(item, NodeItem):
                    self.graph.remove_node(item.node_id)
                    removed = True
                elif isinstance(item, EdgeItem):
                    self.graph.remove_edge(item.src.node_id, item.dst.node_id, item.port)
                    removed = True
            if removed:
                self.rebuild()
                self.graph_changed.emit()
                event.accept()
                return
        super().keyPressEvent(event)


class FlowView(QGraphicsView):
    def __init__(self, scene: FlowScene) -> None:
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setMinimumHeight(220)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
            return
        super().wheelEvent(event)
