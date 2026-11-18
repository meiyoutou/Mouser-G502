"""Own a lazy settings QML engine independently of mouse/voice/capture services."""
from PySide6.QtCore import QObject, QRect, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QWindow


class SettingsWindowController(QObject):
    visibilityChanged = Signal(object)
    windowCreated = Signal(object)
    released = Signal()
    IDLE_MS = 60_000

    def __init__(self, factory, parent=None):
        super().__init__(parent)
        self.factory = factory
        self.engine = self.window = None
        self._state = {}
        self._shutdown = False
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.setInterval(self.IDLE_MS)
        self._idle.timeout.connect(self.release_if_safe)

    def ensure(self):
        if self._shutdown:
            return None
        self._idle.stop()
        if self.window is None:
            engine = self.factory()
            roots = engine.rootObjects()
            if not roots:
                engine.deleteLater()
                raise RuntimeError("Failed to load settings QML")
            self.engine, self.window = engine, roots[0]
            for name, value in self._state.items():
                self.window.setProperty(name, value)
            self._keep_window_reachable(self.window)
            self.window.visibilityChanged.connect(self._visibility_changed)
            self.windowCreated.emit(self.window)
        return self.window

    @staticmethod
    def _keep_window_reachable(window):
        # A monitor may have been disconnected while the settings UI was
        # released. Do not recreate it invisibly at the removed monitor's x/y.
        screens = QGuiApplication.screens()
        if not screens:
            return
        title = QRect(window.x(), window.y(), min(200, window.width()), 40)
        if any(screen.availableGeometry().intersected(title).width() >= 80
               and screen.availableGeometry().intersected(title).height() >= 20
               for screen in screens):
            return
        area = (QGuiApplication.primaryScreen() or screens[0]).availableGeometry()
        window.setPosition(area.x() + max(0, (area.width() - window.width()) // 2),
                           area.y() + max(0, (area.height() - window.height()) // 2))

    def show(self):
        window = self.ensure()
        if window is not None:
            window.showNormal()
            window.raise_()
            window.requestActivate()
        return window

    def hide(self):
        if self.window is not None:
            self.window.hide()

    def _visibility_changed(self, visibility):
        self.visibilityChanged.emit(visibility)
        if visibility == QWindow.Visibility.Hidden:
            self._idle.start()
        else:
            self._idle.stop()  # Minimized windows retain their native taskbar surface.

    def release_if_safe(self):
        window = self.window
        if window is None or window.isVisible():
            return False
        if not window.property("canReleaseForBackground"):
            self._idle.start()  # Do not discard open capture dialogs/unsaved vocabulary.
            return False
        self._state = {name: window.property(name) for name in
                       ("width", "height", "x", "y", "currentPage")}
        engine = self.engine
        self.window = self.engine = None
        window.visibilityChanged.disconnect(self._visibility_changed)
        window.deleteLater()
        engine.deleteLater()
        self.released.emit()
        return True

    def shutdown(self):
        self._shutdown = True
        self._idle.stop()
        if self.engine is not None:
            self.window.deleteLater()
            self.engine.deleteLater()
            self.window = self.engine = None
