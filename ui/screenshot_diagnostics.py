"""Explicit, local-only scrolling diagnostics. Never invoked by normal capture.

The user must click consent, select a region and scroll the target themselves.
This entry does not load/save settings, start HID hooks, paste, copy, upload,
or inject input into another application. Only the selected pixels are saved.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import threading
import uuid

from PIL import Image
from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton, QVBoxLayout, QWidget

from core.version import APP_VERSION
from ui.locale_manager import LocaleManager
from ui.screenshot_common import SCREENSHOT_REGION_CLIP, pil_image_to_qimage
from ui.screenshot_overlay import RegionSelectionOverlay, union_rect
from ui.screenshot_scroll import ScrollCaptureSession
from ui.windows_screenshot import (
    WindowsScreenshotController, capture_virtual_desktop, physical_to_logical_rects,
)


def diagnostic_root():
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Mouser" / "scroll_diagnostics"


class PrivateScrollTrace:
    MAX_FRAMES = 8
    MAX_FRAME_PIXELS = 10_000_000

    def __init__(self, root, first, candidate_rect, *, accessibility_candidate=False):
        if first.width * first.height > self.MAX_FRAME_PIXELS:
            raise ValueError("诊断选区过大，请缩小到 1000 万像素以内。")
        x0, y0, x1, y1 = candidate_rect
        if not (0 <= x0 < x1 <= first.width and 0 <= y0 < y1 <= first.height):
            raise ValueError("诊断候选区域无效。")
        stamp = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S")
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.directory = root / (stamp + "-" + uuid.uuid4().hex[:8])
        self.directory.mkdir(mode=0o700)
        self.latest = first
        self._closed = False
        self._count = 0
        self._pending = 0
        self._lock = threading.Lock()
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scroll-trace")
        self.report = {
            "schema": 1, "version": APP_VERSION, "local_only": True,
            "user_initiated": True, "selected_size": list(first.size),
            "candidate_rect": list(candidate_rect),
            "accessibility_candidate": bool(accessibility_candidate),
            "config_loaded": False, "clipboard_changed": False,
            "input_injected": False, "uploaded": False, "max_frames": self.MAX_FRAMES,
            "frames": [], "writer_skipped": 0, "write_errors": [],
        }
        self._save_frame(first, {"reason": "initial", "extra_rows": 0})

    def _save_frame(self, frame, event):
        with self._lock:
            if self._closed or self._count >= self.MAX_FRAMES:
                return
            if self._pending >= 2:
                self.report["writer_skipped"] += 1
                return
            number = self._count
            self._count += 1
            self._pending += 1
        name = f"frame-{number:02d}.png"
        def write():
            try:
                frame.save(self.directory / name, format="PNG")
                with self._lock:
                    self.report["frames"].append({"file": name, **event})
            except Exception as exc:
                with self._lock:
                    self.report["write_errors"].append(type(exc).__name__)
            finally:
                with self._lock:
                    self._pending -= 1
        self._writer.submit(write)

    def observe(self, event):
        # Ignore idle/caret-only redraws; retain accepted AND rejected views.
        if event.get("reason") != "scroll_unchanged":
            self._save_frame(self.latest, dict(event))

    def finish(self, image=None, *, outcome="finished"):
        with self._lock:
            if self._closed:
                return self.completion
            self._closed = True
        self.latest = None
        def complete():
            if image is not None:
                try:
                    image.save(self.directory / "result.png")
                except Exception as exc:
                    self.report["write_errors"].append(type(exc).__name__)
            self.report["outcome"] = outcome
            (self.directory / "trace.json").write_text(
                json.dumps(self.report, ensure_ascii=False, indent=2), encoding="utf-8")
            return self.directory
        self.completion = self._writer.submit(complete)
        self._writer.shutdown(wait=False)
        return self.completion


class DiagnosticController(WindowsScreenshotController):
    ended = Signal(str)
    failed = Signal(str)

    def __init__(self, root, locale, **kwargs):
        super().__init__(locale=locale, **kwargs)
        self.root, self.trace = Path(root), None
        self._closing = False

    def _open_scroll_session(self, capture, action, rect, physical, probe, found):
        if self._scroll_probe is not probe:
            return
        self._scroll_probe = None
        probe.cancel()
        probe.deleteLater()
        self._capture_pending = False
        try:
            used = found.intersected(physical) if hasattr(found, "intersected") else None
            if used is None or used.width < 40 or used.height < 80:
                used = physical
            source = physical.translated(-capture.physical_rect.left, -capture.physical_rect.top)
            full = capture.image.crop((source.left, source.top, source.right, source.bottom))
            crop = (used.left - physical.left, used.top - physical.top,
                    used.right - physical.left, used.bottom - physical.top)
            trace = PrivateScrollTrace(self.root, full, crop, accessibility_candidate=used != physical)
            self.trace = trace
            def provider():
                # One physical capture preserves the fixed panel and candidate
                # at the exact same instant. Nothing outside selection is saved.
                whole = self._capture_scroll_frame(physical, capture.monitor_maps)
                trace.latest = whole
                return whole.crop(crop)
            session = ScrollCaptureSession(full.crop(crop), provider, locale=self._locale,
                capture_rect=rect, viewport_detected=used != physical)
            self._scroll_session = session
            session.analysisObserved.connect(trace.observe)
            session.completed.connect(lambda image: self._finish_scroll(image, action))
            session.cancelled.connect(self._cancel_scroll)
            from ui.screenshot_session import toolbar_position
            logical = physical_to_logical_rects(physical, capture.monitor_maps) or rect
            session.move(toolbar_position(logical, session.size(),
                [m.logical.to_qrect() for m in capture.monitor_maps]))
            session.show()
        except Exception as exc:
            if self.trace is not None:
                self.trace.finish(outcome="setup_error")
            self.failed.emit(str(exc))

    def _finish_scroll(self, image, action):
        self._scroll_session = None
        self._finish_trace(image, "finished")

    def _cancel_scroll(self):
        self._scroll_session = None
        self._finish_trace(None, "cancelled")

    def _finish_trace(self, image, outcome):
        trace = self.trace
        if trace is None:
            self.failed.emit("尚未产生诊断记录。")
            return
        future = trace.finish(image, outcome=outcome)
        def completed(task):
            if self._closing:
                return
            try:
                self.ended.emit(str(task.result()))
            except Exception as exc:
                self.failed.emit("诊断文件保存失败：" + type(exc).__name__)
        future.add_done_callback(completed)

    def _emit_status(self, message):
        # Base setup failures must reopen the launcher rather than leave a
        # hidden process with no way to retry.
        self.failed.emit(str(message))


class ScrollDiagnosticWindow(QWidget):
    def __init__(self, root=None, locale=None):
        super().__init__()
        self.root = Path(root) if root is not None else diagnostic_root()
        self.locale = locale or LocaleManager("zh_CN")  # no personal config read
        self._busy, self._last_directory = False, None
        self.setWindowTitle("Mouser 长截图 · 本地诊断")
        self.setFixedWidth(500)
        layout = QVBoxLayout(self)
        description = QLabel(
            "先把 Codex 聊天向上翻一段，留出向下滚动的空间。\n"
            "开始后框选：左侧固定栏＋聊天正文＋底部输入框。\n"
            "在聊天正文里手动向下滚动几次，最后点缩略图旁的对勾。\n\n"
            "只保存你框选的区域，最多 8 张前后画面及本地分析记录；"
            "可能包含聊天内容，取消后也会保留。不上传、不读写配置、"
            "不启动鼠标钩子，也不改变剪贴板。")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.consent = QCheckBox("同意在本机保存本次选区，用于排查长截图问题")
        layout.addWidget(self.consent)
        self.start_button = QPushButton("框选并开始诊断")
        self.start_button.setEnabled(False)
        self.consent.toggled.connect(self.start_button.setEnabled)
        self.start_button.clicked.connect(self.begin)
        layout.addWidget(self.start_button)
        self.status = QLabel("尚未开始；当前运行的 Mouser 无需退出。")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.open_button = QPushButton("打开本次诊断记录")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_directory)
        layout.addWidget(self.open_button)
        self.controller = DiagnosticController(self.root, self.locale, parent=self)
        self.controller.ended.connect(self.finished)
        self.controller.failed.connect(self.failed)

    def begin(self):
        if not self.consent.isChecked() or self._busy:
            return
        self._busy = True
        self.hide()
        QTimer.singleShot(280, self._select)

    def _select(self):
        try:
            capture = capture_virtual_desktop()
            screens, frozen = [], []
            for monitor in capture.monitor_maps:
                screens.append(monitor.logical)
                r = monitor.physical.translated(-capture.physical_rect.left, -capture.physical_rect.top)
                frozen.append(pil_image_to_qimage(capture.image.crop((r.left, r.top, r.right, r.bottom))))
            self.controller._pending_capture = capture
            self.controller._pending_action = SCREENSHOT_REGION_CLIP
            overlay = RegionSelectionOverlay(union_rect(screens), screen_rects=screens,
                frozen_images=frozen, confirm_on_release=False)
            self.controller._overlay = overlay
            overlay.selected.connect(self.controller._start_scroll)
            overlay.cancelled.connect(self._cancel_selection)
            overlay.show()
        except Exception as exc:
            self.failed(type(exc).__name__)

    def _cancel_selection(self):
        self.controller._cancel_region()

    def finished(self, directory):
        self._busy = False
        self._last_directory = directory
        self.open_button.setEnabled(True)
        try:
            report = json.loads((Path(directory) / "trace.json").read_text(encoding="utf-8"))
            heading = "已保存记录，但有画面写入失败，请一并反馈：" if report["write_errors"] else "已保存本地记录："
        except (OSError, ValueError, KeyError):
            heading = "诊断记录可能不完整，请检查目录："
        self.status.setText(heading + "\n" + directory +
                            "\n回到 Codex 回复“诊断完成”，即可继续分析，无需上传到 GitHub。")
        self.show()

    def failed(self, reason):
        self._busy = False
        self.status.setText("本次诊断未完成：" + reason)
        self.show()

    def open_directory(self):
        if self._last_directory:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_directory))

    def closeEvent(self, event):
        self.controller._closing = True
        probe = self.controller._scroll_probe
        if probe is not None:
            probe.cancel()
            self.controller._scroll_probe = None
        overlay = self.controller._overlay
        if overlay is not None:
            overlay.close()
            self.controller._overlay = None
        session = self.controller._scroll_session
        if session is not None:
            session.close()
        super().closeEvent(event)


def run_diagnostic():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    window = ScrollDiagnosticWindow()
    window.destroyed.connect(app.quit)
    from PySide6.QtCore import Qt
    window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    window.show()
    return app.exec()


def run_check(report_path):
    """Frozen entry verification with generated pixels only, no real capture."""
    import tempfile
    from PIL import ImageDraw
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="mous-diag-", ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        window = ScrollDiagnosticWindow(root / "private")
        assert not window.consent.isChecked() and not window.start_button.isEnabled()
        assert not (root / "private").exists()
        page = Image.new("RGB", (240, 260), "white")
        draw = ImageDraw.Draw(page)
        draw.rectangle((0, 0, 100, 259), fill="#a2c3dd")
        draw.text((120, 110), "SYNTHETIC", fill="black")
        trace = PrivateScrollTrace(root / "private", page, (110, 0, 240, 260),
                                   accessibility_candidate=True)
        for index in range(12):
            trace.latest = page.copy()
            trace.observe({"reason": "scroll_overlap", "extra_rows": 0})
        trace.finish(outcome="synthetic_check").result(timeout=15)
        report = json.loads((trace.directory / "trace.json").read_text(encoding="utf-8"))
        assert 1 <= len(report["frames"]) <= 8
        assert report["candidate_rect"] == [110, 0, 240, 260]
        assert Image.open(trace.directory / "frame-00.png").size == page.size
        assert not report["uploaded"] and not report["input_injected"]
        window.close()
        app.processEvents()
    import sys
    assert "core.config" not in sys.modules and "core.engine" not in sys.modules
    result = {"ok": True, "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "synthetic_only": True, "desktop_captured": False, "config_loaded": False,
              "clipboard_changed": False, "input_injected": False, "uploaded": False,
              "consent_required": True, "selection_preserved_before_candidate_crop": True,
              "bounded_trace": True}
    Path(report_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0
