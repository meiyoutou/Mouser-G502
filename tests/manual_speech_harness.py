"""Interactive source validation with public model samples, no real microphone.

Run with an isolated APPDATA, click the test button, and inspect this test's
own input only. Never bundled in the application or in the portable package.
"""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication

from core.key_simulator import SPEECH_TO_TEXT_ACTION
from core.speech_session import SPEECH_DEFAULTS, STREAMING_MODEL
from ui.locale_manager import translate_string
from ui.speech_to_text import SpeechToTextController, _read_wav_mono_float32

QML = b'''
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
ApplicationWindow {
    visible: true
    width: 900; height: 680
    title: "Mouser Voice Validation - public audio only"
    signal startTest()
    ColumnLayout {
        anchors.fill: parent; anchors.margins: 24; spacing: 16
        Label { text: "Public audio test: two phrases, no microphone"; font.pixelSize: 22 }
        Label { text: "Keep focus in the input below. Preview should remain near the caret." }
        TextArea {
            id: input; objectName: "validationInput"
            Layout.fillWidth: true; Layout.fillHeight: true
            selectByMouse: true; wrapMode: TextEdit.Wrap
            placeholderText: "Finalized phrases will appear here"
        }
        Button { text: "Start public sample test"; onClicked: { input.forceActiveFocus(); startTest() } }
        Label { text: validation.status; Layout.fillWidth: true; wrapMode: Text.Wrap }
        TextArea {
            Layout.fillWidth: true; Layout.preferredHeight: 120
            readOnly: true; text: validation.pending; wrapMode: TextEdit.Wrap
        }
    }
}
'''


def main():
    import tempfile
    import wave
    from core.speech_client import SpeechClient
    from PySide6.QtCore import Property
    class Validation(QObject):
        changed = Signal()
        def __init__(self):
            super().__init__()
            self._status, self._pending = "Ready", ""
        @Property(str, notify=changed)
        def status(self):
            return self._status
        @Property(str, notify=changed)
        def pending(self):
            return self._pending
        def status_set(self, text):
            self._status = text
            self.changed.emit()
        def pending_set(self, text):
            self._pending = text
            self.changed.emit()
    root = Path(__file__).resolve().parents[1]
    tr = lambda key, default, **values: translate_string("zh_CN", key, default).format(**values)
    audio_root = root / "speech_models" / STREAMING_MODEL / "test_wavs"
    silence = np.zeros(32000, dtype=np.float32)
    audio = np.concatenate((silence, _read_wav_mono_float32(audio_root / "0.wav", tr), silence,
                            _read_wav_mono_float32(audio_root / "1.wav", tr), silence))
    temporary = tempfile.TemporaryDirectory(prefix="mouser-public-audio-")
    public_wav = Path(temporary.name) / "two-public-phrases.wav"
    with wave.open(str(public_wav), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(16000)
        file.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    class PublicAudioClient(SpeechClient):
        def run(self, *args, **kwargs):
            kwargs["test_wav"] = public_wav
            return super().run(*args, **kwargs)
    def source(settings, stop):
        for pos in range(0, len(audio), 1024):
            if stop.is_set():
                break
            time.sleep(0.025)
            yield audio[pos:pos + 1024]
    app = QApplication([])
    validation = Validation()
    controller = SpeechToTextController(settings_getter=lambda: {**SPEECH_DEFAULTS, "engine": "sense_voice"},
                                        status_callback=validation.status_set, translator=tr)
    # Never rely on patching the main process's microphone generator: capture
    # now lives in a child. Explicit public-file mode guarantees no real mic.
    controller._speech_client = PublicAudioClient()
    controller.pendingTextChanged.connect(validation.pending_set)
    app.aboutToQuit.connect(controller.shutdown)
    qml = QQmlApplicationEngine()
    qml.rootContext().setContextProperty("validation", validation)
    qml.loadData(QML)
    window = qml.rootObjects()[0]
    input_control = window.findChild(QObject, "validationInput")
    window.startTest.connect(lambda: controller.request_action(SPEECH_TO_TEXT_ACTION))
    report_path = Path(sys.argv[1])
    def report():
        anchor = controller._anchor_tracker.snapshot()
        # Only record the test application's own text, not other apps' content.
        report_path.write_text(json.dumps({"busy": controller._busy, "paused": controller._paused,
            "delivered": controller._delivered, "pending": validation.pending,
            "own_input_text": input_control.property("text"), "editable": anchor.editable,
            "has_caret": bool(anchor.caret), "has_runtime_id": bool(anchor.runtime_id),
            "status": validation.status}, ensure_ascii=False, indent=2), encoding="utf-8")
    timer = QTimer()
    timer.timeout.connect(report)
    timer.start(500)
    try:
        return app.exec()
    finally:
        temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
