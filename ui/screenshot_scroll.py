"""User-controlled scrolling with automatic, bounded, asynchronous stitching."""
from copy import copy
import ctypes
import hashlib
import sys

from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, QTimer, Signal, Slot, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton

from ui.screenshot_tools import StitchError
from ui.screenshot_registration import RegistrationStitcher
from ui.screenshot_locale import screenshot_text


def exclude_capture_window(window_id, user32=None):
    """Keep the live toolbar/preview out of Windows desktop capture."""
    if user32 is None:
        if sys.platform != "win32":
            return False
        user32 = ctypes.windll.user32
    from ctypes import wintypes as w
    try:
        user32.SetWindowDisplayAffinity.argtypes = [w.HWND, w.DWORD]
        user32.SetWindowDisplayAffinity.restype = w.BOOL
        user32.GetWindowDisplayAffinity.argtypes = [w.HWND, ctypes.POINTER(w.DWORD)]
        user32.GetWindowDisplayAffinity.restype = w.BOOL
        affinity = w.DWORD()
        return bool(user32.SetWindowDisplayAffinity(window_id, 0x11)
                    and user32.GetWindowDisplayAffinity(window_id, ctypes.byref(affinity))
                    and affinity.value == 0x11)
    except (OSError, AttributeError):
        return False


def frame_key(frame):
    return (frame.size, hashlib.blake2b(frame.tobytes(), digest_size=16).digest())


class _AnalysisSignals(QObject):
    completed = Signal(object)


class _AnalyzeFrame(QRunnable):
    """Only a private stitcher snapshot is mutated outside the GUI thread."""
    def __init__(self, stitcher, frame, key, epoch, final):
        super().__init__()
        self.signals = _AnalysisSignals()
        self.stitcher = copy(stitcher)
        self.stitcher.parts = list(stitcher.parts)
        self.frame, self.key, self.epoch, self.final = frame, key, epoch, final

    def run(self):
        extra, reason, error_type = 0, None, None
        try:
            extra = self.stitcher.append(self.frame)
            self.stitcher.preview_image()  # resize on worker, not GUI thread
        except StitchError as exc:
            reason = str(exc) if str(exc) in {
                "scroll_size", "scroll_unchanged", "scroll_overlap", "scroll_limit",
            } else "scroll_capture_error"
        except Exception as exc:
            reason, error_type = "scroll_capture_error", type(exc).__name__
        self.signals.completed.emit((self.epoch, self.stitcher, self.key, extra,
                                     reason, error_type, self.final))


