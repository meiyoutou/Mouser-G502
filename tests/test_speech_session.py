"""Deterministic voice tests: no real microphone, paste or user config access."""
import copy
from collections import deque
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
import wave

import numpy as np
from PySide6.QtCore import QMimeData
from core.speech_anchor import InputAnchor, map_physical_rect, place_preview, _selection_caret
from core.speech_session import (SPEECH_DEFAULTS, PhraseDecoder, PhraseJob, correct_text,
                                 custom_words, resolve_engine, run_session)
from ui.speech_to_text import SpeechToTextController, normalize_settings, _read_wav_mono_float32

class FakeVad:
    def __init__(self):
        self.pending, self.ready = [], deque()
        self.active = False
    def accept_waveform(self, audio):
        self.active = bool(audio[0])
        if self.active:
            self.pending.append(audio)
        elif self.pending:
            self._finish()
    def _finish(self):
        self.ready.append(np.concatenate(self.pending))
        self.pending.clear()
    def is_speech_detected(self):
        return self.active
    def empty(self):
        return not self.ready
    @property
    def front(self):
        return type("Segment", (), {"samples": self.ready[0]})()
    def pop(self):
        self.ready.popleft()
    def flush(self):
        if self.pending:
            self._finish()


class SessionTests(unittest.TestCase):
    def _run(self, values, decode=lambda job: str(job.sequence)):
        stop, output, partials = threading.Event(), [], []
        result = run_session(dict(SPEECH_DEFAULTS), stop, preview_recognizer=None,
            transcribe=decode, on_partial=lambda text, level: partials.append(text),
            on_phrase=lambda job, text: output.append((job.sequence, text)), on_status=lambda *a: None,
            target_getter=lambda: "same-field", vad=FakeVad(),
            audio_source=(np.full(1024, value, dtype=np.float32) for value in values))
        return result, output, stop

    def test_pause_commits_multiple_phrases_without_stopping(self):
        result, output, stop = self._run([1, 0, 2, 0])
        self.assertEqual(result["phrases"], 2)
        self.assertEqual(output, [(1, "1"), (2, "2")])
        self.assertFalse(stop.is_set())

    def test_stop_flushes_tail_once(self):
        result, output, stop = self._run([1, 0, 2])
        self.assertEqual(result["phrases"], 2)
        self.assertEqual([key for key, text in output], [1, 2])

    def test_silence_produces_no_hallucinated_phrase(self):
        result, output, stop = self._run([0, 0, 0])
        self.assertEqual(result["phrases"], 0)
        self.assertFalse(output)

    def test_capture_advances_while_phrase_inference_waits(self):
        entered, release = threading.Event(), threading.Event()
        stop, output = threading.Event(), []
        def decode(job):
            if job.sequence == 1:
                entered.set()
                self.assertTrue(release.wait(2))
            return str(job.sequence)
        def audio():
            for value in (1, 0):
                yield np.full(1024, value, dtype=np.float32)
            self.assertTrue(entered.wait(2))
            yield np.full(1024, 2, dtype=np.float32)
            release.set()
            yield np.zeros(1024, dtype=np.float32)
        run_session(SPEECH_DEFAULTS, stop, preview_recognizer=None, transcribe=decode,
            on_partial=lambda *a: None, on_phrase=lambda job, text: output.append(text),
            on_status=lambda *a: None, target_getter=lambda: "same-field", vad=FakeVad(), audio_source=audio())
        self.assertEqual(output, ["1", "2"])

    def test_inference_error_stops_session_and_returns_error(self):
        def failed(job):
            raise RuntimeError("test model failure")
        with self.assertRaisesRegex(RuntimeError, "test model failure"):
            self._run([1, 0], failed)

    def test_bounded_backlog_never_silently_discards(self):
        entered, release, stop = threading.Event(), threading.Event(), threading.Event()
        def slow(job):
            entered.set()
            release.wait(2)
            return "ok"
        decoder = PhraseDecoder(slow, lambda *a: None, lambda *a: None, stop, max_pending=1)
        decoder.submit(PhraseJob(1, None, "", None))
        self.assertTrue(entered.wait(2))
        decoder.submit(PhraseJob(2, None, "", None))
        try:
            with self.assertRaisesRegex(RuntimeError, "backlog"):
                decoder.submit(PhraseJob(3, None, "", None))
            self.assertTrue(stop.is_set())
        finally:
            release.set()
            decoder.finish()

    def test_explicit_model_and_threshold_are_preserved(self):
        with patch.dict("os.environ", {}, clear=True):
            settings = normalize_settings({"engine": "faster_whisper", "model": "medium", "silence_threshold": 0.012})
        self.assertEqual(settings["model"], "medium")
        self.assertEqual(settings["silence_threshold"], 0.012)
        self.assertEqual(settings["engine"], "faster_whisper")

    def test_auto_routing_falls_back_only_when_model_absent(self):
        with patch("core.speech_session.bundled_path", side_effect=[Path("sense"), None]):
            self.assertEqual(resolve_engine({"engine": "auto"}), "sense_voice")
        with patch("core.speech_session.bundled_path", side_effect=[None, Path("stream")]):
            self.assertEqual(resolve_engine({"engine": "auto"}), "sherpa_onnx_streaming")
        with patch("core.speech_session.bundled_path", return_value=None):
            self.assertEqual(resolve_engine({"engine": "auto"}), "none")
        with patch("core.speech_session.bundled_path", side_effect=[None, None, Path("whisper")]):
            self.assertEqual(resolve_engine({"engine": "auto"}), "faster_whisper")

    def test_corrections_are_opt_in_literal_and_not_chained(self):
        settings = {"corrections": "背景=北京\n北京=上海"}
        self.assertEqual(correct_text("去背景", settings), "去背景")
        settings["corrections_enabled"] = True
        self.assertEqual(correct_text("去背景", settings), "去北京")

    def test_terms_deduplicate_and_strip_sensevoice_tags(self):
        self.assertEqual(custom_words({"custom_words": "罗技，Mouser\n罗技"}), ["罗技", "Mouser"])
        self.assertEqual(correct_text("<|zh|><|NEUTRAL|>你好。", {}), "你好。")

    def test_negative_origin_mixed_dpi_mapping(self):
        rect = map_physical_rect((-1800, 150, -1790, 180), (-1920, 0, 0, 1080), (-1280, 0, 0, 720))
        self.assertEqual(rect, (-1200, 100, -1193.3333333333333, 120))
        pos = place_preview((-1200, 100, -1193, 120), (380, 90), (-1280, 0, 0, 720))
        self.assertEqual(pos, (-1200, 130))

    def test_preview_flips_above_caret_at_bottom_edge(self):
        self.assertEqual(place_preview((1850, 1030, 1851, 1050), (380, 90), (0, 0, 1920, 1080)), (1532, 930))

    def test_wav_pyav_bypass_produces_float32_mono(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            with wave.open(str(path), "wb") as file:
                file.setnchannels(1); file.setsampwidth(2); file.setframerate(16000)
                file.writeframes(np.zeros(16000, dtype=np.int16).tobytes())
            audio = _read_wav_mono_float32(path, lambda key, default, **values: default.format(**values))
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.shape, (16000,))

    def test_textpattern1_collapsed_range_caret_geometry(self):
        auto = SimpleNamespace(TextPatternRangeEndpoint=SimpleNamespace(Start=0, End=1),
                               TextUnit=SimpleNamespace(Character=0))
        box = SimpleNamespace(left=50, top=100, right=50, bottom=120)
        selection = Mock()
        selection.CompareEndpoints.return_value = 0
        selection.GetBoundingRectangles.return_value = [box]
        pattern = Mock()
        pattern.GetSelection.return_value = [selection]
        self.assertEqual(_selection_caret(pattern, auto), (50, 100, 51, 120))
        selection.Clone.assert_not_called()

    def test_caret_fallback_only_moves_cloned_range_never_selection(self):
        auto = SimpleNamespace(TextPatternRangeEndpoint=SimpleNamespace(Start=0, End=1),
                               TextUnit=SimpleNamespace(Character=0))
        selection = Mock()
        selection.CompareEndpoints.return_value = 0
        selection.GetBoundingRectangles.return_value = []
        nearby = selection.Clone.return_value
        nearby.MoveEndpointByUnit.return_value = 1
        nearby.GetBoundingRectangles.return_value = [SimpleNamespace(left=50, top=100, right=60, bottom=120)]
        pattern = Mock()
        pattern.GetSelection.return_value = [selection]
        self.assertEqual(_selection_caret(pattern, auto), (50, 100, 51, 120))
        nearby.MoveEndpointByUnit.assert_called_once_with(1, 0, 1, waitTime=0)
        selection.MoveEndpointByUnit.assert_not_called()
        selection.GetText.assert_not_called()
        selection.Select.assert_not_called()

    def test_noncollapsed_selection_is_not_mistaken_for_caret(self):
        auto = SimpleNamespace(TextPatternRangeEndpoint=SimpleNamespace(Start=0, End=1))
        selection, pattern = Mock(), Mock()
        selection.CompareEndpoints.return_value = -3
        pattern.GetSelection.return_value = [selection]
        self.assertIsNone(_selection_caret(pattern, auto))
        selection.GetBoundingRectangles.assert_not_called()


