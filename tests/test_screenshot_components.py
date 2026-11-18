"""Optional engines: isolated data, pinned ZIPs, cancellation and no auto network."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget
from core import screenshot_components as components
from ui.locale_manager import LocaleManager
from ui import screenshot_components as dialogs


class ComponentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.environment = patch.dict(os.environ, {"MOUSER_SCREENSHOT_COMPONENT_DIR": str(self.root / "installed")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.assets = {}
        self.archive = self.make_archive("one", {"module.py": b"public engine"})
        self.catalog = patch.object(components, "catalog", return_value=self.assets)
        self.catalog.start()
        self.addCleanup(self.catalog.stop)
        self.supported = patch.object(components, "_supported")
        self.supported.start()
        self.addCleanup(self.supported.stop)

    def make_archive(self, label, files, *, manifest=None):
        archive = self.root / (label + ".zip")
        manifest = manifest or {"files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
        manifest = json.dumps(manifest).encode()
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
            for name, data in files.items():
                bundle.writestr(name, data)
            bundle.writestr("manifest.json", manifest)
        for kind in components.KINDS:
            self.assets[kind] = {
                "id": kind + "-test", "python_abi": "cp313", "name": archive.name,
                "url": "https://example.test/engine.zip", "available_online": False,
                "size": archive.stat().st_size,
                "expanded_size": len(manifest) + sum(map(len, files.values())),
                "sha256": components.digest(archive),
                "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
            }
        return archive

    def test_missing_component_lookup_never_downloads_or_creates_files(self):
        with patch.object(components, "download") as download:
            self.assertIsNone(components.checked_directory("scroll"))
            self.assertFalse(components.data_directory().exists())
            download.assert_not_called()

    def test_local_first_install_survives_app_path_change_and_uninstall_is_scoped(self):
        unrelated = self.root / "config.json"
        unrelated.write_text("personal")
        with patch.object(components, "download") as download:
            target = components.install("scroll", roots=[self.root])
            download.assert_not_called()
        self.assertEqual(components.checked_directory("scroll"), target)
        self.assertEqual((target / "module.py").read_bytes(), b"public engine")
        with patch("sys.executable", str(self.root / "new-app/Mouser.exe")):
            self.assertEqual(components.checked_directory("scroll"), target)
        components.uninstall("scroll")
        self.assertFalse(target.exists())
        self.assertEqual(unrelated.read_text(), "personal")

    def test_online_download_is_opt_in_and_verified(self):
        self.assets["scroll"]["available_online"] = True
        with patch.object(components, "download", return_value=self.archive) as download:
            result = components.install("scroll", roots=[])
        download.assert_called_once()
        self.assertEqual(components.checked_directory("scroll"), result)

    def test_unpublished_asset_reports_offline_option_without_network(self):
        with patch.object(components, "download") as download:
            with self.assertRaisesRegex(components.ComponentError, "not_published"):
                components.install("text", roots=[])
            download.assert_not_called()

    def test_tampering_or_extra_executable_invalidates_install(self):
        target = components.install("scroll", self.archive)
        (target / "injected.py").write_text("bad")
        self.assertIsNone(components.checked_directory("scroll"))
        (target / "injected.py").unlink()
        (target / "module.py").write_text("bad")
        self.assertIsNone(components.checked_directory("scroll"))

    def test_wrong_archive_preserves_existing_install(self):
        target = components.install("text", self.archive)
        original = (target / "module.py").read_bytes()
        invalid = self.root / "bad.zip"
        invalid.write_bytes(b"not official")
        with self.assertRaisesRegex(components.ComponentError, "checksum"):
            components.install("text", invalid)
        self.assertEqual((target / "module.py").read_bytes(), original)
        self.assertEqual(components.checked_directory("text"), target)

    def test_cancel_during_staging_preserves_existing_install(self):
        target = components.install("text", self.archive)
        event = threading.Event()
        def phase(value):
            if value == "install":
                event.set()
        with self.assertRaisesRegex(components.ComponentError, "cancelled"):
            components.install("text", self.archive, phase=phase, cancel_event=event)
        self.assertEqual(components.checked_directory("text"), target)
        self.assertFalse(list(target.parent.glob(".install-*")))

    def test_failed_atomic_replacement_rolls_back(self):
        target = components.install("scroll", self.archive)
        original_replace = os.replace
        def replace(source, destination):
            if Path(source).name == "new":
                raise OSError("test replacement failure")
            return original_replace(source, destination)
        with patch.object(components.os, "replace", side_effect=replace):
            with self.assertRaises(OSError):
                components.install("scroll", self.archive)
        self.assertEqual(components.checked_directory("scroll"), target)

    def test_active_engine_blocks_replacement_and_removal_not_other_component(self):
        target = components.install("scroll", self.archive)
        with components.using("scroll"):
            with self.assertRaisesRegex(components.ComponentError, "busy"):
                components.uninstall("scroll")
            with self.assertRaisesRegex(components.ComponentError, "busy"):
                components.install("scroll", self.archive)
            components.install("text", self.archive)
        self.assertEqual(components.checked_directory("scroll"), target)
        components.uninstall("scroll")

    def test_unsafe_archive_paths_rejected_before_extraction(self):
        for i, name in enumerate(("../outside.py", "/root.py", "C:/bad.py", "a\\b.py", "a/../b.py")):
            archive = self.make_archive("bad" + str(i), {name: b"bad"})
            with self.assertRaises(components.ComponentError):
                components.install("text", archive)
        self.assertFalse((self.root / "outside.py").exists())

    def test_symlink_directory_cannot_redirect_uninstall(self):
        target = components.install("text", self.archive)
        with patch.object(Path, "is_symlink", side_effect=lambda: True):
            with self.assertRaises(components.ComponentError):
                components.uninstall("text")
        self.assertTrue(target.exists())

    def test_explicit_legacy_import_copies_verified_files_without_deleting_source(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        with zipfile.ZipFile(self.archive) as bundle:
            bundle.extractall(legacy)  # Only this test's known, safe fixture.
        with patch.object(components, "legacy_text_directory", return_value=legacy), \
                patch.object(components, "download") as download:
            result = components.install("text", roots=[])
        download.assert_not_called()
        self.assertEqual(components.checked_directory("text"), result)
        self.assertTrue((legacy / "module.py").exists())

    def test_frozen_scroll_activation_requires_verified_component(self):
        with patch("sys.frozen", True, create=True):
            with self.assertRaisesRegex(components.ComponentError, "scroll_component_missing"):
                components.activate_scroll()

    def test_mutation_blocks_new_job_without_blocking_unrelated_job(self):
        with components._mutation("text"):
            with self.assertRaisesRegex(components.ComponentError, "busy"):
                with components.using("text"):
                    pass
            with components.using("scroll"):
                self.assertEqual(components._ACTIVE["scroll"], 1)
        self.assertEqual(components._ACTIVE["scroll"], 0)


class ComponentDialogTests(ComponentTests):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        super().setUp()
        self.locale = LocaleManager("zh_CN")
        self.dialog = dialogs.ComponentDialog(self.locale)
        self.addCleanup(self.dialog.close)

    def wait(self):
        deadline = time.monotonic() + 5
        while self.dialog.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertFalse(self.dialog.busy)

    def test_dialog_opens_without_installing_and_updates_language(self):
        with patch.object(components, "install") as install:
            self.dialog.show()
            self.app.processEvents()
            install.assert_not_called()
        self.assertEqual(self.dialog.windowTitle(), "截图组件")
        self.locale.setLanguage("en")
        self.assertEqual(self.dialog.windowTitle(), "Screenshot components")
        self.locale.setLanguage("zh_TW")
        self.assertEqual(self.dialog.windowTitle(), "截圖元件")

    def test_offline_import_is_async_and_emits_success(self):
        events = []
        self.dialog.installed.connect(events.append)
        with patch.object(components, "download") as download:
            self.dialog.begin(str(self.archive))
            self.wait()
            download.assert_not_called()
        self.assertEqual(events, ["scroll"])
        self.assertIsNotNone(components.checked_directory("scroll"))

    def test_missing_text_opens_manager_only_not_network_or_automatic_install(self):
        owner = QWidget()
        self.addCleanup(owner.close)
        with patch("core.text_selection.checked_runtime", return_value=None), \
                patch.object(dialogs, "open_manager", return_value=self.dialog) as manager, \
                patch.object(components, "install") as install:
            self.assertFalse(dialogs.ensure_component("text", owner, self.locale, lambda: None))
        manager.assert_called_once()
        install.assert_not_called()
        self.assertEqual(len(self.dialog._callbacks), 1)
        self.dialog.close()
        self.assertFalse(self.dialog._callbacks)

    def test_repeated_feature_click_registers_one_resume(self):
        owner = QWidget()
        self.addCleanup(owner.close)
        with patch("core.text_selection.checked_runtime", return_value=None), \
                patch.object(dialogs, "open_manager", return_value=self.dialog):
            for _ in range(3):
                dialogs.ensure_component("text", owner, self.locale, lambda: None)
        self.assertEqual(len(self.dialog._callbacks), 1)

    def test_install_failure_leaves_other_controls_usable(self):
        with patch.object(components, "install", side_effect=components.ComponentError("checksum")):
            self.dialog.begin(str(self.archive))
            self.wait()
        self.assertIn("校验失败", self.dialog.state.text())
        self.assertTrue(self.dialog.choice.isEnabled())
        self.assertTrue(self.dialog.import_button.isEnabled())

    def test_escape_cancels_busy_install_without_hiding_or_auto_resume(self):
        entered, release = threading.Event(), threading.Event()
        def install(*args, cancel_event=None, **kwargs):
            entered.set()
            release.wait(5)
            components.cancelled(cancel_event)
        with patch.object(components, "install", side_effect=install):
            self.dialog.show()
            self.dialog.begin(str(self.archive))
            self.assertTrue(entered.wait(2))
            self.dialog.reject()
            self.assertTrue(self.dialog._cancel.is_set())
            self.assertTrue(self.dialog.isVisible())
            release.set()
            self.wait()
        self.assertFalse(self.dialog.isVisible())
        self.assertIsNone(components.checked_directory("scroll"))


if __name__ == "__main__":
    unittest.main()
