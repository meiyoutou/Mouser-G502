import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtWidgets import QApplication

    from ui.screenshot_overlay import IntRect, RegionSelectionOverlay
except ImportError:  # pragma: no cover - exercised on developer machines without Qt
    QPoint = QRect = QApplication = None
    IntRect = RegionSelectionOverlay = None


@unittest.skipIf(RegionSelectionOverlay is None, "PySide6 is not installed")
class RegionSelectionOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_preview_rect_uses_actual_overlay_window_coordinates(self):
        overlay = RegionSelectionOverlay(IntRect(-100, 0, 100, 100))
        overlay.setGeometry(QRect(-80, 10, 180, 80))
        overlay._start = QPoint(-60, 20)
        overlay._current = QPoint(40, 50)

        self.assertEqual(
            overlay._selection_global_rect(),
            QRect(QPoint(-60, 20), QPoint(40, 50)).normalized(),
        )
        self.assertEqual(
            overlay._selection_local_rect(),
            QRect(QPoint(20, 10), QPoint(120, 40)).normalized(),
        )


if __name__ == "__main__":
    unittest.main()
