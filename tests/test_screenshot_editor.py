"""Synthetic-only screenshot editing regressions; never capture a real desktop."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

from ui.locale_manager import LocaleManager
from ui.screenshot_common import (
    SCREENSHOT_FULL_CLIP, SCREENSHOT_FULL_FILE, SCREENSHOT_REGION_CLIP,
    SCREENSHOT_REGION_FILE, pil_image_to_qimage,
)
from ui.screenshot_editor import (
    Annotation, ScreenshotCanvas, ScreenshotDocument, ScreenshotEditor,
    ScreenshotPin, rect_handles, resize_selection,
)
from ui.screenshot_overlay import IntRect, RegionSelectionOverlay
from ui.windows_screenshot import (
    MonitorMap, VirtualCapture, WindowsScreenshotController, crop_logical_region,
)


def source_image():
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            image.setPixelColor(x, y, QColor(x % 256, y % 256, (x + y) % 256))
    return image


class ScreenshotEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def close_controller(self, controller):
        if controller._editor is not None:
            controller._editor.close()
        for pin in list(controller._pins):
            pin.close()
        self.app.processEvents()

    def scroll_editor(self, action=SCREENSHOT_REGION_CLIP, *, path_factory=None):
        controller = WindowsScreenshotController(path_factory=path_factory)
        controller._edit_this_capture = True
        controller._scroll_session = object()
        self.addCleanup(self.close_controller, controller)
        source = Image.new("RGB", (320, 2400), "#d8e6f4")
        with patch.object(controller, "_deliver_image") as immediate_output:
            controller._finish_scroll(source, action)
            immediate_output.assert_not_called()
        self.assertIsNone(controller._scroll_session)
        self.assertIsNotNone(controller._editor)
        return controller, controller._editor, source

    def test_long_capture_opens_editor_before_any_clipboard_or_file_output(self):
        for action in (SCREENSHOT_REGION_CLIP, SCREENSHOT_FULL_CLIP,
                       SCREENSHOT_REGION_FILE, SCREENSHOT_FULL_FILE):
            with self.subTest(action=action):
                controller, editor, source = self.scroll_editor(action)
                self.assertEqual(editor.document.base, pil_image_to_qimage(source).convertToFormat(
                    QImage.Format.Format_RGB32))
                self.assertEqual(editor.action_id, action)
                self.assertTrue({"arrow", "rect", "mosaic", "pin", "done"} <= set(editor._actions))
                with patch("ui.windows_screenshot.capture_virtual_desktop") as capture:
                    controller._handle_request(SCREENSHOT_REGION_CLIP)
                    capture.assert_not_called()
                editor.close()
                self.assertIsNone(controller._editor)

    def test_long_capture_annotation_and_checkmark_copy_only_edited_pixels_once(self):
        controller, editor, _ = self.scroll_editor()
        copied = []
        from types import SimpleNamespace
        editor.clipboard_factory = lambda: SimpleNamespace(setImage=lambda image: copied.append(image.copy()))
        editor.document.add(Annotation("redact", ((30, 50), (100, 120)), color="#000000"))
        expected = editor.document.render()
        self.assertEqual(expected.pixelColor(50, 80), QColor("black"))
        self.assertEqual(copied, [])
        editor._actions["done"].trigger()
        self.assertEqual(copied, [expected])
        self.assertIsNone(controller._editor)
        self.assertEqual(controller._pins, [])

    def test_long_capture_pin_uses_edited_full_resolution_and_releases_editor(self):
        controller, editor, _ = self.scroll_editor()
        editor.document.add(Annotation("redact", ((30, 50), (100, 120)), color="#000000"))
        expected = editor.document.render()
        editor._actions["pin"].trigger()
        self.assertIsNone(controller._editor)
        self.assertEqual(len(controller._pins), 1)
        pin = controller._pins[0]
        self.assertEqual(pin.image, expected)
        self.assertEqual(pin.image.size(), editor.document.base.size())
        self.assertTrue(pin.isVisible())
        self.assertEqual(pin.drag_handle.cursor().shape(), Qt.CursorShape.OpenHandCursor)
        pin.close()
        self.assertEqual(controller._pins, [])

    def test_long_capture_file_action_waits_for_editor_checkmark(self):
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "edited-long-capture.png"
            controller, editor, _ = self.scroll_editor(SCREENSHOT_REGION_FILE, path_factory=lambda: target)
            self.assertFalse(target.exists())
            editor.document.add(Annotation("redact", ((30, 50), (100, 120)), color="#000000"))
            expected = editor.document.render()
            editor._actions["done"].trigger()
            self.assertIsNone(controller._editor)
            self.assertEqual(QImage(str(target)), expected)

    def test_long_capture_direct_output_remains_available_when_editing_disabled(self):
        controller = WindowsScreenshotController()
        source = Image.new("RGB", (320, 2400), "#d8e6f4")
        controller._edit_this_capture = False
        controller._scroll_session = object()
        with patch.object(controller, "_deliver_image") as output:
            controller._finish_scroll(source, SCREENSHOT_REGION_CLIP)
            output.assert_called_once_with(source, SCREENSHOT_REGION_CLIP)
        self.assertIsNone(controller._scroll_session)
        self.assertIsNone(controller._editor)

    def test_all_tools_render_and_original_is_unchanged(self):
        base = source_image()
        for tool in ("rect", "ellipse", "arrow", "pen", "text", "number", "mosaic", "redact"):
            with self.subTest(tool=tool):
                doc = ScreenshotDocument(base)
                doc.add(Annotation(tool, ((20, 20), (110, 90)), text="中文 ABC 123"))
                self.assertNotEqual(doc.render(), base)
                self.assertEqual(doc.base, base)
                self.assertEqual(doc.render(), doc.render())

    def test_crop_is_exactly_rendered_pixels_including_mosaic(self):
        doc = ScreenshotDocument(source_image())
        doc.add(Annotation("mosaic", ((20, 20), (180, 140)), block=20))
        doc.add(Annotation("text", ((5, 5),), text="测试"))
        before = doc.render()
        rect = QRect(37, 33, 72, 50)
        doc.set_crop(rect)
        self.assertEqual(doc.render(), before.copy(rect))
        self.assertEqual(doc.render().size(), rect.size())

    def test_crop_and_annotation_undo_redo_and_branch(self):
        doc = ScreenshotDocument(source_image())
        original = doc.render()
        doc.set_crop(QRect(10, 20, 100, 100))
        cropped = doc.render()
        doc.add(Annotation("rect", ((20, 30), (90, 80))))
        marked = doc.render()
        doc.undo()
        self.assertEqual(doc.render(), cropped)
        doc.undo()
        self.assertEqual(doc.render(), original)
        doc.redo()
        doc.redo()
        self.assertEqual(doc.render(), marked)
        doc.undo()
        doc.add(Annotation("arrow", ((30, 40), (80, 90))))
        self.assertFalse(doc.redo())

    def test_crop_clamps_and_rejects_empty(self):
        doc = ScreenshotDocument(source_image())
        self.assertFalse(doc.set_crop(QRect(10, 10, 0, 0)))
        self.assertFalse(doc.set_crop(QRect(1000, 1000, 10, 10)))
        self.assertTrue(doc.set_crop(QRect(-5, -10, 50, 80)))
        self.assertEqual(doc.crop, QRect(0, 0, 45, 70))

    def test_scaled_canvas_coordinates_include_crop_origin(self):
        doc = ScreenshotDocument(source_image())
        doc.set_crop(QRect(100, 50, 100, 80))
        canvas = ScreenshotCanvas(doc)
        for scale in (.5, 1, 1.25, 1.5, 2):
            canvas.set_scale(scale)
            self.assertEqual(canvas.image_point(QPointF(25 * scale, 20 * scale)), QPointF(125, 70))
            self.assertEqual(canvas.image_point(QPointF(-10, -10)), QPointF(100, 50))
        canvas.close()

    def test_mixed_dpi_negative_origin_output_opens_same_editor_pixels(self):
        capture = VirtualCapture(
            Image.new("RGB", (500, 200), (12, 34, 56)),
            IntRect(-200, 0, 300, 200),
            (MonitorMap(IntRect(-100, 0, 0, 100), IntRect(-200, 0, 0, 200)),
             MonitorMap(IntRect(0, 0, 200, 100), IntRect(0, 0, 300, 150))),
        )
        crop = crop_logical_region(capture, IntRect(-30, 10, 80, 70))
        doc = ScreenshotDocument(pil_image_to_qimage(crop))
        self.assertEqual(doc.render(), pil_image_to_qimage(crop).convertToFormat(QImage.Format.Format_RGB32))
        self.assertEqual(doc.render().width(), 180)

    def test_eight_crop_handles_keep_selection_in_image(self):
        bounds = QRectF(0, 0, 320, 180)
        selection = QRectF(50, 30, 100, 80)
        self.assertEqual(len(rect_handles(selection)), 8)
        for handle in range(8):
            result = resize_selection(selection, handle, QPointF(-100, 1000), bounds)
            self.assertTrue(bounds.contains(result))

    def test_redaction_flattens_opaque_exact_color_without_source_metadata(self):
        doc = ScreenshotDocument(source_image())
        doc.add(Annotation("redact", ((20, 20), (90, 70)), color="#000000"))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "redacted.png"
            self.assertTrue(doc.render().save(str(target), "PNG"))
            exported = QImage(str(target))
            for point in (QPoint(20, 20), QPoint(50, 50), QPoint(89, 69)):
                self.assertEqual(exported.pixelColor(point), QColor("#000000"))
            self.assertEqual(exported.textKeys(), [])
            self.assertNotEqual(exported, doc.base)

    def test_editor_exports_exact_preview_and_does_not_recapture(self):
        statuses = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "shot.png"
            editor = ScreenshotEditor(source_image(), SCREENSHOT_REGION_FILE,
                                      path_factory=lambda: path, status_callback=statuses.append,
                                      locale=LocaleManager("zh_CN"))
            editor.document.add(Annotation("redact", ((10, 10), (80, 80))))
            editor.canvas.refresh()
            expected = editor.canvas._display_image
            with patch("ui.windows_screenshot.capture_virtual_desktop") as grab:
                self.assertTrue(editor.save_image())
                grab.assert_not_called()
            self.assertEqual(QImage(str(path)), expected)
            self.assertIn("截图已保存", statuses[-1])
            pin_images = []
            editor.pinRequested.connect(pin_images.append)
            editor.pin_image()
            self.assertEqual(pin_images[0], expected)
            self.app.processEvents()

    def test_editor_live_language_switch_and_tools_present(self):
        locale = LocaleManager("zh_CN")
        editor = ScreenshotEditor(source_image(), SCREENSHOT_FULL_CLIP, locale=locale)
        self.assertEqual(editor._actions["mosaic"].text(), "马赛克")
        self.assertEqual(editor._actions["pin"].text(), "贴图")
        locale.setLanguage("en")
        self.assertEqual(editor._actions["mosaic"].text(), "Mosaic")
        locale.setLanguage("zh_TW")
        self.assertEqual(editor._actions["save"].text(), "儲存")
        editor.close()
        self.app.processEvents()

    def test_cancel_never_writes_or_copies(self):
        editor = ScreenshotEditor(source_image(), SCREENSHOT_FULL_CLIP)
        with patch.object(editor, "copy_image") as copy, patch.object(editor, "save_image") as save:
            editor.close()
            copy.assert_not_called()
            save.assert_not_called()
        self.app.processEvents()

    def test_failed_save_keeps_editor_available(self):
        editor = ScreenshotEditor(source_image(), SCREENSHOT_REGION_FILE,
                                  path_factory=lambda: (_ for _ in ()).throw(OSError("test failure")))
        self.assertFalse(editor.save_image())
        self.assertFalse(editor._completed)
        self.assertIn("test failure", editor.hint.text())
        editor.close()
        self.app.processEvents()

    def test_finish_dispatches_original_clipboard_or_file_action(self):
        for action, output in ((SCREENSHOT_FULL_CLIP, "copy_image"), (SCREENSHOT_REGION_FILE, "save_image")):
            editor = ScreenshotEditor(source_image(), action)
            with patch.object(editor, output, return_value=True) as deliver:
                editor.finish()
                deliver.assert_called_once()
            self.app.processEvents()

    def test_canvas_mouse_stroke_history_and_crop_interaction(self):
        doc = ScreenshotDocument(source_image())
        canvas = ScreenshotCanvas(doc)
        canvas.show()
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(20, 20))
        QTest.mouseMove(canvas, QPoint(80, 80))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
        self.assertEqual(len(doc.annotations), 1)
        # Legacy programmatic crop is separate from the visible pointer tool.
        canvas.set_tool("crop")
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        QTest.mouseMove(canvas, QPoint(130, 130))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(130, 130))
        self.assertEqual(canvas.selection, QRectF(30, 30, 100, 100))
        canvas.apply_crop()
        self.assertEqual(doc.crop, QRect(30, 30, 100, 100))
        canvas.close()

    def test_default_pointer_click_and_drag_never_create_or_apply_crop(self):
        from ui.screenshot_editor_check import CheckClipboard
        clipboard = CheckClipboard()
        editor = ScreenshotEditor(source_image(), SCREENSHOT_FULL_CLIP,
                                  clipboard_factory=lambda: clipboard)
        self.addCleanup(editor.close)
        canvas = editor.canvas
        canvas.show()
        crop = QRect(editor.document.crop)
        pixels = editor.document.render()
        self.assertEqual(canvas.tool, "select")
        self.assertEqual(canvas.cursor().shape(), Qt.CursorShape.ArrowCursor)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=QPoint(40, 40))
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
        QTest.mouseMove(canvas, QPoint(130, 130))
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, pos=QPoint(130, 130))
        self.assertIsNone(canvas.selection)
        self.assertEqual(editor.document.crop, crop)
        self.assertEqual(editor.document.render(), pixels)
        self.assertEqual(editor.document.annotations, ())
        self.assertFalse(editor._actions["crop"].isEnabled())
        editor._invoke("copy")
        self.assertEqual(clipboard.image, pixels)
        self.assertEqual(editor.document.crop, crop)

    def test_frozen_overlay_paints_snapshot_not_live_transparency(self):
        image = QImage(100, 80, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        overlay = RegionSelectionOverlay(IntRect(0, 0, 100, 80),
                                         frozen_images=[image], confirm_on_release=True)
        overlay._start, overlay._current = QPoint(20, 20), QPoint(60, 60)
        rendered = overlay._panes[0].grab().toImage()
        self.assertEqual(rendered.pixelColor(40, 40), QColor("red"))
        self.assertLess(rendered.pixelColor(5, 5).red(), 255)
        overlay.close()

    def test_overlay_release_waits_for_enter_and_cancel_releases_capture(self):
        overlay = RegionSelectionOverlay(IntRect(0, 0, 100, 80), confirm_on_release=True)
        selected = []
        overlay.selected.connect(selected.append)
        pane = overlay._panes[0]
        overlay._start, overlay._current = QPoint(20, 20), QPoint(60, 60)
        overlay._mouse_grab_pane = pane
        event = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(60, 60), QPointF(60, 60),
                            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        overlay._pane_mouse_release_event(event)
        self.assertEqual(selected, [])
        overlay.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(len(selected), 1)
        self.assertIsNone(overlay._mouse_grab_pane)

    def test_direct_output_mode_does_not_construct_editor(self):
        controller = WindowsScreenshotController(editor_enabled=lambda: False)
        with patch.object(controller, "_deliver_image") as delivery:
            controller._edit_this_capture = False
            image = Image.new("RGB", (100, 80))
            controller._edit_or_deliver(image, SCREENSHOT_FULL_CLIP)
            delivery.assert_called_once_with(image, SCREENSHOT_FULL_CLIP)
        self.assertIsNone(controller._editor)

    def test_controller_edit_mode_busy_and_close_lifecycle(self):
        controller = WindowsScreenshotController(editor_enabled=lambda: True, locale=LocaleManager("zh_CN"))
        controller._edit_this_capture = True
        image = Image.new("RGB", (100, 80))
        with patch.object(controller, "_deliver_image") as delivery:
            controller._edit_or_deliver(image, SCREENSHOT_FULL_CLIP)
            self.assertIsNotNone(controller._editor)
            controller._handle_request(SCREENSHOT_FULL_CLIP)
            delivery.assert_not_called()
            controller._editor.close()
        self.assertIsNone(controller._editor)
        self.app.processEvents()

    def test_pin_is_focusless_and_closed_pin_is_released(self):
        controller = WindowsScreenshotController()
        controller._pin_image(source_image())
        pin = controller._pins[0]
        self.assertTrue(pin.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertTrue(pin.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertEqual(pin.image, source_image())
        pin.close()
        self.assertEqual(controller._pins, [])
        self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
