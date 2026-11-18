"""Native Windows screenshot actions for Mouser.

The mouse hook can invoke actions from a non-Qt thread.  This module exposes a
Qt controller whose public request method only emits a queued signal; all
capture, clipboard, file, and overlay work then runs on the GUI thread.
"""
from __future__ import annotations

import ctypes
import os
import sys
from dataclasses import dataclass
from typing import Callable, Sequence

from PIL import Image, ImageGrab
from PySide6.QtCore import QObject, QRect, Qt, Signal, Slot, QTimer
from PySide6.QtGui import QGuiApplication

from ui.screenshot_common import (
    SCREENSHOT_ACTIONS,
    SCREENSHOT_FULL_CLIP,
    SCREENSHOT_FULL_FILE,
    SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE,
    copy_image_to_clipboard,
    pil_image_to_qimage,
    save_image_to_file,
)
from ui.screenshot_overlay import (
    IntRect,
    RegionSelectionOverlay,
    rect_from_qrect as _rect_from_qrect,
    union_rect as _union_rect,
)


# The Actions Ring hides with a short fade-out animation. Screenshot actions can
# be fired from that ring, so capturing immediately bakes the ring (and sometimes
# a just-opened Windows shell transition such as Task View) into the screenshot
# background. Wait a little longer than the ring dismiss animation before reading
# the desktop pixels.
WINDOWS_SCREENSHOT_SETTLE_DELAY_MS = 220


@dataclass(frozen=True)
class MonitorMap:
    logical: IntRect
    physical: IntRect


@dataclass(frozen=True)
class VirtualCapture:
    image: Image.Image
    physical_rect: IntRect
    monitor_maps: tuple[MonitorMap, ...]


def _sort_rects_spatially(rects: Sequence[IntRect]) -> list[IntRect]:
    return sorted(rects, key=lambda r: (r.left, r.top, r.width, r.height))


def build_monitor_maps(
    logical_rects: Sequence[IntRect],
    physical_rects: Sequence[IntRect],
) -> tuple[MonitorMap, ...]:
    """Pair Qt logical screen rectangles with Win32 physical monitor rectangles."""
    logical = [r for r in logical_rects if not r.is_empty]
    physical = [r for r in physical_rects if not r.is_empty]
    if not logical or not physical:
        raise ValueError("monitor mapping requires at least one logical and physical rect")
    if len(logical) != len(physical):
        physical_union = _union_rect(physical)
        return (MonitorMap(physical_union, physical_union),)
    return tuple(
        MonitorMap(logical_rect, physical_rect)
        for logical_rect, physical_rect in zip(
            _sort_rects_spatially(logical),
            _sort_rects_spatially(physical),
        )
    )


def _enum_windows_monitor_rects() -> tuple[IntRect, ...]:
    if sys.platform != "win32":
        raise RuntimeError("Win32 monitor enumeration is only available on Windows")

    import ctypes.wintypes as wintypes

    user32 = ctypes.windll.user32

    monitors: list[IntRect] = []
    monitor_enum_proc = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HMONITOR,
        wintypes.HDC,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def _callback(_monitor, _dc, rect_ptr, _data):
        rect = rect_ptr.contents
        monitors.append(IntRect(rect.left, rect.top, rect.right, rect.bottom))
        return 1

    if not user32.EnumDisplayMonitors(0, 0, monitor_enum_proc(_callback), 0):
        raise RuntimeError("EnumDisplayMonitors failed")
    return tuple(monitors)


def _system_monitor_maps() -> tuple[MonitorMap, ...]:
    physical_rects = _enum_windows_monitor_rects()
    app = QGuiApplication.instance()
    screens = app.screens() if app is not None else []
    logical_rects = [_rect_from_qrect(screen.geometry()) for screen in screens]
    return build_monitor_maps(logical_rects, physical_rects)


