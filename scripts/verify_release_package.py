"""Verify a Windows lite release with public assets, no mic or user settings.

Run after building and creating Mouser-Windows.zip. Reports only public build
metadata. Real online downloading is a separate check, not simulated here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import speech_components, speech_models


def archive_report(archive, version, commit):
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        names = [entry.filename for entry in entries]
        assert len(names) == len(set(names)), "Duplicate archive names"
        private, models, libraries, root_icu = [], [], [], []
        for name in names:
            path = PurePosixPath(name)
            parts = [part.lower() for part in path.parts]
            assert parts and parts[0] == "mouser", "Unexpected archive root"
            assert ".." not in parts and "\\" not in name and ":" not in name
            basename = path.name.lower()
            if (set(parts) & {".git", "appdata", "config_backups", "g502_backups", "logs"}
                    or basename in {"config.json", "metadata.json", ".env"}
                    or basename.startswith("mouser-settings-")
                    or path.suffix.lower() in {".log", ".err", ".wav", ".mp3", ".flac"}):
                private.append(name)
            if "speech_models" in parts or path.suffix.lower() in {".onnx", ".bin"}:
                models.append(name)
            if any(part.startswith(("sherpa_onnx", "faster_whisper", "ctranslate2", "numpy", "sounddevice", "onnxruntime", "torch")) for part in parts):
                libraries.append(name)
            if (len(parts) == 3 and parts[1] == "_internal"
                    and basename.startswith("icu") and basename.endswith(".dll")):
                root_icu.append(name)
        assert not private, f"Private entries: {private}"
        assert not models, f"Bundled models: {models}"
        assert not libraries, f"Bundled ASR libraries: {libraries}"
        assert not root_icu, f"Root ICU DLLs: {root_icu}"
        assert bundle.testzip() is None, "Archive CRC failed"
        info = json.loads(bundle.read("Mouser/_internal/mouser_build_info.json"))
        assert info["version"] == version and info["commit"] == commit
        assert info["dirty"] is False, "Release must describe a committed source tree"
        assert json.loads(bundle.read("Mouser/_internal/speech-runtime.json"))["enabled"] is False
        assert bundle.read("Mouser/_internal/core/speech_component_assets.json") == (ROOT / "core/speech_component_assets.json").read_bytes()
        for source in (ROOT / "ui/qml").glob("*.qml"):
            assert bundle.read("Mouser/_internal/ui/qml/" + source.name) == source.read_bytes(), source.name
        assert any("uiautomation" in name.lower() for name in names), "Caret anchor runtime missing"
        with Path(archive).open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        return {"version": version, "commit": commit, "main_zip_bytes": Path(archive).stat().st_size,
                "main_expanded_bytes": sum(item.file_size for item in entries), "sha256": digest,
                "PersonalDataHitCount": len(private), "ModelFileCount": len(models),
                "SpeechModulesCount": len(libraries), "RootIcuDllCount": len(root_icu),
                "archive_crc_ok": True, "catalog_and_qml_match_source": True}


def frozen_check(executable, environment, report_path):
    result = subprocess.run([str(executable), "--check-speech-runtime", str(report_path)],
                            env=environment, capture_output=True, timeout=75,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["ok"] and report["frozen"]
    assert report["microphone_opened"] is False and report["input_sent"] is False
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--components-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = archive_report(args.archive, args.version, args.commit)
    assets = speech_components.assets_catalog()
    for asset in assets.values():
        archive = args.components_dir / asset["name"]
        assert archive.stat().st_size == asset["size"]
        with archive.open("rb") as file:
            assert hashlib.file_digest(file, "sha256").hexdigest() == asset["sha256"]
    # Windows can briefly retain a helper DLL after the child shuts down.
    # Cleanup contention must not replace a completed verification result.
    with tempfile.TemporaryDirectory(prefix="mouser-release-check-", ignore_cleanup_errors=True) as directory:
        temporary = Path(directory)
        environment = {**os.environ, "APPDATA": str(temporary / "roaming"),
                       "LOCALAPPDATA": str(temporary / "local"),
                       "MOUSER_SPEECH_MODEL_DIR": str(temporary / "speech_models")}
        executable = args.app_dir / "Mouser.exe"
        report["frozen_without_components"] = frozen_check(executable, environment, temporary / "empty.json")
        destination = temporary / "speech_models"
        destination.mkdir()
        speech_components.install_runtime(args.components_dir / assets["runtime"]["name"], assets["runtime"],
                                           destination=temporary / "speech_runtime/v1-win64")
        speech_models.install_pack(args.components_dir / assets["zipformer"]["name"], destination=destination)
        report["frozen_with_components"] = frozen_check(executable, environment, temporary / "installed.json")
        assert report["frozen_with_components"]["checks"]["independent_speech_runtime"]["ok"]
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
