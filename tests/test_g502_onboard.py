import unittest
import json
import tempfile
from pathlib import Path

from core import g502_onboard


class G502OnboardProfileTests(unittest.TestCase):
    def _sample_sector(self):
        data = bytearray([0xFF] * 256)
        data[0:13] = bytes.fromhex("01 02 00 90 01 20 03 40 06 60 09 00 00")
        data[13:32] = bytes.fromhex("FF FF FF FF 00 FF FF FF FF FF FF FF FF FF FF FF FF FF FF")
        buttons = [
            bytes.fromhex("80 01 00 01"),
            bytes.fromhex("80 01 00 02"),
            bytes.fromhex("80 01 00 04"),
            bytes.fromhex("80 01 00 08"),
            bytes.fromhex("80 01 00 10"),
            bytes.fromhex("90 07 FF FF"),
            bytes.fromhex("90 04 FF FF"),
            bytes.fromhex("90 03 FF FF"),
            bytes.fromhex("90 0A FF FF"),
            bytes.fromhex("90 02 FF FF"),
            bytes.fromhex("90 01 FF FF"),
        ]
        offset = g502_onboard.PROFILE_BUTTON_OFFSET
        for i, binding in enumerate(buttons):
            data[offset + i * 4:offset + i * 4 + 4] = binding
        crc = g502_onboard.crc16_ccitt(data[:-2])
        data[-2] = crc >> 8
        data[-1] = crc & 0xFF
        return bytes(data)

    def test_descriptor_parses_g502_hero_shape(self):
        desc = g502_onboard.ProfileDescriptor.from_bytes(
            bytes.fromhex("01 02 01 05 05 0b 10 01 00 0a 01 00 00 00 00 00")
        )

        self.assertEqual(desc.profile_count, 5)
        self.assertEqual(desc.button_count, 11)
        self.assertEqual(desc.sector_count, 16)
        self.assertEqual(desc.sector_size, 256)
        desc.validate_for_g502_hero()

    def test_mouse_button_binding_uses_big_endian_bitmask(self):
        self.assertEqual(g502_onboard.mouse_button_binding(6), bytes.fromhex("80 01 00 20"))
        self.assertEqual(g502_onboard.mouse_button_binding(9), bytes.fromhex("80 01 01 00"))
        self.assertEqual(g502_onboard.mouse_button_binding(11), bytes.fromhex("80 01 04 00"))

    def test_keyboard_key_binding_uses_hid_usage(self):
        self.assertEqual(g502_onboard.keyboard_key_binding(0x68), bytes.fromhex("80 02 00 68"))
        self.assertEqual(g502_onboard.keyboard_key_binding(0x69), bytes.fromhex("80 02 00 69"))
        self.assertEqual(g502_onboard.keyboard_key_binding(0x6A), bytes.fromhex("80 02 00 6A"))
        self.assertEqual(g502_onboard.keyboard_key_binding(0x6B), bytes.fromhex("80 02 00 6B"))

    def test_unlock_scans_special_bindings_at_offset_32_and_updates_crc(self):
        original = self._sample_sector()
        unlocked, changes = g502_onboard._apply_unlock_to_sector(original, 11)

        self.assertEqual(
            [c["button_key"] for c in changes],
            [
                "g502_dpi_shift",
                "g502_dpi_down",
                "g502_dpi_up",
                "g502_profile_cycle",
            ],
        )
        off = g502_onboard.PROFILE_BUTTON_OFFSET
        self.assertEqual(unlocked[off + 5 * 4:off + 5 * 4 + 4], bytes.fromhex("80 02 00 68"))
        self.assertEqual(unlocked[off + 6 * 4:off + 6 * 4 + 4], bytes.fromhex("80 02 00 69"))
        self.assertEqual(unlocked[off + 7 * 4:off + 7 * 4 + 4], bytes.fromhex("80 02 00 6A"))
        self.assertEqual(unlocked[off + 8 * 4:off + 8 * 4 + 4], bytes.fromhex("80 02 00 6B"))
        self.assertEqual(unlocked[off + 9 * 4:off + 9 * 4 + 4], bytes.fromhex("90 02 FF FF"))
        self.assertEqual(unlocked[off + 10 * 4:off + 10 * 4 + 4], bytes.fromhex("90 01 FF FF"))
        self.assertTrue(g502_onboard._sector_crc_info(unlocked)["valid"])
        self.assertNotEqual(original[-2:], unlocked[-2:])

    def test_unlock_migrates_first_mouse_button_unlock_to_f13_f16(self):
        original = bytearray(self._sample_sector())
        off = g502_onboard.PROFILE_BUTTON_OFFSET
        original[off + 5 * 4:off + 5 * 4 + 4] = bytes.fromhex("80 01 00 20")
        original[off + 6 * 4:off + 6 * 4 + 4] = bytes.fromhex("80 01 01 00")
        original[off + 7 * 4:off + 7 * 4 + 4] = bytes.fromhex("80 01 02 00")
        original[off + 8 * 4:off + 8 * 4 + 4] = bytes.fromhex("80 01 04 00")
        crc = g502_onboard.crc16_ccitt(original[:-2])
        original[-2] = crc >> 8
        original[-1] = crc & 0xFF

        unlocked, changes = g502_onboard._apply_unlock_to_sector(bytes(original), 11)

        self.assertEqual([c["target_key"] for c in changes], ["F13", "F14", "F15", "F16"])
        self.assertEqual(unlocked[off + 5 * 4:off + 5 * 4 + 4], bytes.fromhex("80 02 00 68"))
        self.assertEqual(unlocked[off + 6 * 4:off + 6 * 4 + 4], bytes.fromhex("80 02 00 69"))
        self.assertEqual(unlocked[off + 7 * 4:off + 7 * 4 + 4], bytes.fromhex("80 02 00 6A"))
        self.assertEqual(unlocked[off + 8 * 4:off + 8 * 4 + 4], bytes.fromhex("80 02 00 6B"))
        self.assertTrue(g502_onboard._sector_crc_info(unlocked)["valid"])

    def test_unlock_is_noop_when_already_f13_f16(self):
        original = self._sample_sector()
        unlocked, _changes = g502_onboard._apply_unlock_to_sector(original, 11)

        unlocked_again, changes = g502_onboard._apply_unlock_to_sector(unlocked, 11)

        self.assertEqual(changes, [])
        self.assertEqual(unlocked_again, unlocked)

    def test_active_profile_prefers_matching_sector_value(self):
        headers = [
            {"index": 1, "sector": 1, "enabled": 1},
            {"index": 2, "sector": 2, "enabled": 1},
        ]

        self.assertEqual(g502_onboard._resolve_active_sector(2, headers), 2)

    def test_restore_rejects_backup_sector_with_bad_crc(self):
        broken = bytearray(self._sample_sector())
        broken[32] ^= 0x01

        with self.assertRaises(g502_onboard.G502OnboardError):
            g502_onboard._backup_sector_blob("0001", broken.hex(), 256)

    def test_latest_before_unlock_backup_path_prefers_write_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manual = root / "g502_onboard_backup_20260825-153124.json"
            before_unlock = root / "g502_onboard_backup_20260825-153036.json"
            unlocked, _changes = g502_onboard._apply_unlock_to_sector(
                self._sample_sector(),
                11,
            )
            locked_payload = {
                "purpose": "before_unlock",
                "descriptor": {"button_count": 11},
                "active_profile_sector": 1,
                "sectors": {"0001": self._sample_sector().hex()},
            }
            manual.write_text(
                json.dumps({
                    "purpose": "manual_backup",
                    "descriptor": {"button_count": 11},
                    "active_profile_sector": 1,
                    "sectors": {"0001": unlocked.hex()},
                }),
                encoding="utf-8",
            )
            before_unlock.write_text(json.dumps(locked_payload), encoding="utf-8")

            self.assertEqual(
                g502_onboard.latest_before_unlock_backup_path(root),
                before_unlock,
            )

    def test_latest_before_unlock_backup_path_ignores_mistagged_unlocked_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self._sample_sector()
            unlocked, _changes = g502_onboard._apply_unlock_to_sector(original, 11)
            real_before = root / "g502_onboard_backup_20260825-153036.json"
            mistagged_later = root / "g502_onboard_backup_20260825-162046.json"
            common = {
                "purpose": "before_unlock",
                "descriptor": {"button_count": 11},
                "active_profile_sector": 1,
            }
            real_before.write_text(
                json.dumps({**common, "sectors": {"0001": original.hex()}}),
                encoding="utf-8",
            )
            mistagged_later.write_text(
                json.dumps({**common, "sectors": {"0001": unlocked.hex()}}),
                encoding="utf-8",
            )

            self.assertEqual(
                g502_onboard.latest_before_unlock_backup_path(root),
                real_before,
            )

    def test_latest_before_unlock_backup_path_detects_legacy_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = self._sample_sector()
            unlocked, _changes = g502_onboard._apply_unlock_to_sector(original, 11)
            legacy_before = root / "g502_onboard_backup_20260825-153036.json"
            later_unlocked = root / "g502_onboard_backup_20260825-153124.json"
            common = {
                "descriptor": {"button_count": 11},
                "active_profile_sector": 1,
            }
            legacy_before.write_text(
                json.dumps({**common, "sectors": {"0001": original.hex()}}),
                encoding="utf-8",
            )
            later_unlocked.write_text(
                json.dumps({**common, "sectors": {"0001": unlocked.hex()}}),
                encoding="utf-8",
            )

            self.assertEqual(
                g502_onboard.latest_before_unlock_backup_path(root),
                legacy_before,
            )


if __name__ == "__main__":
    unittest.main()
