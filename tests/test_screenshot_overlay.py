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

    def test_multi_screen_overlay_paints_per_screen_panes(self):
        overlay = RegionSelectionOverlay(
            IntRect(-100, 0, 300, 100),
            screen_rects=(IntRect(-100, 0, 0, 100), IntRect(0, 0, 300, 100)),
        )
        overlay._start = QPoint(-50, 20)
        overlay._current = QPoint(120, 60)

        self.assertEqual(len(overlay._panes), 2)
        self.assertEqual(
            overlay._selection_local_rect_for(overlay._panes[0]),
            QRect(QPoint(50, 20), QPoint(220, 60)).normalized(),
        )
        self.assertEqual(
            overlay._selection_local_rect_for(overlay._panes[1]),
            QRect(QPoint(-50, 20), QPoint(120, 60)).normalized(),
        )

    def test_multi_screen_overlay_has_no_initial_selection(self):
        overlay = RegionSelectionOverlay(
            IntRect(-100, 0, 300, 100),
            screen_rects=(IntRect(-100, 0, 0, 100), IntRect(0, 0, 300, 100)),
        )

        self.assertIsNone(overlay._selection_global_rect())
        for pane in overlay._panes:
            self.assertIsNone(overlay._selection_local_rect_for(pane))


if __name__ == "__main__":
    unittest.main()
