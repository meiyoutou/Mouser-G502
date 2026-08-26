import unittest

from core.logi_devices import build_device_capability_inventory


class ExpandedHidInventoryTests(unittest.TestCase):
    def test_inventory_exposes_identity_features_controls_and_wheels(self):
        inventory = build_device_capability_inventory(
            [
                {
                    "index": 0,
                    "cid": "0x00C4",
                    "task": "0x009D",
                    "flags": "0x0531",
                    "pos": 5,
                    "group": 2,
                    "gmask": "0x0F",
                    "mapped_to": "0x00C4",
                    "mapping_flags": "0x0011",
                },
                {
                    "index": 1,
                    "cid": "0x00D7",
                    "task": "0x00B4",
                    "flags": "0x03A0",
                    "mapped_to": "0x00D7",
                    "mapping_flags": "0x0000",
                },
            ],
            device_identity={
                "product_id": 0xB034,
                "product_name": "MX Master 3S",
                "transport": "Bluetooth",
                "backend": "iokit",
            },
            gesture_cids=(0x00D7,),
            active_gesture_cid=0x00D7,
            gesture_rawxy_enabled=True,
            discovered_features=(
                {"feature_id": 0x1B04, "index": 0x09, "version": 4},
                {"feature_id": 0x2111, "index": 0x0E},
                {"feature_id": 0x2121, "index": 0x10},
                {"feature_id": 0x2201, "index": 0x0D},
            ),
        )

        data = inventory.to_dict()

        self.assertEqual(data["device_identity"]["product_id"], "0xB034")
        self.assertEqual(data["device_identity"]["backend"], "iokit")
        self.assertIn(
            {"feature_id": "0x1B04", "name": "REPROG_CONTROLS_V4", "index": "0x09", "version": 4},
            data["raw_features"],
        )

        controls = {
            control["cid"]: control
            for control in data["reprog_control_details"]
        }
        self.assertTrue(controls["0x00C4"]["divertable"])
        self.assertTrue(controls["0x00C4"]["raw_xy_support"])
        self.assertTrue(controls["0x00C4"]["diverted"])
        self.assertEqual(controls["0x00C4"]["position"], 5)
        self.assertEqual(controls["0x00C4"]["group_mask"], "0x0F")

        wheels = {
            feature["feature_id"]: feature
            for feature in data["wheel_features"]
        }
        self.assertTrue(wheels["0x2111"]["present"])
        self.assertTrue(wheels["0x2121"]["present"])
        self.assertFalse(wheels["0x2150"]["present"])

    def test_feature_dict_shape_is_accepted_for_legacy_dump_inputs(self):
        inventory = build_device_capability_inventory(
            [],
            discovered_features={
                "REPROG_V4 (0x1B04)": "index 0x09",
                "SMART_SHIFT (0x2110)": "index 0x0E",
            },
        )

        data = inventory.to_dict()
        self.assertEqual(data["raw_features"][0]["feature_id"], "0x1B04")
        self.assertTrue(data["wheel_features"][0]["present"])


if __name__ == "__main__":
    unittest.main()
