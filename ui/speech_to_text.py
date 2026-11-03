"""Continuous local voice typing with ordered phrase delivery and caret preview."""
from __future__ import annotations
import os
from pathlib import Path
import tempfile
import threading
import time
import traceback
import wave
from datetime import datetime
from PySide6.QtCore import QObject, QPoint, QTimer, Qt, Signal, QMimeData
from PySide6.QtGui import QGuiApplication
from core.key_simulator import SPEECH_TO_TEXT_ACTION
from core.speech_anchor import (InputAnchorTracker, map_physical_rect, modifiers_held,
                                monitor_geometry, place_preview, read_native_anchor)
from core.speech_session import (SPEECH_DEFAULTS, SENSE_VOICE_MODEL, STREAMING_MODEL,
                                 bundle_roots, bundled_path, correct_text, custom_words,
                                 resolve_engine, run_session, model_roots)
from core.speech_models import runtime_enabled

_MODEL_CACHE, _SHERPA_RECOGNIZER_CACHE, _SENSE_VOICE_CACHE = {}, {}, {}
_MODEL_LOCK = threading.Lock()
_SHERPA_MODEL_NAME = STREAMING_MODEL


def normalize_settings(provided=None):
    settings = {**SPEECH_DEFAULTS, **(provided or {})}
    overrides = {"MOUSER_SPEECH_ENGINE": "engine", "MOUSER_SPEECH_MODEL": "model",
                 "MOUSER_SHERPA_MODEL_PATH": "sherpa_model_path", "MOUSER_SPEECH_MODEL_PATH": "model_path"}
    for variable, key in overrides.items():
        if os.environ.get(variable):
            settings[key] = os.environ[variable].strip()
    settings["engine"] = resolve_engine(settings)
    return settings  # Never silently downgrade explicit model/threshold choices.


def describe_runtime(provided=None):
    settings = normalize_settings(provided)
    engine = settings["engine"]
    if engine == "sense_voice":
        name = "SenseVoice Small (int8)"
        ready = bundled_path(SENSE_VOICE_MODEL, settings["sense_voice_model_path"], ("model.int8.onnx", "tokens.txt")) is not None
    elif engine == "sherpa_onnx_streaming":
        name = "Zipformer 14M"
        ready = _resolve_sherpa_model_dir(settings["sherpa_model_path"]) is not None
    elif engine == "faster_whisper":
        name = "Whisper " + str(settings["model"])
        location = Path(_resolve_model_location(settings["model_path"], settings["model"]))
        ready = (location / "model.bin").is_file() and (location / "config.json").is_file()
    else:
        name, ready = "", False
    enabled = runtime_enabled()
    vad_ready = bundled_path("silero_vad.onnx", settings.get("vad_model_path", "")) is not None
    return {"engine": engine, "model": name, "ready": enabled and ready and vad_ready,
            "enabled": enabled, "model_ready": ready, "vad_ready": vad_ready,
            "preview": bool(enabled and settings["preview_enabled"] and _resolve_sherpa_model_dir(settings["sherpa_model_path"]))}


