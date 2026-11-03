"""Optional model/edition tests; use tiny artificial assets, no private data."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

from core import speech_models as models
from core.speech_session import resolve_engine, SPEECH_DEFAULTS
from ui.speech_to_text import SpeechToTextController, describe_runtime
from core.key_simulator import SPEECH_TO_TEXT_ACTION


class OptionalSpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mouser-model-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.installed = self.root / "source", self.root / "installed"
        self.source.mkdir()
        self.data = {"silero_vad.onnx": b"tiny vad", "sense-test/model.int8.onnx": b"tiny model",
                     "sense-test/tokens.txt": b"tiny tokens"}
        self.assets = {key: (len(value), hashlib.sha256(value).hexdigest()) for key, value in self.data.items()}
        self.catalog = {"sensevoice": {"name": "SenseVoice test", "folder": "sense-test",
                                      "engine": "sense_voice", "note": "speech.recommend_sensevoice"}}
        self.addCleanup(patch.stopall)
        patch.object(models, "ASSETS", self.assets).start()
        patch.object(models, "CATALOG", self.catalog).start()
        for name, value in self.data.items():
            file = self.source / name
            file.parent.mkdir(exist_ok=True)
            file.write_bytes(value)
        (self.source / "NOTICE.md").write_text("Synthetic test assets only", encoding="utf-8")
        self.archive = self.root / "model.zip"
        models.create_pack("sensevoice", self.source, self.archive)

    def rewrite(self, change):
        with zipfile.ZipFile(self.archive) as z:
            data = {item.filename: z.read(item) for item in z.infolist()}
        change(data)
        with zipfile.ZipFile(self.archive, "w", zipfile.ZIP_DEFLATED) as z:
            for name, value in data.items():
                z.writestr(name, value)

    def test_pack_contains_only_known_assets_and_not_personal_config(self):
        with zipfile.ZipFile(self.archive) as z:
            self.assertEqual(set(z.namelist()), set(self.data) | {models.PACK_MANIFEST, "NOTICE.md"})

    def test_import_verifies_and_installs_with_progress(self):
        progress = []
        self.assertEqual(models.install_pack(self.archive, self.installed, progress.append), "sensevoice")
        for name, value in self.data.items():
            self.assertEqual((self.installed / name).read_bytes(), value)
        self.assertEqual(progress[-1], 100)
        self.assertFalse(list(self.installed.glob(".model-install-*")))

    def test_corruption_preserves_old_model_and_shared_vad(self):
        models.install_pack(self.archive, self.installed)
        self.rewrite(lambda data: data.update({"sense-test/model.int8.onnx": b"fake model"}))
        with self.assertRaises(models.ModelPackError):
            models.install_pack(self.archive, self.installed)
        self.assertEqual((self.installed / "sense-test/model.int8.onnx").read_bytes(), b"tiny model")
        self.assertEqual((self.installed / "silero_vad.onnx").read_bytes(), b"tiny vad")

    def test_self_advertised_hash_cannot_replace_pinned_asset(self):
        def alter(data):
            value = b"evil model"
            data["sense-test/model.int8.onnx"] = value
            manifest = json.loads(data[models.PACK_MANIFEST])
            manifest["files"]["sense-test/model.int8.onnx"] = {"size": len(value), "sha256": hashlib.sha256(value).hexdigest()}
            data[models.PACK_MANIFEST] = json.dumps(manifest).encode()
        self.rewrite(alter)
        with self.assertRaises(models.ModelPackError):
            models.install_pack(self.archive, self.installed)

    def test_zip_slip_extra_executable_and_absolute_paths_rejected(self):
        for name in ("../escaped.txt", "C:/escaped.txt", "/escaped.txt", "extra.exe", "a\\b"):
            with self.subTest(name=name):
                original = self.archive.read_bytes()
                self.rewrite(lambda data: data.update({name: b"extra"}))
                with self.assertRaises(models.ModelPackError):
                    models.install_pack(self.archive, self.installed)
                self.archive.write_bytes(original)
        self.assertFalse((self.root / "escaped.txt").exists())

    def test_duplicate_entries_rejected(self):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with zipfile.ZipFile(self.archive, "a") as z:
                z.writestr("NOTICE.md", b"duplicate")
        with self.assertRaises(models.ModelPackError):
            models.install_pack(self.archive, self.installed)

    def test_disk_space_failure_does_not_replace_models(self):
        with patch.object(models.shutil, "disk_usage", return_value=SimpleNamespace(free=1)):
            with self.assertRaises(models.ModelPackError):
                models.install_pack(self.archive, self.installed)
        self.assertFalse((self.installed / "sense-test").exists())

    def test_commit_failure_rolls_back_entire_old_pack(self):
        models.install_pack(self.archive, self.installed)
        replace = models.os.replace
        def fail(source, target):
            if Path(source).name == "silero_vad.onnx" and Path(source).parent.name.startswith(".model-install-"):
                raise OSError("simulated locked file")
            return replace(source, target)
        with patch.object(models.os, "replace", side_effect=fail):
            with self.assertRaises(OSError):
                models.install_pack(self.archive, self.installed)
        for name, value in self.data.items():
            self.assertEqual((self.installed / name).read_bytes(), value)

    def test_external_model_location_is_discovered_without_config_edit(self):
        models.install_pack(self.archive, self.installed)
        with patch.dict(os.environ, {"MOUSER_SPEECH_MODEL_DIR": str(self.installed)}):
            status = models.catalog_status()[0]
            self.assertTrue(status["installed"])
            self.assertTrue(status["vad_installed"])

    def test_auto_does_not_route_english_to_chinese_only_zipformer(self):
        def available(name, *args, **kwargs):
            return Path("stream") if name == models.STREAMING_MODEL else None
        with patch("core.speech_session.bundled_path", side_effect=available):
            self.assertEqual(resolve_engine({"engine": "auto", "language": "en"}), "none")
            self.assertEqual(resolve_engine({"engine": "auto", "language": "zh"}), "sherpa_onnx_streaming")

    def test_no_model_is_expected_state_not_fake_whisper_ready(self):
        with patch("core.speech_session.bundled_path", return_value=None), patch("ui.speech_to_text.bundled_path", return_value=None):
            status = describe_runtime({"engine": "auto"})
        self.assertEqual(status["engine"], "none")
        self.assertFalse(status["ready"])

    def test_missing_model_or_lite_never_starts_recording_worker(self):
        for status in ({"enabled": False, "ready": False}, {"enabled": True, "ready": False}):
            control = SimpleNamespace(_settings=lambda: dict(SPEECH_DEFAULTS), _last_request_at=0,
                                      _busy=False, _status=Mock())
            with patch("ui.speech_to_text.describe_runtime", return_value=status), patch("ui.speech_to_text.threading.Thread") as worker:
                SpeechToTextController._handle_request(control, SPEECH_TO_TEXT_ACTION)
                worker.assert_not_called()
            self.assertFalse(control._busy)
            control._status.assert_called_once()

    def test_frozen_marker_distinguishes_lite_and_voice(self):
        marker = self.root / "speech-runtime.json"
        with patch.object(models.sys, "frozen", True, create=True), patch.object(models, "bundle_roots", return_value=[self.root]):
            marker.write_text('{"enabled":false}', encoding="utf-8")
            self.assertFalse(models.runtime_enabled())
            marker.write_text('{"enabled":true}', encoding="utf-8")
            self.assertTrue(models.runtime_enabled())

    def test_recording_started_during_file_picker_blocks_model_install(self):
        from ui.backend import Backend
        backend = SimpleNamespace(speechBusy=False, speechModelInstalling=False,
                                  _tr=lambda key: key, _emit_status_key=Mock())
        def selected(*args):
            backend.speechBusy = True
            return str(self.archive), "ZIP"
        with patch("core.speech_models.runtime_enabled", return_value=True), \
             patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", side_effect=selected), \
             patch("ui.backend.threading.Thread") as worker:
            Backend.installSpeechModelPack(backend)
            worker.assert_not_called()
        backend._emit_status_key.assert_called_once()

    def test_selecting_catalog_model_repairs_only_missing_preview_path(self):
        from ui.backend import Backend
        statuses = [{"id": "sensevoice", "engine": "sense_voice", "installed": True, "vad_installed": True},
                    {"id": "zipformer", "installed": True, "vad_installed": True}]
        for valid in (False, True):
            with self.subTest(valid_custom_preview=valid):
                settings = {"preview_enabled": True, "sherpa_model_path": "old-or-custom-preview",
                            "sense_voice_model_path": "old-final", "vad_model_path": "old-vad"}
                profiles = {"personal": {"buttons": {"middle": "Control_L+c"}}}
                backend = SimpleNamespace(_cfg={"settings": {"speech_to_text": settings}, "profiles": profiles},
                                          speechSettingsChanged=Mock(), _emit_status_key=Mock())
                with patch.object(models, "catalog_status", return_value=statuses), \
                     patch.object(models, "pack_paths", return_value=["silero_vad.onnx", "zip/tokens.txt"]), \
                     patch.object(models, "find_model", return_value=Path("custom") if valid else None), \
                     patch("ui.backend.save_config"):
                    Backend.useSpeechModel(backend, "sensevoice")
                self.assertEqual(settings["sherpa_model_path"], "old-or-custom-preview" if valid else "")
                self.assertEqual(settings["sense_voice_model_path"], "")
                self.assertEqual(settings["vad_model_path"], "")
                self.assertEqual(backend._cfg["profiles"], profiles)


if __name__ == "__main__":
    unittest.main()