class FakeClipboard:
    def __init__(self):
        self.mime = QMimeData()
        self.mime.setText("original clipboard")
        self.writes = []
    def mimeData(self):
        return self.mime
    def text(self):
        return self.mime.text()
    def setText(self, text):
        self.mime = QMimeData(); self.mime.setText(text); self.writes.append(text)
    def setMimeData(self, mime):
        self.mime = mime


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.controller = SpeechToTextController(settings_getter=lambda: {"status_overlay": False})
        self.controller._session = 1
        self.controller._busy = True
        self.controller._session_settings = {**SPEECH_DEFAULTS, "status_overlay": False}
        self.anchor = InputAnchor(100, 200, editable=True)
        self.target = (1, self.anchor.identity, True)
        self.controller._target_snapshot = lambda: self.target
        self.controller._anchor_tracker.snapshot = lambda: self.anchor
        self.clipboard, self.callbacks = FakeClipboard(), []
        self.patches = [patch("ui.speech_to_text.QGuiApplication.clipboard", return_value=self.clipboard),
                        patch("ui.speech_to_text.read_native_anchor", side_effect=lambda: self.anchor),
                        patch("ui.speech_to_text.modifiers_held", return_value=False),
                        patch("ui.speech_to_text.QTimer.singleShot", side_effect=lambda ms, cb: self.callbacks.append(cb)),
                        patch("core.key_simulator.send_paste_checked")]
        self.mocks = [item.start() for item in self.patches]
    def tearDown(self):
        self.controller.shutdown()
        for item in reversed(self.patches):
            item.stop()
    def phrase(self, number, text="你好"):
        self.controller._handle_phrase({"session": 1, "sequence": number, "text": text, "target": self.target})
    def drain(self):
        while self.callbacks:
            self.callbacks.pop(0)()

    def test_ordered_paste_and_clipboard_restoration(self):
        self.phrase(1, "第一句"); self.phrase(2, "第二句")
        self.drain()
        self.assertEqual(self.clipboard.writes, ["第一句", "第二句"])
        self.assertEqual(self.clipboard.text(), "original clipboard")
        self.assertEqual(self.mocks[-1].call_count, 2)
        self.assertEqual([call.args for call in self.mocks[-1].call_args_list], [(), ()])

    def test_duplicate_final_or_stop_never_replays_phrase(self):
        self.phrase(1); self.phrase(1)
        self.drain()
        self.assertEqual(self.mocks[-1].call_count, 1)
        self.controller._handle_worker_finished({"session": 1, "ok": True, "phrases": 1})
        self.assertFalse(self.controller._busy)

    def test_focus_change_blocks_paste_and_retains_text(self):
        self.phrase(1)
        self.target = (2, (300, 400, ()), True)
        self.drain()
        self.mocks[-1].assert_not_called()
        self.assertFalse(self.clipboard.writes)
        self.assertEqual(self.controller._pending_texts, ["你好"])
        self.assertTrue(self.controller._paused)

    def test_leave_and_return_does_not_authorize_old_phrase(self):
        self.phrase(1)
        self.target = (3, self.anchor.identity, True)
        self.drain()
        self.mocks[-1].assert_not_called()

    def test_unknown_or_password_input_is_not_a_paste_target(self):
        self.target = (1, self.anchor.identity, False)
        self.phrase(1)
        self.drain()
        self.mocks[-1].assert_not_called()

    def test_user_clipboard_change_is_not_overwritten(self):
        self.phrase(1)
        self.callbacks.pop(0)()
        self.clipboard.setText("new user clipboard")
        self.drain()
        self.assertEqual(self.clipboard.text(), "new user clipboard")

    def test_model_failure_returns_to_idle_for_next_recording(self):
        self.controller._handle_worker_finished({"session": 1, "ok": False, "error": "test error"})
        self.assertFalse(self.controller._busy)
        self.assertEqual(self.controller._state, "idle")

    def test_auto_input_disabled_keeps_text_without_clipboard_mutation(self):
        self.controller._session_settings["auto_paste"] = False
        self.phrase(1)
        self.assertEqual(self.controller._pending_texts, ["你好"])
        self.assertFalse(self.clipboard.writes)

    def test_paste_permission_failure_retains_text_and_restores_clipboard(self):
        self.mocks[-1].side_effect = RuntimeError("Windows blocked paste")
        self.phrase(1)
        self.drain()
        self.assertEqual(self.controller._pending_texts, ["你好"])
        self.assertEqual(self.clipboard.text(), "original clipboard")

    def test_clipboard_too_large_to_preserve_is_not_overwritten(self):
        with patch("ui.speech_to_text._copy_mime_data", return_value=None):
            self.phrase(1)
            self.drain()
        self.assertFalse(self.clipboard.writes)
        self.mocks[-1].assert_not_called()
        self.assertEqual(self.controller._pending_texts, ["你好"])

    def test_focus_change_before_any_phrase_pauses_new_target_too(self):
        del self.controller._target_snapshot
        self.controller._session_window_focus = self.anchor.identity[:2]
        self.controller._focus_identity = self.anchor.identity
        self.anchor = InputAnchor(300, 400, editable=True)
        self.controller._target_snapshot()
        self.assertTrue(self.controller._paused)
        self.phrase(1)
        self.drain()
        self.mocks[-1].assert_not_called()
        self.assertEqual(self.controller._pending_texts, ["你好"])

    def test_initial_accessibility_refinement_does_not_pause(self):
        del self.controller._target_snapshot
        self.controller._session_window_focus = self.anchor.identity[:2]
        self.controller._focus_identity = self.anchor.identity
        self.anchor = InputAnchor(100, 200, runtime_id=(1, 2), editable=True)
        self.controller._target_snapshot()
        self.assertFalse(self.controller._paused)
        self.assertEqual(self.controller._session_runtime, (1, 2))

    def test_finishing_waits_for_inflight_clipboard_restoration(self):
        self.phrase(1)
        self.callbacks.pop(0)()
        self.controller._handle_worker_finished({"session": 1, "ok": True, "phrases": 1})
        self.controller._pause_delivery()
        self.assertTrue(self.controller._busy)
        self.drain()
        self.assertFalse(self.controller._busy)
        self.assertEqual(self.clipboard.text(), "original clipboard")


if __name__ == "__main__":
    unittest.main()