class ScrollCaptureSession(QWidget):
    completed = Signal(object)
    cancelled = Signal()
    analysisObserved = Signal(object)  # opt-in diagnostic metadata; no pixels
    SAMPLE_MS = 180

    def __init__(self, frame, capture_frame, *, locale=None, capture_rect=None, viewport_detected=False):
        super().__init__()
        self.setObjectName("screenshotScrollSession")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus
                            | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("QWidget {background:white; color:#334155;} "
                          "QPushButton {padding:5px 10px; border:1px solid #dbe1e8; border-radius:5px;} "
                          "QPushButton:hover {background:#deedff;} "
                          "QPushButton#screenshot_done {background:#1677ff;}")
        # UIA often exposes the whole webview, including a fixed chat header
        # and composer. Geometry is a candidate, never proof that every pixel
        # in that rectangle scrolls. Always retain image-based refinement.
        self.stitcher = RegistrationStitcher(frame, detect_content=True, isolated=True)
        self.capture_frame, self.capture_rect, self.locale = capture_frame, capture_rect, locale
        self.viewport_detected = viewport_detected
        self._image_viewport_detected = False
        self._pending = self._done = self._closed = self._paused = self._finishing = False
        self._started = self._excluded = False
        self._epoch = 0
        self._accepted_key = self._sample_key = frame_key(frame.convert("RGB"))
        self._error = None
        self._job = None
        self._drag_offset = None
        self._timer = QTimer(self)
        self._timer.setInterval(self.SAMPLE_MS)
        self._timer.timeout.connect(self._capture)
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._start_capture)
        layout = QVBoxLayout(self)
        # Retain translated diagnostic/accessibility state, not visible prose.
        self.hint, self.status = QLabel(self), QLabel(self)
        self.hint.hide()
        self.status.hide()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.preview.setMinimumHeight(100)
        self.preview.setMaximumHeight(308)
        layout.addWidget(self.preview)
        row = QHBoxLayout()
        row.addStretch()
        self.buttons = {}
        for key, callback in (("cancel", self.close), ("done", self.finish)):
            button = QPushButton()
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(callback)
            button.setObjectName("screenshot_" + key)
            self.buttons[key] = button
            row.addWidget(button)
        from ui.screenshot_toolbar import tool_icon
        for key, color in (("cancel", "#475569"), ("done", "#ffffff")):
            self.buttons[key].setIcon(tool_icon(key, color))
            self.buttons[key].setIconSize(QSize(20, 20))
            self.buttons[key].setFixedSize(34, 30)
        layout.addLayout(row)
        self.preview.setAccessibleName(self.tr_key("scroll_live_preview"))
        self.update_preview()
        if locale:
            locale.languageChanged.connect(self.refresh_language)
        self.setFixedWidth(260)
        self.refresh_language()
        self.adjustSize()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._started:
            self._started = True
            self._excluded = exclude_capture_window(int(self.winId()))
            # Let the selection panes disappear before the first live read.
            self._start_timer.start(280)

    def _start_capture(self):
        if not self._closed and not self._paused and not self._finishing:
            self._timer.start()
            self._capture()

    def tr_key(self, key):
        return screenshot_text(key, self.locale)

    def refresh_language(self):
        self.setWindowTitle(self.tr_key("scroll"))
        self.hint.setText(self.tr_key("scroll_viewport_detected" if self.viewport_detected else "scroll_hint"))
        for key, button in self.buttons.items():
            button.setText("")
            button.setAccessibleName(self.tr_key(key))
            button.setToolTip(self.tr_key(key))
        self.preview.setAccessibleName(self.tr_key("scroll_live_preview"))
        self.update_status()

    def update_status(self):
        progress = self.tr_key("scroll_progress").format(
            count=len(self.stitcher.parts), width=self.stitcher.width, height=self.stitcher.height)
        state = self.tr_key("scroll_paused" if self._paused else "scroll_listening")
        message = self.tr_key(self._error) if self._error else state
        self.status.setText(progress + "\n" + message)
        self.setAccessibleDescription(self.status.text())
        self.preview.setToolTip(message if self._error else "")
        self.setToolTip(message if self._error else "")
        color = "#f59e0b" if self._error else "#dbe1e8"
        self.preview.setStyleSheet(f"QLabel {{border:1px solid {color}; padding:2px;}}")
        self.buttons["done"].setEnabled(not self._finishing)

    def _pause(self):
        self._paused = True
        self._epoch += 1  # Results already being computed may no longer be applied.
        self._timer.stop()
        self._start_timer.stop()

    def toggle_pause(self):
        if self._closed or self._finishing:
            return
        if self._paused:
            self._paused = False
            self._error = None
            self._sample_key = self._accepted_key
            self._timer.start()
        else:
            self._pause()
        self.update_status()

    def toggle_preview(self):
        # Compatibility for integrations; live preview never pauses capture.
        self.update_preview()

    def update_preview(self):
        from ui.screenshot_common import pil_image_to_qimage
        image = pil_image_to_qimage(self.stitcher.preview_image())
        self.preview.setPixmap(QPixmap.fromImage(image))
        self.preview.setAccessibleName(self.tr_key("scroll_live_preview"))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _capture(self, *, final=False):
        if self._closed or self._pending or (self._paused and not final):
            # Capture-exclusion failures may recover after moving the panel.
            if (self._paused and self._error == "scroll_toolbar_overlap"
                    and self.capture_rect is not None
                    and not self.frameGeometry().intersects(self.capture_rect)):
                self._paused, self._error = False, None
            return
        # If Windows cannot exclude us, never silently bake the controls into
        # a full-screen/overlapping capture. User can move this window aside.
        if (not self._excluded and self.capture_rect is not None
                and self.frameGeometry().intersects(self.capture_rect)):
            self._capture_error("scroll_toolbar_overlap", final=final)
            return
        try:
            frame = self.capture_frame().convert("RGB")
            key = frame_key(frame)
        except StitchError as exc:
            self._capture_error(str(exc) if str(exc) == "scroll_size" else "scroll_capture_error",
                                final=final)
            return
        except Exception as exc:
            print(f"[Screenshot] scroll capture failed type={type(exc).__name__}")
            self._capture_error("scroll_capture_error", final=final)
            return
        if key == self._accepted_key:
            self._sample_key = key
            self._error = None
            if final:
                self._complete()
            else:
                self.update_status()
            return
        if not final and key == self._sample_key:
            return  # Unchanged/rejected frames are not analyzed or logged repeatedly.
        self._sample_key = key
        self._pending = True
        job = _AnalyzeFrame(self.stitcher, frame, key, self._epoch, final)
        job.signals.completed.connect(self._analyzed)
        self._job = job
        QThreadPool.globalInstance().start(job)
        self.update_status()

    @Slot(object)
    def _analyzed(self, result):
        epoch, stitcher, key, extra, reason, error_type, final = result
        self._pending = False
        self._job = None
        if self._closed:
            return
        if epoch == self._epoch:
            self.analysisObserved.emit({
                "reason": reason, "extra_rows": extra, "error_type": error_type,
                "content_rect": stitcher.content_rect,
                "position": stitcher._position, "height": stitcher.height,
            })
            if reason == "scroll_unchanged":
                # Ignored fixed panels can blink while the body stays still.
                # This is not a failed join or a reason to block Finish.
                self._accepted_key, self._error = key, None
                self.update_preview()
                if final:
                    self._complete()
                elif self._finishing:
                    # Finish may have been clicked while this ordinary sample
                    # was in flight. An unchanged body is a valid result, not a
                    # reason to leave Finish disabled forever. Still sample the
                    # latest viewport so the last scroll is not silently lost.
                    self._capture(final=True)
                else:
                    self.update_status()
                return
            if reason:
                if error_type:
                    print(f"[Screenshot] scroll capture failed type={error_type}")
                else:
                    print(f"[Screenshot] scroll append rejected reason={reason}")
                if reason in {"scroll_size", "scroll_limit", "scroll_capture_error"} or final:
                    self._capture_error(reason, final=final)
                else:
                    self._error = reason
            else:
                self.stitcher = stitcher
                if stitcher.content_rect is not None and not self._image_viewport_detected:
                    self.viewport_detected = True
                    self._image_viewport_detected = True
                    self.hint.setText(self.tr_key("scroll_viewport_detected"))
                    print(f"[Screenshot] scroll viewport source=image_registration "
                          f"size={stitcher.width}x{stitcher.viewport_height}")
                self._accepted_key, self._error = key, None
                print(f"[Screenshot] scroll auto appended rows={extra} frames={len(stitcher.parts)} "
                      f"size={stitcher.width}x{stitcher.height}")
                self.update_preview()
                if final:
                    self._complete()
                    return
        if self._finishing:
            # The user clicked Finish during an in-flight analysis. Flush the
            # latest viewport once more rather than dropping the final scroll.
            self._capture(final=True)
        else:
            self.update_status()

    def _capture_error(self, reason, *, final=False):
        # A failed final join is not a permanent pause with no Resume button.
        # Continue listening for a recovered overlap; Finish again explicitly
        # accepts the existing partial image if the viewport is still the same.
        if final and reason == "scroll_overlap":
            self._partial_key = self._sample_key
            self._paused = False
            self._timer.start()
        elif reason == "scroll_toolbar_overlap":
            self._pause()
            self._timer.start()  # periodically detect when the user moves us away
        else:
            self._pause()
        self._finishing = False
        self._error = "scroll_finish_partial" if final and reason == "scroll_overlap" else reason
        self.update_status()

    def undo(self):
        if self._pending or self._finishing:
            return
        self._pause()
        self.stitcher.undo()
        self._accepted_key = self._sample_key = frame_key(self.stitcher.last_frame())
        self._error = "scroll_undo_paused"
        if self.preview.isVisible():
            self.update_preview()
        self.update_status()

    def finish(self):
        if self._closed or self._finishing:
            return
        print(f"[Screenshot] scroll finish requested pending={self._pending} paused={self._paused}")
        if self._paused:
            self._complete()  # Explicitly keep the accepted image after pause/undo/error.
            return
        if self._error == "scroll_finish_partial":
            try:
                unchanged = frame_key(self.capture_frame().convert("RGB")) == self._partial_key
            except Exception:
                unchanged = False
            if unchanged:
                self._complete()
                return
        self._finishing = True
        self._timer.stop()
        self._start_timer.stop()
        self.update_status()
        if not self._pending:
            self._capture(final=True)

    def _complete(self):
        if self._closed or self._done:
            return
        self._done = True
        self._timer.stop()
        self._start_timer.stop()
        self.hide()
        image = self.stitcher.render()
        print(f"[Screenshot] scroll complete size={image.width}x{image.height}")
        self.completed.emit(image)
        self.close()

    def closeEvent(self, event):
        self._closed = True
        self._epoch += 1
        self._timer.stop()
        self._start_timer.stop()
        self.stitcher.close()
        if not self._done:
            self.cancelled.emit()
        super().closeEvent(event)
