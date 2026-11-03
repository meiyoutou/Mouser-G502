"""Process lifecycle and Windows UTF-8/pipe regression tests, no real mic."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from core.speech_client import SpeechClient
from core.speech_service import pipe_lines

ROOT = Path(__file__).resolve().parents[1]


class SpeechProcessTests(unittest.TestCase):
    def test_native_dependency_initialization_does_not_block_on_control_pipe(self):
        with tempfile.TemporaryDirectory(prefix="mouser-process-test-") as folder:
            env = {**os.environ, "APPDATA": folder, "MOUSER_SPEECH_MODEL_DIR": folder}
            previous = dict(os.environ)
            try:
                os.environ.update(env)
                client = SpeechClient()
                started = time.monotonic()
                try:
                    event = client.query("check", timeout=10)
                    self.assertTrue(event["ok"])
                    self.assertFalse(event["microphone_opened"])
                    self.assertFalse(event["input_sent"])
                    self.assertLess(time.monotonic() - started, 10)
                    process = client.process
                finally:
                    client.close()
                self.assertEqual(process.wait(timeout=10), 0)
            finally:
                os.environ.clear()
                os.environ.update(previous)

    def test_idle_worker_exits_even_while_control_pipe_is_open(self):
        command = [sys.executable, "-u", "-c", "from core.speech_service import serve; raise SystemExit(serve(idle_seconds=.2))"]
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.addCleanup(process.stdin.close)
        self.addCleanup(process.stdout.close)
        self.addCleanup(process.stderr.close)
        hello = process.stdout.readline().decode("utf-8")
        self.assertEqual(json.loads(hello), {"type": "hello", "protocol": 1})
        self.assertEqual(process.wait(timeout=5), 0)

    def test_frozen_worker_has_utf8_even_when_windows_encoding_is_gbk(self):
        executable = ROOT / "dist-speech-v1/MouserSpeech/MouserSpeech.exe"
        wav = ROOT / "speech_models/sherpa-onnx-streaming-zipformer-zh-14M-2023-02-23/test_wavs/0.wav"
        if os.environ.get("MOUSER_TEST_LOCAL_ASR") != "1" or not executable.is_file() or not wav.is_file():
            self.skipTest("opt-in frozen runtime/public audio regression")
        from core.speech_session import SPEECH_DEFAULTS
        client = SpeechClient(command=[str(executable)])
        try:
            event = client.query("transcribe", settings={**SPEECH_DEFAULTS, "engine": "sense_voice"}, wav=wav, timeout=20)
            self.assertIn("研究", event["text"])
        finally:
            client.close()


if __name__ == "__main__":
    unittest.main()
