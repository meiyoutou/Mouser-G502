"""Native, scoped live-selection helpers; no OCR, text reads or input replay."""
import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QApplication


LIVE_EDGE = 12


def live_pane_region(pane_rect, selection):
    """Keep the outer shade and resize strip; punch a real input/paint hole.

    Inset in *global logical* coordinates before monitor clipping so there is
    no extra unclickable strip at seams between mixed-DPI monitors.
    """
    inside = selection.adjusted(LIVE_EDGE, LIVE_EDGE, -LIVE_EDGE, -LIVE_EDGE)
    hole = inside.intersected(pane_rect).translated(-pane_rect.topLeft())
    return QRegion(pane_rect.translated(-pane_rect.topLeft())).subtracted(QRegion(hole))


def no_activate(window_id, enabled):
    if sys.platform != "win32" or QApplication.platformName() == "offscreen":
        return True
    from ctypes import wintypes as w
    try:
        api = ctypes.WinDLL("user32", use_last_error=True)
        get = api.GetWindowLongPtrW
        get.argtypes, get.restype = [w.HWND, ctypes.c_int], ctypes.c_ssize_t
        put = api.SetWindowLongPtrW
        put.argtypes, put.restype = [w.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
        style = get(window_id, -20)
        put(window_id, -20, style | 0x08000000 if enabled else style & ~0x08000000)
        return bool(get(window_id, -20) & 0x08000000) == bool(enabled)
    except (OSError, AttributeError):
        return False


def source_window_at(point):
    """Return only native window identity/geometry, never document text."""
    if sys.platform != "win32" or QApplication.platformName() == "offscreen":
        return None
    from ctypes import wintypes as w
    api = ctypes.WinDLL("user32", use_last_error=True)
    api.WindowFromPoint.argtypes, api.WindowFromPoint.restype = [w.POINT], w.HWND
    api.GetAncestor.argtypes, api.GetAncestor.restype = [w.HWND, w.UINT], w.HWND
    api.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    handle = api.GetAncestor(api.WindowFromPoint(w.POINT(*point)), 2)
    bounds = w.RECT()
    if not handle or not api.GetWindowRect(handle, ctypes.byref(bounds)):
        return None
    return int(handle), (bounds.left, bounds.top, bounds.right, bounds.bottom)


def source_window_valid(source, own_windows):
    if source is None:
        return True
    from ctypes import wintypes as w
    api = ctypes.WinDLL("user32", use_last_error=True)
    for key in ("IsWindow", "IsWindowVisible", "IsIconic"):
        getattr(api, key).argtypes = [w.HWND]
    api.GetWindowRect.argtypes = [w.HWND, ctypes.POINTER(w.RECT)]
    api.GetForegroundWindow.restype = w.HWND
    api.GetWindow.argtypes, api.GetWindow.restype = [w.HWND, w.UINT], w.HWND
    handle, original_bounds = source
    bounds = w.RECT()
    if (not api.IsWindow(handle) or not api.IsWindowVisible(handle) or api.IsIconic(handle)
            or not api.GetWindowRect(handle, ctypes.byref(bounds))
            or (bounds.left, bounds.top, bounds.right, bounds.bottom) != original_bounds):
        return False
    foreground = int(api.GetForegroundWindow() or 0)
    for _ in range(8):  # Allow owned menus/dialogs, not an unrelated new app.
        if foreground in (handle, *own_windows):
            return True
        foreground = int(api.GetWindow(foreground, 4) or 0)
        if not foreground:
            break
    return False


class LiveEscape(QAbstractNativeEventFilter):
    """Register only Escape while live; never hook Ctrl+C, text, or the mouse."""
    HOTKEY = 0x4D52

    def __init__(self, window_id, callback):
        super().__init__()
        self.window_id, self.callback, self.registered = window_id, callback, False
        if sys.platform == "win32" and QApplication.platformName() != "offscreen":
            from ctypes import wintypes as w
            api = ctypes.WinDLL("user32", use_last_error=True)
            api.RegisterHotKey.argtypes = [w.HWND, ctypes.c_int, w.UINT, w.UINT]
            api.RegisterHotKey.restype = w.BOOL
            self.registered = bool(api.RegisterHotKey(window_id, self.HOTKEY, 0x4000, 0x1B))
            if self.registered:
                QApplication.instance().installNativeEventFilter(self)

    def nativeEventFilter(self, kind, message):
        from ctypes import wintypes as w
        msg = w.MSG.from_address(int(message))
        if msg.message == 0x0312 and msg.hWnd == self.window_id and msg.wParam == self.HOTKEY:
            QTimer.singleShot(0, self.callback)
            return True, 0
        return False, 0

    def close(self):
        if self.registered:
            from ctypes import wintypes as w
            api = ctypes.WinDLL("user32", use_last_error=True)
            api.UnregisterHotKey.argtypes = [w.HWND, ctypes.c_int]
            api.UnregisterHotKey(self.window_id, self.HOTKEY)
            QApplication.instance().removeNativeEventFilter(self)
            self.registered = False
