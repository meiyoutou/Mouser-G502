"""One frozen, per-monitor selection/annotation surface; no second editor."""
from dataclasses import replace

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter
from PySide6.QtWidgets import QApplication, QMenu

from ui.screenshot_common import pil_image_to_qimage
from ui.screenshot_editor import Annotation, ScreenshotDocument, ScreenshotEditor, rect_handles
from ui.screenshot_overlay import RegionSelectionOverlay, rect_from_qrect, union_rect
from ui.screenshot_toolbar import CaptureToolbar, InlineTextBox


def qimage_to_pil(image):
    rgb = image.convertToFormat(QImage.Format.Format_RGB888)
    return Image.frombytes("RGB", (rgb.width(), rgb.height()), bytes(rgb.constBits()),
                           "raw", "RGB", rgb.bytesPerLine())


def toolbar_position(selection, size, screens):
    """Prefer below/right, then above, finally inside; never off a monitor."""
    screen = next((r for r in screens if r.contains(selection.bottomRight())), None)
    if screen is None:
        screen = max(screens, key=lambda r: r.intersected(selection).width() * r.intersected(selection).height())
    x = max(screen.left() + 6, min(selection.x() + selection.width() - size.width(),
                                  screen.x() + screen.width() - size.width() - 6))
    y = selection.y() + selection.height() + 8
    if y + size.height() > screen.y() + screen.height() - 6:
        y = selection.top() - size.height() - 8
    y = max(screen.top() + 6, min(y, screen.y() + screen.height() - size.height() - 6))
    return QPoint(x, y)