class SpeechToTextController(QObject):
    _requestAction, _statusRequested = Signal(str), Signal(object)
    _partialRequested, _phraseReady, _workerFinished = Signal(object), Signal(object), Signal(object)
    pendingTextChanged, runtimeChanged = Signal(str), Signal(str)
    levelChanged, _focusPauseRequested = Signal(float), Signal(int)
    busyChanged = Signal(bool)

    def __init__(self, *, status_callback=None, settings_getter=None, translator=None, parent=None):
        super().__init__(parent)
        self._status_callback, self._settings_getter, self._translator = status_callback, settings_getter, translator
        self._worker = self._stop_event = None
        from core.speech_client import SpeechClient
        self._speech_client = SpeechClient()
        self._busy, self._worker_done = False, False
        self._state = "idle"
        self._started_at = self._last_request_at = 0.0
        self._session = 0
        self._anchor_tracker = InputAnchorTracker()
        self._focus_lock = threading.Lock()
        self._focus_epoch, self._focus_identity = 0, None
        self._session_window_focus, self._session_runtime = None, ()
        self._paused, self._partial, self._status_text = False, "", ""
        self._pause_notified = False
        self._status_template = None
        self._session_settings = {}
        self._status_overlay = None
        self._paste_queue, self._pending_texts, self._seen_phrases = [], [], set()
        self._delivery_active, self._delivered = False, 0
        self._clipboard_inflight = False
        self._focus_timer = QTimer(self)
        self._focus_timer.setInterval(100)
        self._focus_timer.timeout.connect(self._poll_focus)
        self._requestAction.connect(self._handle_request, Qt.QueuedConnection)
        self._statusRequested.connect(self._handle_status, Qt.QueuedConnection)
        self._partialRequested.connect(self._handle_partial, Qt.QueuedConnection)
        self._phraseReady.connect(self._handle_phrase, Qt.QueuedConnection)
        self._workerFinished.connect(self._handle_worker_finished, Qt.QueuedConnection)
        self._focusPauseRequested.connect(self._handle_focus_pause, Qt.QueuedConnection)

    def request_action(self, action_id):
        self._requestAction.emit(action_id)

    def _settings(self):
        try:
            provided = dict(self._settings_getter() or {}) if self._settings_getter else {}
        except Exception:
            provided = {}
        return normalize_settings(provided)

    def _tr(self, key, default, **values):
        if self._translator:
            try:
                return self._translator(key, default, **values)
            except Exception:
                pass
        return default.format(**values)

    def _status(self, key, default, **values):
        self._statusRequested.emit((self._session, key, default, values))

    def _handle_status(self, data):
        session, key, default, values = data
        if session != self._session:
            return
        text = self._tr(key, default, **values)
        self._status_template = (key, default, values)
        self._status_text = text
        _log_speech_event(f"STATUS {key}")  # Never log recognized words.
        if self._status_callback:
            self._status_callback(text)
        self._refresh_overlay()

    def _handle_partial(self, data):
        session, text, level = data
        if session == self._session and self._busy:
            self._partial = str(text or "")
            self.levelChanged.emit(max(0.0, min(1.0, float(level))))
            self._refresh_overlay()

    def _refresh_overlay(self):
        settings = self._session_settings or self._settings()
        if not settings.get("status_overlay", True):
            return
        if self._status_overlay is None:
            self._status_overlay = _StatusOverlay(self, anchor_getter=self._anchor_tracker.snapshot)
        if self._status_template:
            key, default, values = self._status_template
            self._status_text = self._tr(key, default, **values)
        title = self._tr("status.speech_target_paused", "Input target changed; automatic input is paused.") if self._paused else self._status_text
        body = self._partial[-160:] if settings.get("preview_enabled", True) else ""
        self._status_overlay.show_message(title + ("\n" + body if body else ""), duration_ms=0 if self._busy else 3600)

    def _target_snapshot(self):
        anchor = self._anchor_tracker.snapshot()
        changed = False
        with self._focus_lock:
            previous = self._focus_identity
            if (previous is None or previous[:2] != anchor.identity[:2]
                    or (previous[2] and anchor.runtime_id and previous[2] != anchor.runtime_id)):
                self._focus_epoch += 1
            # Missing/transient UIA data does not mean focus left and returned.
            # It still refuses a paste until a fresh editable observation exists.
            if previous is None or previous[:2] != anchor.identity[:2] or anchor.runtime_id:
                self._focus_identity = anchor.identity
            if self._busy and self._session_window_focus is not None:
                changed = (self._session_window_focus != anchor.identity[:2]
                           or bool(self._session_runtime and anchor.runtime_id
                                   and self._session_runtime != anchor.runtime_id))
                if not changed and anchor.editable and anchor.runtime_id and not self._session_runtime:
                    self._session_runtime = anchor.runtime_id
                changed = changed and not self._paused
                if changed:
                    self._paused = True
            result = (self._focus_epoch, anchor.identity, anchor.editable and not anchor.password)
        if changed:
            self._focusPauseRequested.emit(self._session)
        return result

    def _poll_focus(self):
        self._target_snapshot()

    def _handle_focus_pause(self, session):
        if session == self._session and self._busy:
            self._pause_delivery()

    def _handle_request(self, action_id):
        if action_id != SPEECH_TO_TEXT_ACTION:
            return
        now, settings = time.monotonic(), self._settings()
        if now - self._last_request_at < float(settings["request_debounce_seconds"]):
            return
        self._last_request_at = now
        if self._busy:
            if self._state == "stopping" or self._worker_done:
                return
            if now - self._started_at < float(settings["min_toggle_seconds"]):
                return
            self._state = "stopping"
            self._stop_event.set()
            self._status("status.speech_stopping", "Finishing the last phrase...")
            return
        availability = describe_runtime(settings)
        if settings.get("models_installing"):
            self._status("speech.stop_before_install", "Wait for model installation to finish before recording.")
            return
        if not availability["enabled"]:
            self._status("speech.lite_help", "Click Download and enable in Voice settings first; no microphone has been opened.")
            return
        if not availability["ready"]:
            self._status("speech.install_help", "Install a model pack in Voice settings first. No microphone has been opened.")
            return
        self._session += 1
        self._session_settings = settings
        self._busy, self._worker_done, self._paused = True, False, False
        self.busyChanged.emit(True)
        self._pause_notified = False
        self._state, self._partial = "recording", ""
        self._started_at, self._delivered = now, 0
        self._seen_phrases.clear()
        self._stop_event = threading.Event()
        anchor = self._anchor_tracker.snapshot()
        with self._focus_lock:
            self._focus_identity = anchor.identity
            self._session_window_focus = anchor.identity[:2]
            self._session_runtime = anchor.runtime_id if anchor.editable else ()
        self._anchor_tracker.start()
        self._poll_focus()
        self._focus_timer.start()
        self._status("status.speech_model_loading", "Loading local speech model...")
        self._worker = threading.Thread(target=self._run_worker, args=(self._session, settings, self._stop_event), name="MouserDictation", daemon=True)
        self._worker.start()

    def _run_worker(self, session, settings, stop_event):
        try:
            self.runtimeChanged.emit(describe_runtime(settings)["model"])
            def event(data):
                kind = data["type"]
                if kind == "partial":
                    self._partialRequested.emit((session, data["text"], data["level"]))
                elif kind == "phrase":
                    self._phraseReady.emit(data)
                elif kind == "status":
                    self._statusRequested.emit((session, data["key"], data["default"], data.get("values", {})))
                elif kind == "done":
                    self._workerFinished.emit(data)
            self._speech_client.run(session, settings, stop_event,
                target_getter=self._target_snapshot, on_event=event)
        except Exception as exc:
            _log_speech_event(f"ERROR {exc}\n{traceback.format_exc()}")
            self._workerFinished.emit({"session": session, "ok": False, "error": str(exc)})

    def _retain(self, text):
        if text:
            self._pending_texts.append(text)
            self.pendingTextChanged.emit("".join(self._pending_texts))

    def clear_pending(self):
        self._pending_texts.clear()
        self.pendingTextChanged.emit("")

    def _handle_phrase(self, data):
        if data.get("session") != self._session:
            return
        key = (data["session"], data["sequence"])
        if key in self._seen_phrases:
            return
        self._seen_phrases.add(key)
        text = str(data.get("text") or "").strip()
        if not text:
            return
        _log_speech_event(f"PHRASE {data['sequence']}: {len(text)} chars")
        if self._paused or not self._session_settings.get("auto_paste", True):
            self._retain(text)
            return
        self._paste_queue.append({**data, "text": text, "queued": time.monotonic(), "check_after": 0.0})
        self._start_delivery()

    def _start_delivery(self):
        if self._delivery_active or not self._paste_queue:
            self._finish_if_ready()
            return
        self._delivery_active = True
        QTimer.singleShot(max(0, int(self._session_settings.get("paste_delay_ms", 80))), self._deliver_one)

    def _pause_delivery(self):
        self._paused = True
        for data in self._paste_queue:
            self._retain(data["text"])
        self._paste_queue.clear()
        self._delivery_active = False
        if not self._pause_notified:
            self._pause_notified = True
            self._status("status.speech_target_paused", "Input target changed; automatic input is paused. Text is kept in Voice settings.")
        self._refresh_overlay()
        self._finish_if_ready()

    def _deliver_one(self):
        if not self._paste_queue:
            self._delivery_active = False
            self._finish_if_ready()
            return
        data = self._paste_queue[0]
        if self._paused or data["session"] != self._session or data["target"] != self._target_snapshot() or not data["target"][2]:
            self._pause_delivery()
            return
        anchor = self._anchor_tracker.snapshot()
        if anchor.runtime_id:
            if not data["check_after"]:
                data["check_after"] = time.monotonic()
            if anchor.observed_at < data["check_after"]:
                if time.monotonic() - data["check_after"] > 1.0:
                    self._pause_delivery()
                else:
                    QTimer.singleShot(50, self._deliver_one)
                return
        if modifiers_held():
            if time.monotonic() - data["queued"] > 3:
                self._pause_delivery()
            else:
                QTimer.singleShot(80, self._deliver_one)
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            self._pause_delivery()
            return
        try:
            saved = _copy_mime_data(clipboard.mimeData())
        except Exception:
            saved = None
        if saved is None:
            self._pause_delivery()
            return
        text = data["text"]
        clipboard.setText(text)
        try:
            from core.key_simulator import send_paste_checked
            native = read_native_anchor()
            if (native.window, native.focus) != data["target"][1][:2]:
                raise RuntimeError("Input target changed before paste")
            send_paste_checked()
            self._paste_queue.pop(0)
            self._delivered += 1
            self._clipboard_inflight = True
        except Exception as exc:
            _log_speech_event(f"PASTE ERROR {exc}")
            if saved is not None and clipboard.text() == text:
                clipboard.setMimeData(saved)
            self._pause_delivery()
            return
        def restored():
            if saved is not None and clipboard.text() == text:
                clipboard.setMimeData(saved)
            self._delivery_active = False
            self._clipboard_inflight = False
            self._start_delivery()
        QTimer.singleShot(350, restored)

    def _handle_worker_finished(self, data):
        if data.get("session") != self._session:
            return
        self._worker_done, self._partial = True, ""
        if not data.get("ok"):
            error = self._friendly_error(str(data.get("error") or ""))
            self._status("status.speech_error_detail", "Voice typing failed: {error}", error=error)
        elif not data.get("phrases"):
            self._status("status.speech_empty", "No speech was recognized.")
        else:
            self._status("status.speech_session_done", "Dictation stopped. Confirmed phrases: {count}.", count=data["phrases"])
        self._finish_if_ready()

    def _finish_if_ready(self):
        if self._worker_done and not self._paste_queue and not self._delivery_active and not self._clipboard_inflight:
            self._busy, self._state = False, "idle"
            self.busyChanged.emit(False)
            self._stop_event = None
            self._focus_timer.stop()
            self._anchor_tracker.stop()
            self.runtimeChanged.emit("")
            self.levelChanged.emit(0.0)
            self._refresh_overlay()

    def _friendly_error(self, error):
        cases = [("Selected microphone", "status.speech_mic_missing", "Selected microphone is unavailable."),
                 ("Silero VAD", "status.speech_vad_missing", "Voice detector model is missing."),
                 ("backlog", "status.speech_backlog", "Recognition backlog exceeded the safe limit."),
                 ("overflow", "status.speech_backlog", "Audio overflow exceeded the safe limit."),
                 ("Microphone capture", "status.speech_capture_failed", "Microphone capture failed.")]
        for marker, key, default in cases:
            if marker.lower() in error.lower():
                return self._tr(key, default)
        return error or self._tr("status.speech_failed_detail", "Details are in the local speech log.")

    def shutdown(self):
        if self._stop_event:
            self._stop_event.set()
        self._speech_client.close()
        self._anchor_tracker.shutdown()
        self._focus_timer.stop()

    def refresh_language(self):
        if self._status_overlay and self._status_overlay._label and self._status_overlay._label.isVisible():
            self._refresh_overlay()


