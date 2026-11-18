import ast
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PIL import Image, ImageChops
from PySide6.QtCore import QObject, QRect
from PySide6.QtWidgets import QApplication

from ui.locale_manager import LocaleManager
from ui.screenshot_diagnostics import PrivateScrollTrace, ScrollDiagnosticWindow, DiagnosticController
from ui.screenshot_overlay import IntRect
from ui.windows_screenshot import VirtualCapture, MonitorMap


class ScrollDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mous-diag-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def trace(self):
        first = Image.new("RGB", (320, 400), "white")
        first.paste("#c6d9eb", (0, 0, 150, 400))
        return PrivateScrollTrace(self.root / "private", first, (160, 10, 310, 390))

    def test_no_consent_no_capture_no_private_directory(self):
        window = ScrollDiagnosticWindow(self.root / "private")
        with patch("ui.screenshot_diagnostics.capture_virtual_desktop") as grab:
            window.begin()
            self.app.processEvents()
            grab.assert_not_called()
        self.assertFalse(window._busy)
        self.assertFalse(window.start_button.isEnabled())
        self.assertFalse((self.root / "private").exists())
        window.close()

    def test_record_whole_selection_before_candidate_crop_and_cap(self):
        trace = self.trace()
        trace._writer.submit(lambda: None).result(5)
        for index in range(12):
            trace.latest = Image.new("RGB", (320, 400), (index, index, index))
            trace.observe({"reason": "scroll_overlap", "extra_rows": 0})
            trace._writer.submit(lambda: None).result(5)
        trace.finish(outcome="cancelled").result(5)
        report = json.loads((trace.directory / "trace.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["frames"]), 8)
        self.assertEqual(report["frames"][0]["reason"], "initial")
        self.assertEqual(report["candidate_rect"], [160, 10, 310, 390])
        first = Image.open(trace.directory / "frame-00.png")
        self.assertEqual(first.size, (320, 400))
        self.assertEqual(first.getpixel((10, 10)), (198, 217, 235))  # fixed pane retained
        self.assertEqual(report["outcome"], "cancelled")
        self.assertFalse((trace.directory / "result.png").exists())
        self.assertFalse(report["config_loaded"])
        self.assertFalse(report["clipboard_changed"])
        self.assertFalse(report["input_injected"])
        self.assertFalse(report["uploaded"])

    def test_idle_ignored_finish_idempotent_and_late_results_not_written(self):
        trace = self.trace()
        trace.observe({"reason": "scroll_unchanged"})
        first = trace.finish()
        self.assertIs(first, trace.finish())
        first.result(5)
        trace.observe({"reason": "scroll_overlap"})
        self.assertEqual(len(list(trace.directory.glob("frame-*.png"))), 1)

    def test_limits_and_invalid_rect_do_not_create_output(self):
        for image, rect in (
            (SimpleNamespace(width=10_000_001, height=1), (0, 0, 1, 1)),
            (Image.new("RGB", (100, 100)), (-1, 0, 100, 100)),
        ):
            with self.assertRaises(ValueError):
                PrivateScrollTrace(self.root / "private", image, rect)
        self.assertFalse((self.root / "private").exists())

    def test_writer_failure_is_reported_without_changing_matching(self):
        trace = self.trace()
        trace._writer.submit(lambda: None).result(5)
        frame = Mock()
        frame.save.side_effect = OSError("private path must not enter report")
        trace.latest = frame
        trace.observe({"reason": None, "extra_rows": 137})
        trace.finish().result(5)
        report = (trace.directory / "trace.json").read_text(encoding="utf-8")
        self.assertIn("OSError", report)
        self.assertNotIn("private path", report)

    def test_controller_captures_manual_region_once_then_crops_candidate(self):
        image = Image.new("RGB", (320, 400), "white")
        image.paste("#a2c3dd", (0, 0, 150, 400))
        bounds = IntRect(0, 0, 320, 400)
        physical = IntRect(40, 20, 300, 380)
        candidate = IntRect(100, 50, 280, 350)
        maps = (MonitorMap(bounds, bounds),)
        capture = VirtualCapture(image, bounds, maps)
        controller = DiagnosticController(self.root / "private", LocaleManager("zh_CN"))
        probe = QObject()
        probe.cancel = Mock()
        controller._scroll_probe = probe
        live = image.crop((physical.left, physical.top, physical.right, physical.bottom))
        with patch.object(controller, "_capture_scroll_frame", return_value=live) as grab:
            controller._open_scroll_session(capture, "", QRect(40, 20, 260, 360),
                                            physical, probe, candidate)
            session = controller._scroll_session
            self.assertIsNotNone(session)
            session._start_timer.stop()
            frame = session.capture_frame()
            grab.assert_called_once_with(physical, maps)
            self.assertEqual(frame.size, (180, 300))
            self.assertEqual(controller.trace.latest.size, (260, 360))
            self.assertTrue(session.stitcher.detect_content)
            session.close()
            controller.trace.completion.result(5)
        report = json.loads((controller.trace.directory / "trace.json").read_text(encoding="utf-8"))
        self.assertEqual(report["candidate_rect"], [60, 30, 240, 330])
        seed = Image.open(controller.trace.directory / "frame-00.png").convert("RGB")
        self.assertIsNone(ImageChops.difference(seed, live).getbbox())
        self.app.processEvents()

    def test_diagnostic_entry_precedes_configuration_logging_and_hid_imports(self):
        source = (Path(__file__).parents[1] / "main_qml.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        entry = min(node.lineno for node in ast.walk(tree) if isinstance(node, ast.If)
                    and "--diagnose-scroll" in ast.get_source_segment(source, node.test))
        protected = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                     and node.module in {"core.engine", "core.config", "core.log_setup"}]
        self.assertLess(entry, min(protected))


if __name__ == "__main__":
    unittest.main()
