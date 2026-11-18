import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops
from core.scroll_compute import StitchError, _write_all
from ui.screenshot_registration import RegistrationStitcher

ROOT = Path(__file__).resolve().parents[1]


class ScrollComputeTests(unittest.TestCase):
    def setUp(self):
        self.page = Image.effect_noise((320, 1800), 50).convert("RGB")
        self.stitcher = RegistrationStitcher(self.frame(0), isolated=True, detect_content=True)

    def tearDown(self):
        self.stitcher.close()
        process = self.stitcher._compute.process
        if process is not None:
            process.wait(timeout=5)

    def frame(self, y):
        return self.page.crop((0, y, 320, y + 600))

    def test_is_lazy_and_child_output_matches_original_with_undo(self):
        self.assertIsNone(self.stitcher._compute.process)
        expected = RegistrationStitcher(self.frame(0), detect_content=True)
        for offset in (137, 347, 210, 510):
            self.assertEqual(self.stitcher.append(self.frame(offset)), expected.append(self.frame(offset)))
            self.assertEqual(self.stitcher.render().tobytes(), expected.render().tobytes())
        self.assertNotEqual(self.stitcher._compute.process.pid, os.getpid())
        for _ in range(2):
            self.assertEqual(self.stitcher.undo(), expected.undo())
            self.assertEqual(self.stitcher.render().tobytes(), expected.render().tobytes())

    def test_rejection_retains_pixels_and_worker_can_continue(self):
        before = self.stitcher.render().tobytes()
        with self.assertRaisesRegex(StitchError, "scroll_overlap"):
            self.stitcher.append(ImageChops.invert(self.frame(137)))
        self.assertEqual(before, self.stitcher.render().tobytes())
        self.assertEqual(self.stitcher.append(self.frame(137)), 137)

    def test_child_crash_can_restart_without_losing_accepted_image(self):
        self.stitcher.append(self.frame(137))
        process = self.stitcher._compute.process
        process.terminate()
        process.wait(timeout=5)
        self.assertEqual(self.stitcher.append(self.frame(347)), 210)
        self.assertNotEqual(process.pid, self.stitcher._compute.process.pid)
        process.stdin.close()
        process.stdout.close()

    def test_timeout_returns_control_without_changing_original_pixels(self):
        self.stitcher.append(self.frame(137))
        original = self.stitcher.render().tobytes()
        # A stopped/blocked worker must not leave the UI worker thread forever.
        with patch.object(self.stitcher._compute, "TIMEOUT", .001):
            with self.assertRaises(StitchError):
                self.stitcher._compute.query("register", self.frame(137), self.frame(347))
        self.assertEqual(self.stitcher.render().tobytes(), original)

    def test_close_reaps_owned_child_and_forbids_relaunch(self):
        self.stitcher.append(self.frame(137))
        process = self.stitcher._compute.process
        self.stitcher.close()
        process.wait(timeout=5)
        with self.assertRaises(StitchError):
            self.stitcher.append(self.frame(347))

    def test_fresh_parent_never_imports_compute_libraries(self):
        code = """
import json, sys
from PIL import Image
from ui.screenshot_registration import RegistrationStitcher
page = Image.effect_noise((320, 1600), 50).convert("RGB")
s = RegistrationStitcher(page.crop((0, 0, 320, 600)), isolated=True)
assert s.append(page.crop((0, 137, 320, 737))) == 137
p = s._compute.process
s.close()
p.wait(timeout=5)
assert all(name not in sys.modules for name in ("numpy", "cv2", "PySide6"))
print(json.dumps({"ok": True, "child_exited": p.poll() is not None}))
"""
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                                text=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["child_exited"])

    def test_parent_pipe_close_exits_helper_without_error_dialog(self):
        process = subprocess.Popen([sys.executable, "-m", "core.scroll_compute"],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            # Simulate the parent disappearing while a frame is being matched.
            process.stdout.close()
            _write_all(process.stdin, b'{"method":"register","width":320,"height":600}\n')
            _write_all(process.stdin, self.frame(0).tobytes())
            _write_all(process.stdin, self.frame(137).tobytes())
            process.stdin.close()
            self.assertEqual(process.wait(timeout=10), 0)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
