"""Render the integrated device header in an isolated offscreen Qt process."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class MouseDeviceHeaderTests(unittest.TestCase):
    def test_full_qml_header_language_and_narrow_layout(self):
        try:
            import PySide6  # noqa: F401
        except ImportError:
            self.skipTest("PySide6 not installed")
        with tempfile.TemporaryDirectory(prefix="mouser-header-test-") as folder:
            env = os.environ.copy()
            env.update(APPDATA=folder, QT_QPA_PLATFORM="offscreen", PYTHONIOENCODING="utf-8")
            if sys.platform.startswith("win"):
                env["QT_QPA_FONTDIR"] = str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts")
            result = subprocess.run(
                [sys.executable, "-B", "-m", "tests.test_mouse_device_header", "--qml-smoke"],
                cwd=Path(__file__).resolve().parents[1], env=env,
                capture_output=True, text=True, encoding="utf-8", timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("QML_HEADER_SMOKE=PASS", result.stdout)


def _qml_smoke():
    import copy
    from unittest.mock import patch
    from PySide6.QtCore import Property, QEventLoop, QObject, QMetaObject, QPointF, QTimer, QUrl, qInstallMessageHandler
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from core.config import DEFAULT_CONFIG
    from core.logi_devices import build_connected_device_info
    from main_qml import AppIconProvider, SystemIconProvider, UiState
    from tests.test_backend import _FakeEngine
    from ui.backend import Backend
    from ui.locale_manager import LocaleManager

    class WindowsHeaderBackend(Backend):
        # This synthetic UI test exercises the Windows-only selector even
        # when the rendering host is Linux. Do not change sys.platform or
        # load real Windows hardware backends in the test process.
        @Property(bool, constant=True)
        def deviceDiscoverySupported(self):
            return True

    app = QApplication([])
    warnings = []
    qInstallMessageHandler(lambda kind, context, message: warnings.append(message))
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg["settings"]["language"] = "zh_CN"
    root_dir = Path(__file__).resolve().parents[1]
    mouse = build_connected_device_info(product_name="MX Master 2S", transport="USB Receiver")
    engine = _FakeEngine(device_connected=True, connected_device=mouse)
    engine.haptic_supported = False
    with patch("ui.backend.load_config", return_value=cfg), patch("ui.backend.save_config"), patch("ui.backend.supports_login_startup", return_value=False):
        backend = WindowsHeaderBackend(engine=engine, root_dir=str(root_dir))
    backend._device_inventory_snapshot = {"status": "ready", "selected": "mouse1", "devices": [
        {"identity": "mouse1", "mouse": True, "name": "MX Master 2S", "slot": 1,
         "transport": "USB Receiver", "online": True, "status": "online", "model_confirmed": True},
    ]}
    locale = LocaleManager("zh_CN")
    state = UiState(app)
    qml = QQmlApplicationEngine()
    qml.addImageProvider("appicons", AppIconProvider(str(root_dir)))
    qml.addImageProvider("systemicons", SystemIconProvider())
    for key, value in {"backend": backend, "uiState": state, "lm": locale,
                       "launchHidden": True, "appVersion": "3.7.31", "appBuildMode": "test",
                       "appCommit": "test", "appLaunchPath": "test"}.items():
        qml.rootContext().setContextProperty(key, value)
    qml.load(QUrl.fromLocalFile(str(root_dir / "ui/qml/Main.qml")))
    assert qml.rootObjects(), warnings
    window = qml.rootObjects()[0]
    window.setProperty("visible", True)

    def settle():
        loop = QEventLoop()
        QTimer.singleShot(80, loop.quit)
        loop.exec()
        for _ in range(12):
            app.processEvents()

    def find(name):
        result = window.findChildren(QObject, name)
        assert len(result) == 1, (name, len(result))
        return result[0]

    settle()
    selector = find("logitechDeviceSelector")
    rescan = find("logitechDeviceRescan")
    advanced = find("mouseDeviceAdvancedButton")
    popup = find("mouseDeviceAdvancedPopup")
    manual = find("mouseManualLayoutSelector")
    assert not window.findChildren(QObject, "logitechDeviceSelectorTitle"), "duplicate management card"
    assert selector.property("displayText") == "MX Master 2S · 自动"
    assert rescan.property("text") == "重新扫描"
    assert advanced.property("text") == "高级设置"
    assert manual.property("displayText") == "自动检测"
    assert not popup.property("visible"), "advanced controls must start collapsed"

    for language, label, advanced_text, manual_text in [
        ("en", "MX Master 2S · Automatic", "Advanced", "Auto-detect"),
        ("zh_TW", "MX Master 2S · 自動", "進階設定", "自動偵測"),
        ("zh_CN", "MX Master 2S · 自动", "高级设置", "自动检测"),
    ]:
        backend._cfg["settings"]["language"] = language
        locale.setLanguage(language)
        backend.settingsChanged.emit()
        settle()
        assert selector.property("displayText") == label
        assert advanced.property("text") == advanced_text
        assert manual.property("displayText") == manual_text
        for width in [920, 1100, 1500]:
            window.setProperty("width", width)
            settle()
            assert selector.property("width") >= 120
            assert selector.property("x") + selector.property("width") <= rescan.property("x")
            assert rescan.property("x") + rescan.property("width") <= advanced.property("x")
            assert advanced.property("x") + advanced.property("width") <= advanced.parent().property("width") + 1

    # A real target change must update both the title and the diagram, not the
    # manual-layout control alone. No user's config or HID handles are involved.
    backend._cfg["settings"]["preferred_logi_device"] = {"identity": "mouse2", "name": "G502 HERO"}
    backend._device_inventory_snapshot = {"status": "ready", "selected": "mouse2", "devices": [
        {"identity": "mouse2", "mouse": True, "name": "G502 HERO", "slot": 255,
         "transport": "USB", "online": True, "status": "online", "model_confirmed": True},
    ]}
    engine.connected_device = build_connected_device_info(product_id=0xC08B, product_name="G502 HERO", transport="USB")
    with patch("ui.backend.save_config"):
        backend._sync_connected_device_info()
    backend.settingsChanged.emit()
    settle()
    assert selector.property("displayText") == "G502 HERO"
    assert selector.property("currentIndex") == 1
    assert backend.effectiveDeviceLayoutKey == "g502"
    assert manual.property("displayText") == "自动检测"

    screenshot_dir = os.environ.get("MOUSER_QML_SCREENSHOT_DIR")
    if screenshot_dir:
        assert window.grabWindow().save(str(Path(screenshot_dir) / "integrated-header.png"))
    QMetaObject.invokeMethod(popup, "open")
    settle()
    assert popup.property("visible")
    # Bounds alone miss the pre-layout mapToItem bug: the popup was inside
    # the window but far from its button. Check the actual overlay anchor,
    # including live resizing while open and reopening at each width.
    for width in [920, 1500, 1100]:
        window.setProperty("width", width)
        settle()
        anchor = advanced.mapToItem(popup.property("parent"), QPointF(advanced.width(), advanced.height()))
        expected_x = max(16, min(width - popup.property("width") - 16,
                                 anchor.x() - popup.property("width")))
        expected_y = max(16, min(window.height() - popup.property("height") - 16, anchor.y()))
        assert abs(popup.property("x") - expected_x) <= 1, (popup.property("x"), expected_x, width)
        assert abs(popup.property("y") - expected_y) <= 1, (popup.property("y"), expected_y, width)
        assert 0 <= popup.property("x") <= width - popup.property("width")
        assert popup.property("y") + popup.property("height") <= window.height()
        QMetaObject.invokeMethod(popup, "close")
        settle()
        QMetaObject.invokeMethod(popup, "open")
        settle()
        assert abs(popup.property("x") - expected_x) <= 1
    if screenshot_dir:
        assert window.grabWindow().save(str(Path(screenshot_dir) / "advanced-layout.png"))
    QMetaObject.invokeMethod(popup, "close")
    settle()
    assert not warnings, warnings
    print("QML_HEADER_SMOKE=PASS")
    # Clear the engine while context objects remain alive, avoiding shutdown noise.
    qml.deleteLater()
    app.processEvents()


if __name__ == "__main__":
    if "--qml-smoke" in sys.argv:
        _qml_smoke()
    else:
        unittest.main()
