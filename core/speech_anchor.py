"""Read-only Windows input anchors. Never reads the user's document text.

Accessibility queries run on a daemon, not on the Qt or recording threads.
Native window/focus checks are repeated at delivery time; stale UIA snapshots
are not trusted for pasting. Coordinates here are physical Windows pixels.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, replace
import os
import sys
import threading
import time


@dataclass(frozen=True)
class InputAnchor:
    window: int = 0
    focus: int = 0
    rect: tuple[float, float, float, float] | None = None
    caret: tuple[float, float, float, float] | None = None
    runtime_id: tuple[int, ...] = ()
    editable: bool = False
    password: bool = False
    observed_at: float = 0.0

    @property
    def identity(self):
        return self.window, self.focus, self.runtime_id


class _GUIINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


def _user32():
    dll = ctypes.WinDLL("user32", use_last_error=True)
    dll.GetForegroundWindow.restype = wintypes.HWND
    dll.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUIINFO)]
    dll.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    dll.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    dll.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    dll.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    dll.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    return dll


def read_native_anchor() -> InputAnchor:
    if sys.platform != "win32":
        return InputAnchor()
    try:
        api = _user32()
        window = int(api.GetForegroundWindow() or 0)
        if not window:
            return InputAnchor()
        thread = api.GetWindowThreadProcessId(window, None)
        info = _GUIINFO()
        info.cbSize = ctypes.sizeof(info)
        api.GetGUIThreadInfo(thread, ctypes.byref(info))
        focus = int(info.hwndFocus or 0)
        rect = wintypes.RECT()
        bounds = None
        if api.GetWindowRect(focus or window, ctypes.byref(rect)):
            bounds = (rect.left, rect.top, rect.right, rect.bottom)
        caret = None
        if info.hwndCaret and info.rcCaret.bottom > info.rcCaret.top:
            start = wintypes.POINT(info.rcCaret.left, info.rcCaret.top)
            end = wintypes.POINT(info.rcCaret.right, info.rcCaret.bottom)
            if api.ClientToScreen(info.hwndCaret, ctypes.byref(start)) and api.ClientToScreen(info.hwndCaret, ctypes.byref(end)):
                caret = (start.x, start.y, max(start.x + 1, end.x), end.y)
        name = ctypes.create_unicode_buffer(256)
        api.GetClassNameW(focus, name, len(name))
        cls = name.value.lower()
        native_edit = cls == "edit" or cls.startswith("richedit") or cls.startswith("scintilla")
        if cls == "edit" or cls.startswith("richedit"):
            native_edit = native_edit and not bool(api.GetWindowLongW(focus, -16) & 0x800)
        password = cls == "edit" and bool(api.GetWindowLongW(focus, -16) & 0x20)
        return InputAnchor(window, focus, bounds, caret, editable=native_edit and not password,
                           password=password, observed_at=time.monotonic())
    except (OSError, ValueError, AttributeError):
        return InputAnchor()


def _rect_tuple(rect):
    result = (float(rect.left), float(rect.top), float(rect.right), float(rect.bottom))
    return result if result[2] > result[0] and result[3] > result[1] else None


def _selection_caret(text_pattern, auto):
    """Geometry-only TextPattern1 fallback; never reads or selects text."""
    if not text_pattern:
        return None
    ranges = text_pattern.GetSelection()
    if len(ranges) != 1:
        return None
    selection = ranges[0]
    start, end = auto.TextPatternRangeEndpoint.Start, auto.TextPatternRangeEndpoint.End
    if selection.CompareEndpoints(start, selection, end) != 0:
        return None  # A selection does not identify which edge is the caret.
    boxes = selection.GetBoundingRectangles()
    right_edge = False
    if not boxes:
        nearby = selection.Clone()
        if nearby.MoveEndpointByUnit(end, auto.TextUnit.Character, 1, waitTime=0):
            boxes = nearby.GetBoundingRectangles()
        else:
            nearby = selection.Clone()
            if nearby.MoveEndpointByUnit(start, auto.TextUnit.Character, -1, waitTime=0):
                boxes = nearby.GetBoundingRectangles()
                right_edge = True
    if boxes:
        box = boxes[-1] if right_edge else boxes[0]
        if box.bottom > box.top:
            x = box.right if right_edge else box.left
            return (x, box.top, x + 1, box.bottom)
    return None


class InputAnchorTracker:
    def __init__(self):
        self._stop = threading.Event()
        self._active = threading.Event()
        self._lock = threading.Lock()
        self._latest = InputAnchor()
        self._thread = None

    def start(self):
        if sys.platform != "win32":
            return
        self._active.set()
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._observe, name="MouserInputAnchor", daemon=True)
        self._thread.start()

    def stop(self):
        self._active.clear()

    def shutdown(self):
        self._stop.set()
        self._active.set()

    def snapshot(self) -> InputAnchor:
        native = read_native_anchor()
        with self._lock:
            latest = self._latest
        if (native.window and latest.window == native.window and latest.focus == native.focus
                and time.monotonic() - latest.observed_at < 0.65):
            return replace(latest, caret=native.caret or latest.caret,
                           runtime_id=() if native.editable else latest.runtime_id)
        return native

    def _observe(self):
        try:
            import uiautomation as auto
            with auto.UIAutomationInitializerInThread():
                while not self._stop.is_set():
                    if not self._active.is_set():
                        self._active.wait(0.15)
                        continue
                    before = read_native_anchor()
                    try:
                        control = auto.GetFocusedControl()
                        if control is not None:
                            password = bool(control.IsPassword)
                            runtime = tuple(control.GetRuntimeId() or ())
                            rect = _rect_tuple(control.BoundingRectangle)
                            caret = before.caret
                            pattern = control.GetPattern(auto.PatternId.TextPattern2)
                            text_pattern = control.GetPattern(auto.PatternId.TextPattern)
                            if pattern and not password:
                                try:
                                    active, text_range = pattern.pattern.GetCaretRange()
                                    if active and text_range:
                                        boxes = auto.TextRange(text_range).GetBoundingRectangles()
                                        if boxes:
                                            box = boxes[0]
                                            if box.bottom > box.top:
                                                caret = (box.left, box.top, max(box.left + 1, box.right), box.bottom)
                                except Exception:
                                    pass
                            if not caret and text_pattern and not password:
                                try:
                                    caret = _selection_caret(text_pattern, auto)
                                except Exception:
                                    pass
                            value_pattern = control.GetPattern(auto.PatternId.ValuePattern)
                            editable = before.editable
                            if value_pattern:
                                editable = not value_pattern.IsReadOnly
                            elif text_pattern:
                                readonly = text_pattern.DocumentRange.GetAttributeValue(auto.TextAttributeId.IsReadOnlyAttribute)
                                # UIA providers may return VARIANT_BOOL as False or integer 0.
                                editable = isinstance(readonly, (bool, int)) and readonly == 0
                            after = read_native_anchor()
                            if before.window and (before.window, before.focus) == (after.window, after.focus):
                                snapshot = replace(before, rect=rect or before.rect, caret=caret,
                                                   runtime_id=runtime, password=password,
                                                   editable=editable and not password,
                                                   observed_at=time.monotonic())
                                with self._lock:
                                    self._latest = snapshot
                    except Exception:
                        # A closed/inaccessible app must not stall capture or authorize a paste.
                        pass
                    self._stop.wait(0.15)
        except Exception:
            pass


def modifiers_held() -> bool:
    if sys.platform != "win32":
        return False
    api = _user32()
    return any(api.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12))


def monitor_geometry(point: tuple[float, float]):
    """Return the containing display's physical bounds and Qt-compatible name."""
    if sys.platform != "win32":
        return None
    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD),
                    ("szDevice", wintypes.WCHAR * 32)]
    try:
        api = _user32()
        api.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
        api.MonitorFromPoint.restype = wintypes.HANDLE
        api.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        monitor = api.MonitorFromPoint(wintypes.POINT(round(point[0]), round(point[1])), 2)
        info = MonitorInfo()
        info.cbSize = ctypes.sizeof(info)
        if api.GetMonitorInfoW(monitor, ctypes.byref(info)):
            r = info.rcMonitor
            return (r.left, r.top, r.right, r.bottom), info.szDevice
    except (OSError, ValueError):
        pass
    return None


def map_physical_rect(rect, physical_screen, logical_screen):
    px, py, pr, pb = physical_screen
    lx, ly, lr, lb = logical_screen
    sx, sy = (lr - lx) / (pr - px), (lb - ly) / (pb - py)
    return (lx + (rect[0] - px) * sx, ly + (rect[1] - py) * sy,
            lx + (rect[2] - px) * sx, ly + (rect[3] - py) * sy)


def place_preview(anchor_rect, size, available, *, caret=True, gap=10):
    """Pure placement function, also used for negative-origin/mixed-DPI tests."""
    left, top, right, bottom = available
    width, height = min(size[0], right - left - 16), min(size[1], bottom - top - 16)
    x = anchor_rect[0]
    y = anchor_rect[3] + gap if caret else anchor_rect[3] - height - gap
    if caret and y + height > bottom - 8:
        y = anchor_rect[1] - height - gap
    return (round(max(left + 8, min(x, right - width - 8))),
            round(max(top + 8, min(y, bottom - height - 8))))
