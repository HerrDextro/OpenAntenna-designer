"""2D diagram editor: side and top projections of the wire model with draggable
parameter handles and dimension lines."""

from __future__ import annotations

import itertools
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTransform
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem,
                               QGraphicsRectItem, QGraphicsScene, QGraphicsSimpleTextItem,
                               QGraphicsView)

from ..model.document import NODE_ANTENNA
from ..model.units import format_length
from ..templates.base import SIDE, TOP, Handle
from .controller import DocumentController

KIND_COLORS = {
    "antenna": QColor("#1f4e8c"),
    "radials": QColor("#2e8b57"),
    "top_hat": QColor("#c8641e"),
    "loading_coil": QColor("#b22222"),
    "environment": QColor("#1f4e8c"),
}
SELECT_COLOR = QColor("#f0a800")
GROUND_COLOR = QColor("#8b6f47")
DIM_COLOR = QColor("#606060")
HANDLE_COLOR = QColor("#ff7f00")

_KEY_HANDLE = 0
_KEY_PART = 1
_drag_ids = itertools.count(1)


def _pen(color: QColor, width: float, style=Qt.PenStyle.SolidLine) -> QPen:
    pen = QPen(color, width, style)
    pen.setCosmetic(True)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    return pen


def _nice_step(minimum: float) -> float:
    for exp in range(-3, 6):
        for m in (1, 2, 5):
            step = m * 10 ** exp
            if step >= minimum:
                return step
    return 10 ** 6


