"""Isolated full-QML voice settings, localization and diagnostics smoke test."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class SpeechUITests(unittest.TestCase):
    def test_voice_page_and_collapsed_diagnostics_render(self):
        with tempfile.TemporaryDirectory(prefix="mouser-voice-ui-") as folder:
            env = {**os.environ, "APPDATA": folder, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
            if sys.platform.startswith("win"):
                env["QT_QPA_FONTDIR"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts")
            for edition in ("lite", "voice"):
                result = subprocess.run([sys.executable, "-B", "-m", "tests.test_speech_ui", "--smoke"],
                    cwd=Path(__file__).resolve().parents[1], env={**env, "MOUSER_TEST_EDITION": edition}, capture_output=True,
                    encoding="utf-8", timeout=60)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("SPEECH_UI_SMOKE=PASS", result.stdout)


def _smoke():
    import copy
    from unittest.mock import patch
    from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl, qInstallMessageHandler
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from core.config import DEFAULT_CONFIG
    from main_qml import AppIconProvider, SystemIconProvider, UiState
    from tests.test_backend import _FakeEngine
    from ui.backend import Backend
    from ui.locale_manager import LocaleManager
    from ui.speech_locale import SPEECH_TRANSLATIONS

    # Both editions render cleanly when no optional model exists.
    empty_root = Path(os.environ["APPDATA"]) / "no-models"
    patch("core.speech_models.model_roots", return_value=[empty_root]).start()
    voice = os.environ.get("MOUSER_TEST_EDITION", "voice") == "voice"
    patch("core.speech_models.runtime_enabled", return_value=voice).start()
    patch("ui.speech_to_text.runtime_enabled", return_value=voice).start()

    app, warnings = QApplication([]), []
    qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["settings"]["language"] = "zh_CN"
    before = copy.deepcopy(cfg["profiles"])
    root_dir = Path(os.environ.get("MOUSER_TEST_QML_ROOT", Path(__file__).resolve().parents[1]))
    fake_engine = _FakeEngine()
    fake_engine.haptic_supported = False
    with patch("ui.backend.load_config", return_value=cfg), patch("ui.backend.save_config"), patch("ui.backend.supports_login_startup", return_value=False):
        backend = Backend(engine=fake_engine, root_dir=str(root_dir))
    locale, state, qml = LocaleManager("zh_CN"), UiState(app), QQmlApplicationEngine()
    qml.addImageProvider("appicons", AppIconProvider(str(root_dir)))
    qml.addImageProvider("systemicons", SystemIconProvider())
    for key, value in {"backend": backend, "uiState": state, "lm": locale, "launchHidden": True,
                       "appVersion": "3.7.32", "appBuildMode": "test", "appCommit": "test", "appLaunchPath": "test"}.items():
        qml.rootContext().setContextProperty(key, value)
    qml.load(QUrl.fromLocalFile(str(root_dir / "ui/qml/Main.qml")))
    assert qml.rootObjects(), warnings
    window = qml.rootObjects()[0]
    window.setProperty("visible", True)
    def settle():
        loop = QEventLoop()
        QTimer.singleShot(120, loop.quit)
        loop.exec()
    settle()
    def visual_find(item, name):
        if item.objectName() == name:
            return item
        for child in item.childItems():
            found = visual_find(child, name)
            if found:
                return found
    nav = visual_find(window.contentItem(), "navPage4")
    assert nav is not None, ("Voice navigation missing", warnings)
    assert nav.property("visible"), "Voice navigation is hidden"
    assert nav.property("height") >= 40
    diagnostics = window.findChild(QObject, "diagnosticsExpandButton")
    assert diagnostics and diagnostics.property("text") == "展开"
    mouse_page = diagnostics
    while mouse_page and mouse_page.property("diagnosticsExpanded") is None:
        mouse_page = mouse_page.parent()
    assert mouse_page is not None and not mouse_page.property("diagnosticsExpanded")
    mouse_page.setProperty("diagnosticsExpanded", True)
    settle()
    assert diagnostics.property("text") == "收起"
    mouse_page.setProperty("diagnosticsExpanded", False)
    window.setProperty("currentPage", 4)
    settle()
    page = window.findChild(QObject, "speechSettingsPage")
    combo = window.findChild(QObject, "speechEngineCombo")
    assert page and combo, warnings
    assert not backend.speechRuntime["ready"]
    assert backend.speechRuntime["enabled"] == voice
    assert backend.speechRuntime["engine"] == "none"
    assert all(not item["installed"] for item in backend.speechModels)
    assert "优先" in page.property("s")["speech.recommend_sensevoice"]
    assert window.findChild(QObject, "speechTestInput") is not None
    for language in ("zh_CN", "en", "zh_TW"):
        locale.setLanguage(language)
        with patch("ui.backend.save_config"):
            backend.setLanguage(language)
        settle()
        assert page.property("s")["speech.title"] == SPEECH_TRANSLATIONS[language]["speech.title"]
        for width in (920, 1500):
            window.setProperty("width", width)
            settle()
            assert combo.property("width") > 100
    with patch("ui.backend.save_config") as saved:
        backend.setSpeechSetting("engine", "faster_whisper")
        backend.setSpeechSetting("model", "medium")
        backend.setSpeechVocabulary("罗技\nMouser", "罗技鸡=罗技")
        assert saved.call_count == 3
        assert backend.speechSettings["model"] == "medium"
        assert backend.speechSettings["corrections"] == "罗技鸡=罗技"
        assert backend._cfg["profiles"] == before
    for language in ("zh_CN", "en", "zh_TW"):
        assert set(SPEECH_TRANSLATIONS[language]) == set(SPEECH_TRANSLATIONS["en"])
    bad = [message for message in warnings if any(marker in message for marker in
           ("ReferenceError", "TypeError", "Unable to assign", "Binding loop", "Cannot assign to"))]
    assert not bad, bad
    screenshot_dir = os.environ.get("MOUSER_QML_SCREENSHOT_DIR")
    if screenshot_dir:
        locale.setLanguage("zh_CN")
        backend._cfg["settings"]["language"] = "zh_CN"
        backend._cfg["settings"]["speech_to_text"]["engine"] = "auto"
        backend.speechSettingsChanged.emit()
        window.setProperty("width", 1100)
        settle()
        assert window.grabWindow().save(str(Path(screenshot_dir) / "speech-settings.png"))
    print("SPEECH_UI_SMOKE=PASS")
    window.close()
    qml.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        _smoke()
    else:
        unittest.main()
