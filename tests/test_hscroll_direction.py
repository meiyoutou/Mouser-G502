"""Horizontal-scroll direction must mean the same thing on every platform.

The Windows hook classified a positive ``WM_MOUSEHWHEEL`` delta as a *left*
tilt while Linux classified the same sign as *right*, so a wheel tilted right
fired the left binding and vice versa (issue #253). The mapping now lives in
one helper; these tests pin its meaning and that every hook uses it.
"""

from pathlib import Path
import unittest

from core.mouse_hook_types import MouseEvent, hscroll_event_type


ROOT = Path(__file__).resolve().parents[1]
HOOK_SOURCES = {
    "windows": ROOT / "core" / "mouse_hook_windows.py",
    "macos": ROOT / "core" / "mouse_hook_macos.py",
    "linux": ROOT / "core" / "mouse_hook_linux.py",
}


class HscrollEventTypeTests(unittest.TestCase):
    def test_positive_delta_is_a_rightward_scroll(self):
        self.assertEqual(hscroll_event_type(1), MouseEvent.HSCROLL_RIGHT)
        self.assertEqual(hscroll_event_type(120), MouseEvent.HSCROLL_RIGHT)

    def test_negative_delta_is_a_leftward_scroll(self):
        self.assertEqual(hscroll_event_type(-1), MouseEvent.HSCROLL_LEFT)
        self.assertEqual(hscroll_event_type(-120), MouseEvent.HSCROLL_LEFT)

    def test_zero_delta_has_no_direction(self):
        self.assertEqual(hscroll_event_type(0), "")

    def test_float_deltas_are_classified_too(self):
        # macOS fixed-point deltas arrive as floats.
        self.assertEqual(hscroll_event_type(0.5), MouseEvent.HSCROLL_RIGHT)
        self.assertEqual(hscroll_event_type(-0.5), MouseEvent.HSCROLL_LEFT)


class HookSourcesUseTheSharedMappingTests(unittest.TestCase):
    """Platform hooks can't be imported off their own OS, so check the source."""

    def test_every_hook_imports_the_helper(self):
        for name, path in HOOK_SOURCES.items():
            with self.subTest(platform=name):
                self.assertIn("hscroll_event_type", path.read_text(encoding="utf-8"))

    def test_no_hook_hardcodes_a_direction_from_a_delta_sign(self):
        for name, path in HOOK_SOURCES.items():
            source = path.read_text(encoding="utf-8")
            with self.subTest(platform=name):
                self.assertNotIn("MouseEvent(MouseEvent.HSCROLL_LEFT", source)
                self.assertNotIn("MouseEvent(MouseEvent.HSCROLL_RIGHT", source)


if __name__ == "__main__":
    unittest.main()
