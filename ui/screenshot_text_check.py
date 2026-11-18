"""Frozen text-selection check with generated text and a fake clipboard."""
import json
import os
from pathlib import Path
import sys
import time


def _check_long_editor(app, image, report_path):
    """Actual long-image controller/editor/worker/pin, synthetic pixels only."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QMouseEvent, QPainter, QWheelEvent
    from ui.locale_manager import LocaleManager
    from ui.screenshot_common import SCREENSHOT_FULL_CLIP
    from ui.screenshot_editor_check import CheckClipboard
    from ui.screenshot_session import qimage_to_pil
    from ui.windows_screenshot import WindowsScreenshotController

    long_image = QImage(1200, 2600, QImage.Format.Format_RGB32)
    long_image.fill(QColor("white"))
    painter = QPainter(long_image)
    painter.drawImage(0, 0, image)
    font = QFont("Microsoft YaHei")
    font.setPixelSize(34)
    painter.setFont(font)
    painter.setPen(QColor("#152335"))
    painter.drawText(100, 2200, "Long capture text 456 XYZ")
    painter.end()
    controller = WindowsScreenshotController(locale=LocaleManager("zh_CN"))
    controller._edit_this_capture = True
    controller._finish_scroll(qimage_to_pil(long_image), SCREENSHOT_FULL_CLIP)
    editor = controller._editor
    assert editor is not None
    clipboard = CheckClipboard()
    editor.clipboard_factory = lambda: clipboard

    def wheel(widget, delta, modifiers=Qt.KeyboardModifier.NoModifier):
        point = QPoint(50, 50)
        QApplication.sendEvent(widget, QWheelEvent(
            QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(), QPoint(0, delta),
            Qt.MouseButton.NoButton, modifiers, Qt.ScrollPhase.ScrollUpdate, False))
        app.processEvents()

    from PySide6.QtWidgets import QApplication
    try:
        assert editor._selection_worker is None and editor.canvas.text_layer is None
        assert editor._actions["text_select"] in editor.toolbar.more.actions()
        editor._actions["text_select"].trigger()
        deadline = time.monotonic() + 65
        while editor._selection_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        layer = editor.canvas.text_layer
        assert layer is not None, editor.hint.text()
        bottom = [i for i, glyph in enumerate(layer.glyphs) if glyph["box"][1] > 2000]
        assert bottom, "Long-image lower rows were not recognized"
        editor.canvas.set_scale(.75)
        app.processEvents()
        assert editor.canvas.text_layer is layer
        first, last = layer.boxes[bottom[0]], layer.boxes[bottom[-1]]
        editor.scroll.verticalScrollBar().setValue(round((first.top() - 150) * editor.canvas.scale))
        start = QPointF(first.left() + 1, first.center().y()) * editor.canvas.scale
        end = QPointF(last.right() - 1, last.center().y()) * editor.canvas.scale
        for kind, point in ((QMouseEvent.Type.MouseMove, start),
                            (QMouseEvent.Type.MouseButtonPress, start),
                            (QMouseEvent.Type.MouseMove, end),
                            (QMouseEvent.Type.MouseButtonRelease, end)):
            QApplication.sendEvent(editor.canvas, QMouseEvent(
                kind, point, QPointF(editor.canvas.mapToGlobal(point.toPoint())),
                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier))
        assert editor.canvas.cursor().shape() == Qt.CursorShape.IBeamCursor
        QApplication.sendEvent(editor.canvas, QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier))
        assert clipboard.text == "Long capture text 456 XYZ", clipboard.text
        assert clipboard.image is None and editor._output_image() == long_image
        scale = editor.canvas.scale
        wheel(editor.scroll.viewport(), 120, Qt.KeyboardModifier.ControlModifier)
        assert editor.canvas.scale > scale and editor.canvas.text_layer is layer
        scale, position = editor.canvas.scale, editor.scroll.verticalScrollBar().value()
        wheel(editor.canvas, 120)
        assert editor.canvas.scale == scale and editor.scroll.verticalScrollBar().value() < position
        editor.grab().save(str(report_path.parent / "long-editor-text-selection.png"))
        editor._actions["pin"].trigger()
        assert controller._editor is None and len(controller._pins) == 1
        pin = controller._pins[0]
        pin_clipboard = CheckClipboard()
        pin.clipboard_factory = lambda: pin_clipboard
        assert pin.image == long_image
        width = pin.view.width()
        wheel(pin.scroll.viewport(), 120, Qt.KeyboardModifier.ControlModifier)
        assert pin.view.width() > width
        width, position = pin.view.width(), pin.scroll.verticalScrollBar().value()
        wheel(pin.view, -120)
        assert pin.view.width() == width and pin.scroll.verticalScrollBar().value() > position
        pin.zoom_in_button.click()
        assert pin.view.width() > width
        pin.zoom_out_button.click()
        assert abs(pin.view.width() - width) <= 2
        assert pin.resize_grip.isVisible()
        pin.grab().save(str(report_path.parent / "pin-zoom-controls.png"))
        pin.copy_button.click()
        assert pin_clipboard.image == long_image and clipboard.image is None
        return {
            "long_editor_recognizes_lower_rows": True,
            "long_editor_drag_copy_text": clipboard.text,
            "zoom_retains_text_layer": True,
            "ctrl_wheel_zoom_and_plain_wheel_scroll": True,
            "editor_and_pin_full_resolution_pixels_unchanged": True,
            "pin_zoom_buttons_and_resize_grip": True,
            "recognition_is_opt_in_and_worker_isolated": True,
        }
    finally:
        if controller._editor is not None:
            controller._editor.close()
        for pin in list(controller._pins):
            pin.close()
        app.processEvents()


def run_check(report_path):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
    from PySide6.QtCore import QPointF, QRect, Qt
    from PySide6.QtGui import QColor, QFont, QImage, QKeyEvent, QMouseEvent, QPainter
    from PySide6.QtWidgets import QApplication
    from core import text_selection
    from core.version import APP_VERSION
    from ui.locale_manager import LocaleManager
    from ui.screenshot_common import SCREENSHOT_FULL_CLIP
    from ui.screenshot_editor_check import CheckClipboard
    from ui.screenshot_overlay import IntRect
    from ui.screenshot_session import ScreenshotSession, qimage_to_pil
    from ui.windows_screenshot import VirtualCapture, MonitorMap

    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    image = QImage(1200, 660, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    font = QFont("Microsoft YaHei")
    font.setPixelSize(30)
    painter.setFont(font)
    painter.setPen(QColor("#152335"))
    for y, text in ((110, "冻结截图文字选择测试"), (190, "只在图片上选字，不会点击原窗口"),
                    (270, "Drag text to copy 123 ABC"), (350, "Tesseract 小模型 · 仅在本机识别")):
        painter.drawText(100, y, text)
    painter.end()
    image.save(str(report_path.parent / "text-selection-synthetic-input.png"))
    logical, physical = IntRect(-400, 40, 400, 480), IntRect(-600, 60, 600, 720)
    capture = VirtualCapture(qimage_to_pil(image), physical, (MonitorMap(logical, physical),))
    clipboard = CheckClipboard()
    session = ScreenshotSession(capture, SCREENSHOT_FULL_CLIP, full=True,
                                locale=LocaleManager("zh_CN"), clipboard_factory=lambda: clipboard)
    try:
        session.show()
        assert session.toolbar.actions["text_select"].text() == "文字选择"
        assert not session.toolbar.actions["text_select"].icon().isNull()
        assert not {"ocr", "ocr_install"}.intersection(session.toolbar.actions)
        assert sum(a is session.toolbar.actions["text_select"]
                   for a in session.toolbar.more.actions()) == 1
        session._start_text_selection()
        deadline = time.monotonic() + 65
        while session._selection_worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert session._text_layer is not None, session.hint.text()
        layer = session._text_layer
        assert len(layer.glyphs) > 20
        from ui.screenshot_text_layer import logical_fragments
        first = next(logical_fragments(layer.boxes[0], capture))
        last = next(logical_fragments(layer.boxes[-1], capture))
        start = QPointF(first.left()+2, first.center().y()).toPoint()
        end = QPointF(last.right()-2, last.center().y()).toPoint()
        pane = session._panes[0]
        for kind, point in ((QMouseEvent.Type.MouseButtonPress, start),
                            (QMouseEvent.Type.MouseMove, end),
                            (QMouseEvent.Type.MouseButtonRelease, end)):
            event = QMouseEvent(kind, QPointF(pane.mapFromGlobal(point)), QPointF(point),
                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(pane, event)
        QApplication.sendEvent(pane, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_C,
                                               Qt.KeyboardModifier.ControlModifier))
        assert clipboard.text == layer.selected_text() and "Drag text to copy 123 ABC" in (clipboard.text or ""), (
            clipboard.text, layer.selected_text(), "".join(g["prefix"]+g["text"] for g in layer.glyphs))
        assert clipboard.image is None
        assert not session._live and all(p.mask().isEmpty() for p in session._panes)
        assert session._output_image() == image
        session._pointer = first.center().toPoint()
        session._refresh_cursors()
        assert pane.cursor().shape() == Qt.CursorShape.IBeamCursor
        assert not any(name.startswith("tesserocr") for name in sys.modules)
        app.processEvents()
        preview = pane.grab().toImage()
        painter = QPainter(preview)
        painter.drawPixmap(session.toolbar.pos()-pane.pos(), session.toolbar.grab())
        painter.end()
        preview.save(str(report_path.parent / "text-selection-preview.png"))
        menu = session.toolbar.more
        menu.ensurePolished()
        menu.adjustSize()
        menu_image = menu.grab()
        controls = QImage(max(600, session.toolbar.width()+32),
                          session.toolbar.height()+menu_image.height()+64,
                          QImage.Format.Format_RGB32)
        controls.fill(QColor("#eef2f6"))
        painter = QPainter(controls)
        painter.drawPixmap(16, 16, session.toolbar.grab())
        painter.drawPixmap(16, session.toolbar.height()+32, menu_image)
        painter.end()
        controls.save(str(report_path.parent / "text-selection-controls.png"))
        report = {"ok": True, "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
                  "glyph_count": len(layer.glyphs), "text": clipboard.text,
                  "first_line_reference": "冻结截图文字选择测试",
                  "first_line_exact": clipboard.text.splitlines()[0] == "冻结截图文字选择测试",
                  "recognizer_not_loaded_in_ui_process": True,
                  "single_localized_text_selection_action": True,
                  "old_recognition_actions_absent": True,
                  "mixed_dpi_negative_origin_drag_copy": True, "screenshot_pixels_unchanged": True,
                  "click_through_disabled": True, "system_clipboard_changed": False,
                  "desktop_captured": False, "config_loaded": False}
        report["long_editor"] = _check_long_editor(app, image, report_path)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        session.close()
        app.processEvents()
    return 0
