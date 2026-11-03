"""Synthetic security/install tests; no network, microphone, or user config."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, Mock
import zipfile

from core import speech_components as components
from core import speech_models as models


class Response(io.BytesIO):
    def __init__(self, data, url="https://example.invalid/model", length=None):
        super().__init__(data)
        self.url = url
        self.headers = {"Content-Length": str(len(data) if length is None else length)}
    def geturl(self):
        return self.url


class ComponentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="mouser-component-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def asset(self, data):
        return {"name": "model.zip", "url": "https://example.invalid/model.zip",
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def test_streamed_download_verifies_size_hash_and_progress(self):
        data, progress = b"safe" * 1024, []
        path = self.root / "download.zip"
        components.download(self.asset(data), path, progress=lambda *value: progress.append(value),
                            opener=lambda *a, **k: Response(data))
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(progress[-1], (len(data), len(data)))

    def test_non_https_addresses_and_responses_are_rejected(self):
        asset = self.asset(b"safe")
        for change in ("address", "response"):
            with self.subTest(change=change):
                copy = {**asset, **({"url": "http://example.invalid"} if change == "address" else {})}
                with self.assertRaises(components.ComponentError):
                    components.download(copy, self.root / "file", opener=lambda *a, **k: Response(b"safe", "http://example.invalid"))
        self.assertFalse((self.root / "file").exists())

    def test_download_uses_available_chunks_for_responsive_cancellation(self):
        data = b"safe" * 1024
        cancel = threading.Event()
        class SlowResponse(Response):
            def read(self, *args):
                raise AssertionError("A full buffered read could delay cancellation")
            def read1(self, *args):
                return io.BytesIO.read(self, 4)
        def progress(*args):
            cancel.set()
        with self.assertRaises(components.ComponentError) as raised:
            components.download(self.asset(data), self.root / "slow.zip", cancel_event=cancel,
                                progress=progress, opener=lambda *a, **k: SlowResponse(data))
        self.assertEqual(raised.exception.code, "cancelled")
        self.assertFalse((self.root / "slow.zip").exists())

    def test_redirect_downgrade_is_blocked(self):
        with self.assertRaises(components.ComponentError):
            components._HTTPSRedirects().redirect_request(Mock(), None, 302, "", {}, "http://example.invalid")

    def test_bad_checksum_retries_without_leaving_partial_download(self):
        opener = Mock(side_effect=lambda *a, **k: Response(b"evil"))
        with patch.object(components.time, "sleep"), self.assertRaises(components.ComponentError):
            components.download(self.asset(b"safe"), self.root / "bad.zip", opener=opener)
        self.assertEqual(opener.call_count, 3)
        self.assertFalse((self.root / "bad.zip").exists())

    def test_cancel_during_download_removes_temporary_file(self):
        cancel = threading.Event()
        class Cancelling(Response):
            def read1(self, *args):
                cancel.set()
                return super().read1(*args)
        with self.assertRaises(components.ComponentError) as raised:
            components.download(self.asset(b"safe"), self.root / "cancel.zip", cancel_event=cancel,
                                opener=lambda *a, **k: Cancelling(b"safe"))
        self.assertEqual(raised.exception.code, "cancelled")
        self.assertFalse((self.root / "cancel.zip").exists())

    def test_truncated_and_oversized_downloads_are_rejected(self):
        for data in (b"s", b"safee"):
            with patch.object(components.time, "sleep"), self.assertRaises(components.ComponentError):
                components.download(self.asset(b"safe"), self.root / "size.zip",
                                    opener=lambda *a, **k: Response(data, length=4))
        self.assertFalse((self.root / "size.zip").exists())

    def runtime_pack(self, extra=None):
        files = {"MouserSpeech.exe": b"synthetic executable", "_internal/library.dll": b"synthetic DLL"}
        if extra:
            files.update(extra)
        archive = self.root / "runtime.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for name, data in files.items():
                z.writestr(name, data)
        value = archive.read_bytes()
        asset = {**self.asset(value), "expanded_size": sum(len(data) for data in files.values()),
                 "exe_sha256": hashlib.sha256(files["MouserSpeech.exe"]).hexdigest()}
        return archive, asset

    def test_runtime_install_is_version_pinned_and_has_no_user_data(self):
        archive, asset = self.runtime_pack()
        destination = self.root / "installed"
        components.install_runtime(archive, asset, destination=destination)
        marker = json.loads((destination / "mouser-runtime.json").read_text())
        self.assertEqual(marker, {"protocol": 1, "archive_sha256": asset["sha256"]})
        self.assertEqual((destination / "MouserSpeech.exe").read_bytes(), b"synthetic executable")
        self.assertFalse(list(self.root.glob(".speech-runtime-*")))

    def test_runtime_zip_slip_and_unexpected_files_are_rejected(self):
        for name in ("../escape.exe", "/absolute.exe", "C:/drive.exe", "config.json", "plugin.exe"):
            archive, asset = self.runtime_pack({name: b"bad"})
            with self.subTest(name=name), self.assertRaises(ValueError):
                components.install_runtime(archive, asset, destination=self.root / "installed")
        self.assertFalse((self.root / "installed").exists())

    def test_runtime_cancel_and_bad_executable_preserve_existing_files(self):
        archive, asset = self.runtime_pack()
        destination = self.root / "installed"
        destination.mkdir()
        (destination / "MouserSpeech.exe").write_bytes(b"old valid version")
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(components.ComponentError):
            components.install_runtime(archive, asset, destination=destination, cancel_event=cancel)
        with self.assertRaises(components.ComponentError):
            components.install_runtime(archive, {**asset, "exe_sha256": "0" * 64}, destination=destination)
        self.assertEqual((destination / "MouserSpeech.exe").read_bytes(), b"old valid version")

    def test_runtime_commit_failure_rolls_back_previous_version(self):
        archive, asset = self.runtime_pack()
        destination = self.root / "installed"
        components.install_runtime(archive, asset, destination=destination)
        real_replace = components.os.replace
        def replace(source, target):
            if Path(source).name == "new":
                raise OSError("synthetic commit failure")
            return real_replace(source, target)
        with patch.object(components.os, "replace", side_effect=replace), self.assertRaises(OSError):
            components.install_runtime(archive, asset, destination=destination)
        self.assertEqual((destination / "MouserSpeech.exe").read_bytes(), b"synthetic executable")

    def test_already_installed_selection_skips_download_and_runtime_install(self):
        status = [{"id": item, "installed": True, "vad_installed": True} for item in models.CATALOG]
        with patch.object(components.sys, "platform", "win32"), \
             patch.object(components.platform, "machine", return_value="AMD64"), \
             patch.object(models, "catalog_status", return_value=status), \
             patch.object(models, "model_directory", return_value=self.root / "models"), \
             patch.object(components, "model_directory", return_value=self.root / "models"), \
             patch.object(components, "runtime_executable", return_value=self.root / "worker.exe"), \
             patch.object(components, "download") as download:
            self.assertEqual(components.install_selection("sensevoice", True, assets={}), "sensevoice")
            download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
