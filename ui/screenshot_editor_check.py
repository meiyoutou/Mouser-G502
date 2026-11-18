"""Isolated frozen-app editor check/demo with a synthetic image only.

Never loads configuration, opens HID/mic, captures the desktop or uses the
system clipboard. Reports contain public diagnostics, not user screenshots.
"""
import json
import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

from core.version import APP_VERSION
from ui.locale_manager import LocaleManager
from ui.screenshot_common import SCREENSHOT_FULL_CLIP, SCREENSHOT_REGION_FILE, pil_image_to_qimage
from ui.screenshot_editor import Annotation, ScreenshotEditor, ScreenshotPin


def synthetic_image():
    image = QImage(1200, 700, QImage.Format.Format_RGB32)
    image.fill(QColor("#edf2f7"))
    painter = QPainter(image)
    painter.fillRect(60, 50, 1080, 600, QColor("#ffffff"))
    font = QFont("Microsoft YaHei")
    font.setPixelSize(32)
    painter.setFont(font)
    painter.setPen(QColor("#0f172a"))
    painter.drawText(100, 115, "Mouser 截图编辑 · Synthetic demo")
    font.setPixelSize(22)
    painter.setFont(font)
    painter.setPen(QColor("#64748b"))
    painter.drawText(100, 170, "演示图片，不是真实桌面 / No desktop capture")
    for idx, (name, color) in enumerate((("区域截图", "#dbeafe"), ("全屏截图", "#ccfbf1"),
                                        ("裁剪 / 标注 / 遮挡 / 贴图", "#fef3c7"))):
        y = 220 + idx * 100
        painter.fillRect(100, y, 960, 76, QColor(color))
        painter.setPen(QColor("#0f172a"))
        painter.drawText(125, y + 46, name)
    painter.setPen(QColor("#64748b"))
    painter.drawText(100, 585, "复制、保存均只输出编辑后的合成图片")
    painter.end()
    return image


class CheckClipboard:
    image = None
    text = None

    def setImage(self, image):
        self.image = image.copy()

    def setText(self, text):
        self.text = text


