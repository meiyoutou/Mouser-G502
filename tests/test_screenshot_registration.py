"""New registration engine, actual portrait dimensions and UI delivery path."""
import random
import time
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageChops, ImageDraw, ImageFont

from ui.screenshot_registration import RegistrationStitcher
from ui.screenshot_tools import StitchError


def document(width, height, scale=1):
    page = Image.new("RGB", (width, height), "#fafafa")
    draw = ImageDraw.Draw(page)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", round(19 * scale))
    rng = random.Random(935)
    y = 18
    index = 0
    while y < height:
        draw.text((26, y), f"{index:04d}  Paragraph {rng.randrange(10000000)} - scrolling capture test.",
                  font=font, fill="#29313b")
        if index % 4 == 0:
            draw.rectangle((30, y + round(29 * scale), width - 40, y + round(33 * scale)),
                           fill=(rng.randrange(220), rng.randrange(220), rng.randrange(220)))
        y += round((42 + rng.randrange(12)) * scale)
        index += 1
    return page


def framed(page, offset, size):
    w, h = size
    left, top, bottom = 220, 84, h - 190
    frame = Image.new("RGB", size, "#edf0f5")
    draw = ImageDraw.Draw(frame)
    font = ImageFont.truetype(r"C:\Windows\Fonts\arial.ttf", 22)
    draw.text((20, 20), "FIXED title / menu", font=font, fill="#29313b")
    for row in range(h // 44):
        draw.text((8, 102 + row * 44), f"Sidebar {row:03d}", font=font, fill="#34495e")
    draw.rectangle((240, h - 156, w - 24, h - 20), fill="white")
    draw.text((260, h - 130), "FIXED input box. Do not duplicate.", font=font, fill="black")
    frame.paste(page.crop((0, offset, w - left, offset + bottom - top)), (left, top))
    return frame


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = document(800, 4200)

    def test_native_pixels_repeated_appends_no_duplicate_seams(self):
        s = RegistrationStitcher(self.page.crop((0, 0, 800, 700)))
        for offset in (137, 210, 347, 390, 510, 631, 740, 809, 950, 1070):
            s.append(self.page.crop((0, offset, 800, offset + 700)))
            self.assertEqual(s.height, 700 + offset)
            self.assertEqual(s.render().tobytes(), self.page.crop((0, 0, 800, offset + 700)).tobytes())

    def test_actual_landscape_and_portrait_with_static_chrome(self):
        for size in ((1440, 2512), (1689, 1135)):
            with self.subTest(size=size):
                w, h = size
                page = document(w - 220, h + 1800)
                s = RegistrationStitcher(framed(page, 0, size), detect_content=True)
                last = 0
                for offset in (137, 347, 631, 950, 1070):
                    self.assertEqual(s.append(framed(page, offset, size)), offset - last)
                    last = offset
                self.assertIsNotNone(s.content_rect)
                x0, y0, x1, y1 = s.content_rect
                self.assertGreaterEqual(x0, 220)
                self.assertGreaterEqual(y0, 84)
                self.assertLessEqual(y1, h - 190)
                expected = page.crop((x0 - 220, y0 - 84, x1 - 220, y1 - 84 + 1070))
                self.assertEqual(s.render().tobytes(), expected.tobytes())

    def test_font_scales_and_antialiasing_change(self):
        for scale in (1, 1.25, 1.5, 2):
            with self.subTest(scale=scale):
                page = document(1100, 2400, scale)
                first = page.crop((0, 0, 1100, 950))
                second = page.crop((0, 273, 1100, 1223))
                # Subpixel rasterization, plus a small caret and edge scrollbar.
                second = Image.blend(second, ImageChops.offset(second, 0, 1), .15)
                draw = ImageDraw.Draw(second)
                draw.rectangle((1094, 30, 1099, 800), fill="#a2a2a2")
                draw.line((770, 350, 770, 372), fill="black", width=2)
                s = RegistrationStitcher(first)
                self.assertEqual(s.append(second), 273)

    def test_upward_revisit_and_resume_only_adds_unseen_content(self):
        frame = lambda offset: self.page.crop((0, offset, 800, offset + 700))
        s = RegistrationStitcher(frame(0))
        for offset, extra in ((210, 210), (347, 137), (137, 0), (300, 0), (510, 163)):
            self.assertEqual(s.append(frame(offset)), extra)
        self.assertEqual(s.render().tobytes(), self.page.crop((0, 0, 800, 1210)).tobytes())

    def test_overlap_refresh_does_not_repeat_a_fixed_bottom_floating_button(self):
        """Synthetic regression for the private Codex diagnostic, no user pixels."""
        def button(image, offset=0):
            draw = ImageDraw.Draw(image)
            center = 400, offset + 648
            x, y = center
            draw.ellipse((x - 20, y - 20, x + 20, y + 20),
                         fill="white", outline="#d0d0d0", width=1)
            draw.line((x, y - 9, x, y + 8), fill="#333333", width=2)
            draw.line((x - 7, y + 1, x, y + 8, x + 7, y + 1),
                      fill="#333333", width=2)
            return image
        def frame(offset):
            return button(self.page.crop((0, offset, 800, offset + 700)))
        stitcher = RegistrationStitcher(frame(0))
        maximum = 0
        snapshots = []
        for offset in (92, 347, 444, 500, 625, 707, 799, 1000, 809, 1200):
            self.assertEqual(stitcher.append(frame(offset)), max(0, offset - maximum))
            maximum = max(maximum, offset)
            # Keep the last actually captured overlay once, without inventing
            # the pixels hidden by it. Older occurrences must be replaced by
            # verified, unobscured pixels from the next overlapping frame.
            expected = button(self.page.crop((0, 0, 800, maximum + 700)), maximum)
            self.assertEqual(stitcher.render().tobytes(), expected.tobytes())
            snapshots.append(stitcher.render().tobytes())
        self.assertTrue(stitcher.undo())
        self.assertEqual(stitcher.render().tobytes(), snapshots[-2])
        self.assertTrue(stitcher.undo())
        self.assertEqual(stitcher.render().tobytes(), snapshots[-3])

    def test_overlap_refresh_preserves_the_gui_worker_snapshot(self):
        import copy
        first = self.page.crop((0, 0, 800, 700))
        original = RegistrationStitcher(first)
        original_preview = original.preview_image().tobytes()
        worker = copy.copy(original)
        worker.append(self.page.crop((0, 137, 800, 837)))
        self.assertEqual(original.render().tobytes(), first.tobytes())
        self.assertEqual(original.preview_image().tobytes(), original_preview)
        self.assertEqual(original._position, 0)
        self.assertEqual(worker.height, 837)

    def test_bad_match_keeps_anchor_then_recovers(self):
        frame = lambda offset: self.page.crop((0, offset, 800, offset + 700))
        s = RegistrationStitcher(frame(0))
        before = s.render().tobytes()
        for bad in (ImageChops.invert(frame(137)), frame(1200)):
            with self.assertRaisesRegex(StitchError, "scroll_overlap"):
                s.append(bad)
            self.assertEqual(s.render().tobytes(), before)
            self.assertEqual(s._position, 0)
        self.assertEqual(s.append(frame(137)), 137)

    def test_whitespace_and_periodic_content_do_not_guess(self):
        white = Image.new("RGB", (400, 600), "white")
        s = RegistrationStitcher(white)
        changed = white.copy()
        ImageDraw.Draw(changed).rectangle((130, 300, 170, 315), fill="red")
        with self.assertRaises(StitchError):
            s.append(changed)
        tile = document(800, 160)
        page = Image.new("RGB", (800, 1800))
        for y in range(0, 1800, 160):
            page.paste(tile, (0, y))
        s = RegistrationStitcher(page.crop((0, 0, 800, 800)))
        with self.assertRaisesRegex(StitchError, "scroll_overlap"):
            s.append(page.crop((0, 60, 800, 860)))
        self.assertEqual(s.height, 800)

    def test_narrow_selection_size_and_limits(self):
        page = self.page.crop((0, 0, 140, 1800))
        s = RegistrationStitcher(page.crop((0, 0, 140, 700)))
        self.assertEqual(s.append(page.crop((0, 137, 140, 837))), 137)
        with self.assertRaisesRegex(StitchError, "scroll_size"):
            s.append(Image.new("RGB", (141, 700)))
        s.MAX_HEIGHT = 900
        with self.assertRaisesRegex(StitchError, "scroll_limit"):
            s.append(page.crop((0, 347, 140, 1047)))
        self.assertEqual(s.height, 837)

    def test_blinking_input_caret_does_not_expand_body_into_fixed_input(self):
        size = (1440, 2512)
        page = document(1220, 4500)
        first, second = framed(page, 0, size), framed(page, 137, size)
        ImageDraw.Draw(second).rectangle((130, 2440, 131, 2470), fill="black")
        s = RegistrationStitcher(first, detect_content=True)
        self.assertEqual(s.append(second), 137)
        self.assertGreaterEqual(s.content_rect[0], 220)
        self.assertLessEqual(s.content_rect[3], 2512 - 190)

    def test_equal_side_by_side_fixed_and_scrolling_panes(self):
        """Reported layout: not one fullscreen page; half the selection is fixed."""
        for size in ((1440, 2512), (1689, 1135)):
            with self.subTest(size=size):
                w, h = size
                split = w // 2
                page = document(w - split, h + 1500)
                fixed = document(split, h)
                def frame(offset):
                    image = Image.new("RGB", size, "white")
                    image.paste(fixed, (0, 0))
                    image.paste(page.crop((0, offset, w - split, h + offset)), (split, 0))
                    return image
                s = RegistrationStitcher(frame(0), detect_content=True)
                previous = 0
                for offset in (137, 347, 510, 809, 1070):
                    self.assertEqual(s.append(frame(offset)), offset - previous)
                    previous = offset
                self.assertIsNotNone(s.content_rect)
                x0, y0, x1, y1 = s.content_rect
                self.assertGreaterEqual(x0, split)
                expected = page.crop((x0 - split, y0, x1 - split, y1 + 1070))
                self.assertEqual(s.render().tobytes(), expected.tobytes())

    def test_thumbnail_never_renders_full_image_and_undo_memory_bounded(self):
        s = RegistrationStitcher(self.page.crop((0, 0, 800, 700)))
        for offset in (137, 273, 400, 510):
            s.append(self.page.crop((0, offset, 800, offset + 700)))
        with patch.object(s, "render", side_effect=AssertionError("not a preview implementation")):
            preview = s.preview_image()
        self.assertLessEqual(preview.width, 240)
        self.assertLessEqual(preview.height, 300)
        self.assertLessEqual(len(s._undo_states), 2)

    def test_long_capture_uses_same_editing_entry_as_normal_capture(self):
        from PySide6.QtWidgets import QApplication
        from ui.screenshot_common import SCREENSHOT_FULL_CLIP, SCREENSHOT_FULL_FILE
        from ui.windows_screenshot import WindowsScreenshotController
        app = QApplication.instance() or QApplication([])
        controller = WindowsScreenshotController()
        controller._edit_this_capture = True
        image = self.page.crop((0, 0, 800, 700))
        with patch.object(controller, "_deliver_image") as deliver, \
                patch.object(controller, "_edit_or_deliver") as edit:
            for action in (SCREENSHOT_FULL_CLIP, SCREENSHOT_FULL_FILE):
                controller._finish_scroll(image, action)
                edit.assert_called_with(image, action)
            # Long capture now follows the saved editing preference too; it
            # must not bypass annotation/pin controls when editing is enabled.
            deliver.assert_not_called()
        with patch("ui.screenshot_editor.ScreenshotEditor") as editor:
            controller._edit_or_deliver(image, SCREENSHOT_FULL_CLIP)
            editor.assert_called_once()


if __name__ == "__main__":
    unittest.main()
