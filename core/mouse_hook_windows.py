"""
Windows mouse hook implementation.
"""

import ctypes
import ctypes.wintypes as wintypes
import queue
import re
import sys
import threading
import time
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    Union,
    byref,
    c_int,
    c_uint,
    c_ulong,
    c_ushort,
    c_void_p,
    create_string_buffer,
    sizeof,
    windll,
)

from core.key_simulator import MOUSEEVENTF_HWHEEL, MOUSEEVENTF_WHEEL
from core.key_simulator import inject_scroll as _inject_scroll_impl
from core.mouse_hook_base import BaseMouseHook, HidGestureListener
from core.mouse_hook_types import MouseEvent, hscroll_event_type

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEHWHEEL = 0x020E
WM_MOUSEWHEEL = 0x020A

HC_ACTION = 0
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002


class MSLLHOOKSTRUCT(Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        # ULONG_PTR: an opaque *value* the event's sender attached, not an
        # address. Declaring it as a pointer and reading ``.contents`` treats
        # whatever number Windows put here as memory to dereference, which
        # kills the process outright on any event carrying a non-zero value
        # (issue #252 / #253 -- it fired from the debug logging path).
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class KBDLLHOOKSTRUCT(Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        # ULONG_PTR: an opaque value, not a dereferenceable pointer.
        ("dwExtraInfo", wintypes.WPARAM),
    ]


HOOKPROC = CFUNCTYPE(
    ctypes.c_long,
    c_int,
    wintypes.WPARAM,
    ctypes.POINTER(MSLLHOOKSTRUCT),
)

KEYBOARD_HOOKPROC = CFUNCTYPE(
    ctypes.c_long,
    c_int,
    wintypes.WPARAM,
    ctypes.POINTER(KBDLLHOOKSTRUCT),
)

SetWindowsHookExW = windll.user32.SetWindowsHookExW
SetWindowsHookExW.restype = wintypes.HHOOK
SetWindowsHookExW.argtypes = [c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]

CallNextHookEx = windll.user32.CallNextHookEx
CallNextHookEx.restype = ctypes.c_long
CallNextHookEx.argtypes = [
    wintypes.HHOOK,
    c_int,
    wintypes.WPARAM,
    ctypes.POINTER(MSLLHOOKSTRUCT),
]

UnhookWindowsHookEx = windll.user32.UnhookWindowsHookEx
UnhookWindowsHookEx.restype = wintypes.BOOL
UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

GetModuleHandleW = windll.kernel32.GetModuleHandleW
GetModuleHandleW.restype = wintypes.HMODULE
GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

GetMessageW = windll.user32.GetMessageW
PostThreadMessageW = windll.user32.PostThreadMessageW

GetAsyncKeyState = windll.user32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [c_int]
GetAsyncKeyState.restype = ctypes.c_short

VK_SHIFT = 0x10

WM_QUIT = 0x0012
INJECTED_FLAG = 0x00000001
LLKHF_INJECTED = 0x00000010

WM_INPUT = 0x00FF
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003
RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RIM_TYPEHID = 2
RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B
SW_HIDE = 0
STANDARD_BUTTON_MASK = 0x1F
VK_F13 = 0x7C
VK_F14 = 0x7D
VK_F15 = 0x7E
VK_F16 = 0x7F
G502_USB_PRODUCT_IDS = {
    "C07D",  # G502 Proteus Core
    "C332",  # G502 Proteus Spectrum
    "C08B",  # G502 HERO / HERO SE
    "C08D",  # G502 LIGHTSPEED USB receiver path on some systems
    "407F",  # G502 LIGHTSPEED wireless receiver / receiver path
}
RAW_INPUT_DEVICE_USAGES = (
    # Standard mouse input: movement, wheel, and host-visible extra buttons.
    (0x01, 0x02),
    # Existing Logitech vendor collections used by supported devices.
    (0xFF43, 0x0202),
    (0xFF43, 0x0204),
    # G502 HERO exposes Logitech vendor HID collections here. Registering them
    # lets Mouser learn whether DPI Shift / DPI +/- / profile keys produce
    # host-visible raw reports on this machine without touching onboard memory.
    (0xFF00, 0x0001),
    (0xFF00, 0x0002),
    # Consumer page keeps media-style controls visible to the hidden RI window.
    (0x0C, 0x01),
)
RAW_MOUSE_BUTTON_EVENT_MAP = (
    (0x0020, MouseEvent.MOUSE_BUTTON_6_DOWN, MouseEvent.MOUSE_BUTTON_6_UP, "mouse_button_6"),
    (0x0100, MouseEvent.MOUSE_BUTTON_9_DOWN, MouseEvent.MOUSE_BUTTON_9_UP, "mouse_button_9"),
    (0x0200, MouseEvent.MOUSE_BUTTON_10_DOWN, MouseEvent.MOUSE_BUTTON_10_UP, "mouse_button_10"),
    (0x0400, MouseEvent.MOUSE_BUTTON_11_DOWN, MouseEvent.MOUSE_BUTTON_11_UP, "mouse_button_11"),
    # Some Logitech descriptors expose a dedicated DPI mouse-button bit. Treat
    # it as an alternate source for the G502 DPI Shift/sniper mapping.
    (0x2000, MouseEvent.MOUSE_BUTTON_DPI_DOWN, MouseEvent.MOUSE_BUTTON_DPI_UP, "mouse_button_dpi"),
)
G502_FKEY_EVENT_MAP = {
    VK_F13: (
        MouseEvent.G502_DPI_SHIFT_DOWN,
        MouseEvent.G502_DPI_SHIFT_UP,
        "F13",
        "g502_dpi_shift",
    ),
    VK_F14: (
        MouseEvent.G502_DPI_DOWN_DOWN,
        MouseEvent.G502_DPI_DOWN_UP,
        "F14",
        "g502_dpi_down",
    ),
    VK_F15: (
        MouseEvent.G502_DPI_UP_DOWN,
        MouseEvent.G502_DPI_UP_UP,
        "F15",
        "g502_dpi_up",
    ),
    VK_F16: (
        MouseEvent.G502_PROFILE_CYCLE_DOWN,
        MouseEvent.G502_PROFILE_CYCLE_UP,
        "F16",
        "g502_profile_cycle",
    ),
}
G502_FKEY_BUTTONS = frozenset(
    target[3] for target in G502_FKEY_EVENT_MAP.values()
)
_KEY_DOWN_MESSAGES = frozenset({WM_KEYDOWN, WM_SYSKEYDOWN})
_KEY_UP_MESSAGES = frozenset({WM_KEYUP, WM_SYSKEYUP})


def raw_extra_button_events(pressed_buttons, released_buttons):
    """Return MouseEvent objects for host-visible Raw Input extra button bits.

    Windows exposes the first five mouse buttons through normal mouse messages.
    G-series Logitech mice can also surface additional physical controls in the
    RAWMOUSE.ulRawButtons bitfield. We keep wheel-tilt bits out of this table
    because Mouser already handles those through WM_MOUSEHWHEEL.
    """
    events = []
    for mask, down_event, up_event, label in RAW_MOUSE_BUTTON_EVENT_MAP:
        raw_data = {"raw_button": label, "mask": f"0x{mask:X}"}
        if pressed_buttons & mask:
            events.append(MouseEvent(down_event, raw_data))
        if released_buttons & mask:
            events.append(MouseEvent(up_event, raw_data))
    return events


def _raw_device_vid_pid(device_name):
    match = re.search(
        r"VID[_&]([0-9A-Fa-f]{4}).*PID[_&]([0-9A-Fa-f]{4})",
        device_name or "",
    )
    if not match:
        return "", ""
    return match.group(1).upper(), match.group(2).upper()


def _short_raw_device_name(device_name):
    vid, pid = _raw_device_vid_pid(device_name)
    if vid and pid:
        return f"VID_{vid}&PID_{pid}"
    name = device_name or ""
    return name[-80:] if len(name) > 80 else name


def _private_user32_for_keyboard_hook():
    """Return an isolated user32 DLL wrapper for WH_KEYBOARD_LL prototypes.

    The module-level windll.user32 functions above are typed for the mouse
    hook's MSLLHOOKSTRUCT. A keyboard hook has a different lParam structure;
    using a private DLL wrapper here avoids overwriting the mouse hook's
    prototypes or making CallNextHookEx reject keyboard pointers.
    """
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = [
        c_int,
        KEYBOARD_HOOKPROC,
        wintypes.HINSTANCE,
        wintypes.DWORD,
    ]
    user32.CallNextHookEx.restype = ctypes.c_long
    user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK,
        c_int,
        wintypes.WPARAM,
        ctypes.POINTER(KBDLLHOOKSTRUCT),
    ]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
    return user32


