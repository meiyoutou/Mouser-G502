"""Pixel-coordinate editing; opt-in text selection uses a private local worker.

The same flattened QImage is used for the preview, clipboard, save and pin.
Undo stores small immutable commands, not one whole desktop bitmap per stroke.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QFont, QImage, QKeySequence, QPainter,
    QPainterPath, QPen, QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QFileDialog, QHBoxLayout, QInputDialog,
    QLabel, QMessageBox, QScrollArea, QSizeGrip, QSpinBox, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from ui.screenshot_locale import screenshot_text


def _zoom_factor(delta):
    return 1.2 ** max(-10., min(10., delta / 120.))


def _resize_at_pointer(scroll, content, resize, anchor=None):
    """Keep the same image pixel under the pointer, subject to scroll bounds."""
    viewport = scroll.viewport()
    anchor = QPointF(anchor if anchor is not None else viewport.rect().center())
    origin = QPointF(content.mapTo(viewport, QPoint()))
    x = (anchor.x() - origin.x()) / max(1, content.width())
    y = (anchor.y() - origin.y()) / max(1, content.height())
    resize()
    origin = QPointF(content.mapTo(viewport, QPoint()))
    for bar, distance in (
            (scroll.horizontalScrollBar(), origin.x() + x * content.width() - anchor.x()),
            (scroll.verticalScrollBar(), origin.y() + y * content.height() - anchor.y())):
        bar.setValue(bar.value() + round(distance))


class _ImageViewNavigation(QObject):
    """Wheel zoom works over both pixels and viewport padding, without focus."""
    def __init__(self, owner, scroll, content):
        super().__init__(owner)
        self.owner, self.scroll = owner, scroll
        scroll.viewport().installEventFilter(self)
        content.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.Wheel:
            angle, pixels = event.angleDelta().y(), event.pixelDelta().y()
            if not angle and not pixels:
                return False
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                anchor = self.scroll.viewport().mapFromGlobal(event.globalPosition().toPoint())
                self.owner.zoom(angle if angle else pixels, anchor)
            else:
                # Handle both the image and empty viewport explicitly; wheel
                # events on a child widget do not reliably reach QScrollArea.
                bar = (self.scroll.horizontalScrollBar()
                       if event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                       else self.scroll.verticalScrollBar())
                distance = pixels if pixels else angle / 120. * bar.singleStep() * QApplication.wheelScrollLines()
                bar.setValue(bar.value() - round(distance))
            event.accept()
            return True
        return super().eventFilter(watched, event)


@dataclass(frozen=True)
class Annotation:
    kind: str
    points: tuple[tuple[float, float], ...]
    color: str = "#ef4444"
    width: int = 4
    font_size: int = 28
    block: int = 16
    text: str = ""


class ScreenshotDocument:
    def __init__(self, image: QImage):
        if image.isNull():
            raise ValueError("empty screenshot")
        self.base = image.convertToFormat(QImage.Format.Format_RGB32)
        self.base.setDevicePixelRatio(1)
        self.annotations: tuple[Annotation, ...] = ()
        self.crop = self.base.rect()
        self._undo = []
        self._redo = []
        self._cached = None

    def _commit(self):
        self._undo.append((self.annotations, QRect(self.crop)))
        self._undo = self._undo[-200:]
        self._redo.clear()
        self._cached = None

    def add(self, annotation):
        if annotation.kind not in {"rect", "ellipse", "arrow", "pen", "text", "number", "mosaic", "redact"}:
            raise ValueError("unknown annotation tool")
        if not annotation.points:
            return
        self._commit()
        self.annotations += (annotation,)

    def replace_annotation(self, index, annotation):
        self._commit()
        items = list(self.annotations)
        if annotation is None:
            items.pop(index)
        else:
            items[index] = annotation
        self.annotations = tuple(items)

    def set_crop(self, rect):
        rect = QRect(rect).normalized().intersected(self.base.rect())
        if rect.width() < 2 or rect.height() < 2 or rect == self.crop:
            return False
        self._commit()
        self.crop = rect
        return True

    def undo(self):
        if not self._undo:
            return False
        self._redo.append((self.annotations, QRect(self.crop)))
        self.annotations, self.crop = self._undo.pop()
        self._cached = None
        return True

    def redo(self):
        if not self._redo:
            return False
        self._undo.append((self.annotations, QRect(self.crop)))
        self.annotations, self.crop = self._redo.pop()
        self._cached = None
        return True

    def render(self, draft=None):
        if self._cached is None:
            result = self.base.copy()
            for annotation in self.annotations:
                paint_annotation(result, annotation)
            self._cached = result
        if draft is not None:
            result = self._cached.copy()
            paint_annotation(result, draft)
            return result.copy(self.crop)
        return self._cached.copy(self.crop)


def paint_annotation(image, annotation, origin=QPoint()):
    points = [QPointF(x - origin.x(), y - origin.y()) for x, y in annotation.points]
    start, end = points[0], points[-1]
    rect = QRectF(start, end).normalized()
    if annotation.kind == "mosaic":
        # Pixelate the already flattened content, never store a reversible layer
        # or an original screenshot as output metadata.
        area = rect.toAlignedRect().intersected(image.rect())
        if area.isEmpty():
            return
        block = max(2, annotation.block)
        patch = image.copy(area).scaled(
            max(1, math.ceil(area.width() / block)),
            max(1, math.ceil(area.height() / block)),
            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation,
        ).scaled(area.size(), Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
        painter = QPainter(image)
        painter.drawImage(area.topLeft(), patch)
        painter.end()
        return
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(annotation.color)
    painter.setPen(QPen(color, max(1, annotation.width), Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if annotation.kind == "rect":
        painter.drawRect(rect)
    elif annotation.kind == "ellipse":
        painter.drawEllipse(rect)
    elif annotation.kind == "arrow":
        painter.drawLine(start, end)
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        length = max(12, annotation.width * 4)
        wings = [end - QPointF(math.cos(angle + sign * .55) * length,
                               math.sin(angle + sign * .55) * length) for sign in (-1, 1)]
        painter.setBrush(color)
        painter.drawPolygon(QPolygonF([end, *wings]))
    elif annotation.kind == "pen":
        if len(points) == 1:
            painter.drawPoint(start)
        else:
            path = QPainterPath(start)
            for point in points[1:]:
                path.lineTo(point)
            painter.drawPath(path)
    elif annotation.kind == "text":
        font = QFont()
        font.setPixelSize(max(8, annotation.font_size))
        painter.setFont(font)
        for idx, line in enumerate(annotation.text.splitlines()):
            painter.drawText(start + QPointF(0, annotation.font_size * (idx + 1)), line)
    elif annotation.kind == "number":
        radius = max(12, annotation.font_size * .7)
        painter.setBrush(color)
        painter.drawEllipse(start, radius, radius)
        painter.setPen(Qt.GlobalColor.white)
        font = QFont()
        font.setBold(True)
        font.setPixelSize(annotation.font_size)
        painter.setFont(font)
        painter.drawText(QRectF(start.x() - radius, start.y() - radius, radius * 2, radius * 2),
                         Qt.AlignmentFlag.AlignCenter, annotation.text)
    elif annotation.kind == "redact":
        # Integer solid fill avoids anti-aliased edges revealing sensitive pixels.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.fillRect(rect.toAlignedRect(), color)
    painter.end()


def rect_handles(rect):
    return [rect.topLeft(), QPointF(rect.center().x(), rect.top()), rect.topRight(),
            QPointF(rect.right(), rect.center().y()), rect.bottomRight(),
            QPointF(rect.center().x(), rect.bottom()), rect.bottomLeft(),
            QPointF(rect.left(), rect.center().y())]


def resize_selection(rect, handle, point, bounds):
    """Resize 8 handles without ever leaving the original image bounds."""
    r = QRectF(rect)
    p = QPointF(max(bounds.left(), min(bounds.right(), point.x())),
                max(bounds.top(), min(bounds.bottom(), point.y())))
    if handle in (0, 6, 7):
        r.setLeft(p.x())
    if handle in (2, 3, 4):
        r.setRight(p.x())
    if handle in (0, 1, 2):
        r.setTop(p.y())
    if handle in (4, 5, 6):
        r.setBottom(p.y())
    return r.normalized().intersected(bounds)


class ScreenshotCanvas(QWidget):
    changed = Signal()
    imageChanged = Signal()
    textRequested = Signal(object)
    selectionRequested = Signal()

    def __init__(self, document, parent=None):
        super().__init__(parent)
        self.setObjectName("screenshotCanvas")
        self.setAccessibleName("Screenshot canvas")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.document = document
        self.tool = "rect"
        self.color = "#ef4444"
        self.stroke = 4
        self.font_size = 28
        self.block = 16
        self.scale = 1.0
        self.selection = None
        self._points = []
        self._drag_mode = None
        self._drag_start = None
        self._drag_rect = None
        self._display_image = document.render()
        self.text_layer = None
        self._text_dragging = False
        self.magnifier_enabled = False
        self._pointer = None
        self.refresh()

    def refresh(self):
        self.imageChanged.emit()
        self._display_image = self.document.render()
        self._resize_view()
        self.changed.emit()

    def _resize_view(self):
        self.setFixedSize(max(1, round(self._display_image.width() * self.scale)),
                          max(1, round(self._display_image.height() * self.scale)))
        self.update()

    def set_scale(self, scale):
        self.scale = max(.05, min(4.0, float(scale)))
        # Zoom changes view geometry, not image pixels or recognized coordinates.
        self._resize_view()
        self.changed.emit()

    def image_point(self, local):
        r = self.document.crop
        return QPointF(max(r.left(), min(r.x() + r.width(), local.x() / self.scale + r.x())),
                       max(r.top(), min(r.y() + r.height(), local.y() / self.scale + r.y())))

    def set_tool(self, tool):
        self.tool = tool
        self._points = []
        self._drag_mode = None
        self.selection = None
        self._text_dragging = False
        if self.text_layer is not None:
            self.text_layer.clear()
        self.setCursor(Qt.CursorShape.ArrowCursor if tool == "select" else Qt.CursorShape.CrossCursor)
        self.update()

    def annotation(self, points, *, text=""):
        return Annotation(self.tool, tuple((p.x(), p.y()) for p in points),
                          self.color, self.stroke, self.font_size, self.block, text)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.scale(self.scale, self.scale)
        painter.drawImage(0, 0, self._display_image)
        if self._points and self.tool not in {"select", "crop", "text", "number"}:
            draft = self.document.render(self.annotation(self._points))
            painter.drawImage(0, 0, draft)
        if self.selection is not None:
            rect = self.selection.translated(-self.document.crop.x(), -self.document.crop.y())
            painter.setPen(QPen(QColor("#22c1c3"), 1.5 / self.scale, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            painter.setBrush(Qt.GlobalColor.white)
            for point in rect_handles(rect):
                side = 7 / self.scale
                painter.drawRect(QRectF(point.x() - side / 2, point.y() - side / 2, side, side))
        if self.text_layer is not None and self.tool == "select":
            for box in self.text_layer.selected_boxes():
                painter.fillRect(box.translated(-self.document.crop.x(), -self.document.crop.y()),
                                 QColor(22, 119, 255, 85))
        painter.end()
        if self.magnifier_enabled and self._pointer is not None:
            painter = QPainter(self)
            from ui.screenshot_tools import draw_magnifier
            source = QPoint(round(self._pointer.x() / self.scale), round(self._pointer.y() / self.scale))
            draw_magnifier(painter, self._display_image, source, self._pointer.toPoint(), self.rect())
            painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.selectionRequested.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        point = self.image_point(event.position())
        if self.tool == "select":
            # Neutral pointer mode must not create a pending crop which would
            # later be silently applied by Copy, Save, or Finish.
            if self.text_layer is not None:
                self._text_dragging = self.text_layer.begin(point)
                self.update()
            return
        if self.tool == "text":
            self.textRequested.emit(point)
            return
        if self.tool == "number":
            number = 1 + sum(a.kind == "number" for a in self.document.annotations)
            self.document.add(self.annotation([point], text=str(number)))
            self.refresh()
            return
        self._points = [point]
        if self.tool == "crop":
            self._drag_start = point
            self._drag_rect = QRectF(self.selection) if self.selection is not None else None
            self._drag_mode = "new"
            if self.selection is not None:
                for idx, handle in enumerate(rect_handles(self.selection)):
                    if math.hypot(point.x() - handle.x(), point.y() - handle.y()) * self.scale <= 9:
                        self._drag_mode = idx
                        break
                else:
                    if self.selection.contains(point):
                        self._drag_mode = "move"
            if self._drag_mode == "new":
                self.selection = QRectF(point, point)
        self.update()

    def mouseMoveEvent(self, event):
        self._pointer = event.position()
        if self.tool == "select" and self.text_layer is not None:
            point = self.image_point(event.position())
            if self._text_dragging:
                self.text_layer.extend(point)
                self.update()
            self.setCursor(Qt.CursorShape.IBeamCursor if self._text_dragging
                           or self.text_layer.hit(point) is not None else Qt.CursorShape.ArrowCursor)
        if self.magnifier_enabled:
            self.update()
        if not self._points:
            return
        point = self.image_point(event.position())
        if self.tool == "crop":
            bounds = QRectF(self.document.crop)
            if self._drag_mode == "new":
                self.selection = QRectF(self._drag_start, point).normalized()
            elif self._drag_mode == "move":
                r = self._drag_rect.translated(point - self._drag_start)
                r.moveLeft(max(bounds.left(), min(bounds.right() - r.width(), r.left())))
                r.moveTop(max(bounds.top(), min(bounds.bottom() - r.height(), r.top())))
                self.selection = r
            elif isinstance(self._drag_mode, int):
                self.selection = resize_selection(self._drag_rect, self._drag_mode, point, bounds)
        elif self.tool == "pen":
            if len(self._points) < 10000:
                self._points.append(point)
        else:
            self._points = [self._points[0], point]
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._text_dragging:
            self.mouseMoveEvent(event)
            self._text_dragging = False
            self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self._points:
            return
        self.mouseMoveEvent(event)
        if self.tool != "crop":
            self.document.add(self.annotation(self._points))
        self._points = []
        self._drag_mode = None
        self.refresh()

    def apply_crop(self):
        if self.selection is not None:
            self.document.set_crop(self.selection.toAlignedRect())
            self.selection = None
            self.refresh()


class _PinDragHandle(QToolButton):
    """Only explicit user dragging moves the pinned window; no input hooks."""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.owner._drag_offset = event.globalPosition().toPoint() - self.owner.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.owner._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint() - self.owner._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.owner._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)


class _PinnedImageView(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(self.rect(), self.owner.image)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.owner.close()
        elif event.button() == Qt.MouseButton.LeftButton:
            self.owner._drag_offset = event.globalPosition().toPoint() - self.owner.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.owner._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.owner.move(event.globalPosition().toPoint() - self.owner._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.owner._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        event.accept()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.owner.zoom(event.angleDelta().y())
            event.accept()
        else:
            event.ignore()  # QScrollArea scrolls the long image normally.


class ScreenshotPin(QWidget):
    closed = Signal(object)

    def __init__(self, image, locale=None, *, clipboard_factory=None):
        super().__init__()
        if image.isNull():
            raise ValueError("empty screenshot")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.image = image.copy()
        self.image.setDevicePixelRatio(1)
        self.locale = locale
        self.clipboard_factory = clipboard_factory or QApplication.clipboard
        self._drag_offset = None
        self._zoom = 1.0
        self._fit_width = True
        self.setObjectName("screenshotPin")
        self.setStyleSheet("""
            QWidget#screenshotPin {background:white; border:1px solid #cbd5e1;}
            QToolButton {background:transparent; border:1px solid transparent;
                         border-radius:4px; padding:2px;}
            QToolButton:hover {background:#edf3fa; border-color:#dbe1e8;}
            QToolButton#pinDrag {background:#f1f5f9; border-color:#dbe1e8;}
            QToolButton#pinClose:hover {background:#fee2e2;}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(0)
        tools = QWidget(self)
        tools.setFixedHeight(34)
        row = QHBoxLayout(tools)
        row.setContentsMargins(4, 3, 4, 3)
        row.setSpacing(4)
        from ui.screenshot_toolbar import tool_icon
        self.drag_handle = _PinDragHandle(self)
        self.drag_handle.setObjectName("pinDrag")
        self.drag_handle.setIcon(tool_icon("hand"))
        self.drag_handle.setFixedSize(40, 28)
        row.addWidget(self.drag_handle)
        row.addStretch()
        self.zoom_out_button = QToolButton(self)
        self.zoom_in_button = QToolButton(self)
        self.fit_button = QToolButton(self)
        for button, key, callback in (
                (self.zoom_out_button, "zoom_out", lambda: self.zoom(-120)),
                (self.zoom_in_button, "zoom_in", lambda: self.zoom(120)),
                (self.fit_button, "fit", self.fit_image)):
            button.setIcon(tool_icon(key))
            button.clicked.connect(callback)
            row.addWidget(button)
        self.copy_button = QToolButton(self)
        self.copy_button.setIcon(tool_icon("copy"))
        self.copy_button.clicked.connect(self.copy_image)
        row.addWidget(self.copy_button)
        self.close_button = QToolButton(self)
        self.close_button.setObjectName("pinClose")
        self.close_button.setIcon(tool_icon("cancel"))
        self.close_button.clicked.connect(self.close)
        row.addWidget(self.close_button)
        controls = (self.zoom_out_button, self.zoom_in_button, self.fit_button,
                    self.copy_button, self.close_button)
        for button in (self.drag_handle, *controls):
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setIconSize(QSize(22, 22))
        for button in controls:
            button.setFixedSize(28, 28)
        layout.addWidget(tools)
        self.scroll = QScrollArea(self)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.scroll.setStyleSheet("QScrollArea {background:#f8fafc; border:none;}")
        self.view = _PinnedImageView(self)
        self.scroll.setWidget(self.view)
        self.scroll.viewport().installEventFilter(self)
        self._navigation = _ImageViewNavigation(self, self.scroll, self.view)
        layout.addWidget(self.scroll)
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.addStretch()
        self.resize_grip = QSizeGrip(self)
        self.resize_grip.setFixedSize(14, 14)
        footer.addWidget(self.resize_grip)
        layout.addLayout(footer)
        self.setMinimumSize(250, 100)
        if locale is not None:
            locale.languageChanged.connect(self.refresh_language)
        self.refresh_language()
        screen = QApplication.screenAt(self.cursor().pos()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        width = min(self.image.width(), max(120, int(available.width() * .65)))
        height = round(self.image.height() * width / self.image.width())
        self.resize(max(250, width + 2), max(100, min(height + 50, int(available.height() * .7))))
        self._resize_image()
        self.move(available.center() - self.rect().center())

    def refresh_language(self):
        self.setWindowTitle(screenshot_text("pin", self.locale))
        self.setToolTip(screenshot_text("pin_hint", self.locale))
        for button, key in ((self.drag_handle, "pin_drag"), (self.copy_button, "copy"),
                            (self.close_button, "pin_close"), (self.zoom_in_button, "zoom_in"),
                            (self.zoom_out_button, "zoom_out"), (self.fit_button, "fit")):
            button.setToolTip(screenshot_text(key, self.locale))
            button.setAccessibleName(screenshot_text(key, self.locale))
        self.resize_grip.setToolTip(screenshot_text("resize_window", self.locale))
        self.resize_grip.setAccessibleName(self.resize_grip.toolTip())

    def _resize_image(self):
        if self._fit_width:
            self._zoom = min(1., max(1, self.scroll.viewport().width() - 2) / self.image.width())
        width = max(1, round(self.image.width() * self._zoom))
        height = max(1, round(self.image.height() * self._zoom))
        self.view.setFixedSize(width, height)

    def fit_image(self):
        self._fit_width = True
        self._resize_image()

    def eventFilter(self, watched, event):
        if watched is self.scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._resize_image()
        return super().eventFilter(watched, event)

    def zoom(self, delta, anchor=None):
        if delta:
            self._fit_width = False
            self._zoom = max(.05, min(4., self._zoom * _zoom_factor(delta)))
            _resize_at_pointer(self.scroll, self.view, self._resize_image, anchor)

    def copy_image(self):
        try:
            clipboard = self.clipboard_factory()
            if clipboard is None:
                raise RuntimeError("clipboard unavailable")
            clipboard.setImage(self.image)
            self.copy_button.setToolTip(screenshot_text("copied", self.locale))
            return True
        except Exception as exc:
            self.copy_button.setToolTip(screenshot_text("failed", self.locale).format(error=str(exc)))
            return False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.close()
        elif event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

    def closeEvent(self, event):
        self.closed.emit(self)
        super().closeEvent(event)


class ScreenshotEditor(QWidget):
    closed = Signal(object)
    pinRequested = Signal(object)

    def __init__(self, image, action_id, *, path_factory=None, status_callback=None, locale=None,
                 clipboard_factory=None):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setObjectName("screenshotEditor")
        self.document = ScreenshotDocument(image)
        self.action_id = action_id
        self.path_factory = path_factory
        self.status_callback = status_callback
        self.locale = locale
        self.clipboard_factory = clipboard_factory or QApplication.clipboard
        self._completed = False
        self._closing = False
        self._text_box = None
        self._selection_worker = None
        self._actions = {}
        self._text_widgets = {}
        self.canvas = ScreenshotCanvas(self.document)
        self.canvas.textRequested.connect(self._add_text)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        from ui.screenshot_toolbar import CaptureToolbar
        self.toolbar = CaptureToolbar(locale, text_selection_enabled=True, zoom_enabled=True)
        self.toolbar.toolChanged.connect(self._set_tool)
        self.canvas.selectionRequested.connect(lambda: self.toolbar.select_tool("select"))
        self.toolbar.optionChanged.connect(lambda attr, value: setattr(self.canvas, attr, value))
        self.toolbar.invoked.connect(self._invoke)
        self._actions = self.toolbar.actions
        # Compatibility actions remain available for isolated checks, not on the toolbar.
        self._actions["crop"] = QAction(self)
        self._actions["crop"].triggered.connect(self.canvas.apply_crop)
        self._actions["magnifier"] = QAction(self)
        self._actions["magnifier"].setCheckable(True)
        self._actions["magnifier"].triggered.connect(self._toggle_magnifier)
        self.canvas.set_tool("select")
        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidget(self.canvas)
        self._navigation = _ImageViewNavigation(self, self.scroll, self.canvas)
        self.scroll.setStyleSheet("QScrollArea {background:#eef2f6; border:none;}")
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.toolbar, 0, Qt.AlignmentFlag.AlignCenter)
        self.hint = self.toolbar.note
        self.privacy = QLabel()
        self.size_label = QLabel()
        self.canvas.changed.connect(self._update_state)
        self.canvas.imageChanged.connect(self._invalidate_text_layer)
        if self.locale is not None:
            self.locale.languageChanged.connect(self.refresh_language)
        self.refresh_language()
        screen = QApplication.screenAt(self.cursor().pos()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        self.resize(min(1120, area.width() - 40), min(820, area.height() - 40))
        self.move(area.center() - self.rect().center())

    def tr_key(self, key):
        return screenshot_text(key, self.locale)

    def _action(self, toolbar, key, callback, shortcut=None):
        action = QAction(self)
        action.setObjectName("screenshot_" + key)
        action.triggered.connect(callback)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        toolbar.addAction(action)
        self._actions[key] = action
        return action

    def refresh_language(self):
        self.setWindowTitle(self.tr_key("title"))
        for key, action in self._actions.items():
            action.setText(self.tr_key(key))
        for key, widget in self._text_widgets.items():
            widget.setText(self.tr_key(key) + " ")
        self.privacy.setText(self.tr_key("privacy"))
        self.canvas.setAccessibleName(self.tr_key("title"))
        self.toolbar.refresh_language()
        self.toolbar.set_destination(self.action_id)
        self._text_layer_labels()
        self.scroll.setToolTip(self.tr_key("view_navigation"))
        self._update_state()

    def _invoke(self, key):
        commands = {
            "undo": lambda: self._history(False), "redo": lambda: self._history(True),
            "save": self.save_image, "save_as": lambda: self.save_image(True),
            "copy": lambda: self._copy_selected_text() or self.copy_image(),
            "text_select": self._start_text_selection,
            "zoom_in": lambda: self.zoom(120), "zoom_out": lambda: self.zoom(-120),
            "pin": self.pin_image, "done": self.finish,
            "cancel": self.close,
            "fit": self.fit_image, "actual": lambda: self.canvas.set_scale(1),
            "help": lambda: self.toolbar.set_status(self.tr_key("compact_help")),
        }
        if key in commands:
            self._commit_text()
            if self.canvas.selection is not None:
                self.canvas.apply_crop()
            commands[key]()

    def _update_state(self):
        self.size_label.setText(self.tr_key("size").format(
            width=self.document.crop.width(), height=self.document.crop.height()))
        self._actions["undo"].setEnabled(bool(self.document._undo))
        self._actions["redo"].setEnabled(bool(self.document._redo))
        self._actions["crop"].setEnabled(self.canvas.selection is not None)

    def showEvent(self, event):
        super().showEvent(event)
        self.fit_image()
        self.canvas.setFocus()

    def fit_image(self):
        self._commit_text()
        viewport = self.scroll.viewport().size()
        rect = self.document.crop
        self.canvas.set_scale(min(1.0, (viewport.width() - 8) / rect.width(),
                                  (viewport.height() - 8) / rect.height()))

    def zoom(self, delta, anchor=None):
        if delta:
            self._commit_text()
            _resize_at_pointer(self.scroll, self.canvas, lambda: self.canvas.set_scale(
                self.canvas.scale * _zoom_factor(delta)), anchor)

    def _set_tool(self, key):
        self.canvas.set_tool(key)
        self._text_layer_labels()

    def _text_layer_labels(self):
        selecting = self.canvas.text_layer is not None and self.canvas.tool == "select"
        self._actions["select"].setToolTip(self.tr_key("text_select_ready" if selecting else "pointer_hint"))
        self._actions["copy"].setText(self.tr_key("text_select_copy" if selecting else "copy"))

    def _invalidate_text_layer(self):
        self.canvas.text_layer = None
        self.canvas._text_dragging = False
        self.canvas.setCursor(Qt.CursorShape.ArrowCursor if self.canvas.tool == "select" else Qt.CursorShape.CrossCursor)
        worker, self._selection_worker = self._selection_worker, None
        if worker is not None:
            worker.cancelled.set()
            worker.deleteLater()
        self._actions["text_select"].setEnabled(True)
        self._text_layer_labels()

    def _start_text_selection(self):
        if self._closing or self._selection_worker is not None:
            return
        from core import text_selection
        if text_selection.checked_runtime() is None:
            self._status("text_select_missing")
            from ui.screenshot_components import ensure_component
            ensure_component("text", self, self.locale, self._start_text_selection)
            return
        self._commit_text()
        self.toolbar.select_tool("select")
        # Use flattened output, never the unredacted source. Glyph coordinates
        # are document pixels; zoom/scroll only change their display mapping.
        image, origin = self._output_image(), self.document.crop.topLeft()
        from ui.screenshot_text_selection import TextSelectionController
        controller = TextSelectionController(self)
        self._selection_worker = controller
        self.canvas.text_layer = None
        self.canvas.update()
        self._text_layer_labels()
        self._actions["text_select"].setEnabled(False)
        self._status("text_select_working")

        def finish(data=None, error=None):
            if self._closing or self._selection_worker is not controller:
                return
            self._selection_worker = None
            self._actions["text_select"].setEnabled(True)
            if error is not None:
                self._status(error)
            else:
                from ui.screenshot_text_layer import FrozenTextLayer
                self.canvas.text_layer = FrozenTextLayer(data["glyphs"], origin) if data["glyphs"] else None
                self._status("text_select_ready" if self.canvas.text_layer else "text_select_empty")
            self._text_layer_labels()
            self.canvas.update()
            controller.deleteLater()

        controller.result.connect(lambda data: finish(data=data))
        controller.status.connect(lambda error: finish(error=error))
        controller.start(image)
        self.canvas.setFocus()

    def _copy_selected_text(self):
        if self.canvas.tool != "select" or self.canvas.text_layer is None:
            return False
        text = self.canvas.text_layer.selected_text()
        if not text:
            self._status("text_select_ready")
            return True
        try:
            self.clipboard_factory().setText(text)
            self._status("text_select_copied")
        except Exception as error:
            self._status("failed", error=str(error))
        return True

    def _history(self, redo):
        self.canvas._points = []
        self.canvas.selection = None
        (self.document.redo if redo else self.document.undo)()
        self.canvas.refresh()

    def _choose_color(self):
        selected = QColorDialog.getColor(QColor(self.canvas.color), self, self.tr_key("color"))
        if selected.isValid():
            self.canvas.color = selected.name()

    def _toggle_magnifier(self, enabled):
        self.canvas.magnifier_enabled = enabled
        self.canvas.update()

    def _add_text(self, point):
        from ui.screenshot_toolbar import InlineTextBox
        self._commit_text()
        index = None
        for i in range(len(self.document.annotations) - 1, -1, -1):
            a = self.document.annotations[i]
            if a.kind == "text":
                lines = a.text.splitlines() or [""]
                x, y = a.points[0]
                if QRectF(x, y, max(map(len, lines)) * a.font_size, len(lines) * a.font_size * 1.3).contains(point):
                    index = i
                    point = QPointF(x, y)
                    break
        annotation = self.document.annotations[index] if index is not None else self.canvas.annotation([point])
        box = InlineTextBox(self.canvas, annotation.text, font_size=max(8, round(annotation.font_size * self.canvas.scale)))
        x = round((point.x() - self.document.crop.x()) * self.canvas.scale)
        y = round((point.y() - self.document.crop.y()) * self.canvas.scale)
        box.setGeometry(max(0, min(x, self.canvas.width() - 100)),
                        max(0, min(y, self.canvas.height() - 44)),
                        min(320, max(100, self.canvas.width() - x)), 100)
        def complete(text):
            self._text_box = None
            from dataclasses import replace
            if index is not None:
                self.document.replace_annotation(index, replace(annotation, text=text) if text.strip() else None)
            elif text.strip():
                self.document.add(replace(annotation, text=text))
            self.canvas.refresh()
        box.committed.connect(complete)
        box.discarded.connect(lambda: setattr(self, "_text_box", None))
        self._text_box = box
        box.setToolTip(self.tr_key("inline_hint"))
        box.show()
        box.setFocus()

    def _commit_text(self):
        if self._text_box is not None:
            self._text_box.commit()

    def _output_image(self):
        return self.document.render()

    def _status(self, key, **kwargs):
        message = self.tr_key(key).format(**kwargs)
        self.toolbar.set_status(message)
        if self.status_callback is not None:
            self.status_callback(message)

    def copy_image(self):
        try:
            clipboard = self.clipboard_factory()
            if clipboard is None:
                raise RuntimeError("clipboard unavailable")
            self._commit_text()
            clipboard.setImage(self._output_image())
            self._status("copied")
            self._completed = True
            return True
        except Exception as exc:
            self._status("failed", error=str(exc))
            return False

    def save_image(self, save_as=False):
        try:
            from ui.screenshot_common import screenshot_file_path
            target = Path(self.path_factory() if self.path_factory else screenshot_file_path())
            if save_as:
                selected, _ = QFileDialog.getSaveFileName(self, self.tr_key("save_as"), str(target), "PNG (*.png)")
                if not selected:
                    return False
                target = Path(selected)
                if target.suffix.lower() != ".png":
                    target = target.with_suffix(".png")
            target.parent.mkdir(parents=True, exist_ok=True)
            self._commit_text()
            if not self._output_image().save(str(target), "PNG"):
                raise OSError("could not write PNG")
            self._status("saved", path=str(target))
            self._completed = True
            return True
        except Exception as exc:
            self._status("failed", error=str(exc))
            return False

    def pin_image(self):
        self._commit_text()
        self.pinRequested.emit(self._output_image())
        self._status("pinned")
        self._completed = True
        self.close()

    def finish(self):
        from ui.screenshot_common import SCREENSHOT_CLIPBOARD_ACTIONS
        if self.canvas.selection is not None and self.canvas.tool == "crop":
            self.canvas.apply_crop()
        ok = self.copy_image() if self.action_id in SCREENSHOT_CLIPBOARD_ACTIONS else self.save_image()
        if ok:
            self._completed = True
            self.close()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.finish()
        elif event.matches(QKeySequence.StandardKey.Undo):
            self._history(False)
        elif event.matches(QKeySequence.StandardKey.Redo):
            self._history(True)
        elif event.matches(QKeySequence.StandardKey.Copy):
            self._commit_text()
            if not self._copy_selected_text():
                self.copy_image()
        elif (event.matches(QKeySequence.StandardKey.SelectAll)
              and self.canvas.tool == "select" and self.canvas.text_layer is not None):
            self.canvas.text_layer.select_all()
            self.canvas.update()
        elif event.matches(QKeySequence.StandardKey.Save):
            self.save_image()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        self._closing = True
        self._invalidate_text_layer()
        if self._text_box is not None:
            self._text_box.discard()
        if not self._completed:
            self._status("cancelled")
        self.closed.emit(self)
        super().closeEvent(event)
