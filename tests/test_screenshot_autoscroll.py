"""Automatic capture interaction, using synthetic frames only (no desktop I/O)."""
import ctypes
import threading
import time
import unittest
from unittest.mock import Mock, patch

from PIL import ImageChops
from PySide6.QtCore import QRect, Qt, QThreadPool
from PySide6.QtWidgets import QApplication

from tests.test_screenshot_phase2 import content, text_content
from core.scroll_compute import StitchError
from ui.locale_manager import LocaleManager
from ui.screenshot_scroll import ScrollCaptureSession, exclude_capture_window


class AutoScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.page = text_content()

    def setUp(self):
        self.sessions = []

    def tearDown(self):
        for session in self.sessions:
            if not session._closed:
                session.close()
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()

    def session(self, offset=0, **kwargs):
        frame = lambda: self.page.crop((0, offset, 800, offset + 600))
        session = ScrollCaptureSession(self.page.crop((0, 0, 800, 600)), frame, **kwargs)
        self.sessions.append(session)
        return session

    def wait_for(self, condition, message="asynchronous condition not met"):
        deadline = time.monotonic() + 5
        while not condition() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)  # Unlike qWait on this binding, releases the GIL.
        self.assertTrue(condition(), message)

    def sample(self, session):
        session._capture()
        self.wait_for(lambda: not session._pending)

    def test_timer_auto_captures_without_append_button_or_click(self):
        offset = [0]
        grab = Mock(side_effect=lambda: self.page.crop((0, offset[0], 800, offset[0] + 600)))
        session = self.session()
        session.capture_frame = grab
        with patch("ui.screenshot_scroll.exclude_capture_window", return_value=True):
            session.show()
            offset[0] = 137
            self.wait_for(lambda: session.stitcher.height == 737)
            offset[0] = 347
            self.wait_for(lambda: session.stitcher.height == 947)
        self.assertGreaterEqual(grab.call_count, 2)
        self.assertNotIn("scroll_append", session.buttons)
        self.assertEqual(session.stitcher.render().tobytes(), self.page.crop((0, 0, 800, 947)).tobytes())
        self.assertTrue(session.isVisible())  # No repeated hiding/flashing.
        self.assertTrue(session.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertTrue(session.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))

    def test_idle_unchanged_frame_never_starts_matching_or_adds_duplicates(self):
        session = self.session()
        with patch("ui.screenshot_scroll._AnalyzeFrame") as analyze:
            for _ in range(5):
                session._capture()
            analyze.assert_not_called()
        self.assertEqual(len(session.stitcher.parts), 1)

    def test_matching_is_off_gui_thread_and_only_one_job_in_flight(self):
        from ui.screenshot_registration import RegistrationStitcher as ScrollStitcher
        entered, release = threading.Event(), threading.Event()
        threads = []
        original = ScrollStitcher.append
        def append(stitcher, frame):
            threads.append(threading.get_ident())
            entered.set()
            release.wait(5)
            return original(stitcher, frame)
        session = self.session(137)
        grab = Mock(wraps=session.capture_frame)
        session.capture_frame = grab
        try:
            with patch.object(ScrollStitcher, "append", append):
                session._capture()
                self.wait_for(entered.is_set)
                session._capture()
                self.assertEqual(grab.call_count, 1)
                self.assertNotEqual(threads[0], threading.get_ident())
                self.assertEqual(session.stitcher.height, 600)
                release.set()
                self.wait_for(lambda: not session._pending)
        finally:
            release.set()
        self.assertEqual(session.stitcher.height, 737)

    def test_pause_resume_skips_capture_until_resumed(self):
        session = self.session(137)
        grab = Mock(wraps=session.capture_frame)
        session.capture_frame = grab
        session.toggle_pause()
        session._capture()
        grab.assert_not_called()
        session.toggle_pause()
        self.sample(session)
        self.assertEqual(session.stitcher.height, 737)

    def test_pause_discards_already_running_snapshot(self):
        session = self.session(137)
        with patch("ui.screenshot_scroll.QThreadPool.globalInstance") as pool:
            session._capture()
            job = pool.return_value.start.call_args.args[0]
            session.toggle_pause()
            job.run()
        self.app.processEvents()
        self.assertEqual(session.stitcher.height, 600)
        self.assertFalse(session._pending)
        self.assertTrue(session._paused)

    def test_undo_pauses_and_finish_does_not_reappend_removed_strip(self):
        session = self.session(137)
        self.sample(session)
        session.undo()
        self.assertTrue(session._paused)
        delivered = []
        session.completed.connect(delivered.append)
        session.finish()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].tobytes(), self.page.crop((0, 0, 800, 600)).tobytes())

    def test_live_preview_is_always_visible_updates_and_does_not_pause(self):
        session = self.session(137)
        session.show()
        self.assertTrue(session.preview.isVisible())
        before = session.preview.pixmap().cacheKey()
        self.sample(session)
        self.assertNotEqual(before, session.preview.pixmap().cacheKey())
        session.toggle_preview()
        self.assertFalse(session._paused)
        self.assertTrue(session.preview.isVisible())
        self.assertEqual(set(session.buttons), {"cancel", "done"})
        self.assertTrue(session.hint.isHidden())
        self.assertTrue(session.status.isHidden())
        self.assertTrue(all(b.text() == "" for b in session.buttons.values()))
        self.assertTrue(session.windowFlags() & Qt.WindowType.FramelessWindowHint)

    def test_finish_flushes_last_unsampled_scroll_without_extra_click(self):
        session = self.session(347)
        delivered = []
        session.completed.connect(delivered.append)
        session.finish()
        self.wait_for(lambda: bool(delivered))
        self.assertEqual(delivered[0].tobytes(), self.page.crop((0, 0, 800, 947)).tobytes())
        self.assertTrue(session._done)
        self.assertFalse(session._timer.isActive())

    def test_finish_waits_for_inflight_job_then_captures_latest_view(self):
        session = self.session(137)
        delivered = []
        session.completed.connect(delivered.append)
        with patch("ui.screenshot_scroll.QThreadPool.globalInstance") as pool:
            session._capture()
            first = pool.return_value.start.call_args.args[0]
            session.capture_frame = lambda: self.page.crop((0, 347, 800, 947))
            session.finish()
            self.assertTrue(session._finishing)
            first.run()
            self.app.processEvents()
            final = pool.return_value.start.call_args.args[0]
            self.assertIsNot(first, final)
            final.run()
            self.app.processEvents()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].tobytes(), self.page.crop((0, 0, 800, 947)).tobytes())

    def test_checkmark_during_unchanged_analysis_finishes_once(self):
        session = self.session(137)
        delivered = []
        session.completed.connect(delivered.append)
        with patch("ui.screenshot_scroll.QThreadPool.globalInstance") as pool:
            session._capture()
            job = pool.return_value.start.call_args.args[0]
            # Fixed chrome/cursor changed, but the verified scrolling body did
            # not. Finish can be clicked before this normal result arrives.
            with patch.object(job.stitcher, "append", side_effect=StitchError("scroll_unchanged")):
                session.buttons["done"].click()
                self.assertTrue(session._finishing)
                job.run()
                self.app.processEvents()
        self.assertEqual(len(delivered), 1)
        self.assertTrue(session._done)
        self.assertFalse(session._pending)
        self.assertFalse(session._timer.isActive())
        self.assertEqual(delivered[0].tobytes(), self.page.crop((0, 0, 800, 600)).tobytes())

    def test_unchanged_analysis_while_finishing_still_samples_latest_scroll(self):
        session = self.session(137)
        delivered = []
        session.completed.connect(delivered.append)
        with patch("ui.screenshot_scroll.QThreadPool.globalInstance") as pool:
            session._capture()
            first = pool.return_value.start.call_args.args[0]
            session.capture_frame = lambda: self.page.crop((0, 347, 800, 947))
            session.buttons["done"].click()
            with patch.object(first.stitcher, "append", side_effect=StitchError("scroll_unchanged")):
                first.run()
                self.app.processEvents()
            final = pool.return_value.start.call_args.args[0]
            self.assertIsNot(first, final)
            final.run()
            self.app.processEvents()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].tobytes(), self.page.crop((0, 0, 800, 947)).tobytes())

    def test_overlap_failure_does_not_finish_silently_and_can_recover(self):
        session = self.session(900)
        delivered = []
        session.completed.connect(delivered.append)
        session.finish()
        self.wait_for(lambda: not session._pending)
        self.assertEqual(delivered, [])
        self.assertFalse(session._paused)
        self.assertEqual(session._error, "scroll_finish_partial")
        session.capture_frame = lambda: self.page.crop((0, 300, 800, 900))
        self.sample(session)
        session.finish()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].tobytes(), self.page.crop((0, 0, 800, 900)).tobytes())

    def test_failed_final_can_explicitly_keep_accepted_image(self):
        session = self.session(900)
        delivered = []
        session.completed.connect(delivered.append)
        session.finish()
        self.wait_for(lambda: not session._pending)
        session.finish()
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0].height, 600)

    def test_bad_frame_logged_once_and_scroll_back_recovers(self):
        session = self.session()
        session.capture_frame = lambda: ImageChops.invert(self.page.crop((0, 137, 800, 737)))
        with patch("builtins.print") as log:
            self.sample(session)
            self.sample(session)
        self.assertEqual(log.call_count, 1)
        self.assertEqual(session.stitcher.height, 600)
        self.assertFalse(session._paused)
        session.capture_frame = lambda: self.page.crop((0, 137, 800, 737))
        self.sample(session)
        self.assertEqual(session.stitcher.height, 737)

    def test_limit_pauses_preserves_image_and_finish_remains_available(self):
        session = self.session(137)
        session.stitcher.MAX_HEIGHT = 650
        self.sample(session)
        self.assertTrue(session._paused)
        self.assertEqual(session._error, "scroll_limit")
        self.assertEqual(session.stitcher.height, 600)
        self.assertTrue(session.buttons["done"].isEnabled())
        self.assertFalse(session._timer.isActive())

    def test_cancel_stops_timers_and_discards_late_worker_result(self):
        session = self.session(137)
        delivered, cancelled = [], []
        session.completed.connect(delivered.append)
        session.cancelled.connect(lambda: cancelled.append(True))
        with patch("ui.screenshot_scroll.QThreadPool.globalInstance") as pool:
            session._capture()
            job = pool.return_value.start.call_args.args[0]
            session.close()
            job.run()
        self.assertEqual(session.stitcher.height, 600)
        self.assertEqual(cancelled, [True])
        self.assertEqual(delivered, [])
        self.assertFalse(session._timer.isActive())
        self.assertFalse(session._start_timer.isActive())

    def test_unexcluded_overlapping_toolbar_pauses_before_reading_desktop(self):
        session = self.session(137, capture_rect=QRect(-10000, -10000, 30000, 30000))
        session.capture_frame = Mock()
        session._capture()
        session.capture_frame.assert_not_called()
        self.assertTrue(session._paused)
        self.assertEqual(session._error, "scroll_toolbar_overlap")

    def test_excluded_overlapping_toolbar_does_not_block_capture(self):
        session = self.session(137, capture_rect=QRect(-10000, -10000, 30000, 30000))
        session._excluded = True
        self.sample(session)
        self.assertEqual(session.stitcher.height, 737)

    def test_affinity_requires_both_success_and_verified_exclude_value(self):
        user32 = Mock()
        user32.SetWindowDisplayAffinity.return_value = True
        def query(hwnd, pointer):
            ctypes.cast(pointer, ctypes.POINTER(ctypes.wintypes.DWORD)).contents.value = 0x11
            return True
        user32.GetWindowDisplayAffinity.side_effect = query
        self.assertTrue(exclude_capture_window(123, user32))
        user32.SetWindowDisplayAffinity.assert_called_once_with(123, 0x11)
        user32.GetWindowDisplayAffinity.side_effect = None
        self.assertFalse(exclude_capture_window(123, user32))
        user32.SetWindowDisplayAffinity.return_value = False
        self.assertFalse(exclude_capture_window(123, user32))

    def test_controls_and_status_follow_language_and_finish_is_checkmark(self):
        locale = LocaleManager("zh_CN")
        session = self.session(locale=locale)
        for language, preview, title in (("zh_CN", "实时预览", "自动拼接"),
                                        ("en", "preview", "auto stitch"),
                                        ("zh_TW", "即時預覽", "自動拼接")):
            locale.setLanguage(language)
            session.update_preview()
            self.assertIn(preview, session.preview.accessibleName())
            self.assertEqual(set(session.buttons), {"cancel", "done"})
            self.assertIn(title, session.windowTitle())
            self.assertEqual(session.buttons["done"].text(), "")
            self.assertFalse(session.buttons["done"].icon().isNull())
            self.assertNotIn("scroll_append", session.buttons)
            self.assertNotIn("追加", session.hint.text())

    def test_small_auto_updates_do_not_hit_former_50_frame_limit(self):
        page = content(width=40, height=800)
        from ui.screenshot_tools import ScrollStitcher
        stitcher = ScrollStitcher(page.crop((0, 0, 40, 100)))
        for offset in range(1, 61):
            stitcher.append(page.crop((0, offset, 40, offset + 100)))
        self.assertEqual(stitcher.height, 160)
        self.assertEqual(stitcher.render().tobytes(), page.crop((0, 0, 40, 160)).tobytes())