class RAWINPUTDEVICE(Structure):
    _fields_ = [
        ("usUsagePage", c_ushort),
        ("usUsage", c_ushort),
        ("dwFlags", c_ulong),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTDEVICELIST(Structure):
    _fields_ = [
        ("hDevice", c_void_p),
        ("dwType", c_ulong),
    ]


class RAWINPUTHEADER(Structure):
    _fields_ = [
        ("dwType", c_ulong),
        ("dwSize", c_ulong),
        ("hDevice", c_void_p),
        ("wParam", POINTER(c_ulong)),
    ]


class RAWMOUSE(Structure):
    _fields_ = [
        ("usFlags", c_ushort),
        ("usButtonFlags", c_ushort),
        ("usButtonData", c_ushort),
        ("ulRawButtons", c_ulong),
        ("lLastX", c_int),
        ("lLastY", c_int),
        ("ulExtraInformation", c_ulong),
    ]


class RAWHID(Structure):
    _fields_ = [
        ("dwSizeHid", c_ulong),
        ("dwCount", c_ulong),
    ]


class RID_DEVICE_INFO_MOUSE(Structure):
    _fields_ = [
        ("dwId", c_ulong),
        ("dwNumberOfButtons", c_ulong),
        ("dwSampleRate", c_ulong),
        ("fHasHorizontalWheel", wintypes.BOOL),
    ]


class RID_DEVICE_INFO_KEYBOARD(Structure):
    _fields_ = [
        ("dwType", c_ulong),
        ("dwSubType", c_ulong),
        ("dwKeyboardMode", c_ulong),
        ("dwNumberOfFunctionKeys", c_ulong),
        ("dwNumberOfIndicators", c_ulong),
        ("dwNumberOfKeysTotal", c_ulong),
    ]


class RID_DEVICE_INFO_HID(Structure):
    _fields_ = [
        ("dwVendorId", c_ulong),
        ("dwProductId", c_ulong),
        ("dwVersionNumber", c_ulong),
        ("usUsagePage", c_ushort),
        ("usUsage", c_ushort),
    ]


class RID_DEVICE_INFO_UNION(Union):
    _fields_ = [
        ("mouse", RID_DEVICE_INFO_MOUSE),
        ("keyboard", RID_DEVICE_INFO_KEYBOARD),
        ("hid", RID_DEVICE_INFO_HID),
    ]


class RID_DEVICE_INFO(Structure):
    _fields_ = [
        ("cbSize", c_ulong),
        ("dwType", c_ulong),
        ("u", RID_DEVICE_INFO_UNION),
    ]


WNDPROC_TYPE = CFUNCTYPE(
    ctypes.c_longlong,
    wintypes.HWND,
    c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
)


class WNDCLASSEXW(Structure):
    _fields_ = [
        ("cbSize", c_uint),
        ("style", c_uint),
        ("lpfnWndProc", WNDPROC_TYPE),
        ("cbClsExtra", c_int),
        ("cbWndExtra", c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


RegisterRawInputDevices = windll.user32.RegisterRawInputDevices
GetRawInputData = windll.user32.GetRawInputData
GetRawInputData.argtypes = [c_void_p, c_uint, c_void_p, POINTER(c_uint), c_uint]
GetRawInputData.restype = c_uint
GetRawInputDeviceInfoW = windll.user32.GetRawInputDeviceInfoW
GetRawInputDeviceInfoW.restype = c_uint
GetRawInputDeviceList = windll.user32.GetRawInputDeviceList
GetRawInputDeviceList.restype = c_uint
RegisterClassExW = windll.user32.RegisterClassExW

CreateWindowExW = windll.user32.CreateWindowExW
CreateWindowExW.restype = wintypes.HWND
CreateWindowExW.argtypes = [
    wintypes.DWORD,
    wintypes.LPCWSTR,
    wintypes.LPCWSTR,
    wintypes.DWORD,
    c_int,
    c_int,
    c_int,
    c_int,
    wintypes.HWND,
    wintypes.HMENU,
    wintypes.HINSTANCE,
    wintypes.LPVOID,
]

ShowWindow = windll.user32.ShowWindow
DefWindowProcW = windll.user32.DefWindowProcW
DefWindowProcW.restype = ctypes.c_longlong
DefWindowProcW.argtypes = [
    wintypes.HWND,
    c_uint,
    wintypes.WPARAM,
    wintypes.LPARAM,
]

TranslateMessage = windll.user32.TranslateMessage
DispatchMessageW = windll.user32.DispatchMessageW
DestroyWindow = windll.user32.DestroyWindow


def hiword(dword):
    value = (dword >> 16) & 0xFFFF
    if value >= 0x8000:
        value -= 0x10000
    return value


WM_APP = 0x8000
WM_APP_INJECT_VSCROLL = WM_APP + 1
WM_APP_INJECT_HSCROLL = WM_APP + 2
WM_APP_INJECT_SHIFT_HSCROLL = WM_APP + 3

WM_DEVICECHANGE = 0x0219
DBT_DEVNODES_CHANGED = 0x0007

PostMessageW = windll.user32.PostMessageW
PostMessageW.argtypes = [wintypes.HWND, c_uint, wintypes.WPARAM, wintypes.LPARAM]
PostMessageW.restype = wintypes.BOOL


class MouseHook(BaseMouseHook):
    """
    Installs a low-level mouse hook on Windows to intercept side-button clicks
    and horizontal scroll events.
    """

    def __init__(self):
        super().__init__()
        self._hook = None
        self._keyboard_hook = None
        self._hook_thread = None
        self._thread_id = None
        self._running = False
        self._hook_proc = None
        self._keyboard_hook_proc = None
        self._keyboard_user32 = None
        self._g502_fkeys_down = set()
        self.g502_onboard_unlocked = False
        self._pending_vscroll = 0
        self._pending_hscroll = 0
        self._pending_shift_hscroll = 0
        self._vscroll_posted = False
        self._hscroll_posted = False
        self._shift_hscroll_posted = False
        self._ri_wndproc_ref = None
        self._ri_hwnd = None
        self._device_name_cache = {}
        self._startup_event = threading.Event()
        self._startup_ok = False
        self._prev_raw_buttons = {}
        self._prev_hid_reports = {}
        self._raw_hid_learning_until = 0.0
        self._raw_hid_seen_count = 0
        self._last_rehook_time = 0
        # Per-button slide gesture: last cursor position while an owner button
        # is held, to derive per-move deltas from the LL hook's absolute point.
        self._btn_gesture_last_x = 0
        self._btn_gesture_last_y = 0
        self._debug_burst_last_at = 0.0
        self._debug_burst_skipped = 0
        self._init_dispatch_queue(maxsize=512)
        self._dispatch_worker_thread = None

    # Wheel messages arrive in bursts -- a hi-res wheel emits ~15 per detent --
    # and each debug line costs a Qt signal plus a QML list rebuild. Coalesce
    # them so turning debug mode on during a scroll doesn't stall the app.
    _DEBUG_BURST_MESSAGES = (WM_MOUSEWHEEL, WM_MOUSEHWHEEL)
    _DEBUG_BURST_INTERVAL_S = 0.25

    def _debug_event_allowed(self, wParam):
        """Return ``(emit, skipped)`` for one debug line from the hook proc."""
        if wParam not in self._DEBUG_BURST_MESSAGES:
            return True, 0
        now = time.monotonic()
        if now - self._debug_burst_last_at < self._DEBUG_BURST_INTERVAL_S:
            self._debug_burst_skipped += 1
            return False, 0
        skipped = self._debug_burst_skipped
        self._debug_burst_skipped = 0
        self._debug_burst_last_at = now
        return True, skipped

    _WM_NAMES = {
        0x0100: "WM_KEYDOWN",
        0x0101: "WM_KEYUP",
        0x0104: "WM_SYSKEYDOWN",
        0x0105: "WM_SYSKEYUP",
        0x0200: "WM_MOUSEMOVE",
        0x0201: "WM_LBUTTONDOWN",
        0x0202: "WM_LBUTTONUP",
        0x0204: "WM_RBUTTONDOWN",
        0x0205: "WM_RBUTTONUP",
        0x0207: "WM_MBUTTONDOWN",
        0x0208: "WM_MBUTTONUP",
        0x020A: "WM_MOUSEWHEEL",
        0x020B: "WM_XBUTTONDOWN",
        0x020C: "WM_XBUTTONUP",
        0x020E: "WM_MOUSEHWHEEL",
    }

    def _call_next_keyboard_hook(self, nCode, wParam, lParam):
        user32 = self._keyboard_user32
        if user32 is None:
            return 0
        return user32.CallNextHookEx(self._keyboard_hook, nCode, wParam, lParam)

    def _coerce_connected_product_id(self):
        device = getattr(self, "_connected_device", None)
        product_id = getattr(device, "product_id", None)
        if product_id in (None, ""):
            return ""
        try:
            value = int(product_id, 0) if isinstance(product_id, str) else int(product_id)
        except (TypeError, ValueError):
            return ""
        return f"{value:04X}"

    def _should_intercept_g502_fkeys(self):
        """Gate F13-F16 swallowing to a connected G502-family Mouser device."""
        if not getattr(self, "g502_onboard_unlocked", False):
            return False
        if not self._should_intercept_events():
            return False
        device = getattr(self, "_connected_device", None)
        if device is None:
            return False
        buttons = set(getattr(device, "supported_buttons", ()) or ())
        if buttons and G502_FKEY_BUTTONS.intersection(buttons):
            return True
        key = str(getattr(device, "key", "") or "").lower()
        layout = str(getattr(device, "ui_layout", "") or "").lower()
        if key.startswith("g502") or layout.startswith("g502"):
            return True
        return self._coerce_connected_product_id() in G502_USB_PRODUCT_IDS

    def _low_level_keyboard_handler(self, nCode, wParam, lParam):
        try:
            return self._low_level_keyboard_handler_inner(nCode, wParam, lParam)
        except Exception as exc:
            try:
                print(f"[MouseHook] CRITICAL _low_level_keyboard_handler EXCEPTION: {exc}")
                import traceback

                traceback.print_exc()
            except Exception:
                pass
            return self._call_next_keyboard_hook(nCode, wParam, lParam)

    def _low_level_keyboard_handler_inner(self, nCode, wParam, lParam):
        if nCode != HC_ACTION:
            return self._call_next_keyboard_hook(nCode, wParam, lParam)

        data = lParam.contents
        vk = int(data.vkCode)
        mapped = G502_FKEY_EVENT_MAP.get(vk)
        if mapped is None:
            return self._call_next_keyboard_hook(nCode, wParam, lParam)

        message = int(wParam)
        if message not in _KEY_DOWN_MESSAGES and message not in _KEY_UP_MESSAGES:
            return self._call_next_keyboard_hook(nCode, wParam, lParam)

        if int(data.flags) & LLKHF_INJECTED:
            return self._call_next_keyboard_hook(nCode, wParam, lParam)

        if not self._should_intercept_g502_fkeys():
            if message in _KEY_UP_MESSAGES:
                self._g502_fkeys_down.discard(vk)
            return self._call_next_keyboard_hook(nCode, wParam, lParam)

        down_event, up_event, key_name, button_key = mapped
        if message in _KEY_DOWN_MESSAGES:
            if vk in self._g502_fkeys_down:
                return 1
            self._g502_fkeys_down.add(vk)
            event_type = down_event
        else:
            self._g502_fkeys_down.discard(vk)
            event_type = up_event

        self._emit_debug(f"G502 onboard {key_name} -> {event_type}")
        self._enqueue_dispatch_event(MouseEvent(
            event_type,
            {
                "source": "g502_onboard_fkey",
                "key": key_name,
                "button": button_key,
                "vk": f"0x{vk:02X}",
            },
        ))
        return 1

    def _low_level_handler(self, nCode, wParam, lParam):
        try:
            return self._low_level_handler_inner(nCode, wParam, lParam)
        except Exception as exc:
            try:
                print(f"[MouseHook] CRITICAL _low_level_handler EXCEPTION: {exc}")
                import traceback

                traceback.print_exc()
            except Exception:
                pass
            return CallNextHookEx(self._hook, nCode, wParam, lParam)

    def _low_level_handler_inner(self, nCode, wParam, lParam):
        if nCode == HC_ACTION:
            data = lParam.contents
            mouse_data = data.mouseData
            flags = data.flags
            event = None
            should_block = False

            if self.debug_mode and self._debug_callback and wParam != WM_MOUSEMOVE:
                allowed, skipped = self._debug_event_allowed(wParam)
                if allowed:
                    wm_name = self._WM_NAMES.get(wParam, f"0x{wParam:04X}")
                    extra = int(data.dwExtraInfo)
                    info = (
                        f"{wm_name}  mouseData=0x{mouse_data:08X}  "
                        f"hiword={hiword(mouse_data)}  flags=0x{flags:04X}  "
                        f"extraInfo=0x{extra:X}"
                    )
                    if skipped:
                        info += f"  (+{skipped} more)"
                    try:
                        self._debug_callback(info)
                    except Exception:
                        pass

            if flags & INJECTED_FLAG:
                return CallNextHookEx(self._hook, nCode, wParam, lParam)

            # KVM / cold-start guard: when no Logitech is currently bound to
            # this host, the WH_MOUSE_LL hook must be a complete pass-through.
            # The hook sees events from every input device, so without this
            # guard a trackpad scroll or generic USB mouse's xbutton click
            # would still run through Mouser's remap pipeline -- the exact
            # failure mode users hit when their KVM switches the Logitech
            # to another machine while Mouser keeps running here.
            if not self._should_intercept_events():
                return CallNextHookEx(self._hook, nCode, wParam, lParam)

            # ── Per-button slide gestures (back/forward/middle) ──────────
            # When a button is armed as a gesture pad, its press starts the
            # shared recognizer and is swallowed; pointer motion while held is
            # fed to the recognizer (which fires a button_swipe event on a
            # committed slide); the release ends the hold. A quick tap with no
            # slide simply ends as a no-op. Fast None-check when idle.
            if self._button_gesture_active_owner is not None and wParam == WM_MOUSEMOVE:
                # First move of a hold that armed without a start point (e.g.
                # mode shift over HID): establish the origin, don't sample yet.
                if self._button_gesture_origin_needed:
                    self._btn_gesture_last_x = data.pt.x
                    self._btn_gesture_last_y = data.pt.y
                    self._button_gesture_origin_needed = False
                    return CallNextHookEx(self._hook, nCode, wParam, lParam)
                dx = data.pt.x - self._btn_gesture_last_x
                dy = data.pt.y - self._btn_gesture_last_y
                self._btn_gesture_last_x = data.pt.x
                self._btn_gesture_last_y = data.pt.y
                self.sample_button_gesture(dx, dy, "os_motion")
                return CallNextHookEx(self._hook, nCode, wParam, lParam)

            gesture_owner = None
            if wParam in (WM_MBUTTONDOWN, WM_MBUTTONUP):
                gesture_owner = "middle"
            elif wParam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
                xb = hiword(mouse_data)
                if xb == XBUTTON1:
                    gesture_owner = "xbutton1"
                elif xb == XBUTTON2:
                    gesture_owner = "xbutton2"

            if gesture_owner is not None:
                if wParam in (WM_MBUTTONDOWN, WM_XBUTTONDOWN):
                    if (self.is_button_gesture_owner(gesture_owner)
                            and self.arm_button_gesture(gesture_owner)):
                        # Origin is known from this press point.
                        self._btn_gesture_last_x = data.pt.x
                        self._btn_gesture_last_y = data.pt.y
                        self._button_gesture_origin_needed = False
                        return 1
                elif self._button_gesture_active_owner == gesture_owner:
                    # owner-button up while armed -> resolve and swallow
                    self.release_button_gesture(gesture_owner)
                    return 1

            if wParam == WM_XBUTTONDOWN:
                xbutton = hiword(mouse_data)
                if xbutton == XBUTTON1:
                    event = MouseEvent(MouseEvent.XBUTTON1_DOWN)
                    should_block = MouseEvent.XBUTTON1_DOWN in self._blocked_events
                elif xbutton == XBUTTON2:
                    event = MouseEvent(MouseEvent.XBUTTON2_DOWN)
                    should_block = MouseEvent.XBUTTON2_DOWN in self._blocked_events

            elif wParam == WM_XBUTTONUP:
                xbutton = hiword(mouse_data)
                if xbutton == XBUTTON1:
                    event = MouseEvent(MouseEvent.XBUTTON1_UP)
                    should_block = MouseEvent.XBUTTON1_UP in self._blocked_events
                elif xbutton == XBUTTON2:
                    event = MouseEvent(MouseEvent.XBUTTON2_UP)
                    should_block = MouseEvent.XBUTTON2_UP in self._blocked_events

            elif wParam == WM_MBUTTONDOWN:
                event = MouseEvent(MouseEvent.MIDDLE_DOWN)
                should_block = MouseEvent.MIDDLE_DOWN in self._blocked_events

            elif wParam == WM_MBUTTONUP:
                event = MouseEvent(MouseEvent.MIDDLE_UP)
                should_block = MouseEvent.MIDDLE_UP in self._blocked_events

            elif wParam == WM_MOUSEWHEEL:
                delta = hiword(mouse_data)
                if delta != 0 and (GetAsyncKeyState(VK_SHIFT) & 0x8000):
                    if self._ri_hwnd:
                        h_delta = -delta if self.invert_hscroll else delta
                        self._pending_shift_hscroll += h_delta
                        if self._shift_hscroll_posted:
                            return 1
                        if PostMessageW(
                            self._ri_hwnd, WM_APP_INJECT_SHIFT_HSCROLL, 0, 0
                        ):
                            self._shift_hscroll_posted = True
                            return 1
                        self._pending_shift_hscroll -= h_delta
                    else:
                        self._emit_debug(
                            "Shift+wheel translation skipped: "
                            "raw input window unavailable"
                        )
                if self.invert_vscroll and not self.wheel_native_invert_active:
                    if delta != 0 and self._ri_hwnd:
                        self._pending_vscroll += -delta
                        if self._vscroll_posted:
                            return 1
                        if PostMessageW(self._ri_hwnd, WM_APP_INJECT_VSCROLL, 0, 0):
                            self._vscroll_posted = True
                            return 1
                        self._pending_vscroll -= -delta
                    elif delta != 0:
                        self._emit_debug(
                            "Invert vertical scroll skipped: raw input window unavailable"
                        )

            elif wParam == WM_MOUSEHWHEEL:
                delta = hiword(mouse_data)
                event_type = hscroll_event_type(delta)
                if event_type:
                    event = MouseEvent(event_type, abs(delta))
                    should_block = event_type in self._blocked_events

                if self.invert_hscroll and not self.wheel_native_invert_active:
                    if delta != 0 and self._ri_hwnd and not should_block:
                        self._pending_hscroll += -delta
                        if self._hscroll_posted:
                            return 1
                        if PostMessageW(self._ri_hwnd, WM_APP_INJECT_HSCROLL, 0, 0):
                            self._hscroll_posted = True
                            return 1
                        self._pending_hscroll -= -delta
                    elif delta != 0 and not should_block:
                        self._emit_debug(
                            "Invert horizontal scroll skipped: raw input window unavailable"
                        )

            if event:
                self._enqueue_dispatch_event(event)
                if should_block:
                    return 1

        return CallNextHookEx(self._hook, nCode, wParam, lParam)

    def _get_device_name(self, hDevice):
        if hDevice in self._device_name_cache:
            return self._device_name_cache[hDevice]
        try:
            size = c_uint(0)
            GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, None, byref(size))
            if size.value > 0:
                buffer = ctypes.create_unicode_buffer(size.value + 1)
                GetRawInputDeviceInfoW(hDevice, RIDI_DEVICENAME, buffer, byref(size))
                name = buffer.value
            else:
                name = ""
        except Exception:
            name = ""
        self._device_name_cache[hDevice] = name
        return name

    def _is_logitech(self, hDevice):
        return "046d" in self._get_device_name(hDevice).lower()

    def _is_g502_raw_device(self, hDevice):
        vid, pid = _raw_device_vid_pid(self._get_device_name(hDevice))
        return vid == "046D" and pid in G502_USB_PRODUCT_IDS

    def _raw_input_device_info(self, hDevice):
        info = RID_DEVICE_INFO()
        info.cbSize = sizeof(RID_DEVICE_INFO)
        size = c_uint(sizeof(RID_DEVICE_INFO))
        if GetRawInputDeviceInfoW(
            hDevice,
            RIDI_DEVICEINFO,
            byref(info),
            byref(size),
        ) == 0xFFFFFFFF:
            return None
        return info

    def _iter_raw_input_devices(self):
        count = c_uint(0)
        if GetRawInputDeviceList(None, byref(count), sizeof(RAWINPUTDEVICELIST)) == 0xFFFFFFFF:
            return []
        if count.value <= 0:
            return []
        devices = (RAWINPUTDEVICELIST * count.value)()
        result = GetRawInputDeviceList(devices, byref(count), sizeof(RAWINPUTDEVICELIST))
        if result == 0xFFFFFFFF:
            return []
        return list(devices[:result])

    def _emit_g502_raw_hid_inventory(self):
        try:
            devices = self._iter_raw_input_devices()
        except Exception as exc:
            self._emit_debug(f"G502 Raw HID inventory failed: {exc}")
            return 0

        g502_count = 0
        logitech_count = 0
        for device in devices:
            name = self._get_device_name(device.hDevice)
            vid, pid = _raw_device_vid_pid(name)
            if vid != "046D":
                continue
            logitech_count += 1
            info = self._raw_input_device_info(device.hDevice)
            if info is None:
                kind = f"type={int(device.dwType)}"
            elif int(info.dwType) == RIM_TYPEHID:
                kind = (
                    f"hid usage_page=0x{int(info.u.hid.usUsagePage):04X} "
                    f"usage=0x{int(info.u.hid.usUsage):04X}"
                )
            elif int(info.dwType) == RIM_TYPEMOUSE:
                kind = "mouse"
            elif int(info.dwType) == RIM_TYPEKEYBOARD:
                kind = "keyboard"
            else:
                kind = f"type={int(info.dwType)}"
            if pid in G502_USB_PRODUCT_IDS:
                g502_count += 1
                self._emit_debug(
                    "G502 Raw Input interface found: "
                    f"pid=0x{pid} {kind} device={_short_raw_device_name(name) or '-'}"
                )

        if g502_count == 0:
            self._emit_debug(
                "G502 Raw HID detection: no G502 Raw Input interface found "
                f"(Logitech interfaces seen: {logitech_count})."
            )
        return g502_count

    def start_raw_hid_learning(self, duration_s=60):
        duration_s = max(5.0, min(float(duration_s or 60), 300.0))
        self._raw_hid_learning_until = time.monotonic() + duration_s
        self._raw_hid_seen_count = 0
        self._prev_hid_reports.clear()
        self._emit_debug(
            "G502 Raw HID detection started: press DPI Shift, G7, G8, "
            f"G9 during the next {int(duration_s)} seconds."
        )
        found = self._emit_g502_raw_hid_inventory()
        if self._ri_hwnd:
            self._emit_debug("G502 Raw HID detection is listening for changed reports.")
        else:
            self._emit_debug("G502 Raw HID detection cannot listen: Raw Input window is unavailable.")
            return False
        if found == 0:
            self._emit_debug(
                "If the mouse is connected, unplug/replug it once and restart Mouser, "
                "then start detection again."
            )
        return True

    def _raw_hid_learning_active(self):
        if self._raw_hid_learning_until <= 0:
            return False
        if time.monotonic() <= self._raw_hid_learning_until:
            return True
        seen = self._raw_hid_seen_count
        self._raw_hid_learning_until = 0.0
        self._emit_debug(f"G502 Raw HID detection ended. Changed reports seen: {seen}")
        return False

    def _ri_wndproc(self, hwnd, msg, wParam, lParam):
        if msg == WM_INPUT:
            try:
                self._process_raw_input(lParam)
            except Exception as exc:
                print(f"[MouseHook] Raw Input error: {exc}")
            return 0

        if msg == WM_APP_INJECT_VSCROLL:
            delta = self._pending_vscroll
            self._pending_vscroll = 0
            self._vscroll_posted = False
            if delta != 0:
                _inject_scroll_impl(MOUSEEVENTF_WHEEL, delta)
            return 0

        if msg == WM_APP_INJECT_HSCROLL:
            delta = self._pending_hscroll
            self._pending_hscroll = 0
            self._hscroll_posted = False
            if delta != 0:
                _inject_scroll_impl(MOUSEEVENTF_HWHEEL, delta)
            return 0

        if msg == WM_APP_INJECT_SHIFT_HSCROLL:
            delta = self._pending_shift_hscroll
            self._pending_shift_hscroll = 0
            self._shift_hscroll_posted = False
            if delta != 0:
                _inject_scroll_impl(MOUSEEVENTF_HWHEEL, delta)
            return 0

        if msg == WM_DEVICECHANGE:
            if wParam == DBT_DEVNODES_CHANGED:
                self._on_device_change()
            return 0

        return DefWindowProcW(hwnd, msg, wParam, lParam)

    def _process_raw_input(self, lParam):
        size = c_uint(0)
        GetRawInputData(lParam, RID_INPUT, None, byref(size), sizeof(RAWINPUTHEADER))
        if size.value == 0:
            return
        buffer = create_string_buffer(size.value)
        ret = GetRawInputData(
            lParam,
            RID_INPUT,
            buffer,
            byref(size),
            sizeof(RAWINPUTHEADER),
        )
        if ret == 0xFFFFFFFF:
            return
        header = RAWINPUTHEADER.from_buffer_copy(buffer)
        if not self._is_logitech(header.hDevice):
            return
        if header.dwType == RIM_TYPEMOUSE:
            self._check_raw_mouse_gesture(header.hDevice, buffer)
        elif header.dwType == RIM_TYPEHID:
            self._check_raw_hid_report(header.hDevice, buffer, size.value)

    def _check_raw_mouse_gesture(self, hDevice, buffer):
        mouse = RAWMOUSE.from_buffer_copy(buffer, sizeof(RAWINPUTHEADER))
        raw_buttons = mouse.ulRawButtons
        prev_buttons = self._prev_raw_buttons.get(hDevice, 0)
        self._prev_raw_buttons[hDevice] = raw_buttons

        extra_now = raw_buttons & ~STANDARD_BUTTON_MASK
        extra_prev = prev_buttons & ~STANDARD_BUTTON_MASK

        if extra_now != extra_prev:
            pressed = extra_now & ~extra_prev
            released = extra_prev & ~extra_now
            for event in raw_extra_button_events(pressed, released):
                self._emit_debug(
                    f"Raw extra button {event.event_type} "
                    f"mask={event.raw_data.get('mask')}"
                )
                self._enqueue_dispatch_event(event)

        if self._hid_gesture_available():
            return

        if extra_now == extra_prev:
            return
        if extra_now and not extra_prev:
            if not self._gesture_active:
                self._gesture_recognizer.begin()
                self._gesture_active = True
                print(f"[MouseHook] Gesture DOWN (rawBtns extra: 0x{extra_now:X})")
        elif not extra_now and extra_prev:
            if self._gesture_active:
                self._gesture_active = False
                was_click = self._gesture_recognizer.end()
                print("[MouseHook] Gesture UP")
                if was_click:
                    self._enqueue_dispatch_event(MouseEvent(MouseEvent.GESTURE_CLICK))

    def _check_raw_hid_report(self, hDevice, buffer, total_size):
        """Log changed Logitech vendor HID reports for G502 button learning."""
        if not self.debug_mode or not self._raw_hid_learning_active():
            return
        if not self._is_g502_raw_device(hDevice):
            return
        try:
            hid = RAWHID.from_buffer_copy(buffer, sizeof(RAWINPUTHEADER))
        except Exception:
            return

        size_hid = int(hid.dwSizeHid)
        count = int(hid.dwCount)
        if size_hid <= 0 or count <= 0:
            return

        offset = sizeof(RAWINPUTHEADER) + sizeof(RAWHID)
        available = max(0, int(total_size) - offset)
        raw = bytes(buffer.raw[offset:offset + min(available, size_hid * count)])
        if not raw:
            return

        device_name = self._get_device_name(hDevice)
        for index in range(count):
            start = index * size_hid
            chunk = raw[start:start + size_hid]
            if not chunk:
                continue
            key = (hDevice, index)
            previous = self._prev_hid_reports.get(key)
            if previous == chunk:
                continue
            self._prev_hid_reports[key] = chunk
            if not any(chunk) and previous is None:
                continue
            self._raw_hid_seen_count += 1
            hex_bytes = " ".join(f"{byte:02X}" for byte in chunk[:32])
            if len(chunk) > 32:
                hex_bytes += " ..."
            short_name = _short_raw_device_name(device_name)
            self._emit_debug(
                "Raw HID report "
                f"device={short_name or '-'} size={size_hid} "
                f"index={index + 1}/{count} bytes=[{hex_bytes}]"
            )

    def _setup_raw_input(self):
        instance = GetModuleHandleW(None)
        class_name = f"MouserRawInput_{id(self)}"
        self._ri_wndproc_ref = WNDPROC_TYPE(self._ri_wndproc)

        window_class = WNDCLASSEXW()
        window_class.cbSize = sizeof(WNDCLASSEXW)
        window_class.lpfnWndProc = self._ri_wndproc_ref
        window_class.hInstance = instance
        window_class.lpszClassName = class_name
        RegisterClassExW(byref(window_class))

        self._ri_hwnd = CreateWindowExW(
            0,
            class_name,
            "Mouser RI",
            0,
            0,
            0,
            1,
            1,
            None,
            None,
            instance,
            None,
        )
        if not self._ri_hwnd:
            print("[MouseHook] CreateWindowExW failed — gesture detection unavailable")
            return False

        ShowWindow(self._ri_hwnd, SW_HIDE)

        devices = (RAWINPUTDEVICE * len(RAW_INPUT_DEVICE_USAGES))()
        for index, (usage_page, usage) in enumerate(RAW_INPUT_DEVICE_USAGES):
            devices[index].usUsagePage = usage_page
            devices[index].usUsage = usage
            devices[index].dwFlags = RIDEV_INPUTSINK
            devices[index].hwndTarget = self._ri_hwnd

        if RegisterRawInputDevices(devices, len(RAW_INPUT_DEVICE_USAGES), sizeof(RAWINPUTDEVICE)):
            print("[MouseHook] Raw Input: mice + Logitech HID + G502 HID + consumer")
            return True
        if RegisterRawInputDevices(devices, 5, sizeof(RAWINPUTDEVICE)):
            print("[MouseHook] Raw Input: mice + Logitech HID + G502 HID")
            return True
        if RegisterRawInputDevices(devices, 3, sizeof(RAWINPUTDEVICE)):
            print("[MouseHook] Raw Input: mice + Logitech HID short")
            return True
        if RegisterRawInputDevices(devices, 1, sizeof(RAWINPUTDEVICE)):
            print("[MouseHook] Raw Input: mice only")
            return True
        print("[MouseHook] Raw Input registration failed")
        return False

    def _dispatch_worker(self):
        while self._running:
            try:
                event = self._dispatch_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._dispatch(event)
            except Exception as exc:
                print(f"[MouseHook] dispatch worker error: {exc}")

    def _install_keyboard_hook(self):
        """Install the F13-F16 bridge used by the G502 onboard unlock flow."""
        try:
            user32 = _private_user32_for_keyboard_hook()
            proc = KEYBOARD_HOOKPROC(self._low_level_keyboard_handler)
            hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL,
                proc,
                GetModuleHandleW(None),
                0,
            )
        except Exception as exc:
            self._keyboard_hook = None
            self._keyboard_hook_proc = None
            self._keyboard_user32 = None
            print(f"[MouseHook] Failed to install G502 F13-F16 bridge: {exc}")
            return False

        if not hook:
            self._keyboard_hook = None
            self._keyboard_hook_proc = None
            self._keyboard_user32 = None
            print("[MouseHook] Failed to install G502 F13-F16 bridge")
            return False

        self._keyboard_user32 = user32
        self._keyboard_hook_proc = proc
        self._keyboard_hook = hook
        self._g502_fkeys_down.clear()
        print("[MouseHook] G502 F13-F16 bridge installed")
        return True

    def _uninstall_keyboard_hook(self):
        user32 = self._keyboard_user32
        hook = self._keyboard_hook
        if hook and user32 is not None:
            try:
                user32.UnhookWindowsHookEx(hook)
            except Exception:
                pass
        self._keyboard_hook = None
        self._keyboard_hook_proc = None
        self._keyboard_user32 = None
        self._g502_fkeys_down.clear()

    def _run_hook(self):
        self._thread_id = windll.kernel32.GetCurrentThreadId()
        self._hook_proc = HOOKPROC(self._low_level_handler)
        self._hook = SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            GetModuleHandleW(None),
            0,
        )
        if not self._hook:
            self._startup_ok = False
            self._startup_event.set()
            print("[MouseHook] Failed to install hook!")
            return
        print("[MouseHook] Hook installed successfully")
        self._install_keyboard_hook()
        self._setup_raw_input()
        self._running = True
        self._startup_ok = True
        self._startup_event.set()

        message = wintypes.MSG()
        while self._running:
            result = GetMessageW(ctypes.byref(message), None, 0, 0)
            if result == 0 or result == -1:
                break
            TranslateMessage(ctypes.byref(message))
            DispatchMessageW(ctypes.byref(message))

        if self._ri_hwnd:
            DestroyWindow(self._ri_hwnd)
            self._ri_hwnd = None
        self._uninstall_keyboard_hook()
        if self._hook:
            UnhookWindowsHookEx(self._hook)
            self._hook = None
        self._running = False
        print("[MouseHook] Hook removed")

    def _on_device_change(self):
        now = time.time()
        if now - self._last_rehook_time < 2.0:
            return
        self._last_rehook_time = now
        print("[MouseHook] Device change detected — refreshing hook")
        self._device_name_cache.clear()
        self._prev_raw_buttons.clear()
        self._prev_hid_reports.clear()
        self._reinstall_hook()
        self.request_hid_reconnect("device_change")

    def _reinstall_hook(self):
        self._uninstall_keyboard_hook()
        if self._hook:
            UnhookWindowsHookEx(self._hook)
            self._hook = None
        self._hook_proc = HOOKPROC(self._low_level_handler)
        self._hook = SetWindowsHookExW(
            WH_MOUSE_LL,
            self._hook_proc,
            GetModuleHandleW(None),
            0,
        )
        if self._hook:
            print("[MouseHook] Hook reinstalled successfully")
            self._install_keyboard_hook()
        else:
            print("[MouseHook] Failed to reinstall hook!")

    def _emit_gesture_swipe(self, mouse_event):
        """Route gesture swipes through the dispatch queue so they run on
        the dispatch-worker thread, not inline on the HID callback thread."""
        self._enqueue_dispatch_event(mouse_event)

    def _start_dispatch_worker(self):
        if self._dispatch_worker_thread and self._dispatch_worker_thread.is_alive():
            return True
        self._dispatch_worker_thread = threading.Thread(
            target=self._dispatch_worker,
            daemon=True,
            name="HookDispatch",
        )
        self._dispatch_worker_thread.start()
        return True

    def runtime_health(self):
        return {
            "running": bool(self._running),
            "hook_thread_alive": bool(
                self._hook_thread and self._hook_thread.is_alive()
            ),
            "dispatch_worker_alive": bool(
                self._dispatch_worker_thread
                and self._dispatch_worker_thread.is_alive()
            ),
            "hid_listener_alive": bool(self.hid_listener_alive()),
            "hid_listener_present": bool(getattr(self, "_hid_gesture", None)),
        }

    def ensure_runtime_alive(self):
        """Best-effort self-healing for the Windows hook runtime."""
        health = self.runtime_health()
        if not self._running:
            print("[MouseHook] Hook runtime stopped; restarting")
            self.start()
            return self.runtime_health()
        if not health["hook_thread_alive"]:
            print("[MouseHook] Hook thread stopped; restarting hook runtime")
            self._running = False
            self.start()
            return self.runtime_health()
        if not health["dispatch_worker_alive"]:
            print("[MouseHook] Dispatch worker stopped; restarting")
            self._start_dispatch_worker()
        if (
            not health["hid_listener_alive"]
            and getattr(self, "_hid_gesture", None) is not None
        ):
            print("[MouseHook] HID listener stopped; restarting")
            self.request_hid_reconnect("runtime_health")
        return self.runtime_health()

    def start(self):
        if self._hook_thread and self._hook_thread.is_alive():
            self._start_dispatch_worker()
            if not self.hid_listener_alive():
                self.request_hid_reconnect("start")
            return True
        self._startup_ok = False
        self._startup_event.clear()
        self._hook_thread = threading.Thread(target=self._run_hook, daemon=True)
        self._hook_thread.start()
        if not self._startup_event.wait(2):
            print("[MouseHook] Hook startup timed out")
            self.stop()
            return False
        if not self._startup_ok:
            return False
        self._start_hid_listener()
        self._start_dispatch_worker()
        return True

    def stop(self):
        self._running = False
        self.abort_button_gesture("stop")
        self._stop_hid_listener()
        self._connected_device = None
        if self._dispatch_worker_thread:
            self._dispatch_worker_thread.join(timeout=1)
            self._dispatch_worker_thread = None
        if self._thread_id:
            PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._hook_thread:
            self._hook_thread.join(timeout=2)
        self._hook = None
        self._ri_hwnd = None
        self._thread_id = None
        self._startup_ok = False
        self._startup_event.clear()


MouseHook._platform_module = sys.modules[__name__]


__all__ = [
    "MouseHook",
    "HidGestureListener",
    "MSLLHOOKSTRUCT",
    "WM_XBUTTONDOWN",
    "WM_XBUTTONUP",
    "WM_MBUTTONDOWN",
    "WM_MBUTTONUP",
    "WM_MOUSEHWHEEL",
    "WM_MOUSEWHEEL",
]