class DiagramView(QGraphicsView):
    def __init__(self, ctl: DocumentController, view: str, parent=None):
        super().__init__(parent)
        self.ctl = ctl
        self.view_kind = view
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(-1e4, -1e4, 2e4, 2e4)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setMouseTracking(True)
        self.setTransform(QTransform(100, 0, 0, -100, 0, 0))

        self._handles: list[Handle] = []
        self._drag: tuple[Handle, QPointF, str] | None = None
        self._pan_last: QPointF | None = None
        self._press_pos: QPointF | None = None
        self._drag_text = ""
        self._fitted = False

        ctl.model_changed.connect(self.redraw)
        ctl.selection_changed.connect(lambda _: self.redraw())
        ctl.units_changed.connect(lambda _: self.redraw())
        self.redraw()

    # ---- coordinates ---------------------------------------------------

    def _project(self, p) -> QPointF:
        return QPointF(p[0], p[2]) if self.view_kind == SIDE else QPointF(p[0], p[1])

    def _px_to_m(self, px: float) -> float:
        return px / max(abs(self.transform().m11()), 1e-9)

    # ---- drawing ---------------------------------------------------------

    def redraw(self):
        scene = self.scene()
        scene.clear()
        project = self.ctl.project
        model = self.ctl.built.model
        kinds = {p.id: p.kind for p in project.parts}
        selected = self.ctl.selected

        for w in model.wires:
            a, b = self._project(w.p1), self._project(w.p2)
            kind = kinds.get(w.part_id, "antenna")
            color = KIND_COLORS.get(kind, KIND_COLORS["antenna"])
            is_selected = w.part_id == selected or (selected == NODE_ANTENNA and kind == "antenna")
            width = 3.5 if kind in ("antenna", "loading_coil") else 2.5
            path = QPainterPath(a)
            path.lineTo(b)
            if kind == "loading_coil":
                # The coil's wire is one NEC segment long; draw it as element
                # conductor with a fixed-size coil symbol at its centre.
                color = KIND_COLORS["antenna"]
                if self.view_kind == SIDE:
                    self._coil_symbol(QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2), a, b,
                                      w.part_id, is_selected)
            self._add_path(path, color, width, w.part_id, w.name, is_selected)
            if (a - b).manhattanLength() < 1e-9:
                self._marker(a, 7, color, color, w.part_id, w.name)

        for deco in project.template.decorations(project):
            if deco.view != self.view_kind:
                continue
            path = QPainterPath(QPointF(*deco.p1))
            path.lineTo(QPointF(*deco.p2))
            kind = kinds.get(deco.part_id, "antenna")
            style = Qt.PenStyle.DashLine if deco.dashed else Qt.PenStyle.SolidLine
            self._add_path(path, KIND_COLORS.get(kind, DIM_COLOR), 2, deco.part_id,
                           "Buried / ground radial", deco.part_id == selected, style)

        if model.source is not None and model.wires and self.view_kind == SIDE:
            src = model.wires[model.source.wire]
            t = model.source.fraction
            p = [src.p1[i] + (src.p2[i] - src.p1[i]) * t for i in range(3)]
            self._marker(self._project(p), 9, QColor("white"), QColor("#d00000"), "", "Feed point")
            self._label(self._project(p), "feed", QColor("#d00000"), dx=-22, dy=-10)

        for dim in project.template.dimensions(project):
            if dim.view == self.view_kind:
                self._dimension(dim)

        self._handles = [h for h in project.template.handles(project) if h.view == self.view_kind]
        for i, h in enumerate(self._handles):
            item = QGraphicsEllipseItem(-6, -6, 12, 12)
            item.setPos(QPointF(*h.pos))
            item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
            item.setBrush(QBrush(QColor("white")))
            item.setPen(QPen(HANDLE_COLOR, 2.5))
            item.setZValue(10)
            item.setData(_KEY_HANDLE, i)
            item.setToolTip(f"Drag to change {h.label}")
            item.setCursor(Qt.CursorShape.SizeAllCursor)
            scene.addItem(item)

        if not self._fitted and self.isVisible():
            self.fit()

    def _add_path(self, path: QPainterPath, color: QColor, width: float, part_id: str, tip: str,
                  selected: bool, style=Qt.PenStyle.SolidLine, z: float = 2):
        if selected:
            glow = QGraphicsPathItem(path)
            glow.setPen(_pen(SELECT_COLOR, width + 5))
            glow.setZValue(z - 1)
            self.scene().addItem(glow)
        item = QGraphicsPathItem(path)
        item.setPen(_pen(color, width, style))
        item.setZValue(z)
        item.setData(_KEY_PART, part_id)
        item.setToolTip(tip)
        self.scene().addItem(item)

    def _coil_symbol(self, center: QPointF, a: QPointF, b: QPointF, part_id: str, selected: bool):
        length = math.hypot(b.x() - a.x(), b.y() - a.y())
        if length < 1e-12:
            return
        ux, uy = (b.x() - a.x()) / length, (b.y() - a.y()) / length
        nx, ny = -uy, ux
        half = min(self._px_to_m(18), length / 2)
        amp = self._px_to_m(8)
        start = QPointF(center.x() - ux * half, center.y() - uy * half)
        path = QPainterPath(start)
        turns = 5
        for i in range(1, turns * 2):
            t = i / (turns * 2)
            s = amp if i % 2 else -amp
            path.lineTo(QPointF(start.x() + ux * 2 * half * t + nx * s,
                                start.y() + uy * 2 * half * t + ny * s))
        path.lineTo(QPointF(center.x() + ux * half, center.y() + uy * half))
        self._add_path(path, KIND_COLORS["loading_coil"], 2.5, part_id, "Loading coil", selected, z=4)

    def _marker(self, pos: QPointF, size: float, fill: QColor, edge: QColor, part_id: str, tip: str):
        item = QGraphicsEllipseItem(-size / 2, -size / 2, size, size)
        item.setPos(pos)
        item.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        item.setBrush(QBrush(fill))
        item.setPen(QPen(edge, 2))
        item.setZValue(5)
        item.setToolTip(tip)
        if part_id:
            item.setData(_KEY_PART, part_id)
        self.scene().addItem(item)

    def _label(self, pos: QPointF, text: str, color: QColor, dx: float = 0, dy: float = 0,
               bold: bool = False, away: tuple[float, float] = (0.0, 0.0)):
        anchor = QGraphicsRectItem(0, 0, 0, 0)
        anchor.setPen(QPen(Qt.PenStyle.NoPen))
        anchor.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations)
        anchor.setPos(pos)
        anchor.setZValue(8)
        label = QGraphicsSimpleTextItem(text, anchor)
        font = QFont()
        font.setPointSizeF(9)
        font.setBold(bold)
        label.setFont(font)
        label.setBrush(QBrush(color))
        r = label.boundingRect()
        dx += away[0] * (r.width() / 2 + 6)
        dy += away[1] * (r.height() / 2 + 3)
        label.setPos(dx - r.width() / 2, dy - r.height() / 2)
        self.scene().addItem(anchor)

    def _dimension(self, dim):
        (x1, y1), (x2, y2) = dim.p1, dim.p2
        length = math.hypot(x2 - x1, y2 - y1)
        if length < 1e-9:
            return
        nx, ny = -(y2 - y1) / length, (x2 - x1) / length
        o = self._px_to_m(dim.offset_px)
        a = QPointF(x1 + nx * o, y1 + ny * o)
        b = QPointF(x2 + nx * o, y2 + ny * o)
        path = QPainterPath(QPointF(x1, y1))
        path.lineTo(a)
        path.moveTo(QPointF(x2, y2))
        path.lineTo(b)
        path.moveTo(a)
        path.lineTo(b)
        tick = self._px_to_m(5)
        ux, uy = (x2 - x1) / length, (y2 - y1) / length
        for p in (a, b):
            path.moveTo(QPointF(p.x() - (ux - nx) * tick, p.y() - (uy - ny) * tick))
            path.lineTo(QPointF(p.x() + (ux - nx) * tick, p.y() + (uy - ny) * tick))
        item = QGraphicsPathItem(path)
        item.setPen(_pen(DIM_COLOR, 1))
        item.setZValue(0)
        self.scene().addItem(item)
        text = f"{dim.label} = {format_length(dim.value_m, self.ctl.project.units, 2)}"
        mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
        # Push the label off the line, on the offset side (device y points down).
        sign = 1 if o >= 0 else -1
        self._label(mid, text, DIM_COLOR, away=(sign * nx, -sign * ny))

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, QColor("#fbfbfd"))
        step = _nice_step(self._px_to_m(40))
        pen = _pen(QColor("#e6e8ee"), 1)
        painter.setPen(pen)
        x = math.floor(rect.left() / step) * step
        while x <= rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = math.floor(min(rect.top(), rect.bottom()) / step) * step
        while y <= max(rect.top(), rect.bottom()):
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step
        if self.view_kind == SIDE and self.ctl.project.environment["ground"] != "free_space":
            top = max(rect.top(), rect.bottom())
            bottom = min(rect.top(), rect.bottom())
            if bottom < 0:
                ground = QRectF(QPointF(rect.left(), 0), QPointF(rect.right(), bottom))
                painter.fillRect(ground.normalized(), QColor(139, 111, 71, 40))
            painter.setPen(_pen(GROUND_COLOR, 2))
            if bottom <= 0 <= top:
                painter.drawLine(QPointF(rect.left(), 0), QPointF(rect.right(), 0))

    def drawForeground(self, painter: QPainter, rect: QRectF):
        painter.save()
        painter.resetTransform()
        painter.setPen(QColor("#505050"))
        font = QFont()
        font.setBold(True)
        painter.setFont(font)
        title = "Side view" if self.view_kind == SIDE else "Top view"
        painter.drawText(10, 20, title)
        font.setBold(False)
        painter.setFont(font)
        step = _nice_step(self._px_to_m(40))
        painter.drawText(10, 38, f"grid {format_length(step, self.ctl.project.units, 2)}")
        if self._drag_text:
            painter.setPen(QColor("#202020"))
            painter.drawText(10, self.viewport().height() - 12, self._drag_text)
        painter.restore()

    # ---- view control ----------------------------------------------------

    def fit(self):
        model = self.ctl.built.model
        if not model.wires:
            return
        pts = [self._project(p) for w in model.wires for p in (w.p1, w.p2)]
        project = self.ctl.project
        pts += [QPointF(*p) for d in project.template.decorations(project)
                if d.view == self.view_kind for p in (d.p1, d.p2)]
        if self.view_kind == SIDE and self.ctl.project.environment["ground"] != "free_space":
            pts.append(QPointF(pts[0].x(), 0.0))
        xs, ys = [p.x() for p in pts], [p.y() for p in pts]
        w = max(max(xs) - min(xs), 0.5)
        h = max(max(ys) - min(ys), 0.5)
        # Leave pixel room for dimension labels and handles around the geometry.
        vw = self.viewport().width() - min(180, self.viewport().width() * 0.2)
        vh = self.viewport().height() - min(100, self.viewport().height() * 0.15)
        vw, vh = max(vw, 50), max(vh, 50)
        s = min(vw / (w * 1.1), vh / (h * 1.1))
        self.setTransform(QTransform(s, 0, 0, -s, 0, 0))
        self.centerOn(QPointF((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2))
        self._fitted = True
        self.redraw()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._fitted:
            self.fit()

    def wheelEvent(self, event):
        factor = 1.15 ** (event.angleDelta().y() / 120)
        self.scale(factor, factor)
        self.redraw()

    def mouseDoubleClickEvent(self, event):
        self.fit()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton and event.button() != Qt.MouseButton.MiddleButton:
            return super().mousePressEvent(event)
        self._press_pos = event.position()
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and item is not None \
                and item.data(_KEY_HANDLE) is not None:
            handle = self._handles[item.data(_KEY_HANDLE)]
            self._drag = (handle, self.mapToScene(event.position().toPoint()), f"drag{next(_drag_ids)}")
            self.ctl.select(handle.node_id)
            return
        self._pan_last = event.position()
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._drag is not None:
            handle, start, token = self._drag
            now = self.mapToScene(event.position().toPoint())
            dx, dy = now.x() - start.x(), now.y() - start.y()
            value = handle.value + dx * handle.axis[0] + dy * handle.axis[1]
            self.ctl.set_value(handle.node_id, handle.key, value, merge_token=token)
            new = self.ctl.project.node_values(handle.node_id)[handle.key]
            self._drag_text = f"{handle.label}: {format_length(new, self.ctl.project.units)}"
            self.viewport().update()
            return
        if self._pan_last is not None:
            delta = event.position() - self._pan_last
            self._pan_last = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was_click = (self._press_pos is not None
                     and (event.position() - self._press_pos).manhattanLength() < 4)
        if self._drag is None and was_click and event.button() == Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            part = item.data(_KEY_PART) if item is not None else None
            if part:
                self.ctl.select(part)
        self._drag = None
        self._drag_text = ""
        self._pan_last = None
        self._press_pos = None
        self.viewport().unsetCursor()
        self.viewport().update()
        super().mouseReleaseEvent(event)
