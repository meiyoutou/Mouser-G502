"""Frozen text selection and component safety; no desktop or system clipboard."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from core import text_selection
from ui.screenshot_text_layer import FrozenTextLayer, logical_fragments
from ui.screenshot_editor import Annotation, ScreenshotEditor
from ui.locale_manager import LocaleManager
from ui.screenshot_locale import SCREENSHOT_TRANSLATIONS
from ui.screenshot_toolbar import CaptureToolbar, tool_icon
from tests import test_screenshot_session as helpers


def glyphs():
    return [
        {"text": "你", "prefix": "", "box": [35, 40, 55, 60]},
        {"text": "好", "prefix": "", "box": [56, 40, 76, 60]},
        {"text": "A", "prefix": " ", "box": [90, 40, 105, 60]},
        {"text": "B", "prefix": "", "box": [106, 40, 121, 60]},
        {"text": "下", "prefix": "\n", "box": [35, 80, 55, 100]},
    ]


class LayerTests(unittest.TestCase):
    def test_select_text_and_reverse_drag_keep_newlines(self):
        layer = FrozenTextLayer(glyphs(), QPointF(0, 0))
        self.assertTrue(layer.begin(QPointF(36, 45)))
        layer.extend(QPointF(120, 45))
        self.assertEqual(layer.selected_text(), "你好 AB")
        self.assertEqual(len(layer.selected_boxes()), 4)
        layer.begin(QPointF(54, 90))
        layer.extend(QPointF(36, 45))
        self.assertEqual(layer.selected_text(), "你好 AB\n下")

    def test_hit_requires_actual_box_and_blank_click_clears(self):
        layer = FrozenTextLayer(glyphs(), QPointF(0, 0))
        self.assertIsNone(layer.hit(QPointF(80, 45)))
        layer.select_all()
        self.assertFalse(layer.begin(QPointF(80, 45)))
        self.assertEqual(layer.selected_text(), "")
        self.assertFalse(layer.begin(None))

    def test_origin_and_mixed_dpi_coordinates(self):
        layer = FrozenTextLayer(glyphs(), QPointF(240, 20))
        self.assertEqual(layer.hit(QPointF(280, 65)), 0)
        capture = helpers.capture()
        self.assertEqual(list(logical_fragments(QRectF(300, 40, 40, 20), capture)),
                         [QRectF(-50, 20, 20, 10)])
        self.assertEqual(list(logical_fragments(QRectF(420, 40, 40, 20), capture)),
                         [QRectF(20, 40, 40, 20)])
        pieces = list(logical_fragments(QRectF(390, 40, 20, 20), capture))
        self.assertEqual(pieces, [QRectF(-5, 20, 5, 10), QRectF(0, 40, 10, 20)])

    def test_bad_manifest_and_traversal_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "manifest.json"
            path.write_text(json.dumps({"files": {"../evil.pyd": "x"}}))
            asset = {"manifest_sha256": text_selection.digest(path)}
            with patch.object(text_selection, "catalog", return_value=asset):
                self.assertIsNone(text_selection.checked_runtime(root))
            path.write_text("{}")
            with patch.object(text_selection, "catalog", return_value=asset):
                self.assertIsNone(text_selection.checked_runtime(root))

    def test_worker_unicode_directory_uses_relative_native_path_and_skips_empty_blocks(self):
        from PIL import Image
        from core.text_selection_worker import recognize
        original = Path.cwd()
        calls = []
        iterator = MagicMock()
        iterator.GetUTF8Text.side_effect = RuntimeError("No text returned")
        iterator.Next.return_value = False
        engine = MagicMock()
        engine.__enter__.return_value = engine
        engine.GetIterator.return_value = iterator
        def create(**kwargs):
            calls.append((Path.cwd(), kwargs))
            return engine
        module = SimpleNamespace(PyTessBaseAPI=create, OEM=SimpleNamespace(LSTM_ONLY=1),
                                 PSM=SimpleNamespace(AUTO=3), RIL=SimpleNamespace(SYMBOL=4))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "中文可选组件"
            (root / "tessdata").mkdir(parents=True)
            (root / "tesserocr").mkdir()
            image = root / "空白.png"
            Image.new("RGB", (20, 20), "white").save(image)
            try:
                with patch("core.text_selection.checked_runtime", return_value=root), \
                        patch.dict(sys.modules, {"tesserocr": module}):
                    result = recognize(image, root)
                self.assertEqual(result["glyphs"], [])
                self.assertEqual(calls[0][0], root / "tessdata")
                self.assertEqual(calls[0][1]["path"], ".")
            finally:
                os.chdir(original)

    def test_child_cancellation_and_timeout_keep_specific_error(self):
        from PySide6.QtGui import QImage
        for cancelled, clock, reason in (
                (SimpleNamespace(is_set=lambda: True), [0, 0], "text_select_cancelled"),
                (None, [0, 61], "text_select_timeout")):
            process = MagicMock()
            process.poll.return_value = None
            image = QImage(20, 20, QImage.Format.Format_RGB32)
            image.fill(Qt.GlobalColor.white)
            with patch.object(text_selection, "checked_runtime", return_value=Path(".")), \
                    patch.object(text_selection.subprocess, "Popen", return_value=process), \
                    patch.object(text_selection.time, "monotonic", side_effect=clock):
                with self.assertRaisesRegex(text_selection.TextSelectionError, reason):
                    text_selection.recognize(image, cancelled=cancelled)
            process.terminate.assert_called_once()


class SessionTests(unittest.TestCase):
    make, select, drag, event = (helpers.SessionTests.make, helpers.SessionTests.select,
                                 helpers.SessionTests.drag, helpers.SessionTests.event)

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def recognized(self):
        s = self.make()
        self.select(s)
        s._text_layer = FrozenTextLayer(glyphs(), QPointF(400, 0))
        return s

    def test_one_localized_menu_entry_distinct_icon_and_no_old_entry(self):
        locale = LocaleManager("zh_CN")
        toolbar = CaptureToolbar(locale, scroll_enabled=True)
        self.addCleanup(toolbar.close)
        for language, label in (("zh_CN", "文字选择"), ("en", "Text selection"),
                                ("zh_TW", "文字選取")):
            locale.setLanguage(language)
            action = toolbar.actions["text_select"]
            self.assertEqual(action.text(), label)
            self.assertEqual(sum(a.text() == label for a in toolbar.more.actions()), 1)
            self.assertFalse(action.icon().isNull())
            self.assertTrue(action.isIconVisibleInMenu())
            self.assertNotIn("text_select", toolbar.buttons)
            self.assertNotIn("ocr", toolbar.actions)
            self.assertNotIn("ocr_install", toolbar.actions)
        icon = tool_icon("text_select").pixmap(QSize(22, 22)).toImage()
        for key in ("select", "text", "help"):
            self.assertNotEqual(icon, tool_icon(key).pixmap(QSize(22, 22)).toImage())
        for strings in SCREENSHOT_TRANSLATIONS.values():
            self.assertFalse(any("ocr" in key.lower() or "ocr" in value.lower()
                                 for key, value in strings.items()))

    def test_removed_implementation_and_packaging_files_do_not_exist(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("core/ocr_components.py", "core/ocr_worker.py",
                     "core/ocr_component_assets.json", "ui/screenshot_ocr.py",
                     "MouserOCR.spec", "scripts/package_ocr_runtime.py"):
            self.assertFalse((root / name).exists(), name)

    def test_drag_copy_does_not_change_frozen_pixels_or_crop(self):
        s = self.recognized()
        original, crop = s._output_image(), s._selection_global_rect()
        self.drag(s, QPoint(36, 45), QPoint(120, 45))
        self.assertEqual(s._text_layer.selected_text(), "你好 AB")
        s.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_C,
                                 Qt.KeyboardModifier.ControlModifier))
        self.assertEqual(self.clipboard.text, "你好 AB")
        self.assertIsNone(self.clipboard.image)
        self.assertEqual(s._output_image(), original)
        self.assertEqual(s._selection_global_rect(), crop)
        self.assertTrue(all(p.mask().isEmpty() for p in s._panes))
        self.assertFalse(s._live)

    def test_ibeam_only_over_text_not_blank_space(self):
        s = self.recognized()
        s._pointer = QPoint(45, 50)
        s._refresh_cursors()
        self.assertEqual(s._panes[1].cursor().shape(), Qt.CursorShape.IBeamCursor)
        s._pointer = QPoint(82, 50)
        s._refresh_cursors()
        self.assertEqual(s._panes[1].cursor().shape(), Qt.CursorShape.ArrowCursor)

    def test_select_all_and_menu_copy_text_not_image(self):
        s = self.recognized()
        s.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A,
                                 Qt.KeyboardModifier.ControlModifier))
        s._invoke("copy")
        self.assertEqual(self.clipboard.text, "你好 AB\n下")
        self.assertIsNone(self.clipboard.image)
        s._text_layer.clear()
        s._invoke("copy")
        self.assertIsNone(self.clipboard.image)

    def test_finish_still_copies_image_and_has_no_text_overlay(self):
        s = self.recognized()
        image = s._output_image()
        s._text_layer.select_all()
        s.finish()
        self.assertEqual(self.clipboard.image, image)
        self.assertIsNone(self.clipboard.text)

    def test_hand_invalidates_old_coordinates_and_stays_frozen(self):
        s = self.recognized()
        s.toolbar.buttons["hand"].click()
        self.drag(s, QPoint(130, 130), QPoint(150, 150))
        self.assertIsNone(s._text_layer)
        self.assertFalse(s._live)
        self.assertEqual(s.tool, "hand")

    def test_annotations_invalidate_text_and_are_used_as_selection_input(self):
        s = self.recognized()
        s.document.add(Annotation("redact", ((430, 30), (535, 110)), color="#000000"))
        s._refresh_images()
        self.assertIsNone(s._text_layer)
        images = []
        with patch("core.text_selection.checked_runtime", return_value=Path(".")), \
                patch("ui.screenshot_text_selection.TextSelectionController.start",
                      lambda controller, image: images.append(image.copy())):
            s._start_text_selection()
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0], s._output_image())
        self.assertEqual(images[0].pixelColor(20, 20).name(), "#000000")
        controller = s._selection_worker
        s._invalidate_text_layer()
        controller.result.emit({"glyphs": glyphs()})
        self.assertIsNone(s._text_layer)
        self.assertTrue(controller.cancelled.is_set())

    def test_no_automatic_recognition_and_no_doubleclick_finish_in_text_mode(self):
        s = self.recognized()
        self.assertIsNone(s._selection_worker)
        pane = s._panes[1]
        s._pane_double_click_event(pane, self.event(QMouseEvent.Type.MouseButtonDblClick, QPoint(45, 50)))
        self.assertFalse(s._closing)
        self.assertIsNone(self.clipboard.image)


class EditorSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self):
        from PySide6.QtGui import QImage
        from ui.screenshot_common import SCREENSHOT_FULL_CLIP
        from ui.screenshot_editor_check import CheckClipboard
        image = QImage(320, 2400, QImage.Format.Format_RGB32)
        image.fill(Qt.GlobalColor.white)
        self.clipboard = CheckClipboard()
        editor = ScreenshotEditor(image, SCREENSHOT_FULL_CLIP, locale=LocaleManager("zh_CN"),
                                  clipboard_factory=lambda: self.clipboard)
        self.addCleanup(editor.close)
        editor.show()
        self.app.processEvents()
        return editor

    def start(self, editor):
        with patch("core.text_selection.checked_runtime", return_value=Path(".")), \
                patch("ui.screenshot_text_selection.TextSelectionController.start") as start:
            editor._invoke("text_select")
            self.assertEqual(start.call_args.args[0], editor._output_image())
        return editor._selection_worker

    def recognize(self, editor):
        worker = self.start(editor)
        self.assertIsNotNone(worker)
        worker.result.emit({"glyphs": glyphs()})
        return editor.canvas.text_layer

    def test_editor_has_one_localized_opt_in_text_selection_entry(self):
        editor = self.make()
        self.assertIsNone(editor._selection_worker)
        for language, label in (("zh_CN", "文字选择"), ("en", "Text selection"), ("zh_TW", "文字選取")):
            editor.locale.setLanguage(language)
            self.assertEqual(editor._actions["text_select"].text(), label)
            self.assertEqual(sum(a is editor._actions["text_select"]
                                 for a in editor.toolbar.more.actions()), 1)

    def test_scaled_drag_and_ctrl_c_copy_text_not_pixels(self):
        from PySide6.QtTest import QTest
        editor = self.make()
        original = editor._output_image()
        layer = self.recognize(editor)
        editor.canvas.set_scale(1.5)
        self.assertIs(editor.canvas.text_layer, layer)
        QTest.mouseMove(editor.canvas, QPoint(68, 75))
        self.assertEqual(editor.canvas.cursor().shape(), Qt.CursorShape.IBeamCursor)
        QTest.mousePress(editor.canvas, Qt.MouseButton.LeftButton, pos=QPoint(54, 68))
        QTest.mouseMove(editor.canvas, QPoint(180, 68))
        QTest.mouseRelease(editor.canvas, Qt.MouseButton.LeftButton, pos=QPoint(180, 68))
        self.assertEqual(layer.selected_text(), "你好 AB")
        QApplication.sendEvent(editor.canvas, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_C,
                                                       Qt.KeyboardModifier.ControlModifier))
        self.assertEqual(self.clipboard.text, "你好 AB")
        self.assertIsNone(self.clipboard.image)
        self.assertEqual(editor._output_image(), original)
        self.assertIsNone(editor.canvas.selection)

    def test_select_all_copy_menu_and_done_still_outputs_clean_image(self):
        editor = self.make()
        original = editor._output_image()
        self.recognize(editor)
        editor.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A,
                                      Qt.KeyboardModifier.ControlModifier))
        editor._invoke("copy")
        self.assertEqual(self.clipboard.text, "你好 AB\n下")
        self.assertIsNone(self.clipboard.image)
        editor._actions["done"].trigger()
        self.assertEqual(self.clipboard.image, original)

    def test_redaction_invalidates_results_and_recognizes_only_flattened_pixels(self):
        editor = self.make()
        self.recognize(editor)
        editor.document.add(Annotation("redact", ((0, 0), (150, 150)), color="#000000"))
        editor.canvas.refresh()
        self.assertIsNone(editor.canvas.text_layer)
        self.start(editor)
        self.assertEqual(editor._output_image().pixelColor(45, 50).name(), "#000000")

    def test_changed_image_and_close_cancel_worker_and_ignore_late_result(self):
        editor = self.make()
        worker = self.start(editor)
        editor.document.add(Annotation("redact", ((0, 0), (150, 150)), color="#000000"))
        editor.canvas.refresh()
        self.assertTrue(worker.cancelled.is_set())
        worker.result.emit({"glyphs": glyphs()})
        self.assertIsNone(editor.canvas.text_layer)
        worker = self.start(editor)
        editor.close()
        self.assertTrue(worker.cancelled.is_set())
        self.assertIsNone(editor._selection_worker)
        worker.result.emit({"glyphs": glyphs()})
        self.assertIsNone(editor.canvas.text_layer)

    def test_missing_and_failed_recognition_leave_editor_usable(self):
        editor = self.make()
        with patch("core.text_selection.checked_runtime", return_value=None):
            editor._invoke("text_select")
        self.assertIsNone(editor._selection_worker)
        self.assertIn("文字选择组件", editor.hint.text())
        worker = self.start(editor)
        worker.status.emit("text_select_failed")
        self.assertIsNone(editor._selection_worker)
        self.assertTrue(editor._actions["text_select"].isEnabled())
        self.assertTrue(editor.copy_image())

    def test_document_crop_origin_and_empty_result_do_not_corrupt_coordinates(self):
        editor = self.make()
        editor.document.set_crop(QRect(20, 30, 200, 300))
        editor.canvas.refresh()
        layer = self.recognize(editor)
        self.assertEqual(layer.boxes[0].topLeft(), QPointF(55, 70))
        editor.canvas.set_scale(1.25)
        point = editor.canvas.image_point(QPointF(45 * 1.25, 50 * 1.25))
        self.assertEqual(layer.hit(point), 0)
        worker = self.start(editor)
        worker.result.emit({"glyphs": []})
        self.assertIsNone(editor.canvas.text_layer)
        self.assertTrue(editor._actions["text_select"].isEnabled())
        self.assertTrue(editor.copy_image())

    def test_zoom_neither_reflattens_image_nor_cancels_pending_recognition(self):
        editor = self.make()
        worker = self.start(editor)
        with patch.object(editor.document, "render", side_effect=AssertionError("zoom must not render")):
            editor.zoom(120)
            editor.zoom(-120)
        self.assertIs(editor._selection_worker, worker)
        self.assertFalse(worker.cancelled.is_set())


if __name__ == "__main__":
    unittest.main()