def physical_to_logical_rects(physical_rect, maps):
    """Map one top-level window to the Qt selection coordinate space."""
    parts = []
    for monitor in maps:
        part = physical_rect.intersected(monitor.physical)
        if part is None:
            continue
        sx = monitor.logical.width / monitor.physical.width
        sy = monitor.logical.height / monitor.physical.height
        parts.append(IntRect(
            monitor.logical.left + round((part.left - monitor.physical.left) * sx),
            monitor.logical.top + round((part.top - monitor.physical.top) * sy),
            monitor.logical.left + round((part.right - monitor.physical.left) * sx),
            monitor.logical.top + round((part.bottom - monitor.physical.top) * sy),
        ))
    return _union_rect(parts).to_qrect() if parts else None


def visible_window_rects(maps):
    """Read visible top-level bounds in z-order; never fetch titles or content."""
    if sys.platform != "win32":
        return ()
    from ctypes import wintypes as w
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    user32.IsWindowVisible.argtypes = [w.HWND]
    user32.IsIconic.argtypes = [w.HWND]
    user32.GetWindowThreadProcessId.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
    user32.GetClassNameW.argtypes = [w.HWND, w.LPWSTR, ctypes.c_int]
    dwm.DwmGetWindowAttribute.argtypes = [w.HWND, w.DWORD, ctypes.c_void_p, w.DWORD]
    callback_type = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, w.LPARAM]
    result = []

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid, name = w.DWORD(), ctypes.create_unicode_buffer(256)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        user32.GetClassNameW(hwnd, name, 256)
        if pid.value == os.getpid() or name.value in {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
            return True
        cloaked = w.DWORD()
        if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
            return True
        rect = w.RECT()
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) == 0:
            logical = physical_to_logical_rects(IntRect(rect.left, rect.top, rect.right, rect.bottom), maps)
            if logical is not None and logical.width() >= 8 and logical.height() >= 8:
                result.append(logical)
        return True

    if not user32.EnumWindows(callback_type(visit), 0):
        return ()
    return tuple(result)


def logical_to_physical_rect(monitor: MonitorMap, logical_rect: IntRect) -> IntRect:
    if monitor.logical.is_empty:
        raise ValueError("logical monitor rectangle is empty")
    scale_x = monitor.physical.width / float(monitor.logical.width)
    scale_y = monitor.physical.height / float(monitor.logical.height)
    return IntRect(
        monitor.physical.left + int(round((logical_rect.left - monitor.logical.left) * scale_x)),
        monitor.physical.top + int(round((logical_rect.top - monitor.logical.top) * scale_y)),
        monitor.physical.left + int(round((logical_rect.right - monitor.logical.left) * scale_x)),
        monitor.physical.top + int(round((logical_rect.bottom - monitor.logical.top) * scale_y)),
    )


def capture_virtual_desktop(
    monitor_maps: Sequence[MonitorMap] | None = None,
    grab: Callable[..., Image.Image] | None = None,
) -> VirtualCapture:
    maps = tuple(monitor_maps or _system_monitor_maps())
    physical_bounds = _union_rect(m.physical for m in maps)
    grab_screen = grab or ImageGrab.grab
    canvas = Image.new("RGB", (physical_bounds.width, physical_bounds.height), (0, 0, 0))
    for monitor in maps:
        bbox = (
            monitor.physical.left,
            monitor.physical.top,
            monitor.physical.right,
            monitor.physical.bottom,
        )
        image = grab_screen(
            bbox=bbox,
            all_screens=True,
            include_layered_windows=True,
        ).convert("RGB")
        canvas.paste(
            image,
            (
                monitor.physical.left - physical_bounds.left,
                monitor.physical.top - physical_bounds.top,
            ),
        )
    return VirtualCapture(canvas, physical_bounds, maps)


def physical_region_segments(capture: VirtualCapture, logical_rect: IntRect) -> list[IntRect]:
    segments: list[IntRect] = []
    for monitor in capture.monitor_maps:
        logical_part = logical_rect.intersected(monitor.logical)
        if logical_part is not None:
            segments.append(logical_to_physical_rect(monitor, logical_part))
    if not segments:
        raise ValueError("selected region does not intersect any screen")
    return segments


