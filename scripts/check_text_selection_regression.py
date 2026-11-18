"""Local text-selection regression; isolated settings, no background update network."""
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT = Path(sys.argv[1]).resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
os.environ.update(QT_QPA_PLATFORM="offscreen", QT_QPA_FONTDIR=r"C:\Windows\Fonts",
                  APPDATA=str(OUTPUT / "isolated/roaming"),
                  LOCALAPPDATA=str(OUTPUT / "isolated/local"),
                  MOUSER_SPEECH_MODEL_DIR=str(OUTPUT / "isolated/speech_models"))
MODULES = (
    "text_selection", "screenshot_live",
    "screenshot_session", "screenshot_editor", "screenshot_pin", "screenshot_phase2",
    "screenshot_autoscroll", "screenshot_scroll_region", "screenshot_motion",
    "screenshot_registration", "screenshot_diagnostics", "windows_screenshot_helpers",
    "screenshot_common", "screenshot_overlay", "config", "backend", "actions_ring",
    "low_sensitivity", "gesture_recognizer", "engine", "button_gestures",
    "speech_components", "speech_models", "speech_process", "speech_session",
    "speech_ui", "optional_speech", "version_metadata", "spec_coverage", "startup",
    "single_instance", "update_installer", "updater", "resource_limits", "log_setup",
    "scroll_compute", "settings_window", "main_qml_shortcuts",
    "hid_gesture", "logi_discovery", "hidpp_transaction", "hid_inventory",
    "hid_diagnostics", "logi_devices", "mouse_device_header", "device_layouts",
)
HOST_PATH_LIMITATIONS = {
    "tests.test_startup.ApplyLoginStartupLinuxTests.test_linux_source_checkout_prefers_project_venv_python",
    "tests.test_startup.ApplyLoginStartupMacTests.test_macos_plist_path_uses_canonical_launch_agent_name",
}


def flatten(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from flatten(test)
        else:
            yield test


tests = list(flatten(unittest.defaultTestLoader.loadTestsFromNames(
    ["tests.test_" + name for name in MODULES])))
selected = unittest.TestSuite(test for test in tests if test.id() not in HOST_PATH_LIMITATIONS)
original_run = threading.Thread.run
def thread_run(thread):
    if thread.name != "MouserUpdateCheck":
        return original_run(thread)

with patch("ui.backend.Backend._runUpdateCheck", return_value=None), \
        patch.object(threading.Thread, "run", thread_run):
    result = unittest.TextTestRunner(verbosity=1).run(selected)
report = {"tests_run": result.testsRun, "skipped": len(result.skipped),
          "failures": len(result.failures), "errors": len(result.errors),
          "ok": result.wasSuccessful(), "excluded_windows_host_path_tests": sorted(HOST_PATH_LIMITATIONS),
          "background_update_network_disabled": True, "user_configuration_used": False}
(OUTPUT / "regression-summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(0 if result.wasSuccessful() else 1)
