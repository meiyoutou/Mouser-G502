"""Generated pixels only: fixed result, hand dragging and original-image copy."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QApplication

from ui.locale_manager import LocaleManager
from ui.screenshot_common import SCREENSHOT_FULL_CLIP, SCREENSHOT_FULL_FILE, pil_image_to_qimage
from ui.screenshot_editor import ScreenshotPin, ScreenshotEditor
from ui.screenshot_editor_check import CheckClipboard
from ui.screenshot_overlay import IntRect
from ui.screenshot_session import ScreenshotSession
from ui.windows_screenshot import MonitorMap, VirtualCapture, WindowsScreenshotController


class FixedScreenshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def image(self, width=320, height=180):
        image = QImage(width, height, QImage.Format.Format_RGB32)
        image.fill(QColor("#c8dff2"))
        image.setPixelColor(width // 2, height // 2, QColor("red"))
        return image

    def pin(self, image=None, locale=None):
        self.clipboard = CheckClipboard()
        pin = ScreenshotPin(image if image is not None else self.image(), locale,
                            clipboard_factory=lambda: self.clipboard)
        pin.show()
        self.app.processEvents()
        self.addCleanup(pin.close)
        return pin

    def test_fixed_result_has_hand_copy_close_and_does_not_steal_focus(self):
        image = self.image()
        pin = self.pin(image)
        self.assertTrue(pin.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertTrue(pin.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertTrue(pin.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertFalse(pin.drag_handle.icon().isNull())
        self.assertFalse(pin.copy_button.icon().isNull())
        self.assertFalse(pin.close_button.icon().isNull())
        self.assertTrue(pin.drag_handle.isVisible())
        self.assertEqual(pin.image, image)

    def test_hand_moves_window_without_modifying_pixels(self):
        pin = self.pin()
        before, image = pin.pos(), pin.image.copy()
        local = QPointF(10, 10)
        start = pin.drag_handle.mapToGlobal(QPoint(10, 10))
        def mouse(kind, point, button, buttons):
            return QMouseEvent(kind, local, QPointF(point), button, buttons,
                               Qt.KeyboardModifier.NoModifier)
        pin.drag_handle.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, start,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
        self.assertEqual(pin.drag_handle.cursor().shape(), Qt.CursorShape.ClosedHandCursor)
        delta = QPoint(73, 41)
        pin.drag_handle.mouseMoveEvent(mouse(QEvent.Type.MouseMove, start + delta,
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
        pin.drag_handle.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, start + delta,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
        self.assertEqual(pin.pos(), before + delta)
        self.assertIsNone(pin._drag_offset)
        self.assertEqual(pin.drag_handle.cursor().shape(), Qt.CursorShape.OpenHandCursor)
        self.assertEqual(pin.image, image)

    def test_long_image_scrolls_instead_of_becoming_an_unreadable_thin_strip(self):
        pin = self.pin(self.image(930, 5991))
        self.assertGreater(pin.view.width(), 200)
        self.assertGreater(pin.view.height(), pin.scroll.viewport().height())
        bar = pin.scroll.verticalScrollBar()
        self.assertGreater(bar.maximum(), 0)
        event = QWheelEvent(QPointF(30, 30), QPointF(pin.scroll.mapToGlobal(QPoint(30, 30))),
            QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
        QApplication.sendEvent(pin.scroll.viewport(), event)
        self.assertGreater(bar.value(), 0)

    def test_copy_remains_full_resolution_without_recognition(self):
        image = self.image(930, 5991)
        pin = self.pin(image)
        pin.scroll.verticalScrollBar().setValue(100)
        pin.zoom(-120)
        self.app.processEvents()
        with patch("ui.screenshot_text_selection.TextSelectionController.start") as selection, \
                patch("ui.windows_screenshot.capture_virtual_desktop") as capture:
            pin.copy_button.click()
            selection.assert_not_called()
            capture.assert_not_called()
        self.assertEqual(self.clipboard.image, image)
        self.assertEqual(self.clipboard.image.size(), image.size())

    def wheel(self, widget, delta, modifiers=Qt.KeyboardModifier.NoModifier, *, point=None, pixel=False):
        point = point or QPoint(40, 40)
        event = QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)),
            QPoint(0, delta) if pixel else QPoint(), QPoint() if pixel else QPoint(0, delta),
            Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.ScrollUpdate, False)
        QApplication.sendEvent(widget, event)
        self.app.processEvents()

    def test_pin_ctrl_wheel_and_buttons_zoom_without_changing_original(self):
        pin = self.pin(self.image(930, 5991))
        original, width = pin.image.copy(), pin.view.width()
        self.wheel(pin.view, 120, Qt.KeyboardModifier.ControlModifier)
        self.assertGreater(pin.view.width(), width)
        self.wheel(pin.scroll.viewport(), -120, Qt.KeyboardModifier.ControlModifier)
        self.assertAlmostEqual(pin.view.width(), width, delta=2)
        pin.zoom_in_button.click()
        self.assertGreater(pin.view.width(), width)
        pin.zoom_out_button.click()
        self.assertAlmostEqual(pin.view.width(), width, delta=2)
        self.assertFalse(pin.resize_grip.isHidden())
        self.assertEqual(pin.image, original)
        self.assertTrue(pin.copy_image())
        self.assertEqual(self.clipboard.image, original)

    def test_plain_wheel_scrolls_pin_without_zooming(self):
        pin = self.pin(self.image(930, 5991))
        width = pin.view.width()
        self.wheel(pin.view, -120)
        self.assertGreater(pin.scroll.verticalScrollBar().value(), 0)
        self.assertEqual(pin.view.width(), width)

    def test_editor_ctrl_wheel_zooms_around_pointer_and_plain_wheel_scrolls(self):
        editor = ScreenshotEditor(self.image(1600, 4000), SCREENSHOT_FULL_CLIP,
                                  clipboard_factory=lambda: CheckClipboard())
        self.addCleanup(editor.close)
        editor.show()
        self.app.processEvents()
        editor.canvas.set_scale(1)
        self.app.processEvents()
        editor.scroll.horizontalScrollBar().setValue(300)
        editor.scroll.verticalScrollBar().setValue(700)
        point = QPoint(180, 130)
        canvas_point = editor.canvas.mapFrom(editor.scroll.viewport(), point)
        before = editor.canvas.image_point(QPointF(canvas_point))
        original = editor._output_image()
        self.wheel(editor.scroll.viewport(), 120, Qt.KeyboardModifier.ControlModifier, point=point)
        after = editor.canvas.image_point(QPointF(editor.canvas.mapFrom(editor.scroll.viewport(), point)))
        self.assertGreater(editor.canvas.scale, 1)
        self.assertAlmostEqual(before.x(), after.x(), delta=2)
        self.assertAlmostEqual(before.y(), after.y(), delta=2)
        scale, position = editor.canvas.scale, editor.scroll.verticalScrollBar().value()
        self.wheel(editor.canvas, -120)
        self.assertGreater(editor.scroll.verticalScrollBar().value(), position)
        self.assertEqual(editor.canvas.scale, scale)
        self.wheel(editor.canvas, 15, Qt.KeyboardModifier.ControlModifier, pixel=True)
        self.assertGreater(editor.canvas.scale, scale)
        self.assertEqual(editor._output_image(), original)
        self.assertIn("zoom_in", editor.toolbar.buttons)
        self.assertIn("zoom_out", editor.toolbar.buttons)

    def test_zoom_controls_follow_language_and_fit_keeps_long_pin_readable(self):
        locale = LocaleManager("zh_CN")
        pin = self.pin(self.image(930, 5991), locale)
        self.assertIn("放大", pin.zoom_in_button.toolTip())
        pin.zoom(480)
        pin.fit_button.click()
        self.app.processEvents()
        self.assertLessEqual(pin.view.width(), pin.scroll.viewport().width())
        self.assertGreater(pin.view.width(), 200)
        locale.setLanguage("en")
        self.assertIn("Zoom", pin.zoom_in_button.toolTip())

    def test_hand_and_close_labels_follow_live_language(self):
        locale = LocaleManager("zh_CN")
        pin = self.pin(locale=locale)
        self.assertEqual(pin.drag_handle.accessibleName(), "拖动小手移动截图")
        locale.setLanguage("en")
        self.assertIn("Drag the hand", pin.drag_handle.toolTip())
        self.assertIn("Close", pin.close_button.toolTip())
        locale.setLanguage("zh_TW")
        self.assertEqual(pin.close_button.toolTip(), "關閉固定截圖")

    def test_close_releases_window_without_copying(self):
        pin = self.pin()
        ended = []
        pin.closed.connect(ended.append)
        pin.close_button.click()
        self.assertEqual(ended, [pin])
        self.assertIsNone(self.clipboard.image)

    def test_clipboard_failure_keeps_fixed_image_available(self):
        pin = self.pin()
        pin.clipboard_factory = lambda: None
        self.assertFalse(pin.copy_image())
        self.assertTrue(pin.isVisible())

    def test_editor_finish_never_automatically_pins(self):
        for action, method in ((SCREENSHOT_FULL_CLIP, "copy_image"), (SCREENSHOT_FULL_FILE, "save_image")):
            for success in (True, False):
                editor = ScreenshotEditor(self.image(), action)
                outputs = []
                editor.pinRequested.connect(outputs.append)
                expected = editor._output_image()
                with patch.object(editor, method, return_value=success):
                    editor.finish()
                self.assertEqual(outputs, [])
                editor.close()

    def test_region_session_finish_copies_without_automatic_pin(self):
        image = Image.new("RGB", (320, 180), "#a7c4d2")
        bounds = IntRect(0, 0, 320, 180)
        capture = VirtualCapture(image, bounds, (MonitorMap(bounds, bounds),))
        clipboard = CheckClipboard()
        session = ScreenshotSession(capture, SCREENSHOT_FULL_CLIP,
                                    clipboard_factory=lambda: clipboard)
        session._start, session._current = QPoint(30, 20), QPoint(150, 100)
        expected = session._output_image()
        outputs = []
        session.pinRequested.connect(outputs.append)
        session.finish()
        self.assertEqual(outputs, [])
        self.assertEqual(clipboard.image, expected)

    def test_long_and_direct_deliveries_do_not_automatically_pin(self):
        image = Image.new("RGB", (320, 900), "#d8e6f4")
        for action in (SCREENSHOT_FULL_CLIP, SCREENSHOT_FULL_FILE):
            controller = WindowsScreenshotController()
            with patch("ui.windows_screenshot.copy_image_to_clipboard") as copy, \
                    patch("ui.windows_screenshot.save_image_to_file", return_value="fake.png") as save, \
                    patch.object(controller, "_pin_image") as pin:
                controller._finish_scroll(image, action)
                pin.assert_not_called()
                (copy if action == SCREENSHOT_FULL_CLIP else save).assert_called_once()

    def test_explicit_pin_is_freely_draggable_from_the_image_itself(self):
        pin = self.pin()
        before = pin.pos()
        start = pin.view.mapToGlobal(QPoint(20, 20))
        def mouse(kind, point, button, buttons):
            return QMouseEvent(kind, QPointF(20, 20), QPointF(point), button, buttons,
                               Qt.KeyboardModifier.NoModifier)
        pin.view.mousePressEvent(mouse(QEvent.Type.MouseButtonPress, start,
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton))
        delta = QPoint(-42, 63)
        pin.view.mouseMoveEvent(mouse(QEvent.Type.MouseMove, start + delta,
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton))
        pin.view.mouseReleaseEvent(mouse(QEvent.Type.MouseButtonRelease, start + delta,
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton))
        self.assertEqual(pin.pos(), before + delta)
        self.assertIsNone(pin._drag_offset)

    def test_failed_delivery_does_not_open_a_result_window(self):
        controller = WindowsScreenshotController()
        with patch("ui.windows_screenshot.copy_image_to_clipboard", side_effect=OSError("test")), \
                patch.object(controller, "_pin_image") as pin:
            controller._deliver_image(Image.new("RGB", (40, 80)), SCREENSHOT_FULL_CLIP)
            pin.assert_not_called()


if __name__ == "__main__":
    unittest.main()