class ScreenshotSession(RegionSelectionOverlay):
    closed = Signal(object)
    pinRequested = Signal(object)

    # Shared output implementations only use _output_image (flattened crop).
    tr_key = ScreenshotEditor.tr_key
    _status = ScreenshotEditor._status
    _commit_text = ScreenshotEditor._commit_text

    def __init__(self, capture, action_id, *, locale=None, path_factory=None,
                 status_callback=None, clipboard_factory=None, window_rects=(), full=False,
                 live_capture=None):
        self.capture = capture
        self.document = ScreenshotDocument(pil_image_to_qimage(capture.image))
        self.locale = locale
        self.action_id = action_id
        self.path_factory = path_factory
        self.status_callback = status_callback
        self.clipboard_factory = clipboard_factory or QApplication.clipboard
        self._completed = False
        self._closing = False
        self._text_box = None
        self._selection_worker = None
        self._text_layer = None
        self._text_dragging = False
        self._points = []
        self._live_capture = live_capture
        self._live = self._live_ready = False
        self._live_hidden = set()
        self._live_escape = None
        self._live_source = None
        self.tool = "select"
        self.color, self.stroke, self.font_size, self.block = "#ef4444", 4, 28, 16
        self._whole_desktop = full
        screens = tuple(m.logical for m in capture.monitor_maps)
        super().__init__(union_rect(screens), screen_rects=screens,
                         confirm_on_release=True, window_rects=window_rects,
                         size_provider=self._pixel_size, magnifier=True)
        self._source_timer = QTimer(self)
        self._source_timer.setInterval(350)
        self._source_timer.timeout.connect(self._check_live_source)
        self.toolbar = CaptureToolbar(locale, floating=True, scroll_enabled=True)
        self.toolbar.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        if live_capture is not None:
            for pane in self._panes:
                pane.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self._actions = self.toolbar.actions
        self.toolbar.toolChanged.connect(self._set_tool)
        self.toolbar.optionChanged.connect(lambda attr, value: setattr(self, attr, value))
        self.toolbar.invoked.connect(self._invoke)
        self.toolbar._relayout = self._place_toolbar
        self.hint = self.toolbar.note
        if locale:
            locale.languageChanged.connect(self.refresh_language)
        for name in ("fit", "actual"):
            self.toolbar.more.removeAction(self._actions[name])
        self.refresh_language()
        self._refresh_images()
        if full:
            self._start = self._bounds.to_qrect().topLeft()
            self._current = self._bounds.to_qrect().bottomRight()
            self._magnifier = False
        self._refresh_cursors()

    def refresh_language(self):
        self._hint = self.tr_key("compact_selection_hint") if self._selection_global_rect() is None else ""
        self.toolbar.refresh_language()
        self.toolbar.set_destination(self.action_id)
        self._text_layer_labels()
        if self._live:
            self._live_labels()
        self._place_toolbar()
        self._update_panes()

    def show(self):
        super().show()
        # Keyboard grabs would redirect menu/inline-text typing into the overlay.
        self._release_keyboard()
        if self._selection_global_rect() is not None:
            self._magnifier = False
            self._refresh_cursors()
            self._place_toolbar()
        if self._live_capture is not None:
            from ui.screenshot_scroll import exclude_capture_window
            # Refuse live mode if our controls cannot be excluded from a fresh
            # image capture; never silently bake masks/toolbars into output.
            self._live_ready = all([exclude_capture_window(int(window.winId()))
                                    for window in [*self._panes, self.toolbar]])
            if not self._live_ready:
                self._status("live_unavailable")
            self._try_live()

    def _live_labels(self):
        from ui.screenshot_common import SCREENSHOT_CLIPBOARD_ACTIONS
        label = self.tr_key("live_finish_copy" if self.action_id in SCREENSHOT_CLIPBOARD_ACTIONS
                            else "live_finish_save")
        self._actions["done"].setText(label)
        self._actions["done"].setToolTip(label)
        self.toolbar.buttons["done"].setAccessibleName(label)
        self._actions["select"].setToolTip(self.tr_key("live_pointer_hint"))
        self._actions["copy"].setText(self.tr_key("live_copy_image"))
        self._actions["copy"].setToolTip(self.tr_key("live_copy_image"))

    def _set_live(self, enabled):
        from ui.screenshot_live import LiveEscape, no_activate
        if enabled and not no_activate(int(self.toolbar.winId()), True):
            self._status("live_unavailable")
            return False
        self._live = enabled
        self.toolbar.native_selection = enabled
        if enabled:
            self._release_keyboard()
            if self._live_escape is None:
                self._live_escape = LiveEscape(int(self.toolbar.winId()), self.close)
            self._magnifier = False
            self._hint = ""
            self._live_labels()
            self.toolbar.set_status(self.tr_key("live_hint"))
        else:
            if self._live_escape is not None:
                self._live_escape.close()
                self._live_escape = None
            no_activate(int(self.toolbar.winId()), False)
            self.toolbar.set_destination(self.action_id)
            self._actions["select"].setToolTip(self.tr_key("pointer_hint"))
            self._actions["copy"].setText(self.tr_key("copy"))
            self._actions["copy"].setToolTip(self.tr_key("copy"))
        self._update_panes()
        if enabled:
            from ui.screenshot_live import source_window_at
            point = self._selection_global_rect().center()
            physical = self._physical_point(point)
            self._live_source = source_window_at((
                round(physical.x()+self.capture.physical_rect.left),
                round(physical.y()+self.capture.physical_rect.top))) if physical is not None else None
            own = [int(w.winId()) for w in [*self._panes, self.toolbar]]
            if self._live_source and self._live_source[0] in own:
                self._live_source = None
            self._source_timer.start()
        else:
            self._source_timer.stop()
            self._live_source = None
        return True

    def _check_live_source(self):
        from ui.screenshot_live import source_window_valid
        if self._live and not source_window_valid(self._live_source,
                [int(w.winId()) for w in [*self._panes, self.toolbar]]):
            self._set_live(False)
            self._live_ready = False
            self._status("live_source_changed")

    def _try_live(self):
        if not self._live_ready or self._closing or self._selection_global_rect() is None:
            return
        if self.tool == "select" and self._mouse_grab_pane is None and not self._points:
            if self.document.annotations:
                self._status("live_marks")
            elif not self._live:
                self._set_live(True)

    def _update_panes(self):
        from ui.screenshot_live import live_pane_region
        rect = self._selection_global_rect()
        for pane in self._panes:
            if self._live and rect is not None:
                region = live_pane_region(pane.geometry(), rect)
                if region.isEmpty():
                    # In Qt an EMPTY mask means "no mask", not "no window".
                    # Hide panes wholly inside the hole instead of blocking it.
                    self._live_hidden.add(pane)
                    pane.hide()
                    continue
                pane.setMask(region)
            else:
                pane.clearMask()
            if pane in self._live_hidden:
                self._live_hidden.remove(pane)
                if not self._closing:
                    pane.show()
            pane.update()

    def _refresh_live_frame(self):
        if not self._live:
            return True
        try:
            from ui.screenshot_scroll import exclude_capture_window
            for menu in self.toolbar.findChildren(QMenu):
                if menu.isVisible() and not exclude_capture_window(int(menu.winId())):
                    raise ValueError("popup capture exclusion unavailable")
            fresh = self._live_capture()
            if (fresh.monitor_maps != self.capture.monitor_maps
                    or fresh.physical_rect != self.capture.physical_rect
                    or fresh.image.size != self.capture.image.size):
                raise ValueError("display geometry changed")
            self.capture = fresh
            self.document = ScreenshotDocument(pil_image_to_qimage(fresh.image))
            self._refresh_images()
            return True
        except Exception:
            # Do not deliver a stale screenshot or leave an unsafe live hole.
            self._set_live(False)
            self._live_ready = False
            self._status("live_capture_failed")
            return False

    def copy_image(self):
        return self._refresh_live_frame() and ScreenshotEditor.copy_image(self)

    def save_image(self, force_dialog=False):
        return self._refresh_live_frame() and ScreenshotEditor.save_image(self, force_dialog)

    def pin_image(self):
        if self._refresh_live_frame():
            return ScreenshotEditor.pin_image(self)

    def _release_keyboard(self):
        if self._keyboard_grab_pane is not None:
            self._keyboard_grab_pane.releaseKeyboard()
            self._keyboard_grab_pane = None

    def _pixel_size(self, rect):
        from ui.windows_screenshot import physical_region_segments
        try:
            bounds = union_rect(physical_region_segments(self.capture, rect_from_qrect(rect)))
            return bounds.width, bounds.height
        except ValueError:
            return 0, 0

    def _physical_point(self, point):
        for m in self.capture.monitor_maps:
            if m.logical.to_qrect().contains(point):
                return QPointF(
                    m.physical.left - self.capture.physical_rect.left
                    + (point.x() - m.logical.left) * m.physical.width / m.logical.width,
                    m.physical.top - self.capture.physical_rect.top
                    + (point.y() - m.logical.top) * m.physical.height / m.logical.height)
        return None

    def _annotation(self, points, text=""):
        return Annotation(self.tool, tuple((p.x(), p.y()) for p in points),
                          self.color, self.stroke, self.font_size, self.block, text)

    def _refresh_images(self, draft=None):
        self._invalidate_text_layer()
        image = self.document.render(draft)
        bounds = self.capture.physical_rect
        self._frozen_images = tuple(image.copy(QRect(
            m.physical.left - bounds.left, m.physical.top - bounds.top,
            m.physical.width, m.physical.height)) for m in self.capture.monitor_maps)
        self._actions["undo"].setEnabled(bool(self.document._undo))
        self._actions["redo"].setEnabled(bool(self.document._redo))
        self._update_panes()

    def _invalidate_text_layer(self):
        self._text_layer = None
        self._text_dragging = False
        if self._selection_worker is not None:
            self._selection_worker.cancelled.set()
            self._selection_worker = None
        if "text_select" in self._actions:
            self._actions["text_select"].setEnabled(True)
        self._text_layer_labels()

    def _text_layer_labels(self):
        if not hasattr(self, "_actions"):
            return
        if "select" in self._actions:
            self._actions["select"].setToolTip(self.tr_key(
                "text_select_ready" if self._text_layer else "pointer_hint"))
        if "copy" in self._actions:
            self._actions["copy"].setText(self.tr_key("text_select_copy" if self._text_layer else "copy"))

    def _start_text_selection(self):
        if self._selection_worker is not None or self._selection_global_rect() is None or self._live:
            return
        from core import text_selection
        if text_selection.checked_runtime() is None:
            self._status("text_select_missing")
            from ui.screenshot_components import ensure_component
            ensure_component("text", self, self.locale, self._start_text_selection)
            return
        self._commit_text()
        self.toolbar.select_tool("select")
        # Flatten annotations FIRST, including redactions. Recognition must never
        # see hidden original text. Coordinates are physical crop coordinates.
        from ui.windows_screenshot import physical_region_segments
        bounds = union_rect(physical_region_segments(
            self.capture, rect_from_qrect(self._selection_global_rect())))
        origin = QPointF(bounds.left-self.capture.physical_rect.left,
                         bounds.top-self.capture.physical_rect.top)
        image = self._output_image()
        from ui.screenshot_text_selection import TextSelectionController
        controller = TextSelectionController(self)
        self._selection_worker = controller
        self._text_layer = None
        self._actions["text_select"].setEnabled(False)
        self._status("text_select_working")
        def ready(data):
            if self._closing or self._selection_worker is not controller:
                return
            self._selection_worker = None
            self._actions["text_select"].setEnabled(True)
            from ui.screenshot_text_layer import FrozenTextLayer
            self._text_layer = FrozenTextLayer(data["glyphs"], origin) if data["glyphs"] else None
            self._text_layer_labels()
            self._status("text_select_ready" if self._text_layer else "text_select_empty")
            self._refresh_cursors()
            self._update_panes()
        def failed(key):
            if not self._closing and self._selection_worker is controller:
                self._selection_worker = None
                self._actions["text_select"].setEnabled(True)
                self._status(key)
        controller.result.connect(ready)
        controller.status.connect(failed)
        controller.start(image)

    def _copy_selected_text(self):
        if self.tool != "select" or self._text_layer is None:
            return False
        text = self._text_layer.selected_text()
        if text:
            self.clipboard_factory().setText(text)
            self._status("text_select_copied")
        else:
            self._status("text_select_ready")
        return True

    def _paint_pane(self, pane):
        super()._paint_pane(pane)
        if self._text_layer is None or self.tool != "select":
            return
        from ui.screenshot_text_layer import logical_fragments
        painter = QPainter(pane)
        selection = self._selection_global_rect()
        if selection is not None:
            painter.setClipRect(selection.translated(-pane.x(), -pane.y()))
        for box in self._text_layer.selected_boxes():
            for fragment in logical_fragments(box, self.capture):
                painter.fillRect(fragment.translated(-pane.x(), -pane.y()),
                                 QColor(22, 119, 255, 85))
        painter.end()

    def _output_image(self):
        from ui.windows_screenshot import VirtualCapture, crop_logical_region
        image = self.document.render()
        if self._whole_desktop:
            return image
        rect = self._selection_global_rect()
        if rect is None:
            raise ValueError("no selected region")
        capture = VirtualCapture(qimage_to_pil(image), self.capture.physical_rect, self.capture.monitor_maps)
        return pil_image_to_qimage(crop_logical_region(capture, rect_from_qrect(rect)))

    def _place_toolbar(self):
        if self._closing:
            return
        rect = self._selection_global_rect()
        if rect is None:
            self.toolbar.hide()
            return
        self.toolbar.adjustSize()
        screens = [m.logical.to_qrect() for m in self.capture.monitor_maps]
        if self.toolbar.user_positioned:
            position, size = self.toolbar.pos(), self.toolbar.size()
            screen = next((r for r in screens if r.contains(position)), screens[0])
            self.toolbar.move(QPoint(
                max(screen.left()+6, min(position.x(), screen.right()-size.width()-5)),
                max(screen.top()+6, min(position.y(), screen.bottom()-size.height()-5))))
        else:
            self.toolbar.move(toolbar_position(rect, self.toolbar.size(), screens))
        self.toolbar.show()
        self.toolbar.raise_()

    def _refresh_cursors(self):
        cursor = Qt.CursorShape.CrossCursor
        if self._mouse_grab_pane is not None and isinstance(self._drag_mode, int):
            cursor = (Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeVerCursor,
                      Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeHorCursor,
                      Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeVerCursor,
                      Qt.CursorShape.SizeBDiagCursor, Qt.CursorShape.SizeHorCursor)[self._drag_mode]
        elif self.tool == "select" and self._selection_global_rect() is not None:
            cursor = Qt.CursorShape.ArrowCursor
            if self._text_layer and self._pointer is not None:
                rect = self._selection_global_rect()
                on_handle = any((p-self._pointer).manhattanLength() <= 12
                                for p in rect_handles(QRectF(rect)))
                if (not on_handle and rect.contains(self._pointer)
                        and self._text_layer.hit(self._physical_point(self._pointer)) is not None):
                    cursor = Qt.CursorShape.IBeamCursor
        elif self.tool == "hand":
            cursor = (Qt.CursorShape.ClosedHandCursor
                      if self._mouse_grab_pane is not None and self._drag_mode == "move"
                      else Qt.CursorShape.OpenHandCursor)
        for pane in self._panes:
            pane.setCursor(cursor)

    def _set_tool(self, key):
        if self._live and key != "select":
            if not self._refresh_live_frame():
                self.toolbar.select_tool("select", emit=False)
                return
            self._set_live(False)
        self._commit_text()
        had_draft = bool(self._points)
        if self._mouse_grab_pane is not None:
            self._mouse_grab_pane.releaseMouse()
            self._mouse_grab_pane = None
        self._drag_mode = None
        self.tool = key
        if self._text_layer:
            self._text_layer.clear()
        self._text_dragging = False
        self._points = []
        self._magnifier = key == "select" and self._selection_global_rect() is None
        self._hint = ""
        self.toolbar.set_status("")
        self._refresh_cursors()
        # Switching tools does not alter pixels. Reuse monitor images unless an
        # unfinished preview has to be cleared (text commit refreshes itself).
        if had_draft:
            self._refresh_images()
        else:
            self._update_panes()
        self._try_live()

    def _invoke(self, key):
        self._commit_text()
        commands = {
            "undo": lambda: self._history(False), "redo": lambda: self._history(True),
            "copy": lambda: self._copy_selected_text() or self.copy_image(), "save": self.save_image,
            "save_as": lambda: self.save_image(True), "pin": self.pin_image,
            "text_select": self._start_text_selection, "done": self.finish,
            "cancel": self.close, "scroll": self._start_scroll,
            "help": lambda: self.toolbar.set_status(self.tr_key("compact_help")),
        }
        if key in commands:
            commands[key]()

    def _history(self, redo):
        self._commit_text()
        self._points = []
        (self.document.redo if redo else self.document.undo)()
        self._refresh_images()
        self._try_live()

    def _start_scroll(self):
        if not self._refresh_live_frame():
            return
        if self._live:
            self._set_live(False)
        rect = self._selection_global_rect()
        from ui.windows_screenshot import physical_region_segments
        if len(physical_region_segments(self.capture, rect_from_qrect(rect))) != 1:
            self._status("scroll_single_screen")
            return
        # Restart from the original capture, never mix painted first frame with
        # subsequent live ones. Require the user to undo annotations first.
        if self.document.annotations:
            self._status("scroll_before_marks")
            return
        from ui.screenshot_components import ensure_component
        if not ensure_component("scroll", self, self.locale, self._start_scroll):
            return
        self._completed = True
        self.scrollRequested.emit(rect)
        self.close()

    def finish(self):
        self._commit_text()
        if self._selection_global_rect() is None:
            if self._hover_rect is None:
                return
            self._start, self._current = self._hover_rect.topLeft(), self._hover_rect.bottomRight()
        from ui.screenshot_common import SCREENSHOT_CLIPBOARD_ACTIONS
        ok = self.copy_image() if self.action_id in SCREENSHOT_CLIPBOARD_ACTIONS else self.save_image()
        if ok:
            self._completed = True
            self.close()

    def _confirm_selection(self):
        self.finish()

    def _pane_double_click_event(self, pane, event):
        if self._live or event.button() != Qt.MouseButton.LeftButton or self.tool == "hand":
            return
        point = self._event_global_pos(event)
        rect = self._selection_global_rect()
        if rect is None or not rect.contains(point):
            return
        if self.tool == "select" and self._text_layer is not None:
            # Never finish/copy the image while trying to select recognized text.
            return
        physical = self._physical_point(point)
        index = self._text_hit(physical)
        if index is not None and self._text_box is None:
            self._edit_text(pane, point, physical, index)
        elif self.tool == "select" and self._text_box is None and not any(
                (p - point).manhattanLength() <= 12 for p in rect_handles(QRectF(rect))):
            self.finish()

    def _text_hit(self, point):
        if point is None:
            return None
        for index in range(len(self.document.annotations) - 1, -1, -1):
            a = self.document.annotations[index]
            if a.kind == "text":
                x, y = a.points[0]
                lines = a.text.splitlines() or [""]
                area = QRectF(x, y, max(map(len, lines)) * a.font_size, len(lines) * a.font_size * 1.3)
                if area.contains(point):
                    return index
        return None

    def _edit_text(self, pane, logical, physical, index=None):
        self._commit_text()
        a = self.document.annotations[index] if index is not None else self._annotation([physical])
        scale = next(m.physical.width / m.logical.width for m in self.capture.monitor_maps
                     if m.logical == pane.logical_rect)
        box = InlineTextBox(pane, a.text, max(8, round(a.font_size / scale)))
        local = pane.mapFromGlobal(logical)
        box.setGeometry(max(0, min(local.x(), pane.width() - 180)),
                        max(0, min(local.y(), pane.height() - 100)),
                        min(340, pane.width()), 100)
        def complete(text):
            self._text_box = None
            if index is not None:
                self.document.replace_annotation(index, replace(a, text=text) if text.strip() else None)
            elif text.strip():
                self.document.add(replace(a, text=text))
            self._refresh_images()
        box.committed.connect(complete)
        box.discarded.connect(lambda: setattr(self, "_text_box", None))
        box.setToolTip(self.tr_key("inline_hint"))
        self._text_box = box
        self._release_keyboard()
        box.show()
        pane.activateWindow()
        box.setFocus()

    def _pane_mouse_press_event(self, pane, event):
        if event.button() == Qt.MouseButton.RightButton:
            self.toolbar.select_tool("select")
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._commit_text()
        point = self._event_global_pos(event)
        rect = self._selection_global_rect()
        # Selection handles always remain usable, even while a pen is selected.
        on_handle = rect is not None and any((p - point).manhattanLength() <= 12
                                             for p in rect_handles(QRectF(rect)))
        if self._live and on_handle:
            if not self._refresh_live_frame():
                return
            self._set_live(False)
        if self.tool == "select" and rect is not None and not on_handle:
            # Once the initial region exists, Select is an ordinary pointer,
            # not a second crop tool (including outside the current region).
            self._magnifier = False
            if self._text_layer:
                physical = self._physical_point(point) if rect.contains(point) else None
                if self._text_layer.begin(physical):
                    self._text_dragging = True
                    self._mouse_grab_pane = pane
                    pane.activateWindow()
                    pane.setFocus()
                    pane.grabMouse()
                self._update_panes()
            return
        if self.tool == "hand" and not on_handle and (rect is None or not rect.contains(point)):
            # Moving outside a selection must not silently create a new crop.
            return
        if self.tool in ("select", "hand") or rect is None or on_handle:
            self._invalidate_text_layer()
            self._points = []
            self.toolbar.hide()
            self._whole_desktop = False
            self._magnifier = self.tool != "hand"
            super()._pane_mouse_press_event(pane, event)
            self._refresh_cursors()
            return
        if not rect.contains(point):
            return
        physical = self._physical_point(point)
        if physical is None:
            return
        self._invalidate_text_layer()
        if self.tool == "text":
            self._edit_text(pane, point, physical, self._text_hit(physical))
            return
        self._points = [physical]
        self._mouse_grab_pane = pane
        pane.grabMouse()
        self._magnifier = False

    def _pane_mouse_move_event(self, event):
        if self._text_dragging and self._text_layer is not None:
            self._pointer = self._event_global_pos(event)
            self._text_layer.extend(self._physical_point(self._pointer))
            self._update_panes()
            return
        if not self._points:
            super()._pane_mouse_move_event(event)
            # No magnifier hovering over a finished selection unless adjusting.
            self._magnifier = self.tool != "hand" and (
                self._selection_global_rect() is None or self._mouse_grab_pane is not None)
            self._refresh_cursors()
            return
        point = self._event_global_pos(event)
        rect = self._selection_global_rect()
        point = QPoint(max(rect.left(), min(rect.right(), point.x())),
                       max(rect.top(), min(rect.bottom(), point.y())))
        physical = self._physical_point(point)
        if physical is None:
            return
        if self.tool == "pen":
            if len(self._points) < 10000:
                self._points.append(physical)
        else:
            self._points = [self._points[0], physical]
        self._refresh_images(self._annotation(self._points))

    def _pane_mouse_release_event(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._text_dragging:
            self._pane_mouse_move_event(event)
            self._text_dragging = False
            if self._mouse_grab_pane is not None:
                self._mouse_grab_pane.releaseMouse()
                self._mouse_grab_pane = None
            self._refresh_cursors()
            return
        if self._points:
            self._pane_mouse_move_event(event)
            self.document.add(self._annotation(self._points))
            self._points = []
            if self._mouse_grab_pane:
                self._mouse_grab_pane.releaseMouse()
                self._mouse_grab_pane = None
            self._refresh_images()
        else:
            if self._mouse_grab_pane is not None:
                super()._pane_mouse_release_event(event)
        self._magnifier = False
        self._drag_mode = None
        self._refresh_cursors()
        self._hint = ""
        self._release_keyboard()
        self._place_toolbar()
        self._update_panes()
        self._try_live()

    def keyPressEvent(self, event):
        if self._live and event.key() != Qt.Key.Key_Escape:
            event.ignore()
            return
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
            if not self._copy_selected_text() and self._selection_global_rect():
                self.copy_image()
        elif event.matches(QKeySequence.StandardKey.SelectAll) and self._text_layer and self.tool == "select":
            self._text_layer.select_all()
            self._update_panes()
        elif event.matches(QKeySequence.StandardKey.Save):
            self._commit_text()
            if self._selection_global_rect():
                self.save_image()
        elif event.key() == Qt.Key.Key_S and not event.modifiers():
            if self._selection_global_rect() is not None:
                self._start_scroll()
        else:
            # A/M/S no longer mandatory; retain them for existing users.
            super().keyPressEvent(event)

    def close(self):
        if self._closing:
            return True
        self._closing = True
        self._invalidate_text_layer()
        if self._live or self._live_escape is not None:
            self._set_live(False)
        if self._text_box:
            self._text_box.discard()
        self.toolbar.close()
        self.toolbar.deleteLater()
        if not self._completed:
            self._status_without_toolbar()
        result = super().close()
        self.closed.emit(self)
        return result

    def _status_without_toolbar(self):
        if self.status_callback:
            self.status_callback(self.tr_key("cancelled"))
