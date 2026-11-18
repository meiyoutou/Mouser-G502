"""Isolated generated-image and settings-lifecycle check; no real user services."""
import copy
import gc
import json
import os
from pathlib import Path
import sys
import time


def _check_scroll_finish(app, *, editing=False):
    """Actual QRunnable -> queued result -> checkmark -> mocked delivery.

    The GUI used to return early on an unchanged, non-final result after the
    user had already requested Finish. Exercise that interleaving with real
    image matching and the packaged compute child, not a mocked reason code.
    """
    from PIL import Image, ImageChops
    from PySide6.QtCore import QThreadPool
    from ui.screenshot_common import SCREENSHOT_REGION_CLIP
    from ui.screenshot_scroll import ScrollCaptureSession
    from ui import windows_screenshot as delivery
    from ui.screenshot_editor import Annotation
    from ui.screenshot_session import qimage_to_pil

    page = Image.effect_noise((320, 1600), 50).convert("RGB")
    chrome = Image.effect_noise((600, 800), 40).convert("RGB")

    def frame(offset):
        image = chrome.copy()
        image.paste(page.crop((0, offset, 320, offset + 600)), (220, 84))
        return image

    def wait_for(condition):
        deadline = time.monotonic() + 10
        while not condition() and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.005)
        assert condition(), "Checkmark did not complete after an unchanged sample"

    original_copy = delivery.copy_image_to_clipboard
    cases = []
    try:
        for last_offset in (137, 347):
            current = [frame(137)]
            session = ScrollCaptureSession(frame(0), lambda: current[0])
            controller = delivery.WindowsScreenshotController()
            controller._edit_this_capture = editing
            controller._scroll_session = session
            delivered = []
            delivery.copy_image_to_clipboard = lambda image: delivered.append(image.copy())
            session.completed.connect(lambda image: controller._finish_scroll(image, SCREENSHOT_REGION_CLIP))
            process = None
            observed = []
            session.analysisObserved.connect(lambda info: observed.append(info["reason"]))
            try:
                session._capture()
                wait_for(lambda: not session._pending)
                assert session.stitcher.content_rect is not None
                bounds = session.stitcher.content_rect
                left, top, right, bottom = bounds
                assert left <= 220 and right >= 540 and top <= 84 and bottom >= 684
                assert session.stitcher.height == bottom - top + 137
                process = session.stitcher._compute.process
                # Only an excluded, fixed panel blinks. The scrolling body is
                # pixel-identical and real append() must return unchanged.
                current[0] = current[0].copy()
                current[0].putpixel((0, 0), (255, 0, 0))
                session._capture()
                assert session._pending
                if last_offset != 137:
                    current[0] = frame(last_offset)
                session.buttons["done"].click()  # No event pumping before click.
                assert session._finishing
                wait_for(lambda: controller._editor is not None if editing else bool(delivered))
                assert session._done
                assert "scroll_unchanged" in observed
                assert controller._scroll_session is None
                expected = page.crop((0, 0, 320, 600 + last_offset))
                if editing:
                    assert not delivered, "Long capture must not copy before editing"
                    editor = controller._editor
                    assert {"arrow", "rect", "mosaic", "pin", "done"} <= set(editor._actions)
                    output = qimage_to_pil(editor.document.base)
                else:
                    assert len(delivered) == 1
                    output = delivered[0]
                assert output.size == (right - left, bottom - top + last_offset)
                body = output.crop((220 - left, 84 - top, 540 - left,
                                    84 - top + 600 + last_offset))
                assert ImageChops.difference(body, expected).getbbox() is None
                wait_for(lambda: session._closed)
                process.wait(timeout=5)
                record = {"last_scroll": last_offset, "scrolling_body_pixels_exact": True,
                          "compute_child_exited": True}
                if editing:
                    editor.document.add(Annotation("redact", ((15, 15), (40, 40)), color="#000000"))
                    edited = editor.document.render()
                    assert edited != editor.document.base
                    if last_offset == 137:
                        from types import SimpleNamespace
                        copied = []
                        editor.clipboard_factory = lambda: SimpleNamespace(
                            setImage=lambda image: copied.append(image.copy()))
                        editor._actions["done"].trigger()
                        assert copied == [edited] and not controller._pins
                        record["editor_checkmark_copies_edited_image_once"] = True
                    else:
                        editor._actions["pin"].trigger()
                        assert len(controller._pins) == 1
                        pin = controller._pins[0]
                        assert pin.image == edited and pin.isVisible()
                        assert pin.image.size() == editor.document.base.size()
                        pin.close()
                        assert not controller._pins
                        record["editor_pin_retains_full_resolution_edits"] = True
                    assert controller._editor is None
                    record["editor_opened_before_output"] = True
                else:
                    record["delivered_once"] = True
                cases.append(record)
            finally:
                if not session._closed:
                    session.close()
                if controller._editor is not None:
                    controller._editor.close()
                for pin in list(controller._pins):
                    pin.close()
                QThreadPool.globalInstance().waitForDone(5000)
                app.processEvents()
    finally:
        delivery.copy_image_to_clipboard = original_copy
    return cases


