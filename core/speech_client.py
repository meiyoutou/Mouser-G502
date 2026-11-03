"""Local helper IPC. Only the main application owns focus and paste safety."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

from core.speech_components import runtime_executable, verify_executable, ComponentError
from core.speech_service import PROTOCOL, MAX_LINE, freeze, pipe_lines
_SPAWN_LOCK = threading.Lock()


def _spawn(command, **kwargs):
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return subprocess.Popen(command, **kwargs)
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDllDirectoryW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
    kernel.SetDllDirectoryW.argtypes = [ctypes.c_wchar_p]
    with _SPAWN_LOCK:
        length = kernel.GetDllDirectoryW(0, None)
        buffer = ctypes.create_unicode_buffer(length + 1)
        kernel.GetDllDirectoryW(len(buffer), buffer)
        previous = buffer.value or None
        # External runtime must not inherit the main app's bundled DLL preference.
        if not kernel.SetDllDirectoryW(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return subprocess.Popen(command, **kwargs)
        finally:
            kernel.SetDllDirectoryW(previous)


def helper_command():
    executable = runtime_executable()
    if executable is not None:
        verify_executable(executable)
        return [str(executable)]
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-u", str(Path(__file__).resolve().parents[1] / "speech_worker.py")]
    raise ComponentError("runtime", "Install the speech component in Voice settings first")


def worker_settings(settings):
    from core.speech_models import find_model, SENSE_VOICE_MODEL, STREAMING_MODEL
    result = dict(settings)
    # Pass resolved absolute paths, including legacy bundled/custom models.
    for key, name in (("sense_voice_model_path", SENSE_VOICE_MODEL),
                      ("sherpa_model_path", STREAMING_MODEL), ("vad_model_path", "silero_vad.onnx")):
        path = find_model(name, str(result.get(key) or ""))
        if path is not None:
            result[key] = str(path.resolve())
    if not result.get("model_path"):
        path = find_model("faster-whisper-" + str(result.get("model") or "small"))
        if path is not None:
            result["model_path"] = str(path.resolve())
    return result


class SpeechClient:
    def __init__(self, *, command=None):
        self.command = command
        self.process = None
        self.events = None
        self._write_lock = threading.Lock()
        self._request = 1000000
        self._model_signature = None

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYINSTALLER_RESET_ENVIRONMENT": "1"}
        # Do not inherit the main PyInstaller app's DLL search override when
        # launching an independently packaged runtime (its own bootloader resets it).
        command = self.command or helper_command()
        process = _spawn(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1,
            env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            cwd=str(Path(command[-1]).resolve().parent))
        events = queue.Queue(maxsize=512)
        self.process, self.events = process, events
        def read():
            try:
                for line in pipe_lines(process.stdout):
                    if len(line) > MAX_LINE:
                        raise ValueError("Oversized speech response")
                    events.put(json.loads(line), timeout=5)
            except (ValueError, OSError, queue.Full):
                pass
            finally:
                try:
                    events.put({"type": "closed"}, timeout=1)
                except queue.Full:
                    pass
                process.stdout.close()
        threading.Thread(target=read, name="SpeechResponses", daemon=True).start()
        try:
            hello = events.get(timeout=30)
        except queue.Empty as error:
            self.close()
            raise RuntimeError("Speech runtime startup timed out") from error
        if hello != {"type": "hello", "protocol": PROTOCOL}:
            self.close()
            raise RuntimeError("Incompatible speech runtime; reinstall its component")

    def _send(self, message):
        data = json.dumps(message, ensure_ascii=False)
        if len(data.encode("utf-8")) > MAX_LINE:
            raise ValueError("Speech settings exceed protocol limit")
        with self._write_lock:
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError("Speech runtime exited")
            self.process.stdin.write(data + "\n")
            self.process.stdin.flush()

    def query(self, op, *, settings=None, wav=None, timeout=60):
        self._start()
        self._request += 1
        request = self._request
        message = {"op": op, "session": request}
        if settings is not None:
            message["settings"] = worker_settings(settings)
        if wav is not None:
            message["wav"] = str(Path(wav).resolve())
        self._send(message)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.events.get(timeout=min(1, max(.01, deadline - time.monotonic())))
            except queue.Empty:
                continue
            if event["type"] == "closed":
                raise RuntimeError("Speech runtime exited unexpectedly")
            if event.get("session") == request and event["type"] not in {"started", "checking"}:
                if event["type"] == "done" and not event.get("ok"):
                    raise RuntimeError(event.get("error", "Speech request failed"))
                return event
        raise RuntimeError("Speech component request timed out")

    def run(self, session, settings, stop_event, *, target_getter, on_event, test_wav=None):
        resolved = worker_settings(settings)
        signature_keys = ("engine", "model", "model_path", "sense_voice_model_path", "sherpa_model_path",
                          "vad_model_path", "language", "ui_language", "device", "compute_type",
                          "preview_enabled", "sherpa_num_threads", "sherpa_use_int8", "custom_words")
        signature = tuple(str(resolved.get(key, "")) for key in signature_keys)
        if self._model_signature is not None and self._model_signature != signature:
            # Different models must not accumulate in one native allocator.
            self.close()
        self._model_signature = signature
        self._start()
        message = {"op": "start", "session": session, "settings": resolved,
                   "target": target_getter()}
        if test_wav is not None:
            message["test_wav"] = str(Path(test_wav).resolve())
        self._send(message)
        sent_stop, stopping_at, last_target, started = False, None, 0., False
        deadline = time.monotonic() + 30
        while True:
            now = time.monotonic()
            if stop_event.is_set() and not sent_stop:
                self._send({"op": "stop", "session": session})
                sent_stop, stopping_at = True, now
            if now - last_target >= .1:
                self._send({"op": "target", "session": session, "target": target_getter()})
                last_target = now
            if (not started and now > deadline) or (stopping_at is not None and now - stopping_at > 120):
                self.close()
                raise RuntimeError("Speech runtime did not finish within its safe time limit")
            try:
                event = self.events.get(timeout=.1)
            except queue.Empty:
                continue
            if event["type"] == "closed":
                raise RuntimeError("Speech runtime exited unexpectedly; recording was stopped")
            if event.get("session") != session:
                continue
            if event["type"] == "started":
                started = True
            if "target" in event:
                event["target"] = freeze(event["target"])
            on_event(event)
            if event["type"] == "done":
                return event

    def close(self):
        process, self.process = self.process, None
        if process is None:
            return
        try:
            if process.poll() is None:
                with self._write_lock:
                    process.stdin.write('{"op":"shutdown"}\n')
                    process.stdin.flush()
            process.stdin.close()
        except (OSError, ValueError):
            pass
        # This is our own helper, not another Mouser or a user's application.
        # Wait off the Qt thread; EOF normally drains capture and then exits.
        def reap():
            try:
                process.wait(timeout=125)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)
        threading.Thread(target=reap, name="SpeechShutdown", daemon=True).start()
