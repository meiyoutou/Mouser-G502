"""Non-modal optional screenshot installation; never captures or uploads pixels."""
import threading
import sys
import logging

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel,
                              QMessageBox, QProgressBar, QPushButton, QVBoxLayout)
from shiboken6 import isValid

from core import screenshot_components as components
from ui.screenshot_component_locale import text

_dialog = None
_LOG = logging.getLogger(__name__)


class ComponentDialog(QDialog):
    installed = Signal(str)
    _finished = Signal(str, str)
    _phase = Signal(str)
    _progress = Signal(int)

    def __init__(self, locale=None, kind="scroll"):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.locale = locale
        self.busy = False
        self._cancel = threading.Event()
        self._close_pending = False
        self._callbacks = {}
        self.setMinimumWidth(470)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)
        self.description = QLabel()
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        self.choice = QComboBox()
        for item in components.KINDS:
            self.choice.addItem("", item)
        self.choice.setCurrentIndex(components.KINDS.index(kind))
        layout.addWidget(self.choice)
        self.size = QLabel()
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.size)
        layout.addWidget(self.state)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.hide()
        layout.addWidget(self.progress)
        row = QHBoxLayout()
        self.download_button = QPushButton()
        self.import_button = QPushButton()
        self.remove_button = QPushButton()
        for button in (self.download_button, self.import_button, self.remove_button):
            row.addWidget(button)
        layout.addLayout(row)
        self.close_button = QPushButton()
        layout.addWidget(self.close_button)
        self.download_button.clicked.connect(lambda: self.begin())
        self.import_button.clicked.connect(self.import_archive)
        self.remove_button.clicked.connect(self.remove)
        self.close_button.clicked.connect(self.close)
        self.choice.currentIndexChanged.connect(self.refresh)
        self._finished.connect(self.finished_install, Qt.ConnectionType.QueuedConnection)
        self._phase.connect(self.show_phase, Qt.ConnectionType.QueuedConnection)
        self._progress.connect(self.progress.setValue, Qt.ConnectionType.QueuedConnection)
        if hasattr(locale, "languageChanged"):
            locale.languageChanged.connect(self.retranslate)
        self.retranslate()

    @property
    def kind(self):
        return self.choice.currentData()

    def tr_key(self, key, **values):
        return text(key, self.locale, **values)

    def retranslate(self):
        self.setWindowTitle(self.tr_key("title"))
        self.description.setText(self.tr_key("description"))
        for index, kind in enumerate(components.KINDS):
            self.choice.setItemText(index, self.tr_key(kind))
        self.download_button.setText(self.tr_key("download"))
        self.import_button.setText(self.tr_key("import"))
        self.remove_button.setText(self.tr_key("remove"))
        self.close_button.setText(self.tr_key("cancel" if self.busy else "close"))
        self.refresh()

    def refresh(self):
        asset = components.catalog()[self.kind]
        self.size.setText(self.tr_key("sizes", download=asset["size"] / 1048576,
                                     installed=asset["expanded_size"] / 1048576))
        installed = components.checked_directory(self.kind) is not None
        self.choice.setEnabled(not self.busy)
        self.download_button.setEnabled(not self.busy)
        self.import_button.setEnabled(not self.busy)
        self.remove_button.setEnabled(not self.busy and components.directory(self.kind).exists())
        if not self.busy:
            self.state.setText(self.tr_key("installed" if installed else "missing"))

    def show_phase(self, phase):
        self.state.setText(self.tr_key("downloading" if phase == "download" else phase))

    def import_archive(self):
        path, _ = QFileDialog.getOpenFileName(self, self.tr_key("import"), "", "ZIP (*.zip)")
        if path:
            self.begin(path)

    def begin(self, archive=None):
        if self.busy:
            return
        kind = self.kind
        self.busy = True
        self._close_pending = False
        self._cancel.clear()
        self.progress.setValue(0)
        self.progress.show()
        self.retranslate()
        self.show_phase("verify")
        def run():
            try:
                components.install(kind, archive, cancel_event=self._cancel,
                    progress=lambda done, total: self._progress.emit(round(done * 100 / total)),
                    phase=self._phase.emit)
                error = ""
            except Exception as exc:
                error = exc.code if isinstance(exc, components.ComponentError) else "error"
                _LOG.warning("Screenshot component %s installation failed reason=%s", kind, error)
            self._finished.emit(kind, error)
        threading.Thread(target=run, name="MouserScreenshotInstall", daemon=True).start()

    def finished_install(self, kind, error):
        self.busy = False
        self.progress.hide()
        self.retranslate()
        self.state.setText(self.tr_key(error or "success"))
        if not error and not self._close_pending:
            self.installed.emit(kind)
        if self._close_pending:
            self.close()

    def remove(self):
        if self.busy:
            return
        if QMessageBox.question(self, self.tr_key("title"), self.tr_key("confirm_remove")) != QMessageBox.StandardButton.Yes:
            return
        try:
            components.uninstall(self.kind)
            self.refresh()
            self.state.setText(self.tr_key("removed"))
        except Exception as exc:
            self.state.setText(self.tr_key(exc.code if isinstance(exc, components.ComponentError) else "error"))

    def closeEvent(self, event):
        if self.busy:
            self._cancel.set()
            self._close_pending = True
            self.state.setText(self.tr_key("busy_close"))
            event.ignore()
        else:
            self._clear_callbacks()
            super().closeEvent(event)

    def _clear_callbacks(self):
        for callback in list(self._callbacks.values()):
            try:
                self.installed.disconnect(callback)
            except RuntimeError:
                pass
        self._callbacks.clear()

    def reject(self):
        if self.busy:
            self._cancel.set()
            self._close_pending = True
            self.state.setText(self.tr_key("busy_close"))
        else:
            self._clear_callbacks()
            super().reject()


def open_manager(locale=None, kind="scroll"):
    global _dialog
    if _dialog is None or not isValid(_dialog):
        _dialog = ComponentDialog(locale, kind)
    elif not _dialog.busy:
        _dialog.locale = locale
        _dialog.choice.setCurrentIndex(components.KINDS.index(kind))
        _dialog.retranslate()
    _dialog.show()
    _dialog.raise_()
    _dialog.activateWindow()
    return _dialog


def ensure_component(kind, owner, locale=None, ready=None):
    if kind == "text":
        from core.text_selection import checked_runtime
        if checked_runtime() is not None:
            return True
    elif not getattr(sys, "frozen", False) or components.checked_directory(kind) is not None:
        return True
    dialog = open_manager(locale, kind)
    if ready is not None:
        key = (id(owner), kind)
        previous = dialog._callbacks.pop(key, None)
        if previous is not None:
            dialog.installed.disconnect(previous)
        def resume(installed):
            if installed != kind:
                return
            try:
                dialog.installed.disconnect(resume)
            except RuntimeError:
                pass
            dialog._callbacks.pop(key, None)
            if isValid(owner) and not getattr(owner, "_closing", False):
                dialog.hide()
                # Hide installation UI before refreshing the real target.
                QTimer.singleShot(300, lambda: ready() if isValid(owner) else None)
        dialog._callbacks[key] = resume
        dialog.installed.connect(resume)
    return False
