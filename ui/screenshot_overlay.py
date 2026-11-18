"""Shared screenshot geometry and region selection overlay helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget


@dataclass(frozen=True)
class IntRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0

    def translated(self, dx: int, dy: int) -> "IntRect":
        return IntRect(self.left + dx, self.top + dy, self.right + dx, self.bottom + dy)

    def intersected(self, other: "IntRect") -> "IntRect | None":
        rect = IntRect(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )
        return None if rect.is_empty else rect

    def to_qrect(self) -> QRect:
        return QRect(self.left, self.top, self.width, self.height)


def union_rect(rects: Iterable[IntRect]) -> IntRect:
    rects = [r for r in rects if not r.is_empty]
    if not rects:
        raise ValueError("no non-empty rectangles")
    return IntRect(
        min(r.left for r in rects),
        min(r.top for r in rects),
        max(r.right for r in rects),
        max(r.bottom for r in rects),
    )


def rect_from_qrect(rect: QRect) -> IntRect:
    return IntRect(rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height())


class _RegionSelectionPane(QWidget):
    """One visible screenshot shade window for a single physical screen."""

    def __init__(self, owner: "RegionSelectionOverlay", logical_rect: IntRect):
        super().__init__(None)
        self._owner = owner
        self._logical_rect = logical_rect
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(logical_rect.to_qrect())

    @property
    def logical_rect(self) -> IntRect:
        return self._logical_rect

    def paintEvent(self, _event) -> None:
        self._owner._paint_pane(self)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        self._owner.keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._owner._pane_mouse_press_event(self, event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self._owner._pane_mouse_move_event(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._owner._pane_mouse_release_event(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self._owner._pane_double_click_event(self, event)


class RegionSelectionOverlay(QWidget):
    selected = Signal(QRect)
    scrollRequested = Signal(QRect)
    cancelled = Signal()

    def __init__(
        self,
        logical_bounds: IntRect,
        parent=None,
        screen_rects: Sequence[IntRect] | None = None,
        frozen_images: Sequence[QImage] | None = None,
        confirm_on_release: bool = False,
        hint: str = "",
        size_provider=None,
        window_rects=(),
        magnifier=False,
    ):
        super().__init__(parent)
        self._bounds = logical_bounds
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._mouse_grab_pane: _RegionSelectionPane | None = None
        self._keyboard_grab_pane: _RegionSelectionPane | None = None
        self._closed = False
        self._confirm_on_release = confirm_on_release
        self._hint = hint
        self._size_provider = size_provider
        self._drag_mode = None
        self._drag_start = None
        self._drag_rect = None
        self._window_rects = tuple(window_rects)
        self._auto_window = bool(window_rects)
        self._magnifier = magnifier
        self._pointer = None
        self._hover_rect = None
        self._press_point = None
        self._frozen_images = tuple(frozen_images or ())
        pane_rects = tuple(r for r in (screen_rects or (logical_bounds,)) if not r.is_empty)
        if not pane_rects:
            pane_rects = (logical_bounds,)
        self._panes = [_RegionSelectionPane(self, rect) for rect in pane_rects]
        # Keep the coordinator geometry aligned with the virtual desktop for
        # tests and geometry helpers, but paint only per-screen panes.  A single
        # translucent top-level window spanning several Windows monitors can
        # leave stale clear regions on one display when mixed DPI/negative
        # coordinates are involved.
        self.setGeometry(logical_bounds.to_qrect())

    def show(self) -> None:
        self._closed = False
        for pane in self._panes:
            pane.show()
            pane.raise_()
        if self._panes:
            self._keyboard_grab_pane = self._panes[0]
            self._keyboard_grab_pane.activateWindow()
            self._keyboard_grab_pane.grabKeyboard()

    def close(self) -> bool:
        self._close_panes()
        return super().close()

    def closeEvent(self, event):
        try:
            self._close_panes()
        finally:
            super().closeEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            self.close()
            return
        if self._confirm_on_release and event.key() == Qt.Key.Key_M:
            self._magnifier = not self._magnifier
            self._update_panes()
            return
        if self._confirm_on_release and event.key() == Qt.Key.Key_A:
            self._auto_window = not self._auto_window
            self._update_hover()
            self._update_panes()
            return
        if self._confirm_on_release and event.key() == Qt.Key.Key_S:
            rect = self._selection_global_rect() or self._hover_rect
            if rect is not None:
                self.scrollRequested.emit(rect)
                self.close()
            return
        if self._confirm_on_release and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm_selection()
            return
        super().keyPressEvent(event)

    def _confirm_selection(self):
        rect = self._selection_global_rect() or self._hover_rect
        if rect is not None and rect.width() >= 2 and rect.height() >= 2:
            self.selected.emit(rect)
            self.close()

    def _pane_double_click_event(self, pane, event):
        if self._confirm_on_release and event.button() == Qt.MouseButton.LeftButton:
            self._confirm_selection()

    def _pane_mouse_press_event(self, pane: _RegionSelectionPane, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = self._event_global_pos(event)
        self._pointer = point
        self._update_hover()
        self._press_point = point
        rect = self._selection_global_rect()
        self._drag_mode = "new"
        if self._confirm_on_release and rect is not None:
            from PySide6.QtCore import QRectF
            from ui.screenshot_editor import rect_handles
            self._drag_start = point
            self._drag_rect = QRectF(rect)
            for idx, handle in enumerate(rect_handles(self._drag_rect)):
                if (handle - point).manhattanLength() <= 12:
                    self._drag_mode = idx
                    break
            else:
                if rect.contains(point):
                    self._drag_mode = "move"
        if self._drag_mode == "new":
            self._start = point
            self._current = self._start
        self._mouse_grab_pane = pane
        self._mouse_grab_pane.grabMouse()
        self._update_panes()

    def _pane_mouse_move_event(self, event: QMouseEvent) -> None:
        self._pointer = self._event_global_pos(event)
        self._update_hover()
        self._update_panes()
        if self._start is None:
            return
        point = self._event_global_pos(event)
        if self._mouse_grab_pane is None:
            return
        if self._drag_mode == "move":
            rect = self._drag_rect.translated(point - self._drag_start)
            bounds = self._bounds.to_qrect()
            rect.moveLeft(max(bounds.left(), min(bounds.x() + bounds.width() - rect.width(), rect.left())))
            rect.moveTop(max(bounds.top(), min(bounds.y() + bounds.height() - rect.height(), rect.top())))
            # QRectF's bottomRight is exclusive, QRect's is inclusive. Convert
            # the rectangle first so moving never adds one pixel to its size.
            moved = rect.toRect()
            self._start, self._current = moved.topLeft(), moved.bottomRight()
        elif isinstance(self._drag_mode, int):
            from PySide6.QtCore import QRectF
            from ui.screenshot_editor import resize_selection
            rect = resize_selection(self._drag_rect, self._drag_mode, point, QRectF(self._bounds.to_qrect()))
            self._start, self._current = rect.topLeft().toPoint(), rect.bottomRight().toPoint()
        else:
            self._current = point
        self._update_panes()

    def _pane_mouse_release_event(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._pane_mouse_move_event(event)
        if (self._confirm_on_release and self._drag_mode == "new"
                and self._press_point is not None
                and (self._event_global_pos(event) - self._press_point).manhattanLength() <= 3
                and self._hover_rect is not None):
            self._start = self._hover_rect.topLeft()
            self._current = self._hover_rect.bottomRight()
        rect = self._selection_global_rect()
        if self._mouse_grab_pane is not None:
            self._mouse_grab_pane.releaseMouse()
            self._mouse_grab_pane = None
        if self._confirm_on_release:
            if rect is None or rect.width() < 2 or rect.height() < 2:
                self._start = self._current = None
            self._update_panes()
            return
        if rect is None:
            self.cancelled.emit()
            self.close()
            return
        if rect.width() < 2 or rect.height() < 2:
            self.cancelled.emit()
        else:
            self.selected.emit(rect)
        self.close()

    def paintEvent(self, _event) -> None:
        # The coordinator itself stays hidden; visible painting is done by the
        # per-screen panes.  Keep this fallback for direct test/dev rendering.
        self._paint_selection(self, self._selection_local_rect())

    def _paint_pane(self, pane: _RegionSelectionPane) -> None:
        idx = self._panes.index(pane)
        frozen = self._frozen_images[idx] if idx < len(self._frozen_images) else None
        local = self._selection_local_rect_for(pane)
        if local is None and self._hover_rect is not None:
            local = self._hover_rect.translated(-pane.logical_rect.left, -pane.logical_rect.top)
        self._paint_selection(pane, local, frozen)

    def _paint_selection(self, widget: QWidget, local: QRect | None, frozen=None) -> None:
        painter = QPainter(widget)
        if frozen is not None:
            painter.drawImage(widget.rect(), frozen)
        painter.fillRect(widget.rect(), QColor(0, 0, 0, 90))
        if local is not None:
            if frozen is not None:
                painter.save()
                painter.setClipRect(local)
                painter.drawImage(widget.rect(), frozen)
                painter.restore()
            else:
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
                painter.fillRect(local, Qt.GlobalColor.transparent)
                painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawRect(local.adjusted(0, 0, -1, -1))
            if self._confirm_on_release:
                from PySide6.QtCore import QRectF
                from ui.screenshot_editor import rect_handles
                painter.setBrush(Qt.GlobalColor.white)
                for point in rect_handles(QRectF(local)):
                    painter.drawRect(QRectF(point.x() - 3, point.y() - 3, 6, 6))
                rect = self._selection_global_rect()
                rect = rect or self._hover_rect
                size = self._size_provider(rect) if self._size_provider and rect else (local.width(), local.height())
                label = f"{size[0]} × {size[1]} px"
                painter.drawText(local.topLeft() + QPoint(5, -6), label)
        if self._hint:
            painter.setPen(Qt.GlobalColor.white)
            painter.fillRect(QRect(12, 12, widget.width() - 24, 56), QColor(0, 0, 0, 180))
            painter.drawText(QRect(20, 16, widget.width() - 40, 48),
                             Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self._hint)
        if self._magnifier and frozen is not None and self._pointer is not None:
            point = widget.mapFromGlobal(self._pointer)
            if widget.rect().contains(point):
                from ui.screenshot_tools import draw_magnifier
                source = QPoint(round(point.x() * frozen.width() / widget.width()),
                                round(point.y() * frozen.height() / widget.height()))
                draw_magnifier(painter, frozen, source, point, widget.rect())
        painter.end()

    def _update_hover(self):
        self._hover_rect = None
        if self._auto_window and self._pointer is not None:
            for rect in self._window_rects:
                if rect.contains(self._pointer):
                    self._hover_rect = rect
                    break

    def _selection_global_rect(self) -> QRect | None:
        if self._start is None or self._current is None:
            return None
        return QRect(self._start, self._current).normalized()

    def _selection_local_rect(self) -> QRect | None:
        if self._start is None or self._current is None:
            return None
        return QRect(
            self.mapFromGlobal(self._start),
            self.mapFromGlobal(self._current),
        ).normalized()

    def _selection_local_rect_for(self, widget: QWidget) -> QRect | None:
        if self._start is None or self._current is None:
            return None
        return QRect(
            widget.mapFromGlobal(self._start),
            widget.mapFromGlobal(self._current),
        ).normalized()

    def _update_panes(self) -> None:
        for pane in self._panes:
            pane.update()

    def _close_panes(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._mouse_grab_pane is not None:
            try:
                self._mouse_grab_pane.releaseMouse()
            except RuntimeError:
                pass
            self._mouse_grab_pane = None
        if self._keyboard_grab_pane is not None:
            try:
                self._keyboard_grab_pane.releaseKeyboard()
            except RuntimeError:
                pass
            self._keyboard_grab_pane = None
        for pane in self._panes:
            pane.close()
            pane.deleteLater()
        self._panes = []
        self._frozen_images = ()

    @staticmethod
    def _event_global_pos(event: QMouseEvent) -> QPoint:
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()