def run_check(path):
    app = QApplication.instance() or QApplication([])
    root = Path(path).resolve().parent
    root.mkdir(parents=True, exist_ok=True)
    clipboard = CheckClipboard()
    locale = LocaleManager("zh_CN")
    editor = ScreenshotEditor(synthetic_image(), SCREENSHOT_REGION_FILE, locale=locale,
                              path_factory=lambda: root / "synthetic-export.png",
                              clipboard_factory=lambda: clipboard)
    editor.document.add(Annotation("arrow", ((100, 200), (600, 275)), width=8))
    editor.document.add(Annotation("text", ((200, 80),), text="标注 / TEST"))
    editor.document.add(Annotation("mosaic", ((750, 300), (990, 440)), block=20))
    editor.document.add(Annotation("redact", ((150, 500), (450, 550)), color="#000000"))
    full = editor.document.render()
    editor.document.set_crop(QRect(90, 70, 1000, 550))
    expected = full.copy(editor.document.crop)
    editor.canvas.refresh()
    assert editor.canvas._display_image == expected
    assert editor.copy_image() and clipboard.image == expected
    assert editor.save_image() and QImage(str(root / "synthetic-export.png")) == expected
    for scale in (.5, 1, 1.25, 1.5, 2):
        editor.canvas.set_scale(scale)
        assert editor.canvas.image_point(QPointF(40 * scale, 30 * scale)) == QPointF(130, 100)
    for lang, label in (("en", "Mosaic"), ("zh_CN", "马赛克"), ("zh_TW", "馬賽克")):
        locale.setLanguage(lang)
        assert editor._actions["mosaic"].text() == label
    pin = ScreenshotPin(expected, locale, clipboard_factory=lambda: clipboard)
    pin.show()
    app.processEvents()
    assert pin.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    assert pin.image == expected
    assert pin.drag_handle.isVisible() and not pin.drag_handle.icon().isNull()
    assert pin.drag_handle.cursor().shape() == Qt.CursorShape.OpenHandCursor
    pin.zoom(-120)
    assert pin.copy_image() and clipboard.image == expected
    assert pin.copy_button.text() == "" and pin.close_button.text() == ""
    pin.close()
    long_image = QImage(930, 5991, QImage.Format.Format_RGB32)
    long_image.fill(QColor("#c8dff2"))
    long_pin = ScreenshotPin(long_image, locale, clipboard_factory=lambda: clipboard)
    long_pin.show()
    app.processEvents()
    assert long_pin.view.width() > 200
    assert long_pin.scroll.verticalScrollBar().maximum() > 0
    long_pin.scroll.verticalScrollBar().setValue(120)
    long_pin.zoom(-120)
    assert long_pin.copy_image() and clipboard.image == long_image
    long_pin.close()
    fixed = ScreenshotEditor(expected, SCREENSHOT_FULL_CLIP,
                             clipboard_factory=lambda: clipboard, locale=locale)
    pinned_outputs = []
    fixed.pinRequested.connect(pinned_outputs.append)
    fixed.finish()
    assert pinned_outputs == [] and clipboard.image == expected
    editor.close()
    app.processEvents()
    report = {
        "ok": True, "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
        "synthetic_image_only": True, "desktop_captured": False, "system_clipboard_changed": False,
        "config_loaded": False, "microphone_opened": False,
        "preview_export_clipboard_pin_pixels_match": True, "crop_mosaic_pixels_match": True,
        "pin_hand_drag_handle": True, "pin_full_resolution_copy": True,
        "pin_scrollable_long_image": True, "copy_finish_no_automatic_pin": True,
        "scale_mapping": [0.5, 1, 1.25, 1.5, 2], "locales": ["en", "zh_CN", "zh_TW"],
    }
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def run_phase2_check(path):
    """Frozen-entry check without reading user settings or capturing the desktop."""
    run_check(path)
    from PIL import Image, ImageDraw
    import random
    from ui.screenshot_tools import ScrollStitcher, magnifier_patch
    from ui.windows_screenshot import MonitorMap, physical_to_logical_rects
    from ui.screenshot_overlay import IntRect
    from core import text_selection
    rng = random.Random(123)
    source = Image.new("RGB", (180, 800))
    painter = ImageDraw.Draw(source)
    for row in range(source.height):
        painter.line((0, row, 179, row), fill=tuple(rng.randrange(256) for _ in range(3)))
    stitch = ScrollStitcher(source.crop((0, 0, 180, 400)))
    assert stitch.append(source.crop((0, 137, 180, 537))) == 137
    assert stitch.render().tobytes() == source.crop((0, 0, 180, 537)).tobytes()
    # Native-sized text on white background: the former narrow gray sampler
    # could refuse a perfectly valid overlap here.
    from ui.screenshot_session import qimage_to_pil
    text_page = QImage(800, 2400, QImage.Format.Format_RGB32)
    text_page.fill(QColor("white"))
    painter = QPainter(text_page)
    font = QFont("Microsoft YaHei")
    font.setPixelSize(24)
    painter.setFont(font)
    painter.setPen(QColor("#222222"))
    for row in range(60):
        painter.drawText(35, 40 + row * 38,
                         f"{row + 1:03d}. 长截图原始像素匹配 / paragraph {row + 1}")
    painter.end()
    page = qimage_to_pil(text_page)
    for offset in (3, 137, 347, 450):
        text_stitch = ScrollStitcher(page.crop((0, 0, 800, 600)))
        assert text_stitch.append(page.crop((0, offset, 800, 600 + offset))) == offset
        assert text_stitch.render().tobytes() == page.crop((0, 0, 800, 600 + offset)).tobytes()
    # Geometry-only provider fixture: fixed chrome never participates in the
    # initial or later cropped image. No real UIA/desktop is queried here.
    from contextlib import nullcontext
    from types import SimpleNamespace
    from ui.screenshot_scroll_region import detect_scroll_viewport
    body = IntRect(280, 100, 1080, 700)
    class GeometryControl:
        BoundingRectangle = SimpleNamespace(left=280, top=100, right=1080, bottom=700)
        ControlType, ProcessId, IsOffscreen = 50033, -1, False
        def GetPattern(self, _):
            return SimpleNamespace(VerticallyScrollable=True)
        def GetParentControl(self):
            return None
        def GetFirstChildControl(self):
            return None
    provider = SimpleNamespace(UIAutomationInitializerInThread=nullcontext,
                               ControlFromPoint=lambda *_: GeometryControl())
    detected = detect_scroll_viewport(IntRect(0, 0, 1100, 900),
                                      automation=provider, ignore_process=-2)
    assert detected == body
    frames = []
    for offset in (0, 137):
        frame = Image.new("RGB", (1100, 900), "#e8edf2")
        frame.paste(page.crop((0, offset, 800, 600 + offset)), (280, 100))
        frames.append(frame.crop((detected.left, detected.top, detected.right, detected.bottom)))
    cropped = ScrollStitcher(frames[0])
    assert cropped.append(frames[1]) == 137
    assert cropped.render().tobytes() == page.crop((0, 0, 800, 737)).tobytes()
    changed = page.crop((0, 137, 800, 737))
    local = ImageDraw.Draw(changed)
    local.rectangle((795, 0, 799, 599), fill="#999999")
    local.rectangle((100, 200, 101, 225), fill="red")
    assert ScrollStitcher.overlap(page.crop((0, 0, 800, 600)), changed) == 463
    # Accessibility deliberately absent: fixed white chat chrome, ten scrolls.
    def chat_frame(offset):
        image = Image.new("RGB", (1100, 900), "white")
        drawing = ImageDraw.Draw(image)
        drawing.text((30, 30), "Fixed chat header", fill="black")
        for row in range(20):
            drawing.text((25, 115 + row * 32), f"Sidebar item {row}", fill="black")
        drawing.text((340, 790), "Fixed input placeholder", fill="black")
        image.paste(page.crop((0, offset, 800, offset + 600)), (280, 100))
        return image
    from ui.screenshot_registration import RegistrationStitcher
    motion = RegistrationStitcher(chat_frame(0), detect_content=True)
    last_offset = 0
    for next_offset in (137, 210, 347, 390, 510, 631, 740, 809, 950, 1070):
        assert motion.append(chat_frame(next_offset)) == next_offset - last_offset
        last_offset = next_offset
    assert motion.content_rect is not None
    x0, y0, x1, y1 = motion.content_rect
    expected_motion = Image.new("RGB", (1100, 1970), "white")
    expected_motion.paste(page.crop((0, 0, 800, 1670)), (280, 100))
    assert motion.render().tobytes() == expected_motion.crop((x0, y0, x1, y1 + 1070)).tobytes()
    # A fixed bottom button must not be baked into each appended strip.
    # These are generated pixels, not private diagnostic images.
    def with_button(image, offset=0):
        drawing = ImageDraw.Draw(image)
        x, y = 400, offset + 548
        drawing.ellipse((x - 20, y - 20, x + 20, y + 20),
                        fill="white", outline="#d0d0d0")
        drawing.line((x, y - 9, x, y + 8), fill="#333333", width=2)
        drawing.line((x - 7, y + 1, x, y + 8, x + 7, y + 1),
                     fill="#333333", width=2)
        return image
    floating = RegistrationStitcher(with_button(page.crop((0, 0, 800, 600))))
    for position in (92, 347, 444, 625, 799, 1000):
        floating.append(with_button(page.crop((0, position, 800, 600 + position))))
        assert floating.render().tobytes() == with_button(
            page.crop((0, 0, 800, 600 + position)), position).tobytes()
    # Exercise the actual timer + worker path in the frozen program as well.
    # This provider only returns synthetic pixels; no system capture is used.
    from PySide6.QtCore import QEventLoop, QTimer
    from ui.screenshot_scroll import ScrollCaptureSession
    offset = [137]
    auto = ScrollCaptureSession(page.crop((0, 0, 800, 600)),
                               lambda: page.crop((0, offset[0], 800, offset[0] + 600)),
                               locale=LocaleManager("zh_CN"), viewport_detected=True)
    assert auto.stitcher.detect_content, "UIA must never disable image refinement"
    assert set(auto.buttons) == {"cancel", "done"} and auto.buttons["done"].text() == ""
    assert auto.hint.isHidden() and auto.status.isHidden()
    assert all(button.text() == "" for button in auto.buttons.values())
    assert auto.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert isinstance(auto.stitcher, RegistrationStitcher)
    assert auto.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    delivered, preview_keys = [], set()
    loop, watch, timeout = QEventLoop(), QTimer(), QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    auto.completed.connect(lambda image: (delivered.append(image), loop.quit()))
    def advance():
        assert not auto._paused
        if auto.isVisible():
            assert auto.preview.isVisible()
            preview_keys.add(auto.preview.pixmap().cacheKey())
        if auto.stitcher.height == 737:
            offset[0] = 347
        elif auto.stitcher.height == 947 and not auto._pending:
            # Finish must flush a final viewport not yet sampled by the timer.
            offset[0] = 450
            auto.finish()
    watch.timeout.connect(advance)
    watch.start(20)
    timeout.start(10000)
    auto.show()
    loop.exec()
    watch.stop()
    timeout.stop()
    if not delivered:
        auto.close()
    assert len(delivered) == 1, "automatic timer/final flush failed"
    assert delivered[0].tobytes() == page.crop((0, 0, 800, 1050)).tobytes()
    assert len(preview_keys) >= 2, "live preview did not update"
    # Actual portrait dimensions, independent of the legacy row-hash matcher.
    portrait_page = page.resize((1100, 5500))
    portrait = RegistrationStitcher(portrait_page.crop((0, 0, 1100, 2512)))
    for position in (137, 347, 631, 950):
        portrait.append(portrait_page.crop((0, position, 1100, 2512 + position)))
    assert portrait.render().tobytes() == portrait_page.crop((0, 0, 1100, 3462)).tobytes()
    thumbnail = portrait.preview_image()
    assert thumbnail.width <= 240 and thumbnail.height <= 300
    half = portrait_page.resize((720, 5500))
    def mixed_frame(position):
        image = Image.new("RGB", (1440, 2512), "white")
        image.paste(half.crop((0, 0, 720, 2512)), (0, 0))
        image.paste(half.crop((0, position, 720, 2512 + position)), (720, 0))
        return image
    mixed = RegistrationStitcher(mixed_frame(0), detect_content=True)
    for position in (137, 347, 631, 950, 1070):
        mixed.append(mixed_frame(position))
    assert mixed.content_rect is not None
    x0, y0, x1, y1 = mixed.content_rect
    assert x0 >= 720
    assert mixed.render().tobytes() == half.crop((x0 - 720, y0, x1 - 720, y1 + 1070)).tobytes()
    # Long images use the existing editor when enabled, and must not reach
    # clipboard/file output until the user confirms that editor.
    from ui.windows_screenshot import WindowsScreenshotController
    control, outputs = WindowsScreenshotController(), []
    control._edit_this_capture = True
    control._deliver_image = lambda image, action: outputs.append((image, action))
    control._finish_scroll(delivered[0], SCREENSHOT_FULL_CLIP)
    assert not outputs and control._editor is not None
    long_editor = control._editor
    long_clipboard = CheckClipboard()
    long_editor.clipboard_factory = lambda: long_clipboard
    long_editor.document.add(Annotation("redact", ((15, 15), (40, 40)), color="#000000"))
    edited = long_editor.document.render()
    long_editor._actions["done"].trigger()
    assert long_clipboard.image == edited and control._editor is None
    assert not outputs and not control._pins
    control._edit_this_capture = False
    control._finish_scroll(delivered[0], SCREENSHOT_FULL_CLIP)
    assert len(outputs) == 1 and outputs[0][1] == SCREENSHOT_FULL_CLIP
    assert control._editor is None
    from ui.screenshot_common import SCREENSHOT_FULL_FILE
    target = Path(path).parent / "fixed-result.png"
    fixed_control = WindowsScreenshotController(path_factory=lambda: target)
    fixed_control._edit_this_capture = True
    fixed_control._finish_scroll(delivered[0], SCREENSHOT_FULL_FILE)
    assert fixed_control._editor is not None and not fixed_control._pins
    file_editor = fixed_control._editor
    expected_file = file_editor.document.render()
    file_editor._actions["done"].trigger()
    assert QImage(str(target)) == expected_file and fixed_control._editor is None
    QApplication.instance().processEvents()
    patch, center, pixel = magnifier_patch(synthetic_image(), QPointF(110, 120))
    assert patch.pixelColor(center) == synthetic_image().pixelColor(pixel)
    mapped = physical_to_logical_rects(IntRect(-180, 20, -20, 160),
        (MonitorMap(IntRect(-100, 0, 0, 100), IntRect(-200, 0, 0, 200)),))
    assert mapped == QRect(-90, 10, 80, 70)
    asset = text_selection.catalog()
    assert len(asset["manifest_sha256"]) == 64 and asset["directory"] == "文字选择组件"
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    report.update({
        "scroll_overlap_original_pixels": True, "magnifier_original_pixels": True,
        "window_bounds_mixed_dpi_mapping": True, "text_selection_catalog_loaded": True,
        "recognizer_loaded": False,
        "scroll_native_text_overlap": True, "scroll_small_steps": True,
        "scroll_automatic_timer_stitch": True, "scroll_finish_flushes_last_view": True,
        "scroll_no_append_button": True, "scroll_focusless_controls": True,
        "scroll_content_viewport_crop": True, "scroll_local_change_matching": True,
        "scroll_motion_fallback_without_uia": True, "scroll_motion_repeated_appends": 10,
        "scroll_motion_no_duplicate_seams": True,
        "scroll_registration_engine": "opencv-verified-registration",
        "scroll_overlap_refresh_no_repeated_bottom_button": True,
        "scroll_live_preview_without_pause": True,
        "scroll_only_cancel_and_finish": True,
        "scroll_refinement_retained_after_accessibility": True,
        "scroll_thumbnail_only_no_visible_prose": True,
        "scroll_half_fixed_half_scrolling_selection": True,
        "scroll_portrait_2512px_native_rows": True,
        "scroll_bounded_thumbnail": True,
        "scroll_editor_before_clipboard_or_file_output": True,
        "scroll_editor_annotation_pixels_preserved": True,
        "scroll_direct_delivery_when_editing_disabled": True,
        "scroll_finish_no_automatic_pin": True,
    })
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def run_demo():
    app = QApplication.instance() or QApplication([])
    clipboard = CheckClipboard()
    editor = ScreenshotEditor(synthetic_image(), SCREENSHOT_FULL_CLIP,
                              locale=LocaleManager("zh_CN"),
                              clipboard_factory=lambda: clipboard)
    pins = []

    def pin_image(image):
        pin = ScreenshotPin(image, editor.locale)
        pins.append(pin)
        pin.closed.connect(lambda p: pins.remove(p) if p in pins else None)
        pin.show()

    editor.pinRequested.connect(pin_image)
    app.setQuitOnLastWindowClosed(True)
    editor.show()
    QTimer.singleShot(600000, app.quit)
    return app.exec()


