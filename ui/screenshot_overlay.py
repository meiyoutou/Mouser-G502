"""Shared screenshot geometry and region selection overlay helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
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


class RegionSelectionOverlay(QWidget):
    selected = Signal(QRect)
    cancelled = Signal()

    def __init__(
        self,
        logical_bounds: IntRect,
        parent=None,
        screen_rects: Sequence[IntRect] | None = None,
    ):
        super().__init__(parent)
        self._bounds = logical_bounds
        self._start: QPoint | None = None
        self._current: QPoint | None = None
        self._mouse_grab_pane: _RegionSelectionPane | None = None
        self._keyboard_grab_pane: _RegionSelectionPane | None = None
        self._closed = False
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
        super().keyPressEvent(event)

    def _pane_mouse_press_event(self, pane: _RegionSelectionPane, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._start = self._event_global_pos(event)
        self._current = self._start
        self._mouse_grab_pane = pane
        self._mouse_grab_pane.grabMouse()
        self._update_panes()

    def _pane_mouse_move_event(self, event: QMouseEvent) -> None:
        if self._start is None:
            return
        self._current = self._event_global_pos(event)
        self._update_panes()

    def _pane_mouse_release_event(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._start is None:
            return
        self._current = self._event_global_pos(event)
        rect = self._selection_global_rect()
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
        self._paint_selection(pane, self._selection_local_rect_for(pane))

    def _paint_selection(self, widget: QWidget, local: QRect | None) -> None:
        painter = QPainter(widget)
        painter.fillRect(widget.rect(), QColor(0, 0, 0, 90))
        if local is not None:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(local, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor(255, 255, 255), 2))
            painter.drawRect(local.adjusted(0, 0, -1, -1))
        painter.end()

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

    @staticmethod
    def _event_global_pos(event: QMouseEvent) -> QPoint:
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        return event.globalPos()
