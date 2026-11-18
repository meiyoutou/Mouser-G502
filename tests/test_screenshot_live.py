"""Synthetic, isolated live-selection tests; no desktop or clipboard access."""
import unittest
from unittest.mock import Mock, patch
import ctypes

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from ui.locale_manager import LocaleManager
from ui.screenshot_common import SCREENSHOT_FULL_CLIP
from ui.screenshot_editor import Annotation
from ui.screenshot_editor_check import CheckClipboard
from ui.screenshot_live import live_pane_region
from ui.screenshot_overlay import IntRect
from ui.screenshot_session import ScreenshotSession
from ui.windows_screenshot import VirtualCapture, MonitorMap


def frame(color="white"):
    bounds = IntRect(0, 0, 500, 400)
    return VirtualCapture(Image.new("RGB", (500, 400), color), bounds,
                          (MonitorMap(bounds, bounds),))


class LiveSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self):
        self.clipboard = CheckClipboard()
        self.capture = Mock(return_value=frame("red"))
        session = ScreenshotSession(frame(), SCREENSHOT_FULL_CLIP,
            locale=LocaleManager("zh_CN"), live_capture=self.capture,
            clipboard_factory=lambda: self.clipboard)
        self.addCleanup(self.app.processEvents)
        self.addCleanup(session.close)
        session._start, session._current = QPoint(50, 50), QPoint(350, 250)
        with patch("ui.screenshot_scroll.exclude_capture_window", return_value=True):
            session.show()
        return session

    def test_mask_is_real_hole_but_keeps_controls_and_outside(self):
        s = self.make()
        pane = s._panes[0]
        self.assertTrue(s._live)
        self.assertFalse(pane.mask().contains(QPoint(100, 100)))
        self.assertTrue(pane.mask().contains(QPoint(51, 51)))
        self.assertTrue(pane.mask().contains(QPoint(10, 10)))
        self.assertIsNone(self.clipboard.image)
        self.capture.assert_not_called()
        self.assertIsNone(s._keyboard_grab_pane)

    def test_mixed_screen_logical_hole_has_no_extra_monitor_seam(self):
        selected = QRect(-160, 20, 400, 180)
        left, right = QRect(-200, 0, 200, 200), QRect(0, 0, 400, 400)
        self.assertFalse(live_pane_region(left, selected).contains(QPoint(199, 100)))
        self.assertFalse(live_pane_region(right, selected).contains(QPoint(0, 100)))
        self.assertTrue(live_pane_region(left, selected).contains(QPoint(41, 21)))

    def test_wholly_inside_monitor_pane_is_hidden_not_empty_unmasked(self):
        s = self.make()
        s._start, s._current = QPoint(-100, -100), QPoint(600, 500)
        s._update_panes()
        self.assertTrue(s._panes[0].isHidden())
        self.assertIn(s._panes[0], s._live_hidden)
        s._set_live(False)
        self.assertFalse(s._panes[0].isHidden())
        self.assertTrue(s._panes[0].mask().isEmpty())

    def test_native_copy_enter_undo_and_save_are_never_image_shortcuts(self):
        s = self.make()
        for key, modifiers in ((Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier),
                               (Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier),
                               (Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier),
                               (Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier)):
            for widget in (s, s.toolbar):
                event = QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers)
                widget.keyPressEvent(event)
                self.assertFalse(event.isAccepted())
        self.capture.assert_not_called()
        self.assertIsNone(self.clipboard.image)
        self.assertFalse(s._completed)
        self.assertFalse(s._closing)

    def test_image_button_recaptures_current_pixels_not_initial_frame(self):
        s = self.make()
        self.assertTrue(s.copy_image())
        self.capture.assert_called_once()
        self.assertEqual(self.clipboard.image.pixelColor(20, 20).name(), "#ff0000")
        self.assertEqual(self.clipboard.image.width(), 301)
        self.assertTrue(s._live)

    def test_switch_to_hand_recaptures_and_freezes_then_select_reopens(self):
        s = self.make()
        s.toolbar.buttons["hand"].click()
        self.assertFalse(s._live)
        self.assertFalse(s.toolbar.native_selection)
        self.assertTrue(s._panes[0].mask().isEmpty())
        self.capture.assert_called_once()
        self.assertEqual(s.document.render().pixelColor(100, 100).name(), "#ff0000")
        s.toolbar.buttons["select"].click()
        self.assertTrue(s._live)
        self.assertFalse(s._panes[0].mask().contains(QPoint(100, 100)))

    def test_marks_are_not_deleted_or_hidden_by_live_selection(self):
        s = self.make()
        s.toolbar.buttons["pen"].click()
        mark = Annotation("arrow", ((80, 80), (150, 150)))
        s.document.add(mark)
        s._refresh_images()
        s.toolbar.buttons["select"].click()
        self.assertFalse(s._live)
        self.assertEqual(s.document.annotations, (mark,))
        self.assertIn("已有标注", s.toolbar.note.text())
        s._history(False)
        self.assertTrue(s._live)

    def test_failed_or_changed_capture_cancels_output_and_closes_hole(self):
        for result in (OSError("test"), VirtualCapture(frame().image, IntRect(0, 0, 501, 400),
                                                      frame().monitor_maps)):
            s = self.make()
            if isinstance(result, Exception):
                self.capture.side_effect = result
            else:
                self.capture.return_value = result
            self.assertFalse(s.copy_image())
            self.assertFalse(s._live)
            self.assertFalse(s._live_ready)
            self.assertIsNone(self.clipboard.image)
            self.assertTrue(s._panes[0].mask().isEmpty())
            self.assertIn("取消本次输出", s.toolbar.note.text())

    def test_unavailable_capture_exclusion_never_opens_live_hole(self):
        s = ScreenshotSession(frame(), SCREENSHOT_FULL_CLIP, full=True, live_capture=lambda: frame())
        self.addCleanup(s.close)
        with patch("ui.screenshot_scroll.exclude_capture_window", return_value=False):
            s.show()
        self.assertFalse(s._live)
        self.assertTrue(s._panes[0].mask().isEmpty())

    def test_language_and_explicit_image_labels(self):
        s = self.make()
        self.assertIn("图片", s.toolbar.buttons["done"].toolTip())
        self.assertIn("在框内选择原文", s._actions["select"].toolTip())
        for language, text in (("en", "current image"), ("zh_TW", "目前圖片")):
            s.locale.setLanguage(language)
            self.assertIn(text, s.toolbar.buttons["done"].toolTip())
        s.close()
        self.assertIsNone(s._live_escape)
        self.assertFalse(s._live)

    def test_drag_toolbar_moves_only_toolbar_and_survives_relayout(self):
        s = self.make()
        toolbar = s.toolbar
        before, selected = toolbar.pos(), s._selection_global_rect()
        start = toolbar.mapToGlobal(QPoint(2, 2))
        for kind, point in ((QMouseEvent.Type.MouseButtonPress, start),
                            (QMouseEvent.Type.MouseMove, start+QPoint(15, 20)),
                            (QMouseEvent.Type.MouseButtonRelease, start+QPoint(15, 20))):
            QApplication.sendEvent(toolbar, QMouseEvent(
                kind, QPointF(toolbar.mapFromGlobal(point)), QPointF(point),
                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier))
        self.assertTrue(toolbar.user_positioned)
        moved = toolbar.pos()
        self.assertNotEqual(before, moved)
        s._place_toolbar()
        self.assertEqual(toolbar.pos(), moved)
        self.assertEqual(s._selection_global_rect(), selected)
        self.assertTrue(s._live)
        self.capture.assert_not_called()

    def test_native_escape_message_uses_windows_msg_handle_field(self):
        from ctypes import wintypes as w
        from ui.screenshot_live import LiveEscape
        callback = Mock()
        escape = LiveEscape(123, callback)
        message = w.MSG()
        message.hWnd, message.message, message.wParam = 123, 0x0312, escape.HOTKEY
        self.assertEqual(escape.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(message)), (True, 0))
        self.app.processEvents()
        callback.assert_called_once()

    def test_source_disappearance_closes_hole_without_copy_or_recapture(self):
        s = self.make()
        with patch("ui.screenshot_live.source_window_valid", return_value=False):
            s._check_live_source()
        self.assertFalse(s._live)
        self.assertFalse(s._source_timer.isActive())
        self.assertIn("已暂停框内交互", s.toolbar.note.text())
        self.capture.assert_not_called()
        self.assertIsNone(self.clipboard.image)


if __name__ == "__main__":
    unittest.main()