def compact_capture():
    """Synthetic two-screen capture with negative coordinates and mixed scale."""
    from PIL import Image
    from ui.screenshot_session import qimage_to_pil
    from ui.windows_screenshot import VirtualCapture, MonitorMap
    from ui.screenshot_overlay import IntRect
    first = qimage_to_pil(synthetic_image())
    canvas = Image.new("RGB", (2400, 900), "#edf2f7")
    canvas.paste(first.resize((1200, 900)), (0, 0))
    canvas.paste(first, (1200, 0))
    return VirtualCapture(canvas, IntRect(-1200, 0, 1200, 900),
        (MonitorMap(IntRect(-960, 0, 0, 720), IntRect(-1200, 0, 0, 900)),
         MonitorMap(IntRect(0, 0, 1200, 900), IntRect(0, 0, 1200, 900))))


def run_compact_check(path):
    run_phase2_check(path)
    from ui.screenshot_session import ScreenshotSession, toolbar_position, qimage_to_pil
    from PySide6.QtCore import QPoint, QSize
    from ui.windows_screenshot import VirtualCapture, crop_logical_region
    from ui.screenshot_overlay import IntRect
    app = QApplication.instance()
    clipboard = CheckClipboard()
    session = ScreenshotSession(compact_capture(), SCREENSHOT_FULL_CLIP,
                                locale=LocaleManager("zh_CN"), clipboard_factory=lambda: clipboard)
    session._start, session._current = QPoint(-120, 60), QPoint(500, 399)
    session.document.add(Annotation("redact", ((1170, 160), (1230, 210)), color="#000000"))
    session._refresh_images()
    expected = pil_image_to_qimage(crop_logical_region(
        VirtualCapture(qimage_to_pil(session.document.render()), session.capture.physical_rect,
                       session.capture.monitor_maps), IntRect(-120, 60, 501, 400)))
    assert session._output_image() == expected
    assert session.copy_image() and clipboard.image == expected
    assert len(session.toolbar.buttons) == 13 and session.toolbar.options.isHidden()
    assert session.tool == "select" and session.toolbar.buttons["select"].isChecked()
    assert not session.toolbar.buttons["hand"].isChecked()
    base = session.document.render()
    initial = session._selection_global_rect()
    from PySide6.QtGui import QMouseEvent
    handle = session.toolbar.buttons["hand"]
    handle.click()
    assert session.tool == "hand" and handle.isChecked()
    assert not session.toolbar.buttons["select"].isChecked()
    assert session.toolbar.options.isHidden()
    def drag(start, end):
        pane = session._panes[1]
        for kind, point in ((QMouseEvent.Type.MouseButtonPress, start),
                            (QMouseEvent.Type.MouseMove, end),
                            (QMouseEvent.Type.MouseButtonRelease, end)):
            QApplication.sendEvent(pane, QMouseEvent(
                kind, QPointF(pane.mapFromGlobal(point)), QPointF(point),
                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier))
    drag(QPoint(100, 100), QPoint(120, 115))
    assert session._selection_global_rect() == initial.translated(20, 15)
    assert session.tool == "hand" and handle.isChecked()
    assert not session._magnifier and session._mouse_grab_pane is None
    drag(QPoint(120, 115), QPoint(130, 120))
    assert session._selection_global_rect() == initial.translated(30, 20)
    assert session.document.render() == base
    assert session.copy_image() and clipboard.image == session._output_image()
    session.toolbar.buttons["select"].click()
    drag(QPoint(130, 120), QPoint(160, 140))
    assert session._selection_global_rect() == initial.translated(30, 20)
    drag(QPoint(800, 600), QPoint(1000, 750))
    assert session._selection_global_rect() == initial.translated(30, 20)
    assert session._panes[1].cursor().shape() == Qt.CursorShape.ArrowCursor
    assert session.toolbar.buttons["select"].isChecked() and not handle.isChecked()
    assert not {"number", "reset_crop"} & session._actions.keys()
    assert all(button.size() == QSize(34, 34) for button in session.toolbar.buttons.values())
    assert "scroll" in session.toolbar.buttons and "pin" in session.toolbar.buttons
    assert "text" not in session.toolbar.buttons
    assert session._actions["text"] in session.toolbar.more.actions()
    assert session.toolbar.buttons["done"].toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
    for language, done in (("zh_CN", "完成并复制"), ("en", "Copy & finish"), ("zh_TW", "完成並複製")):
        session.locale.setLanguage(language)
        assert session._actions["done"].text() == done
        assert session.toolbar.buttons["done"].accessibleName() == done
        assert done in session.toolbar.buttons["done"].toolTip()
    screens = [m.logical.to_qrect() for m in session.capture.monitor_maps]
    point = toolbar_position(QRect(1000, 850, 190, 45), QSize(470, 90), screens)
    assert any(r.contains(QRect(point, QSize(470, 90))) for r in screens)
    session.tool = "text"
    session._edit_text(session._panes[1], QPoint(100, 200), QPointF(1300, 200))
    session._text_box.setPlainText("原位输入 / INLINE")
    session._text_box.commit()
    assert session.document.annotations[-1].text == "原位输入 / INLINE"
    session.close()
    app.processEvents()
    pointer_editor = ScreenshotEditor(synthetic_image(), SCREENSHOT_FULL_CLIP,
                                     locale=LocaleManager("zh_CN"),
                                     clipboard_factory=lambda: clipboard)
    canvas = pointer_editor.canvas
    pointer_pixels = pointer_editor.document.render()
    for kind, point in ((QMouseEvent.Type.MouseButtonPress, QPoint(30, 30)),
                        (QMouseEvent.Type.MouseMove, QPoint(300, 200)),
                        (QMouseEvent.Type.MouseButtonRelease, QPoint(300, 200))):
        QApplication.sendEvent(canvas, QMouseEvent(
            kind, QPointF(point), QPointF(canvas.mapToGlobal(point)),
            Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseMove else Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
    assert canvas.tool == "select" and canvas.cursor().shape() == Qt.CursorShape.ArrowCursor
    assert canvas.selection is None and pointer_editor.document.render() == pointer_pixels
    assert pointer_editor.copy_image() and clipboard.image == pointer_pixels
    pointer_editor.close()
    app.processEvents()
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    report.update({
        "single_surface_region_and_full": True, "compact_toolbar": True,
        "inline_text": True, "mixed_dpi_annotation_export": True,
        "destination_labels": True, "toolbar_screen_bounds": True,
        "icon_only_finish": True, "primary_scroll_and_pin": True,
        "text_in_more_menu": True,
        "removed_number_and_full_image": True,
        "uniform_button_sizes": True,
        "selection_hand_before_finish": True,
        "selection_hand_moves_bounds_not_pixels": True,
        "selection_visible_default_tool": True,
        "selection_hand_click_latches_mode": True,
        "selection_hand_repeated_interior_drags": True,
        "selection_switch_back_locks_interior": True,
        "default_arrow_pointer_no_reselection": True,
        "result_editor_pointer_no_crop": True,
    })
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def run_compact_demo():
    """Show synthetic pixels on one actual monitor; no screenshot/config access."""
    from ui.screenshot_session import ScreenshotSession, qimage_to_pil
    from ui.windows_screenshot import VirtualCapture, MonitorMap
    from ui.screenshot_overlay import IntRect, rect_from_qrect
    app = QApplication.instance() or QApplication([])
    screen = app.primaryScreen().geometry()
    logical = rect_from_qrect(screen)
    image = qimage_to_pil(synthetic_image()).resize((screen.width(), screen.height()))
    capture = VirtualCapture(image, logical, (MonitorMap(logical, logical),))
    session = ScreenshotSession(capture, SCREENSHOT_FULL_CLIP, locale=LocaleManager("zh_CN"),
                                clipboard_factory=lambda: CheckClipboard())
    rect = QRect(screen.x() + 100, screen.y() + 130,
                 min(900, screen.width() - 200), min(500, screen.height() - 270))
    session._start, session._current = rect.topLeft(), rect.bottomRight()
    # Give synthetic test windows normal discoverable identities for desktop
    # inspection. Production capture panes remain taskbar-free Qt Tool windows.
    for pane in session._panes:
        pane.setWindowTitle("Mouser 截图交互演示（合成图片）")
        pane.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint)
    session.toolbar.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
                                   | Qt.WindowType.WindowStaysOnTopHint)
    session.closed.connect(lambda _: app.quit())
    session.show()
    QTimer.singleShot(600000, session.close)
    return app.exec()
