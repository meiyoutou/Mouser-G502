import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QWindow
from PySide6.QtWidgets import QApplication

from ui.settings_window import SettingsWindowController


class SettingsWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.created = []
        from PySide6.QtCore import QObject
        def factory():
            window = QWindow()
            window.setProperty("canReleaseForBackground", True)
            window.setProperty("currentPage", 0)
            engine = QObject()
            engine.rootObjects = lambda: [window]
            self.created.append((engine, window))
            return engine
        self.controller = SettingsWindowController(factory)

    def tearDown(self):
        self.controller.shutdown()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_tray_start_is_lazy_and_reopening_reuses_window(self):
        self.assertEqual(self.created, [])
        first = self.controller.ensure()
        self.assertIs(first, self.controller.ensure())
        self.assertEqual(len(self.created), 1)

    def test_release_and_recreate_restores_page_and_geometry(self):
        window = self.controller.ensure()
        window.setWidth(1234)
        window.setProperty("currentPage", 4)
        self.assertTrue(self.controller.release_if_safe())
        self.assertIsNone(self.controller.engine)
        fresh = self.controller.ensure()
        self.assertEqual(fresh.width(), 1234)
        self.assertEqual(fresh.property("currentPage"), 4)
        self.assertEqual(len(self.created), 2)

    def test_unsaved_drafts_or_dialog_block_release(self):
        window = self.controller.ensure()
        window.setProperty("canReleaseForBackground", False)
        self.assertFalse(self.controller.release_if_safe())
        self.assertIs(self.controller.window, window)
        self.assertTrue(self.controller._idle.isActive())
        window.setProperty("canReleaseForBackground", True)
        self.assertTrue(self.controller.release_if_safe())

    def test_visible_window_cannot_be_released(self):
        window = self.controller.ensure()
        window.show()
        self.assertFalse(self.controller.release_if_safe())
        window.hide()
        self.assertTrue(self.controller.release_if_safe())

    def test_failed_qml_load_does_not_prevent_later_retry(self):
        from PySide6.QtCore import QObject
        engine = QObject()
        engine.rootObjects = lambda: []
        with patch.object(self.controller, "factory", return_value=engine):
            with self.assertRaises(RuntimeError):
                self.controller.ensure()
        self.assertIsNotNone(self.controller.ensure())

    def test_shutdown_stops_recreation(self):
        self.controller.ensure()
        self.controller.shutdown()
        self.assertIsNone(self.controller.ensure())
        self.assertFalse(self.controller._idle.isActive())

    def test_removed_monitor_position_is_not_restored_offscreen(self):
        from PySide6.QtGui import QGuiApplication
        window = self.controller.ensure()
        window.setPosition(100000, 100000)
        self.assertTrue(self.controller.release_if_safe())
        recreated = self.controller.ensure()
        area = QGuiApplication.primaryScreen().availableGeometry()
        self.assertTrue(area.contains(recreated.x(), recreated.y()))

    def test_hidden_idle_timer_releases_and_can_reopen(self):
        window = self.controller.ensure()
        self.controller._idle.setInterval(1)
        window.show()
        window.hide()
        deadline = time.monotonic() + 2
        while self.controller.engine is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.assertIsNone(self.controller.engine)
        self.assertIsNotNone(self.controller.ensure())
        self.assertFalse(self.controller._idle.isActive())

    def test_backend_hidden_refresh_stops_only_ui_timer(self):
        from PySide6.QtCore import QTimer
        from ui.backend import Backend
        engine = SimpleNamespace(start=Mock(), stop=Mock())
        backend = SimpleNamespace(_engine=engine, _device_inventory_timer=QTimer(),
            _refreshDeviceInventorySnapshot=Mock(), _emitBatteryAgeTick=Mock())
        with patch("ui.backend.sys.platform", "win32"):
            Backend.set_frontend_visible(backend, True)
            self.assertTrue(backend._device_inventory_timer.isActive())
            backend._refreshDeviceInventorySnapshot.assert_called_once()
            Backend.set_frontend_visible(backend, False)
            self.assertFalse(backend._device_inventory_timer.isActive())
        engine.start.assert_not_called()
        engine.stop.assert_not_called()
