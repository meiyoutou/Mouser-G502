import unittest

from core.logi_devices import build_device_capability_inventory


class HidInventoryDiagnosticsTests(unittest.TestCase):
    def test_inventory_adds_reprog_unavailable_diagnostic_without_controls(self):
        inventory = build_device_capability_inventory([])

        diagnostics = inventory.to_dict()["diagnostics"]
        self.assertIn(
            {
                "code": "reprog_controls_unavailable",
                "severity": "info",
                "message": "REPROG_CONTROLS_V4 was not discovered; runtime remap evidence is limited.",
            },
            diagnostics,
        )

    def test_explicit_diagnostics_are_serialized(self):
        inventory = build_device_capability_inventory(
            [],
            diagnostics=[
                {
                    "code": "missing_permissions",
                    "severity": "warning",
                    "message": "hidraw path is not readable by this user",
                },
                "unsupported receiver",
            ],
        )

        diagnostics = inventory.to_dict()["diagnostics"]
        self.assertIn(
            {
                "code": "missing_permissions",
                "severity": "warning",
                "message": "hidraw path is not readable by this user",
            },
            diagnostics,
        )
        self.assertIn(
            {
                "code": "note",
                "severity": "info",
                "message": "unsupported receiver",
            },
            diagnostics,
        )


if __name__ == "__main__":
    unittest.main()
