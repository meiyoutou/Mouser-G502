"""Private stdin/stdout ASR service. Never pastes, uploads, or stores speech."""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

PROTOCOL = 1
MAX_LINE = 128 * 1024
IDLE_SECONDS = 30


def freeze(value):
    return tuple(freeze(item) for item in value) if isinstance(value, list) else value


def pipe_lines(stream):
    """Bounded pipe framing without a perpetually blocked Windows stdin read.

    Blocking stdin reads stalled native module initialization on the tested
    Windows runtime. Poll availability and read only bytes already in the pipe.
    """
    descriptor = None
    if sys.platform == "win32":
        try:
            descriptor = stream.fileno()
        except (AttributeError, OSError):
            pass
    if descriptor is not None:
        import ctypes
        from ctypes import wintypes
        import msvcrt
        handle = msvcrt.get_osfhandle(descriptor)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        read_file = kernel.ReadFile
        read_file.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                              ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        read_file.restype = wintypes.BOOL
        peek = kernel.PeekNamedPipe
        peek.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        peek.restype = wintypes.BOOL
        buffer, count = ctypes.create_string_buffer(4096), wintypes.DWORD()
        def read_chunk():
            available = wintypes.DWORD()
            while True:
                if not peek(handle, None, 0, None, ctypes.byref(available), None):
                    if ctypes.get_last_error() in {109, 6}:
                        return b""
                    raise ctypes.WinError(ctypes.get_last_error())
                if available.value:
                    break
                time.sleep(.02)
            if not read_file(handle, buffer, min(len(buffer), available.value), ctypes.byref(count), None):
                if ctypes.get_last_error() in {109, 6}:
                    return b""
                raise ctypes.WinError(ctypes.get_last_error())
            return buffer.raw[:count.value]
        pending = b""
        while chunk := read_chunk():
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if len(line) > MAX_LINE:
                    raise ValueError("Speech command exceeded protocol limit")
                yield line.decode("utf-8")
            if len(pending) > MAX_LINE:
                raise ValueError("Speech command exceeded protocol limit")
    else:
        while line := stream.readline(MAX_LINE + 1):
            if len(line.encode("utf-8")) > MAX_LINE:
                raise ValueError("Speech command exceeded protocol limit")
            yield line


def serve(input_stream=None, output_stream=None, *, idle_seconds=IDLE_SECONDS):
    """EOF/Shutdown stops capture; normal Stop drains the last phrase first."""
    source, output = input_stream or sys.stdin, output_stream or sys.stdout
    # Frozen console bootloaders can use the Windows locale (GBK) despite the
    # caller's environment. Protocol messages and recognized Chinese are UTF-8.
    if output is sys.stdout and hasattr(output, "reconfigure"):
        output.reconfigure(encoding="utf-8", errors="strict")
    commands, write_lock, state_lock = queue.Queue(maxsize=8), threading.Lock(), threading.Lock()
    state = {"session": None, "stop": None, "target": None}
    closing = threading.Event()
    pending_stops = set()

    def emit(kind, **data):
        line = json.dumps({"type": kind, **data}, ensure_ascii=False)
        if len(line.encode("utf-8")) > MAX_LINE:
            raise RuntimeError("Speech response exceeded protocol limit")
        with write_lock:
            output.write(line + "\n")
            output.flush()

    def read():
        try:
            for line in pipe_lines(source):
                message = json.loads(line)
                op = message.get("op")
                if op in {"target", "stop"}:
                    with state_lock:
                        if message.get("session") == state["session"]:
                            if op == "stop" and state["stop"]:
                                state["stop"].set()
                            elif op == "target":
                                state["target"] = freeze(message.get("target"))
                        elif op == "stop":
                            pending_stops.add(message.get("session"))
                elif op == "shutdown":
                    break
                elif op in {"start", "devices", "check", "transcribe"}:
                    commands.put_nowait(message)
                else:
                    break
        except (ValueError, OSError, queue.Full):
            pass
        finally:
            closing.set()
            with state_lock:
                if state["stop"]:
                    state["stop"].set()
            try:
                commands.put_nowait({"op": "shutdown"})
            except queue.Full:
                pass

    emit("hello", protocol=PROTOCOL)
    threading.Thread(target=read, name="SpeechControl", daemon=True).start()
    while not closing.is_set():
        try:
            command = commands.get(timeout=idle_seconds)
        except queue.Empty:
            break  # Exit the process, including all native model allocations.
        op = command["op"]
        if op == "shutdown":
            break
        session = command.get("session", 0)
        try:
            if op == "devices":
                from core.speech_session import list_microphones
                emit("devices", session=session, devices=list_microphones())
                continue
            if op == "check":
                import importlib
                for name in ("numpy", "sherpa_onnx", "soxr", "sounddevice", "faster_whisper"):
                    emit("checking", session=session, module=name)
                    importlib.import_module(name)
                emit("check", session=session, ok=True, microphone_opened=False, input_sent=False)
                continue
            from core.speech_recognizer import _prepare_final_model, _get_sherpa_recognizer, _transcribe_phrase, _read_wav_mono_float32
            from core.speech_session import SPEECH_DEFAULTS, STREAMING_MODEL, bundled_path, correct_text, run_session, PhraseJob
            settings = {**SPEECH_DEFAULTS, **command.get("settings", {})}
            tr = lambda key, default, **values: default.format(**values)
            stop = threading.Event()
            with state_lock:
                state.update(session=session, stop=stop, target=freeze(command.get("target")))
                if session in pending_stops:
                    stop.set()
                    pending_stops.discard(session)
            emit("started", session=session)
            _prepare_final_model(settings, tr)
            if op == "transcribe":
                # Explicit, opt-in diagnostics use public audio; never sent by the normal UI.
                path = Path(command["wav"])
                audio = _read_wav_mono_float32(path, tr)
                text = _transcribe_phrase(PhraseJob(1, audio, "", None), settings, tr)
                emit("transcribed", session=session, text=text)
                continue
            if stop.is_set():
                emit("done", session=session, ok=True, phrases=0)
                continue
            preview = None
            if settings.get("preview_enabled") and bundled_path(STREAMING_MODEL, settings.get("sherpa_model_path", "")):
                preview = _get_sherpa_recognizer(settings, tr, preview=True)
            def target():
                with state_lock:
                    return state["target"]
            def status(key, default, **values):
                emit("status", session=session, key=key, default=default, values=values)
            def phrase(job, text):
                emit("phrase", session=session, sequence=job.sequence, text=text, target=job.target)
            # Test source is opt-in, file-only, and cannot inject input into applications.
            audio_source = None
            if command.get("test_wav"):
                import numpy as np
                audio = np.concatenate((np.zeros(16000, dtype=np.float32),
                    _read_wav_mono_float32(command["test_wav"], tr), np.zeros(32000, dtype=np.float32)))
                audio_source = (audio[i:i + 1024] for i in range(0, len(audio), 1024))
            result = run_session(settings, stop, preview_recognizer=preview,
                transcribe=lambda job: correct_text(_transcribe_phrase(job, settings, tr), settings),
                on_partial=lambda text, level: emit("partial", session=session, text=text, level=level),
                on_phrase=phrase, on_status=status, target_getter=target, audio_source=audio_source)
            emit("done", session=session, ok=True, **result)
        except Exception as error:
            # Report only the error; no recognized content, recording, or config is logged.
            emit("done", session=session, ok=False, error=str(error))
        finally:
            with state_lock:
                state.update(session=None, stop=None, target=None)
    return 0
