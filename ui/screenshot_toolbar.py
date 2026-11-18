"""Compact, original line-icon controls shared by screenshot surfaces."""
from functools import lru_cache

from PySide6.QtCore import Qt, QSize, QPointF, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QIcon, QPainter, QPainterPath,
    QPen, QPixmap, QKeySequence,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QToolButton, QMenu, QLabel, QSpinBox,
    QPlainTextEdit, QAbstractSpinBox,
)
from ui.screenshot_locale import screenshot_text


ICON_SIZE = 22
BUTTON_SIZE = 34


def _draw_icon(p, key, color):
    """Original vector geometry on one 24-unit grid; no font-based symbols."""
    p.setPen(QPen(QColor(color), 1.75, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    if key in ("rect", "shape", "redact"):
        if key == "redact":
            p.setBrush(QColor(color))
        p.drawRoundedRect(4, 5, 16, 14, 1.5, 1.5)
    elif key == "ellipse":
        p.drawEllipse(4, 4, 16, 16)
    elif key == "select":
        # A normal mouse pointer, deliberately distinct from region selection
        # and from the diagonal annotation arrow.
        path = QPainterPath(QPointF(5, 3))
        for x, y in ((5, 19), (9.5, 15), (13, 21), (16, 19.5),
                     (12.5, 13.5), (19, 13), (5, 3)):
            path.lineTo(x, y)
        p.drawPath(path)
    elif key == "arrow":
        p.drawLine(5, 19, 19, 5)
        p.drawLine(10, 5, 19, 5)
        p.drawLine(19, 5, 19, 14)
    elif key == "pen":
        path = QPainterPath(QPointF(4, 20))
        for x, y in ((5.5, 14.5), (16, 4), (20, 8), (9.5, 18.5), (4, 20)):
            path.lineTo(x, y)
        p.drawPath(path)
        p.drawLine(QPointF(13.5, 6.5), QPointF(17.5, 10.5))
    elif key == "text":
        p.drawLine(5, 5, 19, 5)
        p.drawLine(5, 5, 5, 8)
        p.drawLine(19, 5, 19, 8)
        p.drawLine(12, 5, 12, 19)
        p.drawLine(9, 19, 15, 19)
    elif key == "mosaic":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        for row in range(3):
            for col in range(3):
                if (row, col) not in ((0, 2), (2, 0)):
                    p.drawRoundedRect(4 + col * 6, 4 + row * 6, 4, 4, .6, .6)
    elif key in ("undo", "redo"):
        if key == "redo":
            p.translate(24, 0)
            p.scale(-1, 1)
        path = QPainterPath(QPointF(4, 10))
        path.lineTo(13, 10)
        path.cubicTo(22, 10, 22, 20, 13, 20)
        p.drawPath(path)
        p.drawLine(4, 10, 9, 5)
        p.drawLine(4, 10, 9, 15)
    elif key in ("save", "save_as"):
        p.drawLine(12, 4, 12, 15)
        p.drawLine(8, 11, 12, 15)
        p.drawLine(12, 15, 16, 11)
        path = QPainterPath(QPointF(4, 15))
        for x, y in ((4, 20), (20, 20), (20, 15)):
            path.lineTo(x, y)
        p.drawPath(path)
    elif key == "cancel":
        p.drawLine(6, 6, 18, 18)
        p.drawLine(18, 6, 6, 18)
    elif key == "done":
        p.drawLine(5, 12, 10, 17)
        p.drawLine(10, 17, 19, 7)
    elif key == "more":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(color))
        for x in (5.5, 12, 18.5):
            p.drawEllipse(QPointF(x, 12), 1.5, 1.5)
    elif key == "scroll":
        p.drawRoundedRect(5, 3, 14, 18, 2, 2)
        p.drawLine(9, 8, 15, 8)
        p.drawLine(12, 11, 12, 17)
        p.drawLine(9, 14, 12, 17)
        p.drawLine(12, 17, 15, 14)
    elif key == "text_select":
        # Text rows + I-beam caret, distinct from the annotation T and pointer.
        for y in (6, 12, 18):
            p.drawLine(4, y, 10, y)
        p.drawLine(17, 4, 17, 20)
        p.drawLine(14, 4, 20, 4)
        p.drawLine(14, 20, 20, 20)
    elif key == "pin":
        path = QPainterPath(QPointF(14, 3))
        for x, y in ((21, 10), (17, 10), (13, 14), (13, 17),
                     (7, 11), (10, 11), (14, 7), (14, 3)):
            path.lineTo(x, y)
        p.drawPath(path)
        p.drawLine(10, 14, 4, 20)
    elif key == "copy":
        p.drawRoundedRect(8, 8, 12, 12, 1.5, 1.5)
        path = QPainterPath(QPointF(16, 5))
        for x, y in ((16, 4), (4, 4), (4, 16), (5, 16)):
            path.lineTo(x, y)
        p.drawPath(path)
    elif key == "hand":
        # Leave antialiasing room on 100/125% displays, matching other icons.
        p.translate(1.2, 1.2)
        p.scale(.9, .9)
        path = QPainterPath(QPointF(8, 13))
        path.lineTo(8, 5)
        path.cubicTo(8, 2.5, 11, 2.5, 11, 5)
        path.lineTo(11, 10)
        path.lineTo(11, 3.5)
        path.cubicTo(11, 1, 14, 1, 14, 3.5)
        path.lineTo(14, 10)
        path.lineTo(14, 5)
        path.cubicTo(14, 2.5, 17, 2.5, 17, 5)
        path.lineTo(17, 11)
        path.lineTo(17, 8)
        path.cubicTo(17, 5.5, 20, 5.5, 20, 8)
        path.lineTo(20, 15)
        path.cubicTo(20, 20, 17, 22, 13, 22)
        path.cubicTo(10, 22, 8, 20, 7, 18)
        path.lineTo(3.5, 14)
        path.cubicTo(1, 11, 4, 9.5, 6, 12)
        path.lineTo(8, 14)
        p.drawPath(path)
    elif key == "fit":
        for x, y, dx, dy in ((4, 4, 5, 5), (20, 4, -5, 5),
                              (4, 20, 5, -5), (20, 20, -5, -5)):
            p.drawLine(x, y, x + dx, y)
            p.drawLine(x, y, x, y + dy)
    elif key in ("zoom_in", "zoom_out"):
        p.drawEllipse(3, 3, 13, 13)
        p.drawLine(15, 15, 21, 21)
        p.drawLine(6, 9, 13, 9)
        if key == "zoom_in":
            p.drawLine(9, 6, 9, 13)
    elif key == "actual":
        p.drawLine(6, 8, 9, 5)
        p.drawLine(9, 5, 9, 19)
        p.drawLine(17, 8, 17, 8)
        p.drawLine(17, 16, 17, 16)
    else:  # Help: vector question mark, identical on systems with different fonts.
        p.drawEllipse(4, 4, 16, 16)
        path = QPainterPath(QPointF(9, 9))
        path.cubicTo(9, 5.5, 17, 6.5, 14, 11)
        path.cubicTo(13, 12, 12, 12, 12, 14)
        p.drawPath(path)
        p.drawPoint(12, 17)


@lru_cache(maxsize=64)
def tool_icon(key, color="#475569"):
    icon = QIcon()
    # Render the same geometry at native display densities, avoiding upscaled
    # 24px bitmaps on 125/150/200% Windows displays.
    for mode, ink in ((QIcon.Mode.Normal, color), (QIcon.Mode.Disabled, "#b8c2ce"),
                       (QIcon.Mode.Active, color), (QIcon.Mode.Selected, "#1677ff")):
        for dpr in (1, 1.25, 1.5, 2, 3):
            pixmap = QPixmap(round(ICON_SIZE * dpr), round(ICON_SIZE * dpr))
            pixmap.fill(Qt.GlobalColor.transparent)
            p = QPainter(pixmap)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(pixmap.width() / 24, pixmap.height() / 24)
            _draw_icon(p, key, ink)
            p.end()
            pixmap.setDevicePixelRatio(dpr)
            icon.addPixmap(pixmap, mode)
    return icon


STYLE = """
QWidget#captureToolbar {background: white; border: 1px solid #dbe1e8; border-radius: 8px;}
QToolButton {border: none; border-radius: 5px; padding: 5px; color: #334155; background: transparent;}
QToolButton:hover {background: #edf3fa;}
QToolButton:checked {background: #deedff; color: #1677ff;}
QToolButton:disabled {color: #cbd5e1;}
QToolButton::menu-indicator {image: none; width: 0px;}
QToolButton#screenshot_done {background: #1677ff; color: white; padding: 5px;}
QToolButton#screenshot_done:hover {background: #0964db;}
QLabel {color: #64748b; background: transparent; border: none;}
QSpinBox {color: #334155; background: #f8fafc; border: 1px solid #dbe1e8; border-radius: 4px; padding: 2px;}
QMenu {color: #334155; background: white; border: 1px solid #dbe1e8; padding: 4px;}
QMenu::item {padding: 7px 20px;}
QMenu::item:selected {background: #deedff;}
"""


class CaptureToolbar(QWidget):
    """Host owns all behavior; toolbar only exposes localized actions/options."""
    toolChanged = Signal(str)
    optionChanged = Signal(str, object)
    invoked = Signal(str)

    def __init__(self, locale=None, *, floating=False, parent=None, scroll_enabled=False,
                 text_selection_enabled=None, zoom_enabled=False):
        super().__init__(parent)
        self.locale = locale
        self.tool = "select"
        self._floating = floating
        self._relayout = None
        self._destination_action = None
        self.native_selection = False
        self.user_positioned = False
        self._toolbar_drag = None
        if text_selection_enabled is None:
            text_selection_enabled = scroll_enabled
        if floating:
            self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnTopHint)
        self.setObjectName("captureToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(STYLE)
        self.actions = {}
        self.buttons = {}
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(7, 7, 7, 7)
        self.root_layout.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(2)
        self.root_layout.addLayout(row)
        self.group = QActionGroup(self)
        self.group.setExclusive(True)
        tools = ("select",) + (("hand",) if scroll_enabled else ()) + (
            "rect", "ellipse", "arrow", "pen", "text", "mosaic", "redact")
        for key in tools:
            action = self._action(key, tool=True)
            self.group.addAction(action)
        self._action("scroll").setEnabled(scroll_enabled)
        main_tools = ("select",) + (("hand",) if scroll_enabled else ()) + ("shape", "arrow", "pen", "mosaic", "undo") + (
                      ("zoom_out", "zoom_in") if zoom_enabled else ()) + (
                      "scroll", "pin", "save", "more", "cancel", "done")
        for key in main_tools:
            # A finished long image cannot start a second live scrolling capture.
            if key == "scroll" and not scroll_enabled:
                continue
            button = QToolButton()
            button.setObjectName("screenshot_" + key)
            button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if key == "shape":
                button.setIcon(tool_icon("shape"))
                menu = QMenu(button)
                for shape in ("rect", "ellipse"):
                    menu.addAction(self.actions[shape])
                button.setMenu(menu)
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            elif key == "more":
                button.setIcon(tool_icon("more"))
                self.more = QMenu(button)
                extras = ("text", "redact", "redo") + (("text_select",) if text_selection_enabled else ()) + (
                    "copy", "save_as", "fit", "actual", "help")
                for extra in extras:
                    self.more.addAction(self.actions.get(extra) or self._action(extra))
                button.setMenu(self.more)
                button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            else:
                button.setDefaultAction(self.actions.get(key) or self._action(key))
            row.addWidget(button)
            self.buttons[key] = button
        self.options = QWidget()
        self.option_layout = QHBoxLayout(self.options)
        self.option_layout.setContentsMargins(4, 2, 4, 2)
        self.option_layout.setSpacing(5)
        self.colors = []
        for color in ("#ef4444", "#f59e0b", "#1677ff", "#22c55e", "#000000", "#ffffff"):
            button = QToolButton()
            button.setFixedSize(19, 19)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setStyleSheet(f"background:{color}; border:1px solid #cbd5e1; border-radius:9px;")
            button.clicked.connect(lambda checked=False, color=color: self.optionChanged.emit("color", color))
            self.option_layout.addWidget(button)
            self.colors.append(button)
        self.stroke_buttons = []
        for width in (2, 4, 8):
            button = QToolButton()
            pix = QPixmap(26, 18)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setPen(QPen(QColor("#475569"), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(5, 9, 21, 9)
            p.end()
            button.setIcon(QIcon(pix))
            button.setFixedSize(28, 24)
            button.setIconSize(QSize(22, 18))
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda checked=False, width=width: self.optionChanged.emit("stroke", width))
            self.option_layout.addWidget(button)
            self.stroke_buttons.append(button)
        self.labels, self.spins = {}, {}
        for key, attr, lo, hi, value in (("width", "stroke", 1, 30, 4),
                                        ("font", "font_size", 8, 96, 28),
                                        ("block", "block", 4, 80, 16)):
            label = QLabel()
            spin = QSpinBox()
            spin.setObjectName("screenshot_" + key)
            spin.setRange(lo, hi)
            spin.setValue(value)
            spin.setFixedWidth(58)
            spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
            spin.valueChanged.connect(lambda v, attr=attr: self.optionChanged.emit(attr, v))
            self.option_layout.addWidget(label)
            self.option_layout.addWidget(spin)
            self.labels[key], self.spins[key] = label, spin
        self.option_layout.addStretch()
        self.root_layout.addWidget(self.options)
        self.note = QLabel()
        self.note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.note.setWordWrap(True)
        self.note.setMaximumWidth(500)
        self.root_layout.addWidget(self.note)
        self.note.hide()
        self.actions["select"].setChecked(True)
        if locale:
            locale.languageChanged.connect(self.refresh_language)
        self.refresh_language()
        self.select_tool("select", emit=False)

    def _action(self, key, *, tool=False):
        action = QAction(tool_icon(key, "white" if key == "done" else "#475569"), "", self)
        action.setIconVisibleInMenu(True)
        action.setObjectName("screenshot_" + key)
        if tool:
            action.setCheckable(True)
            # Selection/navigation modes stay active after clicking again.
            # Drawing tools retain the second-click shortcut back to selection.
            action.triggered.connect(
                lambda checked=False, key=key: self.select_tool(
                    key if key in ("select", "hand") or self.tool != key else "select"))
        else:
            action.triggered.connect(lambda checked=False, key=key: self.invoked.emit(key))
        self.actions[key] = action
        return action

    def select_tool(self, key, *, emit=True):
        self.tool = key
        self.actions[key].setChecked(True)
        self.buttons["shape"].setIcon(tool_icon(key if key in ("rect", "ellipse") else "shape"))
        self.buttons["shape"].setStyleSheet("background:#deedff;" if key in ("rect", "ellipse") else "")
        self.options.setVisible(key not in ("select", "hand"))
        for i, button in enumerate(self.colors):
            button.setVisible(key not in ("select", "hand", "mosaic"))
        for button in self.stroke_buttons:
            button.setVisible(key in ("rect", "ellipse", "arrow", "pen"))
        relevant = "font" if key == "text" else "block" if key == "mosaic" else "width"
        for name in self.spins:
            visible = name == relevant and key not in ("select", "hand", "redact")
            self.spins[name].setVisible(visible)
            self.labels[name].setVisible(visible)
        if emit:
            self.toolChanged.emit(key)
        self.adjustSize()
        if self._relayout:
            self._relayout()

    def refresh_language(self):
        for key, action in self.actions.items():
            action.setText(screenshot_text(key, self.locale))
            action.setToolTip(screenshot_text("pointer_hint" if key == "select" else key, self.locale))
        for key, button in self.buttons.items():
            button.setAccessibleName(screenshot_text(key, self.locale))
            if key == "hand":
                button.setToolTip(screenshot_text(key, self.locale))
        for key in ("shape", "more"):
            self.buttons[key].setToolTip(screenshot_text(key, self.locale))
            self.buttons[key].setAccessibleName(screenshot_text(key, self.locale))
        for key, label in self.labels.items():
            label.setText(screenshot_text(key, self.locale))
        self.setWindowTitle(screenshot_text("title", self.locale))
        for index, button in enumerate(self.colors):
            button.setToolTip(screenshot_text("color", self.locale) + f" {index + 1}")
            button.setAccessibleName(button.toolTip())
        for width, button in zip((2, 4, 8), self.stroke_buttons):
            button.setToolTip(screenshot_text("width", self.locale) + f" {width}")
            button.setAccessibleName(button.toolTip())
        if self._destination_action is not None:
            self.set_destination(self._destination_action)
        self.adjustSize()

    def set_destination(self, action_id):
        from ui.screenshot_common import SCREENSHOT_CLIPBOARD_ACTIONS
        self._destination_action = action_id
        key = "finish_copy" if action_id in SCREENSHOT_CLIPBOARD_ACTIONS else "finish_save"
        label = screenshot_text(key, self.locale)
        self.actions["done"].setText(label)
        self.actions["done"].setToolTip(label + " · Enter")
        self.buttons["done"].setAccessibleName(label)
        self.adjustSize()

    def set_status(self, message):
        self.note.setText(message)
        self.note.setVisible(bool(message))
        self.adjustSize()
        if self._relayout:
            self._relayout()

    def keyPressEvent(self, event):
        if self.native_selection and event.key() != Qt.Key.Key_Escape:
            # Never reinterpret native Ctrl+C, typing, Undo or Enter as an
            # image action if a live-selection toolbar happens to get focus.
            event.ignore()
            return
        if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
            self.invoked.emit("done")
        elif event.key() == Qt.Key.Key_Escape:
            self.invoked.emit("cancel")
        elif event.matches(QKeySequence.StandardKey.Undo):
            self.invoked.emit("undo")
        elif event.matches(QKeySequence.StandardKey.Redo):
            self.invoked.emit("redo")
        elif event.matches(QKeySequence.StandardKey.Copy):
            self.invoked.emit("copy")
        elif event.matches(QKeySequence.StandardKey.Save):
            self.invoked.emit("save")
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self._floating and event.button() == Qt.MouseButton.LeftButton:
            self._toolbar_drag = event.globalPosition().toPoint() - self.pos()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._toolbar_drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.user_positioned = True
            self.move(event.globalPosition().toPoint() - self._toolbar_drag)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._toolbar_drag is not None:
            self._toolbar_drag = None
            if self._relayout:
                self._relayout()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class InlineTextBox(QPlainTextEdit):
    """Enter inserts a line; Ctrl+Enter/focus-out commits; Esc discards text."""
    committed = Signal(str)
    discarded = Signal()

    def __init__(self, parent, text="", font_size=28):
        super().__init__(parent)
        self._ended = False
        self.setObjectName("screenshotInlineText")
        self.setPlainText(text)
        font = self.font()
        font.setPixelSize(font_size)
        self.setFont(font)
        self.setStyleSheet("QPlainTextEdit {background:white; color:#1e293b; border:1px solid #1677ff; padding:3px;}")
        self.setTabChangesFocus(True)
        self.setMinimumSize(100, 44)

    def commit(self):
        if self._ended:
            return
        self._ended = True
        self.committed.emit(self.toPlainText()[:10000])
        self.hide()
        self.deleteLater()

    def discard(self):
        if self._ended:
            return
        self._ended = True
        self.discarded.emit()
        self.hide()
        self.deleteLater()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.commit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.discard()
            event.accept()
        elif event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.commit()
            event.accept()
        else:
            super().keyPressEvent(event)
