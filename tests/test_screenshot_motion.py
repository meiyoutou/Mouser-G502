"""No UIA, desktop capture, private screenshots or optional image runtimes."""
import unittest
from PIL import Image, ImageChops, ImageDraw
from tests.test_screenshot_phase2 import text_content, content
from tests.test_screenshot_scroll_region import chat_frame
from ui.screenshot_tools import ScrollStitcher, StitchError


class MotionTests(unittest.TestCase):
    def test_white_chat_panels_and_blinking_input_cursor(self):
        page = text_content()
        def frame(offset, blink=False):
            image = Image.new("RGB", (1100, 900), "white")
            draw = ImageDraw.Draw(image)
            for row in range(20):
                draw.text((30, 100 + row * 32), f"Fixed sidebar {row}", fill="black")
            draw.text((300, 30), "Fixed chat title", fill="black")
            draw.text((350, 800), "Fixed input placeholder", fill="gray")
            if blink:
                draw.rectangle((340, 785, 341, 810), fill="black")
            image.paste(page.crop((0, offset, 800, offset + 600)), (280, 100))
            return image
        stitch = ScrollStitcher(frame(0), detect_content=True)
        for index, offset in enumerate((137, 210, 347, 390, 510, 631, 740, 809, 950, 1070)):
            with self.subTest(offset=offset, rectangle=stitch.content_rect):
                self.assertGreater(stitch.append(frame(offset, bool(index % 2))), 0)
        self.assertIsNotNone(stitch.content_rect)

    def test_fixed_chat_chrome_without_uia_continues_many_times(self):
        page = text_content()
        stitch = ScrollStitcher(chat_frame(page, 0), detect_content=True)
        for offset in (137, 210, 347, 390, 510, 631, 740, 809, 950, 1070):
            self.assertGreater(stitch.append(chat_frame(page, offset)), 0)
            self.assertIsNotNone(stitch.content_rect)
            x0, y0, x1, y1 = stitch.content_rect
            expected = chat_frame(page, 0).crop((x0, y0, x1, y1))
            # The inferred horizontal blank margins may exceed the text page.
            canvas = Image.new("RGB", (1100, 900 + offset), "#e8edf2")
            canvas.paste(page.crop((0, 0, 800, 600 + offset)), (280, 100))
            expected = canvas.crop((x0, y0, x1, y1 + offset))
            self.assertEqual(stitch.height, y1 - y0 + offset)
            self.assertIsNone(ImageChops.difference(stitch.render(), expected).getbbox())

    def test_wrong_unrelated_or_upward_views_are_not_inferred(self):
        page = text_content()
        for before, after in ((chat_frame(page, 137), chat_frame(page, 0)),
                              (chat_frame(page, 0), ImageChops.invert(chat_frame(page, 137)))):
            stitch = ScrollStitcher(before, detect_content=True)
            with self.assertRaises(StitchError):
                stitch.append(after)
            self.assertIsNone(stitch.content_rect)
            self.assertEqual(stitch.height, before.height)

    def test_repeat_pattern_is_not_used_to_guess_scroll(self):
        tile = content(width=800, height=76)
        page = Image.new("RGB", (800, 3200))
        for y in range(0, page.height, 76):
            page.paste(tile, (0, y))
        stitch = ScrollStitcher(chat_frame(page, 0), detect_content=True)
        with self.assertRaises(StitchError):
            stitch.append(chat_frame(page, 38))

    def test_normal_body_and_size_checks_unchanged(self):
        page = text_content()
        stitch = ScrollStitcher(page.crop((0, 0, 800, 600)), detect_content=True)
        self.assertEqual(stitch.append(page.crop((0, 137, 800, 737))), 137)
        self.assertIsNone(stitch.content_rect)
        with self.assertRaises(StitchError):
            stitch.append(page.crop((0, 200, 799, 800)))

    def test_nonoverlapping_repeated_paragraphs_must_not_crop_away_numbers(self):
        page = text_content()
        stitch = ScrollStitcher(page.crop((0, 0, 800, 600)), detect_content=True)
        with self.assertRaises(StitchError):
            stitch.append(page.crop((0, 900, 800, 1500)))
        self.assertIsNone(stitch.content_rect)
        self.assertEqual(stitch.height, 600)

    def test_motion_crop_undo_and_new_branch_preserve_pixels(self):
        page = text_content()
        stitch = ScrollStitcher(chat_frame(page, 0), detect_content=True)
        stitch.append(chat_frame(page, 137))
        accepted = stitch.render().tobytes()
        stitch.append(chat_frame(page, 210))
        stitch.append(chat_frame(page, 347))
        self.assertTrue(stitch.undo())
        self.assertTrue(stitch.undo())
        self.assertEqual(stitch.render().tobytes(), accepted)
        stitch.append(chat_frame(page, 277))
        x0, y0, x1, y1 = stitch.content_rect
        canvas = Image.new("RGB", (1100, 1177), "#e8edf2")
        canvas.paste(page.crop((0, 0, 800, 877)), (280, 100))
        self.assertEqual(stitch.render().tobytes(),
                         canvas.crop((x0, y0, x1, y1 + 277)).tobytes())

    def test_limit_rejection_does_not_commit_a_crop(self):
        page = text_content()
        stitch = ScrollStitcher(chat_frame(page, 0), detect_content=True)
        original = stitch.render().tobytes()
        stitch.MAX_HEIGHT = 650
        with self.assertRaisesRegex(StitchError, "scroll_limit"):
            stitch.append(chat_frame(page, 137))
        self.assertIsNone(stitch.content_rect)
        self.assertEqual(stitch.render().tobytes(), original)
