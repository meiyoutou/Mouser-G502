import unittest
from pathlib import Path

from ui.locale_manager import LocaleManager, _TRANSLATIONS


class LocaleManagerTranslationTests(unittest.TestCase):
    def test_key_capture_error_messages_exist_in_all_locales(self):
        required = {
            "key_capture.error.unsupported_key",
            "key_capture.error.unknown_key",
            "key_capture.error.duplicate_key",
            "key_capture.error.multiple_main_keys",
            "key_capture.error.missing_main_key",
            "key_capture.error.empty_segment",
            "key_capture.error.unsupported",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_g502_layout_strings_exist_in_all_locales(self):
        required = {
            "common.list_separator",
            "layout_note.g502_11",
            "layout_note.g502_x",
            "mouse.physical_controls_prefix",
            "mouse.mappable_controls",
            "mouse.hscroll_left_prefix",
            "mouse.hscroll_right_prefix",
            "mouse.legend_mappable",
            "mouse.legend_conditional",
            "mouse.legend_readonly",
            "mouse.hotspot.conditional",
            "mouse.hotspot.readonly",
            "mouse.hotspot.readonly_primary",
            "mouse.hotspot.readonly_mechanical",
            "mouse.hotspot.readonly_scroll",
            "mouse.gesture",
            "mouse.gesture_swipe",
            "mouse.conditional_button_action_hint",
            "mouse.start_g502_raw_hid",
            "mouse.g502_raw_hid_desc",
            "mouse.g502_onboard_title",
            "mouse.g502_onboard_desc",
            "mouse.g502_onboard_last_backup",
            "mouse.g502_onboard_backup",
            "mouse.g502_onboard_unlock",
            "mouse.g502_onboard_restore",
            "mouse.copy_device_info",
            "mouse.device_info_copied",
            "mouse.no_device_connected",
            "mouse.remove",
            "mouse.dpi_presets",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_g502_button_and_action_labels_are_localized(self):
        g502_button_labels = (
            "Left click",
            "Right click",
            "Wheel click",
            "Back thumb button",
            "Forward thumb button",
            "DPI Shift / sniper",
            "DPI down",
            "DPI up",
            "Wheel tilt left",
            "Wheel tilt right",
            "Scroll up",
            "Scroll down",
            "Profile cycle",
            "Wheel mode shift (mechanical)",
        )
        action_labels = (
            "Cycle DPI Presets",
            "Actions Ring",
            "Gesture Swipe",
            "Left Click",
            "Right Click",
            "Middle Click",
            "Back (Mouse Button 4)",
            "Forward (Mouse Button 5)",
        )

        for locale in ("zh_CN", "zh_TW"):
            manager = LocaleManager(locale)
            with self.subTest(locale=locale):
                for label in g502_button_labels:
                    self.assertNotEqual(manager.trButton(label), label)
                    self.assertNotIn("Mouse Button", manager.trButton(label))
                for label in action_labels:
                    self.assertNotEqual(manager.trAction(label), label)
                self.assertNotEqual(manager.trCategory("Mouse"), "Mouse")

    def test_key_capture_recorder_strings_exist_in_all_locales(self):
        required = {
            "key_capture.placeholder_recording",
            "key_capture.record_hint",
            "key_capture.type_hint",
            "key_capture.mode_type",
            "key_capture.mode_record",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_key_capture_help_text_covers_the_supported_function_keys(self):
        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertIn("f24", strings["key_capture.valid_keys"])

    def test_update_install_messages_exist_in_all_locales(self):
        required = {
            "scroll.update_idle",
            "scroll.update_available",
            "scroll.update_checking",
            "scroll.update_downloading",
            "scroll.update_verifying",
            "scroll.update_ready",
            "scroll.update_installing",
            "scroll.update_installed",
            "scroll.update_installed_version",
            "scroll.update_cancelled",
            "scroll.update_manual",
            "scroll.update_manual_windows",
            "scroll.update_manual_macos",
            "scroll.update_manual_linux",
            "scroll.update_no_asset",
            "scroll.update_error",
            "scroll.update_error_check_first",
            "scroll.update_error_network_error",
            "scroll.update_error_metadata_missing",
            "scroll.update_error_metadata_invalid",
            "scroll.update_error_permission_denied",
            "scroll.update_error_file_error",
            "scroll.update_error_install_failed",
            "scroll.update_error_sha256_mismatch",
            "scroll.update_error_size_mismatch",
            "scroll.update_error_expired_metadata",
            "scroll.update_error_older_build",
            "scroll.update_check",
            "scroll.update_download",
            "scroll.update_cancel",
            "scroll.update_verify",
            "scroll.update_install",
            "scroll.update_open_release",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_config_backup_strings_exist_in_all_locales(self):
        required = {
            "scroll.config_backup",
            "scroll.config_backup_desc",
            "scroll.config_backup_steps",
            "scroll.config_export",
            "scroll.config_import",
            "scroll.config_open_folder",
            "status.config_exported",
            "status.config_imported",
            "status.config_export_failed",
            "status.config_import_failed",
            "status.config_import_wrong_zip",
            "status.config_folder_missing",
            "dialog.export_config",
            "dialog.import_config",
            "dialog.config_backup_filter",
            "dialog.config_restore_filter",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_actions_ring_scope_and_status_toasts_exist_in_all_locales(self):
        required = {
            "ring.scope_title",
            "ring.scope_global_desc",
            "ring.scope_perapp_desc",
            "ring.scope_app",
            "status.saved",
            "status.profile_exists",
            "status.profile_created",
            "status.profile_deleted",
            "status.profile_active",
            "status.connect_device_first",
            "status.unknown_layout",
            "status.layout_applied",
            "status.layout_auto",
            "status.g502_onboard_backup_saved",
            "status.g502_onboard_unlocked",
            "status.g502_onboard_restored",
            "status.g502_onboard_failed",
            "dialog.choose_screenshot_folder",
            "dialog.select_application",
            "accessibility.open_named",
            "debug.mode_enabled",
            "debug.mode_disabled",
            "debug.events_enabled",
            "debug.events_paused",
            "debug.g502_onboard_backup_path",
            "debug.g502_onboard_unlock_mapping",
            "debug.g502_onboard_failed_detail",
            "debug.mouse_connected",
            "debug.mouse_disconnected",
            "error.g502_onboard.no_backup_file",
            "error.g502_onboard.no_supported_interface",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_battery_and_mouse_reconnect_strings_exist_in_all_locales(self):
        required = {
            "mouse.battery_refresh",
            "mouse.battery_just_now",
            "mouse.battery_minutes_ago",
            "mouse.battery_last_prefix",
            "mouse.battery_unknown",
            "mouse.reconnect_listener",
            "status.battery_refreshing",
            "status.battery_refreshed",
            "status.battery_refresh_failed",
            "status.mouse_reconnecting",
            "status.mouse_reconnect_requested",
            "status.mouse_reconnect_failed",
            "status.mouse_listener_restarting",
        }

        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                self.assertTrue(required.issubset(strings))
                for key in required:
                    self.assertTrue(strings[key].strip())

    def test_actions_ring_overlay_short_labels_are_localized(self):
        from core.config import _default_actions_ring_slots
        from ui.actions_ring_overlay import RING_LABEL_TRANSLATIONS

        for locale in ("zh_CN", "zh_TW"):
            labels = RING_LABEL_TRANSLATIONS[locale]
            with self.subTest(locale=locale):
                for platform in ("win32", "darwin", "linux"):
                    for slot in _default_actions_ring_slots(platform):
                        self.assertIn(slot, labels)
                        self.assertTrue(labels[slot].strip())

    def test_language_picker_syncs_backend_language(self):
        qml_path = Path(__file__).resolve().parents[1] / "ui" / "qml" / "ScrollPage.qml"
        source = qml_path.read_text(encoding="utf-8")

        self.assertIn("function selectLanguage(code)", source)
        self.assertIn("lm.setLanguage(code)", source)
        self.assertIn("backend.setLanguage(code)", source)
        self.assertIn("onClicked: scrollPage.selectLanguage(modelData.code)", source)
        self.assertIn(
            "Accessible.onPressAction: scrollPage.selectLanguage(modelData.code)",
            source,
        )


class AccessibilityLocaleTests(unittest.TestCase):
    """The QML accessibility labels added in this batch reference these
    keys. Missing them in a non-English locale silently regresses to a
    KeyError-as-empty-string in the QML lookup ``s[...]``, which leaves
    screen readers reading nothing for an interactive control.
    """

    REQUIRED_KEYS = frozenset({
        "dialog.close",
        "scroll.ignore_trackpad",
        "scroll.ignore_trackpad_desc",
        "scroll.smart_shift",
    })
    ENGLISH_VALUES = frozenset({
        "Close",
        "Ignore trackpad",
        "Only respond to mouse events, not trackpad or Magic Mouse",
    })

    def test_required_accessibility_keys_present_in_all_locales(self):
        for locale, strings in _TRANSLATIONS.items():
            with self.subTest(locale=locale):
                missing = self.REQUIRED_KEYS - strings.keys()
                self.assertFalse(missing, f"{locale} missing keys: {missing}")
                for key in self.REQUIRED_KEYS:
                    self.assertTrue(
                        strings[key].strip(),
                        f"{locale}.{key} is blank",
                    )

    def test_chinese_locales_do_not_passthrough_english(self):
        """Trackpad strings used to ship English text in the zh_CN and
        zh_TW maps. Pin that they are now actually localized."""
        for locale in ("zh_CN", "zh_TW"):
            with self.subTest(locale=locale):
                for key in (
                    "scroll.ignore_trackpad",
                    "scroll.ignore_trackpad_desc",
                ):
                    self.assertNotIn(
                        _TRANSLATIONS[locale][key],
                        self.ENGLISH_VALUES,
                        f"{locale}.{key} still ships English",
                    )
                self.assertNotEqual(
                    _TRANSLATIONS[locale]["scroll.smart_shift"],
                    "SmartShift",
                    f"{locale}.scroll.smart_shift still ships English",
                )


if __name__ == "__main__":
    unittest.main()