def crop_logical_region(capture: VirtualCapture, logical_rect: IntRect) -> Image.Image:
    segments = physical_region_segments(capture, logical_rect)

    output_rect = _union_rect(segments)
    result = Image.new(capture.image.mode, (output_rect.width, output_rect.height), (0, 0, 0))
    for segment in segments:
        source = segment.translated(-capture.physical_rect.left, -capture.physical_rect.top)
        patch = capture.image.crop((source.left, source.top, source.right, source.bottom))
        result.paste(patch, (segment.left - output_rect.left, segment.top - output_rect.top))
    return result


class WindowsScreenshotController(QObject):
    _requestAction = Signal(str)

    def __init__(
        self,
        status_callback: Callable[[str], None] | None = None,
        path_factory: Callable[[], object] | None = None,
        settle_delay_ms: int = WINDOWS_SCREENSHOT_SETTLE_DELAY_MS,
        parent=None,
        editor_enabled: Callable[[], bool] | None = None,
        locale=None,
    ):
        super().__init__(parent)
        self._status_callback = status_callback
        self._path_factory = path_factory
        self._settle_delay_ms = max(0, int(settle_delay_ms))
        self._capture_pending = False
        self._editor_enabled = editor_enabled
        self._edit_this_capture = False
        self._editor = None
        self._pins = []
        self._locale = locale
        self._overlay: RegionSelectionOverlay | None = None
        self._pending_capture: VirtualCapture | None = None
        self._pending_action = ""
        self._scroll_session = None
        self._scroll_probe = None
        self._requestAction.connect(self._handle_request, Qt.ConnectionType.QueuedConnection)

    def request_action(self, action_id: str) -> None:
        self._requestAction.emit(action_id)

    @Slot(str)
    def _handle_request(self, action_id: str) -> None:
        if action_id not in SCREENSHOT_ACTIONS:
            return
        if self._overlay is not None or self._capture_pending or self._editor is not None or self._scroll_session is not None:
            self._emit_status("Finish the current screenshot selection first")
            return
        self._capture_pending = True
        if self._settle_delay_ms <= 0:
            self._begin_capture_request(action_id)
        else:
            QTimer.singleShot(
                self._settle_delay_ms,
                lambda action_id=action_id: self._begin_capture_request(action_id),
            )

    def _begin_capture_request(self, action_id: str) -> None:
        self._capture_pending = False
        if action_id not in SCREENSHOT_ACTIONS:
            return
        if self._overlay is not None or self._editor is not None or self._scroll_session is not None:
            self._emit_status("Finish the current screenshot selection first")
            return
        try:
            self._edit_this_capture = bool(self._editor_enabled and self._editor_enabled())
            capture = capture_virtual_desktop()
            window_rects = ()
            if self._edit_this_capture:
                try:
                    window_rects = visible_window_rects(capture.monitor_maps)
                except (OSError, AttributeError):
                    pass  # Detection is optional; free selection must keep working.
        except Exception as exc:
            self._emit_status(f"Screenshot failed: {exc}")
            print(f"[Screenshot] capture failed: {exc}")
            return

        if self._edit_this_capture:
            from ui.screenshot_session import ScreenshotSession
            self._pending_capture = capture
            self._pending_action = action_id
            self._overlay = ScreenshotSession(
                capture, action_id, locale=self._locale, path_factory=self._path_factory,
                status_callback=self._status_callback, window_rects=window_rects,
                full=action_id in (SCREENSHOT_FULL_CLIP, SCREENSHOT_FULL_FILE))
            self._overlay.scrollRequested.connect(self._start_scroll)
            self._overlay.pinRequested.connect(self._pin_image)
            self._overlay.closed.connect(self._session_closed)
            self._overlay.show()
            return

        if action_id in (SCREENSHOT_FULL_CLIP, SCREENSHOT_FULL_FILE):
            self._edit_or_deliver(capture.image, action_id)
            return

        self._pending_capture = capture
        self._pending_action = action_id
        logical_screens = tuple(m.logical for m in capture.monitor_maps)
        frozen = []
        for monitor in capture.monitor_maps:
            part = monitor.physical.translated(-capture.physical_rect.left, -capture.physical_rect.top)
            frozen.append(pil_image_to_qimage(capture.image.crop(
                (part.left, part.top, part.right, part.bottom))))
        from ui.screenshot_locale import screenshot_text
        self._overlay = RegionSelectionOverlay(
            _union_rect(logical_screens),
            screen_rects=logical_screens,
            frozen_images=frozen,
            confirm_on_release=self._edit_this_capture,
            hint=screenshot_text("selection_hint", self._locale) if self._edit_this_capture else "",
            size_provider=lambda rect: self._region_pixel_size(capture, rect),
            window_rects=window_rects,
            magnifier=self._edit_this_capture,
        )
        self._overlay.selected.connect(self._finish_region)
        self._overlay.cancelled.connect(self._cancel_region)
        self._overlay.scrollRequested.connect(self._start_scroll)
        self._overlay.show()

    def _start_scroll(self, rect):
        from ui.screenshot_components import ensure_component
        if not ensure_component("scroll", self, self._locale, lambda: self._start_scroll(rect)
                                if self._pending_capture is not None and self._overlay is not None else None):
            return
        overlay, self._overlay = self._overlay, None
        capture, self._pending_capture = self._pending_capture, None
        action, self._pending_action = self._pending_action, ""
        if overlay is not None and getattr(overlay, "_live_capture", None) is not None:
            capture = overlay.capture  # The first scrolling frame must be the fresh live snapshot.
        if overlay:
            overlay.close()
            overlay.deleteLater()
        try:
            logical = _rect_from_qrect(rect)
            parts = physical_region_segments(capture, logical)
            if len(parts) != 1:
                from ui.screenshot_tools import StitchError
                raise StitchError("scroll_single_screen")
            physical = parts[0]
            self._capture_pending = True
            from ui.screenshot_scroll_region import ScrollViewportProbe
            probe = ScrollViewportProbe(physical, self)
            self._scroll_probe = probe
            probe.resolved.connect(lambda found: self._open_scroll_session(
                capture, action, rect, physical, probe, found))
            # UIA must see the real target, not our frozen selection panes.
            QTimer.singleShot(240, probe.start)
        except Exception as exc:
            self._capture_pending = False
            from ui.screenshot_locale import screenshot_text
            self._emit_status(screenshot_text(str(exc), self._locale) if str(exc).startswith("scroll_")
                              else screenshot_text("scroll_capture_error", self._locale))

    def _open_scroll_session(self, capture, action, rect, physical, probe, found):
        if self._scroll_probe is not probe:
            return
        self._scroll_probe = None
        probe.cancel()
        probe.deleteLater()
        self._capture_pending = False
        try:
            used = found.intersected(physical) if isinstance(found, IntRect) else None
            if used is None or used.width < 40 or used.height < 80:
                used = physical
            narrowed = used != physical
            logical_rect = physical_to_logical_rects(used, capture.monitor_maps) or rect
            source = used.translated(-capture.physical_rect.left, -capture.physical_rect.top)
            first = capture.image.crop((source.left, source.top, source.right, source.bottom))
            from ui.screenshot_scroll import ScrollCaptureSession
            session = ScrollCaptureSession(first, lambda: self._capture_scroll_frame(
                used, capture.monitor_maps), locale=self._locale, capture_rect=logical_rect,
                viewport_detected=narrowed)
            print(f"[Screenshot] scroll viewport source={'accessibility' if narrowed else 'selection'} "
                  f"size={used.width}x{used.height}")
            self._scroll_session = session
            session.completed.connect(lambda image: self._finish_scroll(image, action))
            session.cancelled.connect(self._cancel_scroll)
            from ui.screenshot_session import toolbar_position
            session.move(toolbar_position(logical_rect, session.size(),
                [m.logical.to_qrect() for m in capture.monitor_maps]))
            session.show()
        except Exception as exc:
            from ui.screenshot_locale import screenshot_text
            self._emit_status(screenshot_text(str(exc), self._locale) if str(exc).startswith("scroll_")
                              else screenshot_text("scroll_capture_error", self._locale))

    def _session_closed(self, session):
        if self._overlay is session:
            self._overlay = None
            self._pending_capture = None
            self._pending_action = ""
        session.deleteLater()

    def _finish_scroll(self, image, action):
        self._scroll_session = None
        # Ending the scrolling session is not the final copy/save action.
        # Retain the capture's editing choice so annotation and pin controls
        # remain available for the completed long image.
        self._edit_or_deliver(image, action)

    def _cancel_scroll(self):
        self._scroll_session = None
        self._emit_status("Screenshot cancelled")

    @staticmethod
    def _capture_scroll_frame(physical, maps):
        if _system_monitor_maps() != maps:
            from ui.screenshot_tools import StitchError
            raise StitchError("scroll_size")
        return ImageGrab.grab(bbox=(physical.left, physical.top, physical.right, physical.bottom),
                              all_screens=True, include_layered_windows=True).convert("RGB")

    @Slot(QRect)
    def _finish_region(self, rect: QRect) -> None:
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            overlay.deleteLater()
        capture = self._pending_capture
        action_id = self._pending_action
        self._pending_capture = None
        self._pending_action = ""
        if capture is None:
            return
        try:
            image = crop_logical_region(capture, _rect_from_qrect(rect))
            self._edit_or_deliver(image, action_id)
        except Exception as exc:
            self._emit_status(f"Screenshot failed: {exc}")
            print(f"[Screenshot] region failed: {exc}")

    @Slot()
    def _cancel_region(self) -> None:
        overlay = self._overlay
        self._overlay = None
        self._pending_capture = None
        self._pending_action = ""
        if overlay is not None:
            overlay.deleteLater()
        self._emit_status("Screenshot cancelled")

    def _deliver_image(self, image: Image.Image, action_id: str) -> None:
        try:
            if action_id in (SCREENSHOT_REGION_CLIP, SCREENSHOT_FULL_CLIP):
                copy_image_to_clipboard(image)
                print("[Screenshot] clipboard delivery complete")
                self._emit_status("Screenshot copied to clipboard")
            else:
                target = self._path_factory() if self._path_factory is not None else None
                path = save_image_to_file(image, target)
                print("[Screenshot] file delivery complete")
                self._emit_status(f"Screenshot saved to {path}")
        except Exception as exc:
            self._emit_status(f"Screenshot failed: {exc}")
            print(f"[Screenshot] delivery failed: {exc}")
            return

    def _edit_or_deliver(self, image, action_id):
        if not self._edit_this_capture:
            self._deliver_image(image, action_id)
            return
        try:
            from ui.screenshot_editor import ScreenshotEditor
            self._editor = ScreenshotEditor(
                pil_image_to_qimage(image), action_id, path_factory=self._path_factory,
                status_callback=self._status_callback, locale=self._locale,
            )
            self._editor.closed.connect(self._editor_closed)
            self._editor.pinRequested.connect(self._pin_image)
            self._editor.show()
            self._editor.raise_()
            self._editor.activateWindow()
        except Exception as exc:
            editor, self._editor = self._editor, None
            if editor is not None:
                editor.close()
            self._emit_status(f"Screenshot failed: {exc}")

    @staticmethod
    def _region_pixel_size(capture, rect):
        try:
            bounds = _union_rect(physical_region_segments(capture, _rect_from_qrect(rect)))
            return bounds.width, bounds.height
        except ValueError:
            return 0, 0

    def _editor_closed(self, editor):
        if self._editor is editor:
            self._editor = None

    def _pin_image(self, image):
        from ui.screenshot_editor import ScreenshotPin
        if len(self._pins) >= 8:
            self._pins[0].close()
        pin = ScreenshotPin(image, self._locale)
        self._pins.append(pin)
        pin.closed.connect(self._pin_closed)
        pin.show()

    def _pin_closed(self, pin):
        if pin in self._pins:
            self._pins.remove(pin)

    def _emit_status(self, message: str) -> None:
        from ui.screenshot_locale import screenshot_text
        key = {
            "Finish the current screenshot selection first": "busy",
            "Screenshot cancelled": "cancelled",
            "Screenshot copied to clipboard": "copied",
        }.get(message)
        if key:
            message = screenshot_text(key, self._locale)
        elif message.startswith("Screenshot failed: "):
            message = screenshot_text("failed", self._locale).format(error=message[19:])
        elif message.startswith("Screenshot saved to "):
            message = screenshot_text("saved", self._locale).format(path=message[20:])
        if self._status_callback is not None:
            self._status_callback(message)
