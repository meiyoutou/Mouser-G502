import unittest
from unittest.mock import patch

from PIL import Image

from ui.windows_screenshot import (
    IntRect,
    MonitorMap,
    VirtualCapture,
    WindowsScreenshotController,
    build_monitor_maps,
    capture_virtual_desktop,
    crop_logical_region,
)
from ui.screenshot_common import SCREENSHOT_FULL_FILE


class WindowsScreenshotGeometryTests(unittest.TestCase):
    def test_build_monitor_maps_pairs_rectangles_spatially(self):
        logical = [IntRect(100, 0, 200, 100), IntRect(-100, 0, 0, 100)]
        physical = [IntRect(0, 0, 200, 200), IntRect(-200, 0, 0, 200)]

        maps = build_monitor_maps(logical, physical)

        self.assertEqual(maps[0], MonitorMap(IntRect(-100, 0, 0, 100), IntRect(-200, 0, 0, 200)))
        self.assertEqual(maps[1], MonitorMap(IntRect(100, 0, 200, 100), IntRect(0, 0, 200, 200)))

    def test_crop_logical_region_scales_single_monitor_selection(self):
        image = Image.new("RGB", (200, 100), (10, 20, 30))
        capture = VirtualCapture(
            image=image,
            physical_rect=IntRect(0, 0, 200, 100),
            monitor_maps=(MonitorMap(IntRect(0, 0, 100, 50), IntRect(0, 0, 200, 100)),),
        )

        cropped = crop_logical_region(capture, IntRect(10, 5, 20, 15))

        self.assertEqual(cropped.size, (20, 20))

    def test_crop_logical_region_handles_negative_monitor_origin(self):
        image = Image.new("RGB", (100, 100), (50, 60, 70))
        capture = VirtualCapture(
            image=image,
            physical_rect=IntRect(-100, 0, 0, 100),
            monitor_maps=(MonitorMap(IntRect(-50, 0, 0, 50), IntRect(-100, 0, 0, 100)),),
        )

        cropped = crop_logical_region(capture, IntRect(-25, 10, 0, 20))

        self.assertEqual(cropped.size, (50, 20))

    def test_capture_virtual_desktop_composes_per_monitor_images(self):
        maps = (
            MonitorMap(IntRect(-100, 0, 0, 50), IntRect(-100, 0, 0, 50)),
            MonitorMap(IntRect(0, 0, 100, 50), IntRect(0, 0, 100, 50)),
        )

        def fake_grab(*, bbox, **_kwargs):
            color = (255, 0, 0) if bbox[0] < 0 else (0, 0, 255)
            return Image.new("RGB", (bbox[2] - bbox[0], bbox[3] - bbox[1]), color)

        capture = capture_virtual_desktop(maps, grab=fake_grab)

        self.assertEqual(capture.image.size, (200, 50))
        self.assertEqual(capture.image.getpixel((25, 10)), (255, 0, 0))
        self.assertEqual(capture.image.getpixel((175, 10)), (0, 0, 255))

    def test_file_delivery_uses_injected_path_factory(self):
        statuses = []
        target = "/tmp/custom-windows-shot.png"
        controller = WindowsScreenshotController(
            status_callback=statuses.append,
            path_factory=lambda: target,
        )

        with patch("ui.windows_screenshot.save_image_to_file", return_value=target) as save_image:
            image = Image.new("RGBA", (2, 2))
            controller._deliver_image(image, SCREENSHOT_FULL_FILE)

        save_image.assert_called_once_with(image, target)
        self.assertEqual(statuses, [f"Screenshot saved to {target}"])

    def test_request_defers_capture_until_after_overlay_can_hide(self):
        statuses = []
        target = "/tmp/deferred-windows-shot.png"
        capture = VirtualCapture(
            image=Image.new("RGB", (2, 2)),
            physical_rect=IntRect(0, 0, 2, 2),
            monitor_maps=(MonitorMap(IntRect(0, 0, 2, 2), IntRect(0, 0, 2, 2)),),
        )
        controller = WindowsScreenshotController(
            status_callback=statuses.append,
            path_factory=lambda: target,
            settle_delay_ms=123,
        )

        with (
            patch("ui.windows_screenshot.QTimer.singleShot") as single_shot,
            patch("ui.windows_screenshot.capture_virtual_desktop", return_value=capture) as grab,
            patch("ui.windows_screenshot.save_image_to_file", return_value=target),
        ):
            controller._handle_request(SCREENSHOT_FULL_FILE)

            grab.assert_not_called()
            single_shot.assert_called_once()
            delay_ms, callback = single_shot.call_args.args
            self.assertEqual(delay_ms, 123)

            callback()

        grab.assert_called_once()
        self.assertEqual(statuses, [f"Screenshot saved to {target}"])

    def test_second_request_is_rejected_while_deferred_capture_pending(self):
        statuses = []
        controller = WindowsScreenshotController(
            status_callback=statuses.append,
            settle_delay_ms=123,
        )

        with patch("ui.windows_screenshot.QTimer.singleShot") as single_shot:
            controller._handle_request(SCREENSHOT_FULL_FILE)
            controller._handle_request(SCREENSHOT_FULL_FILE)

        single_shot.assert_called_once()
        self.assertEqual(statuses, ["Finish the current screenshot selection first"])


if __name__ == "__main__":
    unittest.main()
