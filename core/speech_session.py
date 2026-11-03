"""Bounded, continuous local dictation: capture -> VAD -> phrase recognition.

The PortAudio callback only copies audio. Final recognition has its own worker
so neither a larger model nor pasting a phrase interrupts microphone capture.
No recordings or transcripts are saved by this module.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time
from typing import Any, Callable


from core.speech_models import (SENSE_VOICE_MODEL, STREAMING_MODEL, bundle_roots,
                                find_model, model_roots)
SPEECH_DEFAULTS = {
    "engine": "auto", "model": "small", "model_path": "",
    "sherpa_model_path": "", "sense_voice_model_path": "",
    "sherpa_use_int8": True, "sherpa_num_threads": 2,
    "sherpa_partial_interval_ms": 260, "language": "zh",
    "device": "cpu", "compute_type": "int8", "beam_size": 5,
    "microphone": "", "preview_enabled": True, "continuous": True,
    "auto_paste": True, "sample_rate": 16000, "max_record_seconds": 30.0,
    "max_session_seconds": 3600.0, "min_record_seconds": 0.25,
    "min_toggle_seconds": 0.8, "request_debounce_seconds": 0.2,
    "silence_stop_seconds": 1.2, "silence_threshold": 0.006,
    "vad_threshold": 0.5, "vad_model_path": "", "paste_delay_ms": 80,
    "status_overlay": True, "status_overlay_ms": 3600,
    "custom_words": "", "corrections": "", "corrections_enabled": False,
}


def bundled_path(name, explicit="", required=()):
    return find_model(name, explicit, required)


def resolve_engine(settings):
    engine = str(settings.get("engine") or "auto")
    if engine != "auto":
        return engine
    language = str(settings.get("language") or "zh")
    if language == "follow_ui":
        language = str(settings.get("ui_language") or "auto")
    if language.startswith("zh"):
        language = "zh"
    if language.startswith("en"):
        language = "en"
    if language in {"auto", "zh", "en", "yue", "ja", "ko"} and bundled_path(SENSE_VOICE_MODEL, settings.get("sense_voice_model_path", ""), ("model.int8.onnx", "tokens.txt")):
        return "sense_voice"
    if language == "zh" and bundled_path(STREAMING_MODEL, settings.get("sherpa_model_path", ""),
            ("tokens.txt", "encoder-epoch-99-avg-1.int8.onnx", "decoder-epoch-99-avg-1.int8.onnx", "joiner-epoch-99-avg-1.int8.onnx")):
        return "sherpa_onnx_streaming"
    if settings.get("model_path") and (Path(settings["model_path"]) / "model.bin").is_file() and (Path(settings["model_path"]) / "config.json").is_file():
        return "faster_whisper"
    model_name = str(settings.get("model") or "small")
    if any(bundled_path(name, required=("config.json", "model.bin")) for name in (model_name, "faster-whisper-" + model_name)):
        return "faster_whisper"
    return "none"


def custom_words(settings):
    return list(dict.fromkeys(word.strip() for word in re.split(r"[\n,，;；]+", str(settings.get("custom_words") or "")) if word.strip()))[:200]


def correct_text(text, settings):
    text = re.sub(r"<\|[^>]*\|>", "", str(text or ""))
    text = " ".join(text.split()).strip()
    if settings.get("corrections_enabled", False):
        pairs = []
        for line in str(settings.get("corrections") or "").splitlines():
            if "=" in line:
                wrong, right = (part.strip() for part in line.split("=", 1))
                if wrong and right and wrong != right:
                    pairs.append((wrong, right))
        # Simultaneous, explicit substitutions only: no chained/semantic rewrite.
        mapping = dict(pairs)
        if mapping:
            pattern = "|".join(re.escape(key) for key in sorted(mapping, key=len, reverse=True))
            text = re.sub(pattern, lambda match: mapping[match.group(0)], text)
    return text


def list_microphones():
    import sounddevice as sd
    devices, apis = sd.query_devices(), sd.query_hostapis()
    result = [{"key": "", "name": ""}]
    seen = set()
    for info in devices:
        if info["max_input_channels"] < 1:
            continue
        key = f'{info["name"]} [{apis[info["hostapi"]]["name"]}]'
        if key not in seen:
            result.append({"key": key, "name": key})
            seen.add(key)
    return result


def microphone_device(sd, selected):
    if not selected:
        return None
    apis = sd.query_hostapis()
    for idx, info in enumerate(sd.query_devices()):
        key = f'{info["name"]} [{apis[info["hostapi"]]["name"]}]'
        if info["max_input_channels"] > 0 and key == selected:
            return idx
    raise RuntimeError("Selected microphone is unavailable; choose another microphone in Voice settings.")


def create_vad(settings):
    import sherpa_onnx
    model = bundled_path("silero_vad.onnx", str(settings.get("vad_model_path") or ""))
    if model is None:
        raise RuntimeError("Silero VAD model is missing; install a model pack in Voice settings.")
    config = sherpa_onnx.VadModelConfig()
    config.silero_vad.model = str(model)
    config.silero_vad.threshold = max(0.2, min(0.85, float(settings.get("vad_threshold", 0.5))))
    config.silero_vad.min_silence_duration = max(0.4, min(3.0, float(settings.get("silence_stop_seconds", 1.2))))
    config.silero_vad.min_speech_duration = max(0.1, min(0.5, float(settings.get("min_record_seconds", 0.25))))
    config.silero_vad.max_speech_duration = max(4.0, min(60.0, float(settings.get("max_record_seconds", 30))))
    config.sample_rate, config.num_threads = 16000, 1
    return sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=100)


@dataclass
class PhraseJob:
    sequence: int
    audio: Any
    preview: str
    target: Any


class PhraseDecoder:
    """Finite backlog, ordered callbacks, explicit failure on overflow."""
    def __init__(self, transcribe, completed, failed, stop_event, max_pending=8):
        self.jobs = queue.Queue(maxsize=max_pending)
        self.transcribe, self.completed, self.failed = transcribe, completed, failed
        self.stop_event = stop_event
        self.thread = threading.Thread(target=self._run, name="MouserPhraseASR", daemon=True)
        self.thread.start()

    def submit(self, job):
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            self.stop_event.set()
            raise RuntimeError("Recognition backlog is full. Recording stopped without silently dropping audio; use a faster model.")

    def finish(self):
        # Called after microphone closure. Keep draining accepted jobs in order.
        self.jobs.put(None)
        self.thread.join()

    def _run(self):
        while True:
            job = self.jobs.get()
            try:
                if job is None:
                    return
                text = self.transcribe(job)
                self.completed(job, text)
            except Exception as exc:
                self.stop_event.set()
                self.failed(str(exc))
            finally:
                self.jobs.task_done()


def run_session(settings, stop_event, *, preview_recognizer, transcribe, on_partial,
                on_phrase, on_status, target_getter, vad=None, audio_source=None):
    """Also accepts a synthetic 16-kHz source for deterministic integration tests."""
    import numpy as np
    vad = vad if vad is not None else create_vad(settings)
    failures, phrase_count = [], 0
    def failed(error):
        failures.append(error)
    decoder = PhraseDecoder(transcribe, on_phrase, failed, stop_event)
    stream = None
    preroll = deque(maxlen=4)  # 256 ms at 1024 samples/block
    target = None
    last_partial, last_update = "", 0.0
    partial_interval = max(0.12, float(settings.get("sherpa_partial_interval_ms", 260)) / 1000)
    started = time.monotonic()
    heard_speech = False
    source = audio_source if audio_source is not None else microphone_blocks(settings, stop_event)

    def finalize_segments():
        nonlocal stream, target, last_partial, phrase_count
        while not vad.empty():
            audio = np.asarray(vad.front.samples, dtype=np.float32).copy()
            vad.pop()
            preview_final = last_partial
            if stream is not None:
                stream.input_finished()
                while preview_recognizer.is_ready(stream):
                    preview_recognizer.decode_stream(stream)
                preview_final = str(preview_recognizer.get_result(stream) or "").strip()
            phrase_count += 1
            decoder.submit(PhraseJob(phrase_count, audio, preview_final, target or target_getter()))
            stream, target, last_partial = None, None, ""
            preroll.clear()
            on_partial("", 0.0)
            if not stop_event.is_set():
                on_status("status.speech_phrase_processing", "Recognizing the previous phrase; microphone is still listening...")

    try:
        on_status("status.speech_streaming", "Listening and recognizing locally...")
        for mono in source:
            mono = np.asarray(mono, dtype=np.float32).reshape(-1)
            rms = float(np.sqrt(np.mean(mono * mono))) if mono.size else 0.0
            vad.accept_waveform(mono)
            talking = vad.is_speech_detected()
            if talking and target is None:
                heard_speech = True
                target = target_getter()
                if preview_recognizer is not None:
                    stream = preview_recognizer.create_stream()
                    for chunk in preroll:
                        stream.accept_waveform(16000, chunk)
            if stream is not None:
                stream.accept_waveform(16000, mono)
                while preview_recognizer.is_ready(stream):
                    preview_recognizer.decode_stream(stream)
                partial = str(preview_recognizer.get_result(stream) or "").strip()
            else:
                partial = ""
            now = time.monotonic()
            if now - last_update >= partial_interval:
                last_partial, last_update = partial, now
                on_partial(partial, min(1.0, rms * 12))
            finalize_segments()
            preroll.append(mono.copy())
            max_session = float(settings.get("max_session_seconds", 3600) or 3600)
            if now - started >= max_session:
                on_status("status.speech_session_limit", "Session time limit reached; finishing the last phrase.")
                stop_event.set()
            if failures or (audio_source is not None and stop_event.is_set()):
                break
        vad.flush()
        finalize_segments()
    finally:
        if hasattr(source, "close"):
            source.close()
        decoder.finish()
    if failures:
        raise RuntimeError(failures[0])
    return {"phrases": phrase_count, "heard_speech": heard_speech}


def microphone_blocks(settings, stop_event):
    import numpy as np
    import sounddevice as sd
    import soxr
    device = microphone_device(sd, str(settings.get("microphone") or ""))
    info = sd.query_devices(device, "input")
    native_rate = int(info["default_samplerate"])
    channels = 1
    sd.check_input_settings(device=device, channels=channels, dtype="float32", samplerate=native_rate)
    resampler = None if native_rate == 16000 else soxr.ResampleStream(native_rate, 16000, 1, dtype="float32", quality="HQ")
    blocks, errors = queue.Queue(maxsize=160), []
    def callback(audio, frames, timing, status):
        if status.input_overflow:
            errors.append("Microphone audio overflow. Recording was stopped; try a lighter model.")
            stop_event.set()
        try:
            blocks.put_nowait(audio[:, 0].copy())
        except queue.Full:
            if not errors:
                errors.append("Audio processing backlog is full. Recording was stopped without silently dropping audio.")
            stop_event.set()
    pending = np.empty(0, dtype=np.float32)
    try:
        with sd.InputStream(device=device, samplerate=native_rate, channels=channels, dtype="float32",
                            blocksize=max(256, round(native_rate * 0.064)), callback=callback):
            while not stop_event.is_set():
                try:
                    audio = blocks.get(timeout=0.1)
                except queue.Empty:
                    continue
                converted = resampler.resample_chunk(audio) if resampler else audio
                pending = np.concatenate((pending, converted))
                while pending.size >= 1024:
                    yield pending[:1024]
                    pending = pending[1024:]
        # Close the stream before draining so the callback cannot keep appending
        # more audio while Stop is being finalized.
        while not blocks.empty():
            audio = blocks.get_nowait()
            converted = resampler.resample_chunk(audio) if resampler else audio
            pending = np.concatenate((pending, converted))
        if resampler:
            pending = np.concatenate((pending, resampler.resample_chunk(np.empty(0, dtype=np.float32), last=True)))
        while pending.size:
            yield pending[:1024]
            pending = pending[1024:]
    except Exception as exc:
        raise RuntimeError(f"Microphone capture failed: {exc}") from exc
    if errors:
        raise RuntimeError(errors[0])
