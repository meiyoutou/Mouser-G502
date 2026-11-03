# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for Mouser
Produces a single-directory portable build in  dist/Mouser/
Run:  pyinstaller Mouser.spec
"""

import os
import sys
import shutil
import json
import subprocess
import PySide6
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

block_cipher = None
ROOT = os.path.abspath(".")
DIST_ROOT = os.path.abspath(globals().get("DISTPATH", "dist"))
sys.path.insert(0, ROOT)
PYSIDE6_DIR = os.path.dirname(PySide6.__file__)
SPEECH_MODELS_DIR = os.path.join(ROOT, "speech_models")
EDITION = os.environ.get("MOUSER_EDITION", "lite").strip().lower()
if EDITION not in {"lite", "voice"}:
    raise ValueError("MOUSER_EDITION must be lite or voice")
SPEECH_ENABLED = EDITION == "voice"
EDITION_BUILD_DIR = os.path.join(ROOT, "build", "optional-" + EDITION)
BUILD_INFO_PATH = os.path.join(EDITION_BUILD_DIR, "mouser_build_info.json")
MODEL_SELECTION = os.environ.get("MOUSER_BUNDLE_MODELS", "none").strip().lower()
if MODEL_SELECTION not in {"none", "all", "sensevoice", "zipformer", "whisper-small"}:
    raise ValueError("Unknown MOUSER_BUNDLE_MODELS selection")
if not SPEECH_ENABLED and MODEL_SELECTION != "none":
    raise ValueError("Lite edition must not bundle speech models")
SPEECH_EXCLUDES = [] if SPEECH_ENABLED else [
    "numpy", "sounddevice", "_sounddevice", "_sounddevice_data", "sherpa_onnx",
    "sherpa_onnx_core", "soxr", "faster_whisper",
    "ctranslate2", "tokenizers", "huggingface_hub", "av", "onnxruntime",
    "torch", "transformers", "scipy", "sympy", "numba",
]


def _collect_optional_speech_runtime():
    """Collect native/runtime files for optional local speech-to-text support."""
    binaries = []
    datas = []
    # Read-only accessibility anchors belong to the main app, not ASR.
    datas += collect_data_files("uiautomation", include_py_files=False)
    if not SPEECH_ENABLED:
        return binaries, datas
    for package in ("sounddevice", "ctranslate2", "tokenizers", "sherpa_onnx", "soxr", "uiautomation"):
        try:
            binaries += collect_dynamic_libs(package)
        except Exception:
            pass
    for package in ("faster_whisper", "ctranslate2", "huggingface_hub", "tokenizers", "sherpa_onnx", "uiautomation"):
        try:
            datas += collect_data_files(package, include_py_files=False)
        except Exception:
            pass
    return binaries, datas


def _load_app_version() -> str:
    version_path = os.path.join(ROOT, "core", "version.py")
    namespace = {"__file__": version_path}
    with open(version_path, encoding="utf-8") as version_file:
        exec(version_file.read(), namespace)
    return namespace["APP_VERSION"]


def _run_git(args):
    try:
        return subprocess.check_output(
            ["git", *args],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.5,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _git_dirty():
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=0.5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())


def _write_build_info(version: str) -> str:
    commit = os.environ.get("MOUSER_GIT_COMMIT", "").strip() or _run_git(["rev-parse", "HEAD"])
    dirty_env = os.environ.get("MOUSER_GIT_DIRTY")
    if dirty_env:
        dirty = dirty_env.strip().lower() in {"1", "true", "yes", "on"}
    else:
        dirty = _git_dirty()

    os.makedirs(os.path.dirname(BUILD_INFO_PATH), exist_ok=True)
    with open(BUILD_INFO_PATH, "w", encoding="utf-8") as build_info_file:
        json.dump(
            {
                "version": version,
                "commit": commit,
                "dirty": dirty,
                "edition": EDITION,
            },
            build_info_file,
        )
    return BUILD_INFO_PATH


APP_VERSION = _load_app_version()
BUILD_INFO_DATA = _write_build_info(APP_VERSION)
SPEECH_BINARIES, SPEECH_DATAS = _collect_optional_speech_runtime()
SPEECH_RUNTIME_MARKER = os.path.join(EDITION_BUILD_DIR, "speech-runtime.json")
with open(SPEECH_RUNTIME_MARKER, "w", encoding="utf-8") as marker:
    json.dump({"enabled": SPEECH_ENABLED, "edition": EDITION}, marker)
SPEECH_DATAS.append((SPEECH_RUNTIME_MARKER, "."))
if MODEL_SELECTION != "none":
    from core.speech_models import CATALOG, pack_paths
    selected = list(CATALOG) if MODEL_SELECTION == "all" else [MODEL_SELECTION]
    paths = set(name for pack_id in selected for name in pack_paths(pack_id))
    for name in sorted(paths | {"NOTICE.md"}):
        SPEECH_DATAS.append((os.path.join(SPEECH_MODELS_DIR, name),
                             os.path.join("speech_models", os.path.dirname(name))))

a = Analysis(
    ["main_qml.py"],
    pathex=[ROOT],
    binaries=SPEECH_BINARIES,
    datas=[
        # QML UI files
        (os.path.join(ROOT, "ui", "qml"), os.path.join("ui", "qml")),
        # Image assets
        (os.path.join(ROOT, "images"), "images"),
        (BUILD_INFO_DATA, "."),
        (os.path.join(ROOT, "core", "speech_component_assets.json"), "core"),
    ] + SPEECH_DATAS,
    hiddenimports=[
        # conditional / lazy imports PyInstaller may miss
        "hid",
        "numpy",
        "sounddevice",
        "sherpa_onnx",
        "soxr",
        "uiautomation",
        "comtypes.gen.UIAutomationClient",
        "faster_whisper",
        "ctranslate2",
        "tokenizers",
        "huggingface_hub",
        "logging.handlers",
        "ctypes.wintypes",
        "ui.locale_manager",
        "ui.speech_locale",
        "core.speech_anchor",
        "core.speech_session",
        "core.speech_runtime_check",
        # PySide6 QML runtime
        "PySide6.QtWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQuickControls2",
        "PySide6.QtQml",
        "PySide6.QtNetwork",
        "PySide6.QtOpenGL",
        "PySide6.QtSvg",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        *SPEECH_EXCLUDES,
        # ── Aggressively trim unneeded PySide6 modules ──
        "PySide6.QtWebEngine",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel",
        "PySide6.QtWebSockets",
        "PySide6.Qt3DCore",
        "PySide6.Qt3DRender",
        "PySide6.Qt3DInput",
        "PySide6.Qt3DLogic",
        "PySide6.Qt3DAnimation",
        "PySide6.Qt3DExtras",
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtBluetooth",
        "PySide6.QtNfc",
        "PySide6.QtPositioning",
        "PySide6.QtLocation",
        "PySide6.QtSensors",
        "PySide6.QtSerialPort",
        "PySide6.QtSerialBus",
        "PySide6.QtTest",
        "PySide6.QtPdf",
        "PySide6.QtPdfWidgets",
        "PySide6.QtCharts",
        "PySide6.QtDataVisualization",
        "PySide6.QtRemoteObjects",
        "PySide6.QtScxml",
        "PySide6.QtSql",
        "PySide6.QtTextToSpeech",
        "PySide6.QtQuick3D",
        "PySide6.QtVirtualKeyboard",
        "PySide6.QtGraphs",
        "PySide6.Qt5Compat",
        # ── PySide6 designer / tools (not needed at runtime) ──
        "PySide6.QtDesigner",
        "PySide6.QtHelp",
        "PySide6.QtUiTools",
        "PySide6.QtXml",
        "PySide6.QtConcurrent",
        "PySide6.QtDBus",
        "PySide6.QtStateMachine",
        "PySide6.QtHttpServer",
        "PySide6.QtSpatialAudio",
        # ── Other unused stdlib modules ──
        "unittest",
        "xmlrpc",
        "pydoc",
        "doctest",
        "tkinter",
        "test",
        "distutils",
        "setuptools",
        "ensurepip",
        "lib2to3",
        "idlelib",
        "turtledemo",
        "turtle",
        "sqlite3",
        "multiprocessing",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── Filter out massive Qt DLLs and data we don't need ──────────────────
# The PySide6 hooks copy EVERYTHING (WebEngine=193MB, 3D, Charts, etc.).
# We only need: Core, Gui, Widgets, Qml, Quick, QuickControls2 (Material),
# OpenGL, Network, ShaderTools, and a few essentials.
_qt_keep = {
    # Core Qt
    "Qt6Core", "Qt6Gui", "Qt6Widgets", "Qt6Network", "Qt6OpenGL",
    # QML / Quick
    "Qt6Qml", "Qt6QmlCore", "Qt6QmlMeta", "Qt6QmlModels",
    "Qt6QmlNetwork", "Qt6QmlWorkerScript",
    "Qt6Quick", "Qt6QuickControls2", "Qt6QuickControls2Impl",
    "Qt6QuickControls2Basic", "Qt6QuickControls2BasicStyleImpl",
    "Qt6QuickControls2Material", "Qt6QuickControls2MaterialStyleImpl",
    "Qt6QuickTemplates2", "Qt6QuickLayouts", "Qt6QuickEffects",
    "Qt6QuickShapes",
    # Rendering
    "Qt6ShaderTools", "Qt6Svg",
    # PySide6 runtime
    "pyside6.abi3", "pyside6qml.abi3", "shiboken6.abi3",
    # VC runtime
    "MSVCP140", "MSVCP140_1", "MSVCP140_2",
    "VCRUNTIME140", "VCRUNTIME140_1",
}

def _should_keep(name):
    """Return True if this binary/data entry should be kept."""
    base = os.path.basename(name)
    lower_base = base.lower()

    # PySide6 6.11.x Qt6Core imports the Windows system ICU exports without
    # the ICU version suffix.  PyInstaller may collect standalone ICU 78 DLLs
    # (icuuc.dll/icudt78.dll) whose exports are version-suffixed, which causes
    # "DLL load failed while importing QtWidgets: The specified procedure could
    # not be found" on startup.  Do not bundle these Windows ICU DLLs; let Qt
    # resolve the system ICU instead.
    if lower_base.startswith("icu") and lower_base.endswith(".dll"):
        return False

    # Always keep non-PySide6 files
    if "PySide6" not in name and "pyside6" not in name.lower():
        return True
    # Check the filename (last component)
    stem = os.path.splitext(base)[0]
    # Keep if it's in our whitelist
    if stem in _qt_keep:
        return True
    # Keep all .pyd files (Python extensions — small and needed)
    if base.endswith(".pyd"):
        return True
    # Keep plugin dirs we need (platforms, imageformats, styles, iconengines)
    for keep in ("platforms", "imageformats", "styles", "iconengines",
                 "platforminputcontexts"):
        if keep in name:
            return True
    # Keep QML dirs we need
    for keep_qml in ("QtCore", "QtQml", "QtQuick", "QtNetwork"):
        pat = os.path.join("qml", keep_qml)
        if pat in name.replace("/", os.sep):
            return True
    # Drop everything else (WebEngine, 3D, Charts, Multimedia, etc.)
    return False

a.binaries = [b for b in a.binaries if _should_keep(b[0])]
a.datas    = [d for d in a.datas    if _should_keep(d[0])]

exe = EXE(
    pyz,
    a.scripts,
    [],                     # not one-file (faster startup, easier debugging)
    exclude_binaries=True,
    name="Mouser",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,              # UPX OFF — decompression at startup is very slow
    console=False,          # windowed app (no terminal)
    icon=os.path.join(ROOT, "images", "logo.ico"),
    uac_admin=False,        # does NOT require admin
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,              # UPX OFF — faster cold start
    upx_exclude=[],
    name="Mouser",
)

# ── Post-build cleanup: remove Qt QML/plugin dirs we don't need ──────────
# PyInstaller's hooks copy the entire PySide6 QML tree; we only need
# QtQuick/Controls + Material, QtQml, QtQuick/Layouts, QtQuick/Templates,
# QtQuick/Window.  Everything else is dead weight that slows startup.
_dist = os.path.join(DIST_ROOT, "Mouser", "_internal", "PySide6")

# QML dirs to KEEP (everything else under qml/ is deleted)
_keep_qml = {
    "QtCore", "QtQml", "QtQuick", "QtNetwork",
}

# Under QtQuick, keep only what the app uses
_keep_qtquick = {
    "Controls", "Layouts", "Templates", "Window",
}

# Plugin dirs to KEEP
_keep_plugins = {
    "iconengines", "imageformats", "platforms",
    "platforminputcontexts", "styles",
}

def _cleanup():
    qml_root = os.path.join(_dist, "qml")
    if os.path.isdir(qml_root):
        for d in os.listdir(qml_root):
            if d not in _keep_qml:
                p = os.path.join(qml_root, d)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                    print(f"  [cleanup] removed qml/{d}")

        # Trim inside QtQuick
        qtquick = os.path.join(qml_root, "QtQuick")
        if os.path.isdir(qtquick):
            for d in os.listdir(qtquick):
                if d not in _keep_qtquick:
                    p = os.path.join(qtquick, d)
                    if os.path.isdir(p):
                        shutil.rmtree(p, ignore_errors=True)
                        print(f"  [cleanup] removed qml/QtQuick/{d}")

    plugins_root = os.path.join(_dist, "plugins")
    if os.path.isdir(plugins_root):
        for d in os.listdir(plugins_root):
            if d not in _keep_plugins:
                p = os.path.join(plugins_root, d)
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                    print(f"  [cleanup] removed plugins/{d}")

    # Remove translations (not needed)
    trans = os.path.join(_dist, "translations")
    if os.path.isdir(trans):
        shutil.rmtree(trans, ignore_errors=True)
        print("  [cleanup] removed translations/")


def _ensure_pyside6_adjacent_shiboken():
    """Keep shiboken6.abi3.dll next to pyside6.abi3.dll for Windows loader compatibility."""
    py_side_dir = os.path.join(DIST_ROOT, "Mouser", "_internal", "PySide6")
    shiboken_dir = os.path.join(DIST_ROOT, "Mouser", "_internal", "shiboken6")
    src = os.path.join(shiboken_dir, "shiboken6.abi3.dll")
    dst = os.path.join(py_side_dir, "shiboken6.abi3.dll")
    if not os.path.isfile(src) or not os.path.isdir(py_side_dir):
        print("  [cleanup] skipped PySide6-adjacent shiboken6.abi3.dll")
        return
    if not os.path.isfile(dst) or not os.path.samefile(src, dst):
        shutil.copy2(src, dst)
        print("  [cleanup] copied shiboken6.abi3.dll next to pyside6.abi3.dll")


print("[Mouser] Post-build cleanup...")
_cleanup()
_ensure_pyside6_adjacent_shiboken()
print("[Mouser] Cleanup done.")

# ── macOS App Bundle ───────────────────────────────────────────────────
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Mouser.app',
        icon='images/AppIcon.icns',
        bundle_identifier='com.mouser.app',
        info_plist={
            'CFBundleShortVersionString': APP_VERSION,
            'CFBundleVersion': APP_VERSION,
            'LSUIElement': True, # Runs in background (menu bar app)
            'NSHighResolutionCapable': True,
        },
    )
