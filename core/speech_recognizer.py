"""Local recognition only; no GUI, microphone, keyboard or user config imports."""
from pathlib import Path
import tempfile
import threading
import wave
from core.speech_session import (STREAMING_MODEL, SENSE_VOICE_MODEL, bundled_path,
                                 custom_words, model_roots, bundle_roots)

_MODEL_CACHE, _SHERPA_RECOGNIZER_CACHE, _SENSE_VOICE_CACHE = {}, {}, {}
_MODEL_LOCK = threading.Lock()


def _resolve_sherpa_model_dir(model_path=""):
    return bundled_path(STREAMING_MODEL, model_path, ("tokens.txt",))


def _get_sherpa_recognizer(settings, tr, *, preview=False):
    import sherpa_onnx
    model_dir = _resolve_sherpa_model_dir(settings.get("sherpa_model_path", ""))
    if model_dir is None:
        raise RuntimeError(tr("status.speech_missing_sherpa_model", "Local streaming model was not found."))
    suffix = ".int8.onnx" if settings.get("sherpa_use_int8", True) else ".onnx"
    words = [] if preview else custom_words(settings)
    threads = max(1, min(8, int(settings.get("sherpa_num_threads", 2))))
    key = (str(model_dir), suffix, threads, preview, tuple(words))
    with _MODEL_LOCK:
        if key not in _SHERPA_RECOGNIZER_CACHE:
            for old in list(_SHERPA_RECOGNIZER_CACHE):
                if old[3] == preview:
                    del _SHERPA_RECOGNIZER_CACHE[old]
            hotword_path = ""
            try:
                if words:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".txt", delete=False) as file:
                        file.write("\n".join(words))
                        hotword_path = file.name
                _SHERPA_RECOGNIZER_CACHE[key] = sherpa_onnx.OnlineRecognizer.from_transducer(
                    tokens=str(model_dir / "tokens.txt"), encoder=str(model_dir / f"encoder-epoch-99-avg-1{suffix}"),
                    decoder=str(model_dir / f"decoder-epoch-99-avg-1{suffix}"), joiner=str(model_dir / f"joiner-epoch-99-avg-1{suffix}"),
                    num_threads=threads, sample_rate=16000, feature_dim=80,
                    decoding_method="greedy_search" if preview else "modified_beam_search", max_active_paths=4,
                    hotwords_file=hotword_path, enable_endpoint_detection=True, provider="cpu")
            finally:
                if hotword_path:
                    Path(hotword_path).unlink(missing_ok=True)
        return _SHERPA_RECOGNIZER_CACHE[key]


def _get_sense_voice(settings, tr):
    import sherpa_onnx
    model_dir = bundled_path(SENSE_VOICE_MODEL, settings.get("sense_voice_model_path", ""), ("model.int8.onnx", "tokens.txt"))
    if model_dir is None:
        raise RuntimeError(tr("status.speech_missing_sense_voice", "SenseVoice model is missing; install its model pack in Voice settings."))
    language = _resolve_language(settings) or ""
    if language not in {"", "zh", "en", "ja", "ko", "yue"}:
        raise RuntimeError(tr("status.speech_unsupported_language", "This model does not support the selected speech language."))
    threads = max(1, min(8, int(settings.get("sherpa_num_threads", 2))))
    key = (str(model_dir), language, threads)
    with _MODEL_LOCK:
        if key not in _SENSE_VOICE_CACHE:
            _SENSE_VOICE_CACHE.clear()
            _SENSE_VOICE_CACHE[key] = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=str(model_dir / "model.int8.onnx"), tokens=str(model_dir / "tokens.txt"), language=language,
                use_itn=True, num_threads=threads, provider="cpu")
        return _SENSE_VOICE_CACHE[key]


def _get_whisper(settings, tr):
    from faster_whisper import WhisperModel
    location = _resolve_model_location(str(settings.get("model_path") or ""), str(settings.get("model") or "small"))
    if not Path(location).is_dir():
        raise RuntimeError(tr("status.speech_whisper_not_installed", "Selected Whisper model is not installed. Choose a local model folder in Voice settings."))
    key = (location, settings.get("device", "cpu"), settings.get("compute_type", "int8"))
    with _MODEL_LOCK:
        if key not in _MODEL_CACHE:
            _MODEL_CACHE.clear()
            _MODEL_CACHE[key] = WhisperModel(location, device=key[1], compute_type=key[2], cpu_threads=2)
        return _MODEL_CACHE[key]


def _prepare_final_model(settings, tr):
    if settings["engine"] == "sense_voice":
        return _get_sense_voice(settings, tr)
    if settings["engine"] == "sherpa_onnx_streaming":
        return _get_sherpa_recognizer(settings, tr)
    if settings["engine"] == "faster_whisper":
        return _get_whisper(settings, tr)
    raise RuntimeError("Unknown speech engine: " + str(settings["engine"]))


def _transcribe_phrase(job, settings, tr):
    import numpy as np
    audio, engine = np.asarray(job.audio, dtype=np.float32), settings["engine"]
    if engine == "sense_voice":
        recognizer = _get_sense_voice(settings, tr)
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, audio)
        recognizer.decode_stream(stream)
        return stream.result.text
    if engine == "sherpa_onnx_streaming":
        recognizer = _get_sherpa_recognizer(settings, tr)
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, np.concatenate((audio, np.zeros(4800, dtype=np.float32))))
        stream.input_finished()
        while recognizer.is_ready(stream):
            recognizer.decode_stream(stream)
        return str(recognizer.get_result(stream) or "")
    model, words = _get_whisper(settings, tr), custom_words(settings)
    segments, _ = model.transcribe(audio, language=_resolve_language(settings), beam_size=max(1, min(10, int(settings.get("beam_size", 5)))),
        vad_filter=False, initial_prompt=("术语：" + "、".join(words)) if words else None,
        hotwords=" ".join(words) or None, condition_on_previous_text=False)
    return "".join(segment.text for segment in segments)


def _transcribe_wav(path, settings, tr):
    from core.speech_session import PhraseJob
    return _transcribe_phrase(PhraseJob(1, _read_wav_mono_float32(path, tr), "", None), {**settings, "engine": "faster_whisper"}, tr)


def _read_wav_mono_float32(path, tr):
    """Keep the proven PyAV bypass: read WAV ourselves and pass float32 audio."""
    import numpy as np
    with wave.open(str(path), "rb") as file:
        channels, width, rate = file.getnchannels(), file.getsampwidth(), file.getframerate()
        raw = file.readframes(file.getnframes())
    if width != 2 or rate != 16000 or not raw:
        raise RuntimeError(tr("status.speech_audio_read_failed", "Unsupported or empty recorded audio.", error="16-bit / 16kHz WAV required"))
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return audio.reshape(-1, channels).mean(axis=1) if channels > 1 else audio


def _resolve_model_location(model_path, model_name):
    if model_path.strip():
        return model_path.strip()
    for root in model_roots():
        for name in (model_name, f"faster-whisper-{model_name}"):
            path = root / name
            if (path / "config.json").is_file() and (path / "model.bin").is_file():
                return str(path)
    return model_name


def _candidate_bundle_roots():
    return bundle_roots()


def _resolve_language(settings):
    language = str(settings.get("language") or "zh")
    if language == "auto":
        return None
    if language == "follow_ui":
        language = str(settings.get("ui_language") or "auto")
    if language.startswith("zh"):
        return "zh"
    if language.startswith("en"):
        return "en"
    return None if language in {"", "auto"} else language
