"""Asynchronous one-shot text selection. No automatic clipboard or image upload."""
import threading

from PySide6.QtCore import QObject, Signal, Qt

from core import text_selection


class TextSelectionController(QObject):
    result = Signal(object)
    status = Signal(str)
    completed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cancelled = threading.Event()
        self.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)

    def start(self, image):
        image, signal, cancelled = image.copy(), self.completed, self.cancelled
        def run():
            try:
                data = text_selection.recognize(image, cancelled=cancelled)
            except Exception as error:
                data = {"error": str(error) if isinstance(error, text_selection.TextSelectionError)
                        else "text_select_failed"}
            try:
                signal.emit(data)
            except RuntimeError:
                pass
        threading.Thread(target=run, name="MouserTextSelection", daemon=True).start()

    def _complete(self, data):
        if self.cancelled.is_set():
            return
        if "error" in data:
            self.status.emit(data["error"])
        else:
            self.result.emit(data)
