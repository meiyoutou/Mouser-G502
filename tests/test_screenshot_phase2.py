import os
from pathlib import Path
import random
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageFont
from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from ui.locale_manager import LocaleManager
from ui.screenshot_common import SCREENSHOT_FULL_CLIP
from ui.screenshot_editor import Annotation, ScreenshotEditor
from ui.screenshot_overlay import IntRect, RegionSelectionOverlay
from ui.screenshot_text_selection import TextSelectionController
from ui.screenshot_scroll import ScrollCaptureSession
from ui.screenshot_tools import ScrollStitcher, StitchError, magnifier_patch
from ui.windows_screenshot import MonitorMap, WindowsScreenshotController, physical_to_logical_rects


def content(width=200, height=1800):
    rng = random.Random(1234)
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    for y in range(height):
        for x in range(0, width, 10):
            draw.line((x, y, x + 9, y), fill=tuple(rng.randrange(256) for _ in range(3)))
    return image


def text_content():
    """White document with native-size glyphs, not high-entropy noise rows."""
    font_path = Path(r"C:\Windows\Fonts\arial.ttf")
    font = (ImageFont.truetype(str(font_path), 24) if font_path.exists()
            else ImageFont.load_default(size=24))
    page = Image.new("RGB", (800, 3200), "white")
    draw = ImageDraw.Draw(page)
    for index in range(80):
        y = 28 + index * 38
        draw.text((40, y), f"{index + 1:03d}. Screenshot scrolling content for paragraph {index + 1}.",
                  font=font, fill="#222222")
        if index % 7 == 0:
            draw.rectangle((40, y + 28, 680, y + 30), fill="#999999")
    return page


