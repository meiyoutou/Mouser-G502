"""Viewport resolution and static chrome regressions; no real desktop access."""
from contextlib import nullcontext
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageChops, ImageDraw
from PySide6.QtCore import QObject, QPoint, QRect, Signal
from PySide6.QtWidgets import QApplication

from tests.test_screenshot_phase2 import content, text_content
from ui.locale_manager import LocaleManager
from ui.screenshot_common import SCREENSHOT_FULL_CLIP
from ui.screenshot_overlay import IntRect
from ui.screenshot_scroll import ScrollCaptureSession
from ui.screenshot_scroll_region import detect_scroll_viewport, ScrollViewportProbe
from ui.screenshot_tools import ScrollStitcher, StitchError
from ui.windows_screenshot import WindowsScreenshotController, VirtualCapture, MonitorMap


class Node:
    def __init__(self, rect, *, parent=None, scroll=False, children=(), kind=50033,
                 process=12345, offscreen=False):
        self.BoundingRectangle = SimpleNamespace(left=rect.left, top=rect.top,
                                                right=rect.right, bottom=rect.bottom)
        self.parent, self.children = parent, list(children)
        self.ControlType, self.ProcessId, self.IsOffscreen = kind, process, offscreen
        self.pattern = SimpleNamespace(VerticallyScrollable=True) if scroll else None
        self.sibling = None
        for first, second in zip(self.children, self.children[1:]):
            first.sibling = second
    @property
    def Name(self):
        raise AssertionError("document names/text must never be read")
    def GetPattern(self, pattern):
        assert pattern == 10004
        return self.pattern
    def GetParentControl(self):
        return self.parent
    def GetFirstChildControl(self):
        return self.children[0] if self.children else None
    def GetNextSiblingControl(self):
        return self.sibling


def automation(node):
    return SimpleNamespace(UIAutomationInitializerInThread=nullcontext,
                           ControlFromPoint=Mock(return_value=node))


def chat_frame(page, offset, *, scale=1):
    # Same layout structure as the reported screenshot, without private text.
    frame = Image.new("RGB", (1100, 900), "#e8edf2")
    draw = ImageDraw.Draw(frame)
    draw.rectangle((0, 0, 1099, 79), fill="#34495e")
    draw.text((30, 30), "Fixed title bar", fill="white")
    for row in range(20):
        draw.text((25, 115 + row * 32), f"Fixed sidebar item {row}", fill="#112233")
    draw.rounded_rectangle((310, 730, 1050, 875), radius=20, fill="#ffffff")
    draw.text((340, 790), "Fixed input area", fill="#112233")
    frame.paste(page.crop((0, offset, 800, offset + 600)), (280, 100))
    return frame


class ScrollRegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.page = text_content()

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertTrue(condition())

    def detect(self, selection, node):
        return detect_scroll_viewport(selection, automation=automation(node), ignore_process=-1)

    def test_fixed_sidebar_title_and_input_reproduce_old_failure_but_body_stitches(self):
        first, second = chat_frame(self.page, 0), chat_frame(self.page, 137)
        with self.assertRaises(StitchError):
            ScrollStitcher(first).append(second)
        selection = IntRect(0, 0, 1100, 900)
        body = IntRect(280, 100, 1080, 700)
        rect = self.detect(selection, Node(body, scroll=True))
        self.assertEqual(rect, body)
        crop = lambda frame: frame.crop((rect.left, rect.top, rect.right, rect.bottom))
        stitch = ScrollStitcher(crop(first))
        self.assertEqual(stitch.append(crop(second)), 137)
        self.assertEqual(stitch.render().tobytes(), self.page.crop((0, 0, 800, 737)).tobytes())

    def test_never_expands_a_manual_body_selection(self):
        selection = IntRect(400, 200, 700, 500)
        self.assertEqual(self.detect(selection, Node(IntRect(300, 100, 1000, 800), scroll=True)), selection)

    def test_largest_parent_scroll_body_wins_over_nested_code_pane(self):
        body = Node(IntRect(280, 100, 1080, 700), scroll=True)
        code = Node(IntRect(400, 200, 800, 600), scroll=True, parent=body)
        self.assertEqual(self.detect(IntRect(0, 0, 1100, 900), code), IntRect(280, 100, 1080, 700))

    def test_visible_viewport_child_excludes_scrollbar_and_border(self):
        viewport = Node(IntRect(282, 102, 1060, 698), kind=50026)
        scrollbar = Node(IntRect(1060, 102, 1078, 698), kind=50014)
        body = Node(IntRect(280, 100, 1080, 700), scroll=True, children=(viewport, scrollbar))
        self.assertEqual(self.detect(IntRect(0, 0, 1100, 900), body), IntRect(282, 102, 1060, 698))

    def test_qt_viewport_and_wrapped_scrollbar_without_scroll_pattern(self):
        viewport = Node(IntRect(282, 102, 1060, 698), kind=50026)
        scrollbar = Node(IntRect(1060, 102, 1078, 698), kind=50014)
        wrapper = Node(IntRect(1060, 102, 1078, 698), children=(scrollbar,))
        body = Node(IntRect(280, 100, 1080, 700), children=(viewport, wrapper))
        self.assertEqual(self.detect(IntRect(0, 0, 1100, 900), body),
                         IntRect(282, 102, 1060, 698))

    def test_unrelated_or_horizontal_scrollbar_is_not_a_viewport_signal(self):
        viewport = Node(IntRect(282, 102, 1060, 698))
        for rect in (IntRect(1060, 102, 1078, 300),
                     IntRect(282, 680, 1060, 698),
                     IntRect(800, 102, 818, 698)):
            body = Node(IntRect(280, 100, 1080, 700),
                        children=(viewport, Node(rect, kind=50014)))
            self.assertIsNone(self.detect(IntRect(0, 0, 1100, 900), body))

    def test_stale_child_does_not_discard_valid_scroll_pattern(self):
        body = Node(IntRect(280, 100, 1080, 700), scroll=True)
        body.GetFirstChildControl = Mock(side_effect=RuntimeError())
        self.assertEqual(self.detect(IntRect(0, 0, 1100, 900), body),
                         IntRect(280, 100, 1080, 700))

    def test_unknown_offscreen_tiny_window_and_own_controls_are_not_guessed(self):
        selection = IntRect(0, 0, 1100, 900)
        for node in (Node(selection), Node(selection, scroll=True, offscreen=True),
                     Node(IntRect(0, 0, 20, 200), scroll=True),
                     Node(selection, scroll=True, kind=50032)):
            self.assertIsNone(self.detect(selection, node))
        auto = automation(Node(selection, scroll=True, process=12345))
        self.assertIsNone(detect_scroll_viewport(selection, automation=auto, ignore_process=12345))

    def test_negative_physical_coordinates_are_preserved(self):
        body = IntRect(-1200, 100, -100, 800)
        self.assertEqual(self.detect(IntRect(-1600, 0, 0, 1000), Node(body, scroll=True)), body)

    def test_no_reading_document_text_or_invoking_scroll_methods(self):
        node = Node(IntRect(200, 100, 1000, 800), scroll=True)
        node.pattern = Mock(VerticallyScrollable=True)
        auto = automation(node)
        found = detect_scroll_viewport(IntRect(0, 0, 1100, 900), automation=auto, ignore_process=-1)
        self.assertIsNotNone(found)
        self.assertEqual(node.pattern.method_calls, [])

    def test_probe_runs_off_gui_thread(self):
        threads, results = [], []
        rect = IntRect(0, 0, 100, 200)
        def resolver(selection):
            threads.append(threading.get_ident())
            return selection
        probe = ScrollViewportProbe(rect, resolver=resolver)
        probe.resolved.connect(results.append)
        probe.start()
        self.wait_for(lambda: bool(results))
        self.assertEqual(results, [rect])
        self.assertNotEqual(threads[0], threading.get_ident())
        probe.deleteLater()

    def test_probe_timeout_resolves_once_and_ignores_late_results(self):
        release, results = threading.Event(), []
        def resolver(selection):
            release.wait(5)
            return selection
        probe = ScrollViewportProbe(IntRect(0, 0, 100, 200), resolver=resolver, timeout_ms=20)
        probe.resolved.connect(results.append)
        try:
            probe.start()
            self.wait_for(lambda: bool(results))
            self.assertEqual(results, [None])
        finally:
            release.set()
        for _ in range(20):
            self.app.processEvents()
            time.sleep(.002)
        self.assertEqual(results, [None])
        probe.deleteLater()

    def test_probe_provider_error_falls_back_without_private_error_text(self):
        probe = ScrollViewportProbe(IntRect(0, 0, 100, 200),
                                    resolver=Mock(side_effect=RuntimeError("private text")))
        results = []
        probe.resolved.connect(results.append)
        probe.start()
        self.wait_for(lambda: bool(results))
        self.assertEqual(results, [None])
        probe.deleteLater()

    def test_slow_provider_cannot_accumulate_background_threads(self):
        rect, release, started = IntRect(0, 0, 100, 200), threading.Event(), threading.Event()
        def resolver(_):
            started.set()
            release.wait(5)
        first = ScrollViewportProbe(rect, resolver=resolver)
        first.start()
        self.wait_for(started.is_set)
        second_resolver, results = Mock(), []
        second = ScrollViewportProbe(rect, resolver=second_resolver)
        second.resolved.connect(results.append)
        try:
            second.start()
            self.wait_for(lambda: bool(results))
            second_resolver.assert_not_called()
            self.assertEqual(results, [None])
        finally:
            release.set()
            self.wait_for(lambda: not first._worker_lock.locked())
            first.cancel()
            first.deleteLater()
            second.deleteLater()

    def test_controller_crops_seed_and_live_capture_to_same_detected_physical_body(self):
        bounds = IntRect(0, 0, 1100, 900)
        controller = WindowsScreenshotController(locale=LocaleManager("zh_CN"))
        controller._pending_capture = VirtualCapture(chat_frame(self.page, 0), bounds,
                                                     (MonitorMap(bounds, bounds),))
        controller._pending_action = SCREENSHOT_FULL_CLIP
        class Probe(QObject):
            resolved = Signal(object)
            def __init__(self, *args):
                super().__init__()
            def start(self):
                pass
            def cancel(self):
                pass
        with patch("ui.screenshot_scroll_region.ScrollViewportProbe", Probe), \
                patch("ui.windows_screenshot.QTimer.singleShot"), \
                patch.object(controller, "_capture_scroll_frame",
                             return_value=self.page.crop((0, 137, 800, 737))) as grab:
            controller._start_scroll(QRect(0, 0, 1100, 900))
            self.assertTrue(controller._capture_pending)
            controller._scroll_probe.resolved.emit(IntRect(280, 100, 1080, 700))
            session = controller._scroll_session
            self.assertIsNotNone(session)
            self.assertFalse(controller._capture_pending)
            self.assertEqual(session.stitcher.render().tobytes(),
                             self.page.crop((0, 0, 800, 600)).tobytes())
            self.assertEqual(session.capture_rect, QRect(280, 100, 800, 600))
            self.assertTrue(session.viewport_detected)
            session._excluded = True
            session._capture()
            self.wait_for(lambda: not session._pending)
            self.assertEqual(grab.call_args.args[0], IntRect(280, 100, 1080, 700))
            self.assertEqual(session.stitcher.render().tobytes(), self.page.crop((0, 0, 800, 737)).tobytes())
            session.close()
        self.app.processEvents()

    def test_no_viewport_provider_keeps_original_region(self):
        bounds = IntRect(0, 0, 800, 600)
        controller = WindowsScreenshotController()
        capture = VirtualCapture(self.page.crop((0, 0, 800, 600)), bounds,
                                 (MonitorMap(bounds, bounds),))
        probe = Mock()
        controller._scroll_probe = probe
        controller._open_scroll_session(capture, SCREENSHOT_FULL_CLIP,
                                       bounds.to_qrect(), bounds, probe, None)
        session = controller._scroll_session
        self.assertEqual(session.capture_rect, bounds.to_qrect())
        self.assertFalse(session.viewport_detected)
        session.close()
        self.app.processEvents()

    def test_coarse_accessibility_container_still_excludes_fixed_header_and_input(self):
        """UIA may report the whole chat webview, not its inner scroll body.

        Regression for the real 1322x1010 accessibility-candidate log. This is
        only a control-flow fixture, not a claim to have tested Codex itself.
        """
        page = self.page.resize((1100, 4200))
        def candidate(offset):
            image = Image.new("RGB", (1322, 1010), "#edf0f5")
            draw = ImageDraw.Draw(image)
            draw.text((30, 30), "Fixed chat header / menu", fill="#111111")
            draw.rectangle((80, 850, 1240, 990), fill="white")
            draw.text((110, 880), "Fixed message input area", fill="#111111")
            image.paste(page.crop((0, offset, 1100, offset + 700)), (100, 110))
            return image
        offset = [137]
        session = ScrollCaptureSession(candidate(0), lambda: candidate(offset[0]),
                                       viewport_detected=True)
        try:
            self.assertTrue(session.stitcher.detect_content,
                            "Accessibility geometry must not disable pixel validation")
            previous = 0
            for value in (137, 347, 510):
                offset[0] = value
                session._capture()
                self.wait_for(lambda: not session._pending)
                self.assertIsNone(session._error)
                self.assertEqual(session.stitcher._position, value)
                previous = value
            self.assertIsNotNone(session.stitcher.content_rect)
            x0, y0, x1, y1 = session.stitcher.content_rect
            self.assertGreaterEqual(y0, 110)
            self.assertLessEqual(y1, 810)
            expected = page.crop((x0 - 100, y0 - 110, x1 - 100, y1 - 110 + previous))
            self.assertEqual(session.stitcher.render().tobytes(), expected.tobytes())
            self.assertTrue(session._image_viewport_detected)
        finally:
            session.close()
            self.app.processEvents()

    def test_cancelled_or_stale_probe_never_opens_a_scroll_session(self):
        controller = WindowsScreenshotController()
        controller._scroll_probe = object()
        with patch("ui.screenshot_scroll.ScrollCaptureSession") as session:
            controller._open_scroll_session(None, "", None, None, object(), None)
            session.assert_not_called()

    def test_small_cursor_and_scrollbar_changes_use_consensus_not_blurred_sampling(self):
        first = self.page.crop((0, 0, 800, 600))
        second = self.page.crop((0, 137, 800, 737))
        draw = ImageDraw.Draw(second)
        draw.rectangle((795, 0, 799, 599), fill="#999999")
        draw.rectangle((100, 200, 101, 225), fill="red")
        self.assertIsNone(ScrollStitcher._exact_overlap(first, second))
        with patch.object(Image.Image, "resize", side_effect=AssertionError("no gray sampling")):
            self.assertEqual(ScrollStitcher.overlap(first, second), 463)

    def test_stripe_consensus_does_not_accept_color_inverted_or_horizontal_frames(self):
        page = content()
        first = page.crop((0, 0, 200, 300))
        for second in (ImageChops.invert(page.crop((0, 137, 200, 437))),
                       ImageChops.offset(page.crop((0, 137, 200, 437)), 1, 0)):
            self.assertIsNone(ScrollStitcher._stripe_overlap(first, second))
            with self.assertRaises(StitchError):
                ScrollStitcher(first).append(second)

    def test_periodic_repeated_messages_still_fail_safely(self):
        tile = content(width=200, height=76)
        page = Image.new("RGB", (200, 1800))
        for y in range(0, page.height, tile.height):
            page.paste(tile, (0, y))
        stitch = ScrollStitcher(page.crop((0, 0, 200, 600)))
        with self.assertRaises(StitchError):
            stitch.append(page.crop((0, 38, 200, 638)))
        self.assertEqual(stitch.height, 600)

    def test_detected_viewport_hint_follows_language(self):
        locale = LocaleManager("zh_CN")
        session = ScrollCaptureSession(self.page.crop((0, 0, 800, 600)), Mock(),
                                       locale=locale, viewport_detected=True)
        for language, word in (("zh_CN", "可滚动正文"), ("en", "detected scrolling content"),
                                ("zh_TW", "可捲動正文")):
            locale.setLanguage(language)
            self.assertIn(word, session.hint.text())
        session.close()
        self.app.processEvents()