def _check(path):
    from PIL import Image, ImageChops
    from PySide6.QtCore import QCoreApplication, QEvent, QObject, QUrl
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from core.config import DEFAULT_CONFIG
    from core.version import APP_VERSION
    from ui.screenshot_registration import RegistrationStitcher
    from ui.screenshot_resource_check import memory
    from ui.settings_window import SettingsWindowController
    app = QApplication.instance() or QApplication([])
    rows = [memory("before_scroll")]
    children = []
    for cycle in range(3):
        page = Image.effect_noise((1200, 4000), 50).convert("RGB")
        stitch = RegistrationStitcher(page.crop((0, 0, 1200, 800)), isolated=True)
        try:
            for offset in (137, 347, 650, 1000):
                stitch.append(page.crop((0, offset, 1200, offset + 800)))
            out = stitch.render()
            assert out.size == (1200, 1800)
            assert ImageChops.difference(out, page.crop((0, 0, 1200, 1800))).getbbox() is None
            process = stitch._compute.process
            assert process is not None and process.poll() is None
            children.append(process.pid)
            rows.append(memory(f"scroll{cycle+1}_parent_while_child_active"))
        finally:
            stitch.close()
        process.wait(timeout=5)
        del stitch, page, out, process
        gc.collect()
        rows.append(memory(f"scroll{cycle+1}_parent_after_child_exit"))
    assert all(name not in sys.modules for name in ("numpy", "cv2"))
    from core.scroll_compute import ScrollComputeClient, _write_all
    detached = ScrollComputeClient()
    process = detached._start()
    try:
        process.stdout.close()
        frame = Image.effect_noise((320, 800), 50).convert("RGB")
        _write_all(process.stdin, b'{"method":"register","width":320,"height":600}\n')
        _write_all(process.stdin, frame.crop((0, 0, 320, 600)).tobytes())
        _write_all(process.stdin, frame.crop((0, 137, 320, 737)).tobytes())
        process.stdin.close()
        exit_code = process.wait(timeout=15)
        assert exit_code == 0, f"Closed parent pipe returned exit code {exit_code}"
    finally:
        detached.close()
    finish_cases = _check_scroll_finish(app)
    editor_cases = _check_scroll_finish(app, editing=True)
    # Import UI provider types, but NEVER call the application's main()/Engine().
    from main_qml import AppIconProvider, SystemIconProvider, UiState, ROOT
    from ui import backend as module
    from ui.locale_manager import LocaleManager
    patched = {}
    replacements = {
        "load_config": lambda: copy.deepcopy(DEFAULT_CONFIG), "save_config": lambda cfg: None,
        "supports_login_startup": lambda: False,
    }
    backend_patches = {name: lambda *args, **kwargs: None for name in (
        "_configureUpdateChecks", "_consumeUpdateResultMarker",
        "_cleanupStaleUpdatePreparation", "refreshSpeechMicrophones")}
    for name, value in replacements.items():
        patched[name] = getattr(module, name)
        setattr(module, name, value)
    original_methods = {name: getattr(module.Backend, name) for name in backend_patches}
    for name, value in backend_patches.items():
        setattr(module.Backend, name, value)
    try:
        backend = module.Backend()
        locale, state = LocaleManager("zh_CN"), UiState(app)
        warnings = []
        def factory():
            engine = QQmlApplicationEngine()
            engine.warnings.connect(lambda messages: warnings.extend(m.toString() for m in messages))
            engine.addImageProvider("appicons", AppIconProvider(ROOT))
            engine.addImageProvider("systemicons", SystemIconProvider())
            for key, value in {"backend": backend, "uiState": state, "lm": locale,
                "launchHidden": True, "appVersion": APP_VERSION, "appBuildMode": "self-check",
                "appCommit": "local-test", "appLaunchPath": ROOT}.items():
                engine.rootContext().setContextProperty(key, value)
            engine.load(QUrl.fromLocalFile(str(Path(ROOT) / "ui/qml/Main.qml")))
            return engine
        def drain():
            for _ in range(3):
                app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                gc.collect()
        controller = SettingsWindowController(factory)
        assert controller.engine is None
        rows.append(memory("settings_not_created"))
        window = controller.ensure()
        window.showNormal()
        drain()
        window.setProperty("currentPage", 4)
        drain()
        words = window.findChild(QObject, "speechVocabularyDraft")
        assert words is not None
        words.setProperty("text", "未保存词表测试")
        window.hide()
        drain()
        assert not controller.release_if_safe(), "Unsaved vocabulary must survive"
        assert controller.ensure() is window
        backend.setSpeechVocabulary("未保存词表测试", "")
        drain()
        assert window.property("canReleaseForBackground")
        rows.append(memory("settings_visited_voice"))
        for cycle in range(3):
            window.setProperty("width", 1180)
            window.hide()
            assert controller.release_if_safe()
            drain()
            assert controller.engine is None
            rows.append(memory(f"settings{cycle+1}_released"))
            window = controller.ensure()
            window.showNormal()
            drain()
            assert window.width() == 1180 and window.property("currentPage") == 4
            words = window.findChild(QObject, "speechVocabularyDraft")
            assert words.property("text") == "未保存词表测试"
        controller.shutdown()
        drain()
        assert not warnings, warnings
    finally:
        for name, value in patched.items():
            setattr(module, name, value)
        for name, value in original_methods.items():
            setattr(module.Backend, name, value)
    report = {"ok": True, "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
        "scroll_cycles": 3, "scroll_child_pids": children, "all_scroll_children_exited": True,
        "helper_exits_if_parent_pipe_closes": True,
        "checkmark_after_unchanged_pending_frame": finish_cases,
        "long_capture_editor_after_finish": editor_cases,
        "numpy_opencv_absent_from_parent": True, "scroll_output_exact": True,
        "qml_lazy_start": True, "qml_release_recreate_cycles": 3, "unsaved_vocabulary_preserved": True,
        "page_and_geometry_restored": True, "qml_warnings": warnings, "memory": rows,
        "memory_is_parent_only_not_parent_plus_child": True, "idle_release_called_directly_in_check": True,
        "production_idle_grace_ms": SettingsWindowController.IDLE_MS,
        "user_configuration_used": False, "startup_synchronization_disabled": True,
        "synthetic_only": True, "desktop_captured": False, "microphone_opened": False,
        "system_clipboard_changed": False}
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def run_check(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    try:
        return _check(path)
    except Exception as error:
        import traceback
        Path(path).write_text(json.dumps({"ok": False, "error_type": type(error).__name__,
            "detail": str(error), "traceback": traceback.format_exc()}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        return 1