class Phase2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_analysis(self, session):
        deadline = time.monotonic() + 5
        while session._pending and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)  # Yield the Python GIL to the matching worker.
        self.assertFalse(session._pending, "background stitch timed out")

    def test_stitch_three_frames_exact_no_repeated_overlap(self):
        image = content()
        stitch = ScrollStitcher(image.crop((0, 0, 200, 300)))
        self.assertEqual(stitch.append(image.crop((0, 120, 200, 420))), 120)
        self.assertEqual(stitch.append(image.crop((0, 250, 200, 550))), 130)
        self.assertEqual(stitch.render().tobytes(), image.crop((0, 0, 200, 550)).tobytes())
        self.assertTrue(stitch.undo())
        self.assertEqual(stitch.render().tobytes(), image.crop((0, 0, 200, 420)).tobytes())
        self.assertEqual(stitch.append(image.crop((0, 300, 200, 600))), 180)

    def test_large_viewport_overlap_is_refined_in_original_pixels(self):
        image = content(height=2600)
        stitch = ScrollStitcher(image.crop((0, 0, 200, 1200)))
        self.assertEqual(stitch.append(image.crop((0, 347, 200, 1547))), 347)
        self.assertEqual(stitch.render().tobytes(), image.crop((0, 0, 200, 1547)).tobytes())

    def test_white_text_page_native_overlap_even_for_small_scroll_steps(self):
        page = text_content()
        for shift in (1, 3, 7, 38, 100, 137, 190, 347, 450):
            with self.subTest(shift=shift):
                stitch = ScrollStitcher(page.crop((0, 0, 800, 600)))
                self.assertEqual(stitch.append(page.crop((0, shift, 800, 600 + shift))), shift)
                self.assertEqual(stitch.render().tobytes(),
                                 page.crop((0, 0, 800, 600 + shift)).tobytes())

    def test_native_text_alignment_does_not_depend_on_blurred_gray_sampling(self):
        page = text_content()
        stitch = ScrollStitcher(page.crop((0, 0, 800, 600)))
        # 347px scrolling previously failed despite 253px of exact overlap.
        with patch.object(Image.Image, "resize", side_effect=AssertionError("must compare native rows")):
            self.assertEqual(stitch.append(page.crop((0, 347, 800, 947))), 347)

    def test_text_page_multiple_appends_undo_and_new_branch_keep_exact_pixels(self):
        page = text_content()
        stitch = ScrollStitcher(page.crop((0, 0, 800, 600)))
        last = 0
        for shift in (347, 594, 923):
            self.assertEqual(stitch.append(page.crop((0, shift, 800, shift + 600))), shift - last)
            self.assertEqual(stitch.render().tobytes(), page.crop((0, 0, 800, shift + 600)).tobytes())
            last = shift
        self.assertTrue(stitch.undo())
        self.assertEqual(stitch.render().tobytes(), page.crop((0, 0, 800, 1194)).tobytes())
        self.assertEqual(stitch.append(page.crop((0, 1000, 800, 1600))), 406)
        self.assertEqual(stitch.render().tobytes(), page.crop((0, 0, 800, 1600)).tobytes())

    def test_repeated_pattern_has_multiple_real_alignments_and_is_refused(self):
        tile = content(width=200, height=76)
        page = Image.new("RGB", (200, 1800))
        for y in range(0, page.height, tile.height):
            page.paste(tile, (0, y))
        stitch = ScrollStitcher(page.crop((0, 0, 200, 600)))
        with self.assertRaisesRegex(StitchError, "scroll_overlap"):
            stitch.append(page.crop((0, 38, 200, 638)))
        self.assertEqual(len(stitch.parts), 1)

    def test_row_fingerprints_are_verified_against_actual_color_pixels(self):
        page = content(height=700)
        first = page.crop((0, 0, 200, 300))
        second = ImageChops.invert(page.crop((0, 137, 200, 437)))
        # Even a hypothetical hash collision cannot turn unequal RGB into a match.
        tokens = [ScrollStitcher._row_tokens(first),
                  ScrollStitcher._row_tokens(page.crop((0, 137, 200, 437)))]
        with patch.object(ScrollStitcher, "_row_tokens", side_effect=tokens):
            self.assertIsNone(ScrollStitcher._exact_overlap(first, second))

    def test_minor_render_changes_still_use_verified_fallback(self):
        page = content()
        first = page.crop((0, 0, 200, 300))
        second = ImageChops.add(page.crop((0, 137, 200, 437)),
                               Image.new("RGB", (200, 300), (1, 1, 1)))
        self.assertIsNone(ScrollStitcher._exact_overlap(first, second))
        stitch = ScrollStitcher(first)
        self.assertEqual(stitch.append(second), 137)
        self.assertEqual(stitch.render().crop((0, 300, 200, 437)).tobytes(),
                         second.crop((0, 163, 200, 300)).tobytes())

    def test_upward_horizontal_and_tiny_overlap_do_not_modify_existing_image(self):
        page = content()
        first = page.crop((0, 137, 200, 437))
        for second in (page.crop((0, 0, 200, 300)),
                       ImageChops.offset(page.crop((0, 247, 200, 547)), 1, 0),
                       page.crop((0, 414, 200, 714))):
            stitch = ScrollStitcher(first)
            with self.assertRaises(StitchError):
                stitch.append(second)
            self.assertEqual(stitch.render().tobytes(), first.tobytes())
            self.assertEqual(len(stitch.parts), 1)

    def test_no_change_and_no_overlap_do_not_append(self):
        image = content()
        stitch = ScrollStitcher(image.crop((0, 0, 200, 300)))
        for frame, reason in ((stitch.render(), "scroll_unchanged"),
                              (image.crop((0, 600, 200, 900)), "scroll_overlap")):
            with self.assertRaisesRegex(StitchError, reason):
                stitch.append(frame)
            self.assertEqual(len(stitch.parts), 1)

    def test_repeated_uniform_content_is_not_silently_accepted(self):
        first = Image.new("RGB", (200, 300), "white")
        second = first.copy()
        ImageDraw.Draw(second).rectangle((150, 270, 170, 290), fill="red")
        stitch = ScrollStitcher(first)
        with self.assertRaises(StitchError):
            stitch.append(second)

    def test_size_memory_and_frame_limits_keep_previous_state(self):
        image = content()
        stitch = ScrollStitcher(image.crop((0, 0, 200, 300)))
        with self.assertRaisesRegex(StitchError, "scroll_size"):
            stitch.append(Image.new("RGB", (201, 300)))
        with patch.object(stitch, "MAX_HEIGHT", 350):
            with self.assertRaisesRegex(StitchError, "scroll_limit"):
                stitch.append(image.crop((0, 120, 200, 420)))
        self.assertEqual(stitch.height, 300)
        self.assertFalse(stitch.undo())

    def test_magnifier_at_edges_returns_exact_source_pixel(self):
        image = QImage(20, 20, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        image.setPixelColor(19, 19, QColor("blue"))
        patch_image, center, pixel = magnifier_patch(image, QPoint(400, 400))
        self.assertEqual(pixel, QPoint(19, 19))
        self.assertEqual(patch_image.pixelColor(center), QColor("blue"))
        self.assertEqual(image.pixelColor(0, 0), QColor("red"))

    def test_window_mapping_negative_origin_mixed_dpi(self):
        maps = (MonitorMap(IntRect(-100, 0, 0, 100), IntRect(-200, 0, 0, 200)),
                MonitorMap(IntRect(0, 0, 200, 100), IntRect(0, 0, 300, 150)))
        self.assertEqual(physical_to_logical_rects(IntRect(-180, 20, -20, 160), maps), QRect(-90, 10, 80, 70))
        self.assertIsNone(physical_to_logical_rects(IntRect(1000, 0, 1200, 100), maps))

    def test_topmost_hover_window_enter_and_toggle(self):
        overlay = RegionSelectionOverlay(IntRect(0, 0, 400, 300), confirm_on_release=True,
            window_rects=(QRect(40, 40, 100, 100), QRect(0, 0, 300, 250)))
        overlay._pointer = QPoint(60, 60)
        overlay._update_hover()
        self.assertEqual(overlay._hover_rect, QRect(40, 40, 100, 100))
        overlay.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
        self.assertIsNone(overlay._hover_rect)
        overlay.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier))
        selected = []
        overlay.selected.connect(selected.append)
        overlay._confirm_selection()
        self.assertEqual(selected, [QRect(40, 40, 100, 100)])

    def test_overlay_s_requests_scroll_instead_of_output(self):
        overlay = RegionSelectionOverlay(IntRect(0, 0, 400, 300), confirm_on_release=True)
        overlay._start, overlay._current = QPoint(20, 20), QPoint(200, 200)
        scroll, selected = [], []
        overlay.scrollRequested.connect(scroll.append)
        overlay.selected.connect(selected.append)
        overlay.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_S, Qt.KeyboardModifier.NoModifier))
        self.assertEqual(len(scroll), 1)
        self.assertEqual(selected, [])
        self.assertEqual(overlay._panes, [])

    def test_scroll_session_cancel_never_captures_or_delivers(self):
        with patch("PIL.ImageGrab.grab") as grab:
            session = ScrollCaptureSession(content(height=300), grab)
            delivered, cancelled = [], []
            session.completed.connect(delivered.append)
            session.cancelled.connect(lambda: cancelled.append(True))
            session.close()
            grab.assert_not_called()
            self.assertEqual(delivered, [])
            self.assertEqual(cancelled, [True])
        self.app.processEvents()

    def test_closed_session_pending_timer_never_captures(self):
        with patch("PIL.ImageGrab.grab") as grab:
            session = ScrollCaptureSession(content(height=300), grab)
            session._closed = True
            session._capture()
            grab.assert_not_called()
            session.close()
        self.app.processEvents()

    def test_scroll_session_append_undo_and_finish_preserve_pixels(self):
        image = content()
        session = ScrollCaptureSession(image.crop((0, 0, 200, 300)),
                                       lambda: image.crop((0, 120, 200, 420)))
        delivered, cancelled = [], []
        session.completed.connect(delivered.append)
        session.cancelled.connect(lambda: cancelled.append(True))
        session._capture()
        self.assertTrue(session._pending)
        self.wait_analysis(session)
        self.assertFalse(session._pending)
        self.assertEqual(session.stitcher.height, 420)
        self.assertEqual(set(session.buttons), {"cancel", "done"})
        self.assertTrue(session.preview.pixmap() is not None)
        session.undo()
        self.assertEqual(session.stitcher.height, 300)
        session.finish()
        self.assertEqual(cancelled, [])
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].tobytes(), image.crop((0, 0, 200, 300)).tobytes())
        self.app.processEvents()

    def test_scroll_session_text_page_end_to_end_and_error_logging_has_no_content(self):
        page = text_content()
        session = ScrollCaptureSession(page.crop((0, 0, 800, 600)),
                                       lambda: page.crop((0, 347, 800, 947)),
                                       locale=LocaleManager("zh_CN"))
        with patch("builtins.print") as logged:
            session._capture()
            self.wait_analysis(session)
        self.assertEqual(session.stitcher.render().tobytes(), page.crop((0, 0, 800, 947)).tobytes())
        self.assertIn("rows=347", logged.call_args.args[0])
        self.assertNotIn("paragraph", logged.call_args.args[0])
        session.capture_frame = lambda: (_ for _ in ()).throw(RuntimeError("private window text"))
        with patch("builtins.print") as logged:
            session._capture()
        self.assertEqual(len(session.stitcher.parts), 2)
        self.assertNotIn("private window text", str(logged.call_args))
        self.assertIn("RuntimeError", str(logged.call_args))
        session.close()
        self.app.processEvents()

    def test_scroll_capture_error_recovers_buttons_without_appending(self):
        def fail():
            raise RuntimeError("synthetic capture failure")
        session = ScrollCaptureSession(content(height=300), fail, locale=LocaleManager("zh_CN"))
        session._capture()
        self.assertFalse(session._pending)
        self.assertEqual(len(session.stitcher.parts), 1)
        self.assertTrue(session.buttons["done"].isEnabled())
        self.assertTrue(session._paused)
        self.assertEqual(set(session.buttons), {"cancel", "done"})
        self.assertNotIn("synthetic capture failure", session.status.text())
        session.close()
        self.app.processEvents()

    def test_display_change_refuses_scroll_capture_before_reading_desktop(self):
        maps = (MonitorMap(IntRect(0, 0, 200, 300), IntRect(0, 0, 200, 300)),)
        with patch("ui.windows_screenshot._system_monitor_maps", return_value=()), \
                patch("ui.windows_screenshot.ImageGrab.grab") as grab:
            with self.assertRaisesRegex(StitchError, "scroll_size"):
                WindowsScreenshotController._capture_scroll_frame(maps[0].physical, maps)
            grab.assert_not_called()

    def test_active_scroll_session_blocks_another_screenshot(self):
        statuses = []
        controller = WindowsScreenshotController(status_callback=statuses.append, settle_delay_ms=0)
        controller._scroll_session = object()
        with patch("ui.windows_screenshot.capture_virtual_desktop") as capture:
            controller._handle_request(SCREENSHOT_FULL_CLIP)
            capture.assert_not_called()
        self.assertEqual(len(statuses), 1)
        self.assertFalse(controller._capture_pending)

    def test_cancelled_text_selection_never_delivers_text_or_error(self):
        controller = TextSelectionController()
        text, errors = [], []
        controller.result.connect(text.append)
        controller.status.connect(errors.append)
        controller.cancelled.set()
        controller._complete({"text": "synthetic private text"})
        controller._complete({"error": "text_select_failed"})
        self.assertEqual(text, [])
        self.assertEqual(errors, [])

    def test_old_recognition_removed_and_magnifier_still_works(self):
        image = QImage(200, 100, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        locale = LocaleManager("zh_CN")
        editor = ScreenshotEditor(image, SCREENSHOT_FULL_CLIP, locale=locale)
        for key in ("ocr", "ocr_install"):
            self.assertNotIn(key, editor._actions)
        self.assertIn(editor._actions["text_select"], editor.toolbar.more.actions())
        self.assertIsNone(editor._selection_worker)
        editor._actions["magnifier"].trigger()
        self.assertTrue(editor.canvas.magnifier_enabled)
        locale.setLanguage("en")
        self.assertTrue(editor._actions["magnifier"].text())
        self.assertEqual(editor.document.render(), image)
        editor.close()
        self.app.processEvents()

    def test_selection_controller_only_emits_result_not_clipboard(self):
        controller = TextSelectionController()
        results, errors = [], []
        controller.result.connect(results.append)
        controller.status.connect(errors.append)
        with patch.object(QApplication, "clipboard") as clipboard:
            data = {"glyphs": [], "text": "synthetic"}
            controller._complete(data)
            controller._complete({"error": "text_select_failed"})
            clipboard.assert_not_called()
        self.assertEqual(results, [data])
        self.assertEqual(errors, ["text_select_failed"])


if __name__ == "__main__":
    unittest.main()