def _copy_mime_data(source):
    if source is None:
        return QMimeData()
    clone, total = QMimeData(), 0
    for fmt in source.formats():
        value = source.data(fmt)
        total += value.size()
        if total > 32 * 1024 * 1024:
            return None
        clone.setData(fmt, value)
    return clone


class _StatusOverlay(QObject):
    def __init__(self, parent=None, *, anchor_getter=None):
        super().__init__(parent)
        self._label = None
        self._anchor_getter = anchor_getter or read_native_anchor
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(150)
        self._follow_timer.timeout.connect(self._place)

    def _ensure_label(self):
        if self._label is None:
            from PySide6.QtWidgets import QLabel, QApplication
            if not isinstance(QApplication.instance(), QApplication):
                return None
            label = QLabel()
            label.setObjectName("MouserSpeechPreview")
            label.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                                 | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
            label.setAttribute(Qt.WA_ShowWithoutActivating, True)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            label.setTextFormat(Qt.PlainText)
            label.setWordWrap(True)
            label.setFixedWidth(380)
            label.setMargin(12)
            label.setStyleSheet("QLabel {background: #20242b; color: white; border: 1px solid #475569;"
                                "border-radius: 10px; font-size: 14px; padding: 4px;}")
            self._label = label
        return self._label

    def show_message(self, text, *, duration_ms=3600):
        label = self._ensure_label()
        if label is None:
            return
        label.setText(text)
        label.setFixedHeight(max(64, min(190, label.heightForWidth(label.width()))))
        self._place()
        label.show()
        self._follow_timer.start()
        self._hide_timer.stop()
        if duration_ms:
            self._hide_timer.start(duration_ms)

    def hide(self):
        self._follow_timer.stop()
        if self._label:
            self._label.hide()

    def _place(self):
        label = self._label
        if label is None:
            return
        anchor = self._anchor_getter()
        bounds, screens = anchor.caret or anchor.rect, QGuiApplication.screens()
        if not screens:
            return
        screen = QGuiApplication.primaryScreen()
        if bounds:
            mapping = monitor_geometry((bounds[0], bounds[1]))
            if mapping:
                physical, name = mapping
                screen = next((item for item in screens if item.name() == name), screen)
                geometry = screen.geometry()
                bounds = map_physical_rect(bounds, physical,
                    (geometry.x(), geometry.y(), geometry.x() + geometry.width(), geometry.y() + geometry.height()))
        available = screen.availableGeometry()
        area = (available.x(), available.y(), available.x() + available.width(), available.y() + available.height())
        if not bounds:
            bounds = (area[0] + 24, area[3] - 36, area[0] + 24, area[3] - 24)
        label.setFixedWidth(max(180, min(380, available.width() - 32)))
        x, y = place_preview(bounds, (label.width(), label.height()), area, caret=bool(anchor.caret))
        label.move(QPoint(x, y))


def _log_speech_event(message):
    try:
        root = Path(os.environ.get("APPDATA") or Path.home()) / "Mouser"
        root.mkdir(parents=True, exist_ok=True)
        with (root / "speech_to_text.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}\n")
    except OSError:
        pass


from core.speech_recognizer import (  # Backward-compatible public test helpers.
    _resolve_sherpa_model_dir, _get_sherpa_recognizer, _get_sense_voice,
    _get_whisper, _prepare_final_model, _transcribe_phrase, _transcribe_wav,
    _read_wav_mono_float32, _resolve_model_location, _candidate_bundle_roots,
    _resolve_language,
)
