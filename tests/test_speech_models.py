"""Opt-in integration tests using bundled public audio, never the microphone."""
import os
from pathlib import Path
import threading
import time
import unittest

import numpy as np

from core.speech_session import SPEECH_DEFAULTS, STREAMING_MODEL, run_session
from ui.speech_to_text import (_get_sherpa_recognizer, _prepare_final_model,
                               _read_wav_mono_float32, _transcribe_phrase)

ROOT = Path(__file__).resolve().parents[1]
TR = lambda key, default, **values: default.format(**values)


@unittest.skipUnless(os.environ.get("MOUSER_TEST_LOCAL_ASR") == "1", "opt-in local model integration")
class BundledModelTests(unittest.TestCase):
    def settings(self):
        return {**SPEECH_DEFAULTS, "engine": "sense_voice", "silence_stop_seconds": 1.2}

    def audio(self, name):
        return _read_wav_mono_float32(ROOT / "speech_models" / STREAMING_MODEL / "test_wavs" / name, TR)

    def run_audio(self, audio):
        settings, stop, phrases, partials, times = self.settings(), threading.Event(), [], [], []
        _prepare_final_model(settings, TR)
        preview = _get_sherpa_recognizer(settings, TR, preview=True)
        def transcribe(job):
            started = time.monotonic()
            text = _transcribe_phrase(job, settings, TR)
            times.append(round(time.monotonic() - started, 3))
            return text
        result = run_session(settings, stop, preview_recognizer=preview,
            transcribe=transcribe, on_partial=lambda text, level: partials.append(text),
            on_phrase=lambda job, text: phrases.append((job.sequence, text)),
            on_status=lambda *a: None, target_getter=lambda: "isolated-public-audio-test",
            audio_source=(audio[pos:pos + 1024] for pos in range(0, len(audio), 1024)))
        self.assertFalse(stop.is_set())
        return result, phrases, partials, times

    def test_silero_preview_and_sensevoice_two_ordered_phrases(self):
        silence = np.zeros(32000, dtype=np.float32)
        audio = np.concatenate((silence, self.audio("0.wav"), silence, self.audio("1.wav"), silence))
        result, phrases, partials, times = self.run_audio(audio)
        self.assertEqual(result["phrases"], 2, phrases)
        self.assertEqual([number for number, text in phrases], [1, 2])
        self.assertIn("研究", phrases[0][1])
        self.assertIn("金融", phrases[1][1])
        self.assertTrue(any(partials))
        print("LOCAL_TWO_PHRASES=PASS; final_inference_seconds=" + str(times))

    def test_real_vad_silence_has_no_phrase(self):
        result, phrases, partials, times = self.run_audio(np.zeros(48000, dtype=np.float32))
        self.assertEqual(result["phrases"], 0)
        self.assertFalse(phrases)

    def test_real_vad_stop_tail_is_finalized_once(self):
        audio = np.concatenate((np.zeros(16000, dtype=np.float32), self.audio("0.wav")))
        result, phrases, partials, times = self.run_audio(audio)
        self.assertEqual(result["phrases"], 1)
        self.assertIn("研究", phrases[0][1])

    def test_zipformer_custom_vocabulary_loads_and_transcribes(self):
        from core.speech_session import PhraseJob
        settings = {**SPEECH_DEFAULTS, "engine": "sherpa_onnx_streaming", "custom_words": "罗技\n全球金融\nMouser"}
        text = _transcribe_phrase(PhraseJob(1, self.audio("1.wav"), "", None), settings, TR)
        self.assertIn("金融", text)


if __name__ == "__main__":
    unittest.main()
