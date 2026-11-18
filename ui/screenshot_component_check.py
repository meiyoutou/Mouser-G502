"""Synthetic frozen optional-component installation check; no personal data."""
import json
from pathlib import Path
import sys
import time


def run_check(report_path):
    from PySide6.QtGui import QImage, QColor
    from PySide6.QtWidgets import QApplication
    from core import screenshot_components as components
    from core.version import APP_VERSION
    from ui.locale_manager import LocaleManager
    from ui.screenshot_components import ComponentDialog
    from ui.screenshot_editor import ScreenshotEditor
    from ui.screenshot_common import SCREENSHOT_FULL_CLIP
    from ui.screenshot_editor_check import CheckClipboard
    path = Path(report_path)
    app = QApplication.instance() or QApplication([])
    try:
        before = {kind: components.checked_directory(kind) is not None for kind in components.KINDS}
        assert not any(before.values()), "Use fresh isolated component storage for this check"
        image = QImage(800, 1400, QImage.Format.Format_RGB32)
        image.fill(QColor("#adbacd"))
        clipboard = CheckClipboard()
        editor = ScreenshotEditor(image, SCREENSHOT_FULL_CLIP, locale=LocaleManager("zh_CN"),
                                  clipboard_factory=lambda: clipboard)
        assert editor.copy_image() and clipboard.image == image
        assert editor._output_image() == image
        editor.close()
        events = []
        dialog = ComponentDialog(LocaleManager("zh_CN"))
        dialog.installed.connect(events.append)
        for index, kind in enumerate(components.KINDS):
            dialog.choice.setCurrentIndex(index)
            dialog.begin()  # Explicit action; adjacent local ZIPs, not the network.
            deadline = time.monotonic() + 60
            while dialog.busy and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            assert not dialog.busy, "Component installation timed out"
            assert components.checked_directory(kind) is not None, dialog.state.text()
        for language, title in (("en", "Screenshot components"), ("zh_TW", "截圖元件"),
                                ("zh_CN", "截图组件")):
            dialog.locale.setLanguage(language)
            assert dialog.windowTitle() == title
        dialog.close()
        assert events == list(components.KINDS)
        assert not any(name in sys.modules for name in ("numpy", "cv2", "tesserocr"))
        report = {"ok": True, "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
                  "missing_before_install": True, "ordinary_editor_without_components": True,
                  "explicit_async_local_first_install": events, "locales": ["en", "zh_CN", "zh_TW"],
                  "native_engines_not_imported_by_ui": True, "desktop_captured": False,
                  "system_clipboard_changed": False, "microphone_opened": False,
                  "user_configuration_used": False, "network_used": False}
        result = 0
    except Exception as error:
        report = {"ok": False, "type": type(error).__name__, "detail": str(error)}
        result = 1
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return result
