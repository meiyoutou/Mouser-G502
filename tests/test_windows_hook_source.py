"""Source guards for the Windows hook, which cannot be imported off Windows.

Both crash reports in issues #252 and #253 trace to one line: ``dwExtraInfo``
is a ULONG_PTR *value*, but the struct declared it as a pointer and the debug
path read ``.contents``, dereferencing whatever number the sender attached.
Any event carrying a non-zero value killed the process outright -- silently,
with nothing in the log -- whenever debug mode was on.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_HOOK = (ROOT / "core" / "mouse_hook_windows.py").read_text(encoding="utf-8")
KEY_CAPTURE = (ROOT / "core" / "key_capture.py").read_text(encoding="utf-8")


class ExtraInfoIsAValueNotAPointerTests(unittest.TestCase):
    def test_mouse_hook_struct_declares_extra_info_as_a_value(self):
        self.assertIn('("dwExtraInfo", wintypes.WPARAM)', WINDOWS_HOOK)

    def test_key_capture_struct_declares_extra_info_as_a_value(self):
        self.assertIn('("dwExtraInfo", wintypes.WPARAM)', KEY_CAPTURE)

    def test_no_hook_dereferences_extra_info(self):
        for name, source in (
            ("mouse_hook_windows", WINDOWS_HOOK),
            ("key_capture", KEY_CAPTURE),
        ):
            with self.subTest(module=name):
                self.assertNotIn("dwExtraInfo.contents", source)


class DebugLoggingIsRateLimitedTests(unittest.TestCase):
    def test_wheel_bursts_are_coalesced(self):
        # A hi-res wheel emits ~15 messages per detent; one debug line each
        # costs a Qt signal plus a QML list rebuild.
        self.assertIn("_DEBUG_BURST_MESSAGES", WINDOWS_HOOK)
        self.assertIn("def _debug_event_allowed", WINDOWS_HOOK)

    def test_debug_path_skips_mouse_moves_before_formatting(self):
        self.assertIn(
            "if self.debug_mode and self._debug_callback and wParam != WM_MOUSEMOVE:",
            WINDOWS_HOOK,
        )


class RawExtraButtonSourceTests(unittest.TestCase):
    def test_g502_extra_raw_buttons_are_mapped_and_wheel_tilt_is_not_duplicated(self):
        self.assertIn("RAW_MOUSE_BUTTON_EVENT_MAP", WINDOWS_HOOK)
        self.assertIn("0x0020", WINDOWS_HOOK)
        self.assertIn("MOUSE_BUTTON_6_DOWN", WINDOWS_HOOK)
        self.assertIn("0x0100", WINDOWS_HOOK)
        self.assertIn("MOUSE_BUTTON_9_DOWN", WINDOWS_HOOK)
        self.assertIn("0x0200", WINDOWS_HOOK)
        self.assertIn("MOUSE_BUTTON_10_DOWN", WINDOWS_HOOK)
        self.assertIn("0x0400", WINDOWS_HOOK)
        self.assertIn("MOUSE_BUTTON_11_DOWN", WINDOWS_HOOK)
        self.assertIn("0x2000", WINDOWS_HOOK)
        self.assertIn("MOUSE_BUTTON_DPI_DOWN", WINDOWS_HOOK)
        self.assertNotIn("(0x0040,", WINDOWS_HOOK)
        self.assertNotIn("(0x0080,", WINDOWS_HOOK)

    def test_g502_vendor_raw_hid_usages_are_registered(self):
        self.assertIn("RAW_INPUT_DEVICE_USAGES", WINDOWS_HOOK)
        self.assertIn("(0xFF00, 0x0001)", WINDOWS_HOOK)
        self.assertIn("(0xFF00, 0x0002)", WINDOWS_HOOK)
        self.assertIn("G502 HID", WINDOWS_HOOK)

    def test_g502_vendor_raw_hid_reports_are_logged_for_learning(self):
        self.assertIn("elif header.dwType == RIM_TYPEHID:", WINDOWS_HOOK)
        self.assertIn("_check_raw_hid_report(header.hDevice, buffer, size.value)", WINDOWS_HOOK)
        self.assertIn("def _check_raw_hid_report", WINDOWS_HOOK)
        self.assertIn("def start_raw_hid_learning", WINDOWS_HOOK)
        self.assertIn("_raw_hid_learning_active()", WINDOWS_HOOK)
        self.assertIn("_is_g502_raw_device(hDevice)", WINDOWS_HOOK)
        self.assertIn("Raw HID report", WINDOWS_HOOK)
        self.assertIn("self._prev_hid_reports", WINDOWS_HOOK)


class G502FKeyBridgeSourceTests(unittest.TestCase):
    def test_g502_f13_f16_keyboard_bridge_is_registered(self):
        self.assertIn("WH_KEYBOARD_LL", WINDOWS_HOOK)
        self.assertIn("KBDLLHOOKSTRUCT", WINDOWS_HOOK)
        self.assertIn("KEYBOARD_HOOKPROC", WINDOWS_HOOK)
        self.assertIn("_private_user32_for_keyboard_hook", WINDOWS_HOOK)
        self.assertIn("_install_keyboard_hook", WINDOWS_HOOK)

    def test_g502_f13_f16_events_map_to_semantic_g502_buttons(self):
        self.assertIn("G502_FKEY_EVENT_MAP", WINDOWS_HOOK)
        self.assertIn("VK_F13", WINDOWS_HOOK)
        self.assertIn("VK_F14", WINDOWS_HOOK)
        self.assertIn("VK_F15", WINDOWS_HOOK)
        self.assertIn("VK_F16", WINDOWS_HOOK)
        self.assertIn("G502_DPI_SHIFT_DOWN", WINDOWS_HOOK)
        self.assertIn("G502_DPI_DOWN_DOWN", WINDOWS_HOOK)
        self.assertIn("G502_DPI_UP_DOWN", WINDOWS_HOOK)
        self.assertIn("G502_PROFILE_CYCLE_UP", WINDOWS_HOOK)

    def test_g502_f13_f16_bridge_is_gated_and_swallows(self):
        self.assertIn("g502_onboard_unlocked", WINDOWS_HOOK)
        self.assertIn("def _should_intercept_g502_fkeys", WINDOWS_HOOK)
        self.assertIn("return 1", WINDOWS_HOOK)
        self.assertIn("g502_onboard_fkey", WINDOWS_HOOK)


if __name__ == "__main__":
    unittest.main()
