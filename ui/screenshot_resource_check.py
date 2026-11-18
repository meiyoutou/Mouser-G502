"""Synthetic packaged resource/format/QML check: no hooks, config, mic or capture."""
from __future__ import annotations

import ctypes
import gc
import io
import json
import os
from pathlib import Path
import sys
import time


def memory(stage):
    row = {"stage": stage}
    if sys.platform != "win32":
        return row
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_ = [("cb", w.DWORD), ("PageFaultCount", w.DWORD)] + [
            (name, ctypes.c_size_t) for name in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    kernel, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    kernel.GetCurrentProcess.restype = w.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    class ThreadEntry(ctypes.Structure):
        _fields_ = [(name, w.DWORD) for name in ("dwSize", "cntUsage", "threadID", "ownerPID")] + [
            ("basePri", w.LONG), ("deltaPri", w.LONG), ("flags", w.DWORD)]
    kernel.CreateToolhelp32Snapshot.restype = w.HANDLE
    kernel.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    snapshot = kernel.CreateToolhelp32Snapshot(4, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        raise ctypes.WinError()
    thread, count = ThreadEntry(), 0
    thread.dwSize = ctypes.sizeof(thread)
    try:
        ok = kernel.Thread32First(snapshot, ctypes.byref(thread))
        while ok:
            count += thread.ownerPID == os.getpid()
            ok = kernel.Thread32Next(snapshot, ctypes.byref(thread))
    finally:
        kernel.CloseHandle(snapshot)
    row.update(working_mib=round(counters.WorkingSetSize / 2**20, 2),
               private_mib=round(counters.PrivateUsage / 2**20, 2),
               peak_working_mib=round(counters.PeakWorkingSetSize / 2**20, 2),
               native_threads=count)
    return row


def _check(path):
    from PIL import Image, ImageChops
    from core.compute_limits import child_environment, OPENCV_THREADS
    from core.version import APP_VERSION
    from ui.screenshot_registration import RegistrationStitcher
    before_env = {name: os.environ.get(name) for name in
                  ("OPENBLAS_NUM_THREADS", "OPENBLAS_DEFAULT_NUM_THREADS")}
    rows = [memory("before_optional_long_capture_import")]
    timings = []
    for cycle in range(3):
        page = Image.effect_noise((1200, 4000), 50).convert("RGB")
        start = time.monotonic()
        stitch = RegistrationStitcher(page.crop((0, 0, 1200, 800)), detect_content=False)
        assert stitch.cv.getNumThreads() == OPENCV_THREADS
        rows.append(memory(f"cycle{cycle+1}_stitcher_created"))
        for offset in (137, 347, 650, 1000):
            stitch.append(page.crop((0, offset, 1200, offset + 800)))
            stitch.preview_image()
        out = stitch.render()
        assert out.size == (1200, 1800)
        assert ImageChops.difference(out, page.crop((0, 0, 1200, 1800))).getbbox() is None
        timings.append(round(time.monotonic() - start, 3))
        rows.append(memory(f"cycle{cycle+1}_stitched_1200x1800"))
        del stitch, out, page
        gc.collect()
        rows.append(memory(f"cycle{cycle+1}_closed_and_collected"))
    assert before_env == {name: os.environ.get(name) for name in before_env}
    assert before_env == {name: child_environment().get(name) for name in before_env}
    # Check that trimming AVIF did not break the formats the app actually uses.
    sample = Image.new("RGB", (37, 29), "#709abc")
    for image_format in ("PNG", "JPEG", "BMP"):
        stream = io.BytesIO()
        sample.save(stream, format=image_format)
        stream.seek(0)
        decoded = Image.open(stream)
        decoded.load()
        assert decoded.size == sample.size
        decoded.close()

    os.environ["QT_QUICK_CONTROLS_STYLE"] = "Material"
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Material")
    engine = QQmlApplicationEngine()
    warnings = []
    engine.warnings.connect(lambda messages: warnings.extend(message.toString() for message in messages))
    engine.loadData(b"""
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Controls.Basic as Basic
import QtQuick.Layouts
ApplicationWindow {
    visible: false; width: 640; height: 480
    ColumnLayout {
        Button { text: "Material" }
        Basic.Button { text: "Basic fallback" }
        TextField { text: "input" }
        Slider { value: 0.5 }
        ComboBox { model: ["one", "two"] }
        CheckBox { checked: true }
        ScrollView { TextArea { text: "sample" } }
    }
}
""")
    for _ in range(3):
        app.processEvents()
    assert engine.rootObjects(), warnings
    assert not warnings, warnings
    report = {"ok": True, "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "opencv_threads": OPENCV_THREADS, "environment_restored": True,
              "speech_environment_unchanged": True, "cycles": 3,
              "exact_synthetic_scroll_pixels": True, "cycle_seconds": timings, "memory": rows,
              "image_formats": ["PNG", "JPEG", "BMP"], "material_and_basic_qml_loaded": True,
              "qml_warnings": warnings, "synthetic_only": True, "user_configuration_used": False,
              "desktop_captured": False, "microphone_opened": False, "system_clipboard_changed": False}
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def run_check(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        return _check(path)
    except Exception as error:
        import traceback
        Path(path).write_text(json.dumps({"ok": False, "error_type": type(error).__name__,
            "detail": str(error), "traceback": traceback.format_exc()}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return 1
