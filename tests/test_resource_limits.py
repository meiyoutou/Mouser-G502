import os
import threading
import unittest
from unittest.mock import Mock, patch

from core import compute_limits
from core.bundle_policy import unused_runtime_file


class ComputeLimitTests(unittest.TestCase):
    def setUp(self):
        self.saved = compute_limits._libraries
        compute_limits._libraries = None
        self.addCleanup(setattr, compute_limits, "_libraries", self.saved)

    def test_imports_are_limited_then_environment_restored_and_cached(self):
        cv, np = Mock(), Mock()
        observed = []
        def load(name):
            observed.append((name, os.environ["OPENBLAS_NUM_THREADS"],
                             compute_limits.child_environment().get("OPENBLAS_NUM_THREADS")))
            return {"numpy": np, "cv2": cv}[name]
        with patch.dict(os.environ, {"OPENBLAS_NUM_THREADS": "12"}, clear=False), \
                patch.object(compute_limits.importlib, "import_module", side_effect=load) as loader:
            result = compute_limits.registration_libraries()
            self.assertEqual(result, (cv, np))
            self.assertIs(compute_limits.registration_libraries(), result)
            self.assertEqual(loader.call_count, 2)
            self.assertEqual(os.environ["OPENBLAS_NUM_THREADS"], "12")
        self.assertEqual(observed, [("numpy", "1", "12"), ("cv2", "1", "12")])
        cv.setNumThreads.assert_called_once_with(2)

    def test_failed_import_restores_absent_variables(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("OPENBLAS_")}
        with patch.dict(os.environ, env, clear=True), \
                patch.object(compute_limits.importlib, "import_module", side_effect=ImportError("test")):
            with self.assertRaises(ImportError):
                compute_limits.registration_libraries()
            self.assertNotIn("OPENBLAS_NUM_THREADS", os.environ)
            self.assertNotIn("OPENBLAS_DEFAULT_NUM_THREADS", os.environ)
            self.assertIsNone(compute_limits._libraries)
            self.assertIsNone(compute_limits._original_environment)

    def test_concurrent_speech_snapshot_never_inherits_temporary_limit(self):
        importing, release, snapshot_started = threading.Event(), threading.Event(), threading.Event()
        snapshots, errors = [], []
        cv = Mock()
        def load(name):
            if name == "numpy":
                importing.set()
                if not release.wait(5):
                    raise TimeoutError("test release")
            return cv if name == "cv2" else Mock()
        def initialize():
            try:
                compute_limits.registration_libraries()
            except Exception as error:
                errors.append(error)
        def snapshot():
            snapshot_started.set()
            snapshots.append(compute_limits.child_environment())
        with patch.dict(os.environ, {"OPENBLAS_NUM_THREADS": "9"}), \
                patch.object(compute_limits.importlib, "import_module", side_effect=load):
            worker = threading.Thread(target=initialize)
            helper = threading.Thread(target=snapshot)
            worker.start()
            try:
                self.assertTrue(importing.wait(5))
                helper.start()
                self.assertTrue(snapshot_started.wait(5))
            finally:
                release.set()
                worker.join(5)
                if helper.ident:
                    helper.join(5)
            self.assertFalse(worker.is_alive())
            self.assertFalse(helper.is_alive())
            self.assertFalse(errors)
            self.assertEqual(snapshots[0]["OPENBLAS_NUM_THREADS"], "9")


class BundlePolicyTests(unittest.TestCase):
    def test_only_unused_video_avif_and_controls_styles_are_trimmed(self):
        for name in (
            "cv2/opencv_videoio_ffmpeg500_64.dll", "PIL/_avif.cp313-win_amd64.pyd",
            "PIL/AvifImagePlugin.py", r"PySide6\qml\QtQuick\Controls\FluentWinUI3\Button.qml",
            "PySide6/qml/QtQuick/Controls/Fusion/impl/plugin.dll",
        ):
            with self.subTest(name=name):
                self.assertTrue(unused_runtime_file(name))
        for name in (
            "cv2/cv2.pyd", "numpy.libs/libscipy_openblas64_test.dll", "PIL/_imaging.cp313.pyd",
            "PIL/JpegImagePlugin.py", "PySide6/QtOpenGL.pyd",
            "PySide6/qml/QtQuick/Controls/Material/impl/plugin.dll",
            "PySide6/qml/QtQuick/Controls/Basic/Button.qml",
            "PySide6/qml/QtQuick/Controls/impl/plugin.dll",
            "PySide6/qml/QtQuick/Controls/qmldir", "PySide6/Qt6Widgets.dll",
            "PySide6/plugins/imageformats/qjpeg.dll", "libcrypto-3.dll", "libssl-3.dll",
        ):
            with self.subTest(name=name):
                self.assertFalse(unused_runtime_file(name))
