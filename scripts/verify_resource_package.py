"""Stage a fresh local resource-test package and check frozen/public artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from core import text_selection
from core.bundle_policy import unused_runtime_file
from core.version import APP_VERSION
from scripts.verify_release_package import archive_report
from PyInstaller.archive.readers import CArchiveReader


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(build, assets, app, *, existing=False, installed_models=None, public_release=False,
        release_dir=None):
    source = build / "dist/Mouser"
    assert (source / "Mouser.exe").is_file()
    # Never merge a new runtime into an existing executable/old package.
    if not existing:
        for name in ("Mouser.exe", "_internal", "文字选择组件", "发布包"):
            assert not (app / name).exists(), f"Destination is not fresh: {app / name}"
    if not public_release:
        assert (app / "使用说明.md").is_file(), "Write the local usage note before staging"
    info = json.loads((source / "_internal/mouser_build_info.json").read_text(encoding="utf-8"))
    assert info["version"] == APP_VERSION and info["edition"] == "lite" and len(info["commit"]) == 40
    if public_release:
        assert info["dirty"] is False, "Public release requires committed source"
    if not existing:
        shutil.copy2(source / "Mouser.exe", app / "Mouser.exe")
        shutil.copytree(source / "_internal", app / "_internal")
        shutil.copytree(assets / "component", app / "文字选择组件",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    assert text_selection.checked_runtime(app / "文字选择组件") is not None
    pyz = CArchiveReader(str(app / "Mouser.exe")).open_embedded_archive("PYZ.pyz")
    for name in ("PIL.AvifImagePlugin", "PIL._avif", "core.ocr_components",
                 "core.ocr_worker", "ui.screenshot_ocr", "core.light_ocr"):
        assert name not in pyz.toc, name
    for name in ("core.compute_limits", "core.log_setup", "ui.screenshot_resource_check",
                 "core.text_selection", "ui.screenshot_text_selection",
                 "core.scroll_compute", "ui.settings_window", "ui.resource_lifecycle_check"):
        assert name in pyz.toc, name
    files = [source / "Mouser.exe", *sorted(p for p in (source / "_internal").rglob("*") if p.is_file())]
    for file in files:
        relative = file.relative_to(source)
        assert digest(file) == digest(app / relative), str(relative)
        if relative.parts[0] == "_internal":
            assert not unused_runtime_file(Path(*relative.parts[1:]).as_posix()), str(relative)
    for name in ("PySide6/QtOpenGL.pyd", "PySide6/Qt6Widgets.dll",
                 "PySide6/shiboken6.abi3.dll", "libcrypto-3.dll", "libssl-3.dll",
                 "PySide6/qml/QtQuick/Controls/Material/qmldir",
                 "PySide6/qml/QtQuick/Controls/Basic/qmldir"):
        assert (app / "_internal" / name).is_file(), name
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", QT_QPA_FONTDIR=r"C:\Windows\Fonts",
                       QSG_RHI_BACKEND="software", QT_QUICK_BACKEND="software",
                       APPDATA=str(build / "frozen-isolated/roaming"),
                       LOCALAPPDATA=str(build / "frozen-isolated/local"),
                       MOUSER_SPEECH_MODEL_DIR=str(build / "frozen-isolated/speech_models"))
    checks = {}
    for label, argument, timeout in (
            ("resource", "--check-resource-runtime", 60),
            ("lifecycle", "--check-resource-lifecycle", 90),
            ("text_selection", "--check-text-selection", 75),
            ("compact", "--check-screenshot-compact", 90),
            ("diagnostics", "--check-scroll-diagnostics", 30),
            ("speech", "--check-speech-runtime", 30)):
        report_path = build / f"frozen-{label}.json"
        result = subprocess.run([str(app / "Mouser.exe"), argument, str(report_path)],
                                env=environment, capture_output=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert report_path.is_file(), (label, result.returncode, result.stderr)
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert result.returncode == 0, (label, data, result.stderr.decode("utf-8", "replace"))
        assert data["ok"] and data["frozen"] and data["version"] == APP_VERSION, (label, data)
        checks[label] = data
    if installed_models is not None:
        # Explicit read-only compatibility check against an installed public
        # runtime. Config/logs stay isolated, no microphone or actual input.
        report_path = build / "frozen-installed-speech.json"
        result = subprocess.run([str(app / "Mouser.exe"), "--check-speech-runtime", str(report_path)],
            env=dict(environment, MOUSER_SPEECH_MODEL_DIR=str(installed_models)),
            capture_output=True, timeout=75, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert result.returncode == 0 and data["ok"]
        assert data["checks"]["independent_speech_runtime"]["ok"]
        assert not data["microphone_opened"] and not data["input_sent"]
        checks["installed_speech"] = data
    workers = []
    for label in ("normal", "4k"):
        output = build / f"frozen-worker-{label}.json"
        start = time.monotonic()
        result = subprocess.run([str(app / "Mouser.exe"), "--text-selection-worker",
                                 str(assets / f"benchmark/{label}.png"), str(output),
                                 str(app / "文字选择组件")], env=environment, timeout=65,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        assert result.returncode == 0, label
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["ok"] and "截图冻结后拖选文字" in data["text"] and not data["network_used"], data
        data.update(sample=label, elapsed_seconds=round(time.monotonic() - start, 3))
        data.pop("glyphs")
        workers.append(data)
    if not public_release:
        for name in ("text-selection-preview.png", "text-selection-controls.png"):
            shutil.copy2(build / name, app / name)
    release = release_dir if release_dir is not None else app / "发布包"
    release.mkdir(exist_ok=existing)
    archive = release / ("Mouser-Windows.zip" if public_release else
                         f"Mouser-Windows-{APP_VERSION}-resource-test.zip")
    # Existing mode only refreshes this build's generated release archive after
    # all runtime files and explicit version/commit have been checked above.
    with zipfile.ZipFile(archive, "w" if existing else "x", zipfile.ZIP_DEFLATED) as bundle:
        public_files = ([*sorted(p for p in (app / "文字选择组件").rglob("*") if p.is_file())]
                        if public_release else [app / "使用说明.md"])
        for file in [app / "Mouser.exe", *sorted(p for p in (app / "_internal").rglob("*") if p.is_file()),
                     *public_files]:
            bundle.write(file, "Mouser/" + file.relative_to(app).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        for file in files:
            relative = file.relative_to(source)
            assert hashlib.sha256(bundle.read("Mouser/" + relative.as_posix())).hexdigest() == digest(file)
    if not public_release:
        shutil.copy2(assets / "component.zip", release / "文字选择组件.zip")
    package = archive_report(archive, APP_VERSION, info["commit"], local_test=not public_release)
    report = {"ok": True, "checks": checks, "workers": workers,
              "main_archive": package, "main_file_count": len(files),
              "main_runtime_bytes": sum(file.stat().st_size for file in files),
              "optional_text_selection_bytes": sum(p.stat().st_size for p in (app / "文字选择组件").rglob("*") if p.is_file()),
              "optional_text_selection_sha256_verified": True,
              "unneeded_video_avif_styles_absent": True, "native_compatibility_files_preserved": True,
              "build_desktop_archive_files_match": True, "user_configuration_used": False,
              "public_release": public_release, "archive_path": str(archive),
              "system_clipboard_changed": False, "desktop_captured": False}
    (build / "package-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "checks"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--verify-existing", action="store_true")
    parser.add_argument("--installed-models", type=Path)
    parser.add_argument("--public-release", action="store_true")
    parser.add_argument("--release-dir", type=Path)
    args = parser.parse_args()
    run(args.build.resolve(), args.assets.resolve(), args.app.resolve(), existing=args.verify_existing,
        installed_models=args.installed_models.resolve() if args.installed_models else None,
        public_release=args.public_release,
        release_dir=args.release_dir.resolve() if args.release_dir else None)
