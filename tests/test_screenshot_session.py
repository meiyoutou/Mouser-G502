"""Synthetic surfaces only: no desktop capture, real clipboard or settings."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from ui.locale_manager import LocaleManager
from ui.screenshot_common import SCREENSHOT_REGION_CLIP, SCREENSHOT_FULL_FILE, pil_image_to_qimage
from ui.screenshot_editor import Annotation, ScreenshotEditor
from ui.screenshot_session import ScreenshotSession, toolbar_position, qimage_to_pil
from ui.screenshot_toolbar import CaptureToolbar, InlineTextBox, tool_icon
from ui.windows_screenshot import MonitorMap, VirtualCapture, WindowsScreenshotController, crop_logical_region
from ui.screenshot_overlay import IntRect
from ui.screenshot_editor_check import CheckClipboard


def capture():
    return VirtualCapture(
        Image.new("RGB", (800, 400), (120, 150, 170)), IntRect(-400, 0, 400, 400),
        (MonitorMap(IntRect(-200, 0, 0, 200), IntRect(-400, 0, 0, 400)),
         MonitorMap(IntRect(0, 0, 400, 400), IntRect(0, 0, 400, 400))))


class SessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make(self, action=SCREENSHOT_REGION_CLIP, **kwargs):
        self.clipboard = CheckClipboard()
        session = ScreenshotSession(capture(), action, locale=LocaleManager("zh_CN"),
                                    clipboard_factory=lambda: self.clipboard, **kwargs)
        self.addCleanup(self.app.processEvents)
        self.addCleanup(session.close)
        return session

    def event(self, kind, point, button=Qt.MouseButton.LeftButton):
        return QMouseEvent(kind, QPointF(point), QPointF(point), button,
                           Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)

    def select(self, session, rect=QRect(20, 30, 200, 180)):
        session._start, session._current = rect.topLeft(), rect.bottomRight()

    def drag(self, session, start, end, pane=None):
        pane = pane or next(p for p in session._panes if p.geometry().contains(start))
        for kind, point in ((QMouseEvent.Type.MouseButtonPress, start),
                            (QMouseEvent.Type.MouseMove, end),
                            (QMouseEvent.Type.MouseButtonRelease, end)):
            event = QMouseEvent(kind, QPointF(pane.mapFromGlobal(point)), QPointF(point),
                                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseMove
                                else Qt.MouseButton.LeftButton,
                                Qt.MouseButton.NoButton if kind == QMouseEvent.Type.MouseButtonRelease
                                else Qt.MouseButton.LeftButton,
                                Qt.KeyboardModifier.NoModifier)
            QApplication.sendEvent(pane, event)

    def test_mouse_release_shows_toolbar_without_second_editor_or_output(self):
        s = self.make()
        pane = s._panes[1]
        s._pane_mouse_press_event(pane, self.event(QMouseEvent.Type.MouseButtonPress, QPoint(30, 50)))
        s._pane_mouse_release_event(self.event(QMouseEvent.Type.MouseButtonRelease, QPoint(160, 150)))
        self.assertTrue(s.toolbar.isVisible())
        self.assertTrue(s.toolbar.buttons["hand"].isVisible())
        self.assertIsNone(self.clipboard.image)
        self.assertIsNone(s._keyboard_grab_pane)
        self.assertIsNone(s._mouse_grab_pane)

    def test_original_pixels_cross_monitor_crop_and_preview_match(self):
        s = self.make()
        self.select(s, QRect(-50, 20, 130, 60))
        s.document.add(Annotation("redact", ((330, 30), (350, 100)), color="#000000"))
        s._refresh_images()
        expected = crop_logical_region(VirtualCapture(qimage_to_pil(s.document.render()),
                           s.capture.physical_rect, s.capture.monitor_maps), IntRect(-50, 20, 80, 80))
        self.assertEqual(s._output_image(), pil_image_to_qimage(expected))
        self.assertEqual(s._frozen_images[0].pixelColor(335, 40), QColor("black"))
        self.assertEqual(s._physical_point(QPoint(-50, 20)), QPointF(300, 40))
        self.assertEqual(s._physical_point(QPoint(20, 20)), QPointF(420, 20))
        self.assertTrue(s.copy_image())
        self.assertEqual(self.clipboard.image, s._output_image())

    def test_full_capture_is_not_recropped_or_rescaled(self):
        s = self.make(full=True)
        self.assertEqual(s._output_image(), pil_image_to_qimage(s.capture.image).convertToFormat(QImage.Format.Format_RGB32))
        self.assertEqual(s._output_image().size(), QSize(800, 400))

    def test_toolbar_stays_on_one_monitor_at_edges_and_negative_origin(self):
        screens = [QRect(-1920, 0, 1920, 1080), QRect(0, 0, 1280, 720)]
        for rect in (QRect(-1900, 900, 600, 170), QRect(1000, 650, 250, 60), QRect(-40, 0, 400, 400)):
            point = toolbar_position(rect, QSize(470, 92), screens)
            self.assertTrue(any(screen.contains(QRect(point, QSize(470, 92))) for screen in screens))

    def test_controls_single_row_and_context_only_options(self):
        toolbar = CaptureToolbar(LocaleManager("zh_CN"), scroll_enabled=True)
        self.addCleanup(toolbar.close)
        self.assertEqual(tuple(toolbar.buttons), (
            "select", "hand", "shape", "arrow", "pen", "mosaic", "undo",
            "scroll", "pin", "save", "more", "cancel", "done"))
        self.assertTrue(toolbar.options.isHidden())
        self.assertNotIn("ocr_install", toolbar.buttons)
        self.assertNotIn("text", toolbar.buttons)
        self.assertIn(toolbar.actions["text"], toolbar.more.actions())
        self.assertIn(toolbar.actions["text_select"], toolbar.more.actions())
        self.assertNotIn(toolbar.actions["scroll"], toolbar.more.actions())
        self.assertNotIn(toolbar.actions["pin"], toolbar.more.actions())
        toolbar.select_tool("text")
        self.assertFalse(toolbar.options.isHidden())
        self.assertFalse(toolbar.spins["font"].isHidden())
        self.assertTrue(toolbar.spins["width"].isHidden())
        self.assertTrue(toolbar.spins["block"].isHidden())
        toolbar.select_tool("select")
        self.assertTrue(toolbar.options.isHidden())

    def test_hand_moves_only_crop_while_frozen_pixels_remain_anchored(self):
        s = self.make()
        self.select(s)
        s.document.add(Annotation("redact", ((450, 70), (490, 100)), color="#000000"))
        s._refresh_images()
        original = s.document.render()
        frozen = [frame.copy() for frame in s._frozen_images]
        initial = s._selection_global_rect()
        hand = s.toolbar.buttons["hand"]
        hand.click()  # Release the toolbar button BEFORE dragging in the image.
        self.assertEqual(s.tool, "hand")
        self.drag(s, QPoint(100, 100), QPoint(153, 121))
        self.assertEqual(s._selection_global_rect(), initial.translated(53, 21))
        self.assertEqual(s.document.render(), original)
        self.assertEqual(list(s._frozen_images), frozen)
        self.assertIsNone(self.clipboard.image)
        self.assertTrue(s.copy_image())
        self.assertEqual(self.clipboard.image, s._output_image())
        self.assertIsNone(s._mouse_grab_pane)
        self.assertEqual(s._panes[1].cursor().shape(), Qt.CursorShape.OpenHandCursor)
        self.assertEqual(s.tool, "hand")
        self.assertTrue(hand.isChecked())
        self.assertTrue(s.toolbar.options.isHidden())
        # A second independent drag works without returning to the toolbar.
        self.drag(s, QPoint(170, 150), QPoint(180, 160))
        self.assertEqual(s._selection_global_rect(), initial.translated(63, 31))
        self.assertEqual(s.document.render(), original)
        self.assertEqual(list(s._frozen_images), frozen)

    def test_hand_clamps_selection_at_negative_and_positive_screen_bounds(self):
        s = self.make()
        self.select(s)
        size = s._selection_global_rect().size()
        s.toolbar.buttons["hand"].click()
        for point in (QPoint(-9999, -9999), QPoint(9999, 9999)):
            self.drag(s, s._selection_global_rect().center(), point, s._panes[1])
            self.assertTrue(s._bounds.to_qrect().contains(s._selection_global_rect()))
            self.assertEqual(s._selection_global_rect().size(), size)
        self.assertEqual(s.tool, "hand")

    def test_select_is_visible_checked_default_in_each_new_session(self):
        s = self.make()
        self.assertEqual(s.tool, "select")
        self.assertEqual(s.toolbar.tool, "select")
        self.assertTrue(s.toolbar.buttons["select"].isChecked())
        self.assertFalse(s.toolbar.buttons["hand"].isChecked())
        self.assertIn("默认", s.toolbar.buttons["select"].toolTip())
        s.toolbar.buttons["hand"].click()
        fresh = self.make()
        self.assertTrue(fresh.toolbar.buttons["select"].isChecked())
        self.assertFalse(fresh.toolbar.buttons["hand"].isChecked())

    def test_hand_button_click_latches_exclusively_and_repeated_click_stays_hand(self):
        s = self.make()
        self.select(s)
        before = s._selection_global_rect()
        hand = s.toolbar.buttons["hand"]
        for _ in range(2):
            # Real button press/release delivery, not emitting its drag signals.
            point = hand.rect().center()
            for kind in (QMouseEvent.Type.MouseButtonPress, QMouseEvent.Type.MouseButtonRelease):
                QApplication.sendEvent(hand, QMouseEvent(
                    kind, QPointF(point), QPointF(hand.mapToGlobal(point)),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton if kind == QMouseEvent.Type.MouseButtonPress
                    else Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
            self.assertEqual(s.tool, "hand")
            self.assertTrue(hand.isChecked())
            self.assertFalse(s.toolbar.buttons["select"].isChecked())
            self.assertTrue(s.toolbar.options.isHidden())
            self.assertEqual(s._selection_global_rect(), before)
            self.assertIsNone(s._mouse_grab_pane)
        s.toolbar.buttons["select"].click()
        self.assertEqual(s.tool, "select")
        self.assertFalse(hand.isChecked())
        self.assertTrue(s.toolbar.buttons["select"].isChecked())
        self.drag(s, QPoint(80, 90), QPoint(150, 140))
        self.assertEqual(s._selection_global_rect(), before)

    def test_hand_drag_cursor_and_magnifier(self):
        s = self.make()
        self.select(s)
        s.toolbar.buttons["hand"].click()
        pane = s._panes[1]
        self.assertEqual(pane.cursor().shape(), Qt.CursorShape.OpenHandCursor)
        s._pane_mouse_press_event(pane, self.event(QMouseEvent.Type.MouseButtonPress, QPoint(80, 90)))
        self.assertEqual(pane.cursor().shape(), Qt.CursorShape.ClosedHandCursor)
        s._pane_mouse_move_event(self.event(QMouseEvent.Type.MouseMove, QPoint(100, 110)))
        self.assertFalse(s._magnifier)
        s._pane_mouse_release_event(self.event(QMouseEvent.Type.MouseButtonRelease, QPoint(100, 110)))
        self.assertFalse(s._magnifier)
        self.assertEqual(pane.cursor().shape(), Qt.CursorShape.OpenHandCursor)
        s.toolbar.buttons["select"].click()
        self.assertEqual(pane.cursor().shape(), Qt.CursorShape.ArrowCursor)

    def test_hand_crosses_negative_origin_monitors_without_resize_or_pixel_change(self):
        s = self.make()
        self.select(s, QRect(-120, 25, 100, 100))
        base = s.document.render()
        s.toolbar.buttons["hand"].click()
        for _ in range(5):
            self.drag(s, QPoint(-70, 75), QPoint(80, 95))
            self.assertEqual(s._selection_global_rect(), QRect(30, 45, 100, 100))
            self.drag(s, QPoint(80, 95), QPoint(-70, 75))
            self.assertEqual(s._selection_global_rect(), QRect(-120, 25, 100, 100))
        self.assertEqual(s.document.render(), base)

    def test_hand_edges_still_resize_without_annotation_and_outside_click_does_nothing(self):
        s = self.make()
        self.select(s)
        s.toolbar.buttons["hand"].click()
        self.drag(s, QPoint(20, 30), QPoint(10, 15))
        self.assertEqual(s._selection_global_rect().topLeft(), QPoint(10, 15))
        self.assertEqual(s.document.annotations, ())
        self.assertEqual(s.tool, "hand")
        before = s._selection_global_rect()
        self.drag(s, QPoint(350, 300), QPoint(390, 350))
        self.assertEqual(s._selection_global_rect(), before)
        self.assertIsNone(s._mouse_grab_pane)

    def test_pointer_does_not_reselect_outside_current_region(self):
        s = self.make()
        self.select(s)
        before = s._selection_global_rect()
        pixels = s.document.render()
        s.toolbar.buttons["hand"].click()
        s.toolbar.buttons["select"].click()
        self.drag(s, QPoint(260, 250), QPoint(360, 350))
        self.assertEqual(s._selection_global_rect(), before)
        self.assertEqual(s.document.render(), pixels)
        self.assertTrue(s.toolbar.buttons["select"].isChecked())
        self.assertIsNone(s._mouse_grab_pane)
        self.assertEqual(s.document.annotations, ())
        self.assertFalse(s._magnifier)

    def test_initial_region_selection_becomes_default_arrow_pointer_on_release(self):
        s = self.make()
        pane = s._panes[1]
        self.assertEqual(pane.cursor().shape(), Qt.CursorShape.CrossCursor)
        self.drag(s, QPoint(30, 50), QPoint(160, 150))
        self.assertEqual(s._selection_global_rect(), QRect(QPoint(30, 50), QPoint(160, 150)))
        self.assertEqual(pane.cursor().shape(), Qt.CursorShape.ArrowCursor)
        self.assertFalse(s._magnifier)
        self.assertTrue(s.toolbar.buttons["select"].isChecked())
        s.locale.setLanguage("en")
        self.assertEqual(s._hint, "")
        self.assertIn("pointer", s.toolbar.buttons["select"].toolTip())

    def test_full_capture_default_pointer_and_edge_resize(self):
        s = self.make(full=True)
        pane = s._panes[1]
        self.assertEqual(pane.cursor().shape(), Qt.CursorShape.ArrowCursor)
        self.assertFalse(s._magnifier)
        before = s._selection_global_rect()
        self.drag(s, QPoint(80, 90), QPoint(150, 140))
        self.assertEqual(s._selection_global_rect(), before)
        self.drag(s, QPoint(before.right(), before.bottom()), QPoint(300, 300))
        self.assertLess(s._selection_global_rect().width(), before.width())
        self.assertEqual(s.tool, "select")
        self.assertEqual(pane.cursor().shape(), Qt.CursorShape.ArrowCursor)

    def test_dragging_inside_fixed_selection_does_not_float_or_move_it(self):
        s = self.make()
        self.select(s)
        initial = s._selection_global_rect()
        pane = s._panes[1]
        s._pane_mouse_press_event(pane, self.event(QMouseEvent.Type.MouseButtonPress, QPoint(80, 90)))
        s._pane_mouse_move_event(self.event(QMouseEvent.Type.MouseMove, QPoint(150, 140)))
        s._pane_mouse_release_event(self.event(QMouseEvent.Type.MouseButtonRelease, QPoint(150, 140)))
        self.assertEqual(s._selection_global_rect(), initial)
        self.assertIsNone(s._mouse_grab_pane)

    def test_hand_hint_follows_language_and_does_not_invoke_pin(self):
        s = self.make()
        self.select(s)
        hand = s.toolbar.buttons["hand"]
        self.assertIn("画面保持冻结", hand.toolTip())
        s.locale.setLanguage("en")
        self.assertIn("stays frozen", hand.toolTip())
        self.assertIn("default", s.toolbar.buttons["select"].toolTip())
        s.locale.setLanguage("zh_TW")
        self.assertIn("預設", s.toolbar.buttons["select"].toolTip())
        self.assertIn("點選小手", hand.toolTip())
        outputs = []
        s.pinRequested.connect(outputs.append)
        hand.click()
        self.drag(s, QPoint(80, 90), QPoint(90, 100))
        self.assertEqual(outputs, [])

    def test_done_label_follows_destination_and_language(self):
        for action, label in ((SCREENSHOT_REGION_CLIP, "完成并复制"), (SCREENSHOT_FULL_FILE, "完成并保存")):
            s = self.make(action)
            self.assertEqual(s._actions["done"].text(), label)
            self.assertEqual(s.toolbar.buttons["done"].toolButtonStyle(),
                             Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.assertEqual(s.toolbar.buttons["done"].accessibleName(), label)
            self.assertIn(label, s.toolbar.buttons["done"].toolTip())
            s.locale.setLanguage("en")
            self.assertIn("finish", s._actions["done"].text())
            self.assertIn("finish", s.toolbar.buttons["done"].toolTip())
            self.assertEqual(s.toolbar.buttons["done"].width(), 34)

    def test_primary_scroll_and_pin_buttons_invoke_existing_actions(self):
        s = self.make()
        self.select(s)
        with patch.object(s, "_start_scroll") as scroll:
            s.toolbar.buttons["scroll"].click()
            scroll.assert_called_once()
        with patch.object(s, "pin_image") as pin:
            s.toolbar.buttons["pin"].click()
            pin.assert_called_once()

    def test_text_in_more_menu_activates_inline_editing(self):
        s = self.make()
        self.select(s)
        s.toolbar.actions["text"].trigger()
        self.assertEqual(s.tool, "text")
        self.assertEqual(s.toolbar.tool, "text")
        s._pane_mouse_press_event(s._panes[1], self.event(
            QMouseEvent.Type.MouseButtonPress, QPoint(70, 80)))
        self.assertIsNotNone(s._text_box)
        s._text_box.setPlainText("收纳后的文字工具")
        s._text_box.commit()
        self.assertEqual(s.document.annotations[-1].text, "收纳后的文字工具")

    def test_result_editor_has_pin_but_no_unusable_live_scroll_button(self):
        toolbar = CaptureToolbar(LocaleManager("zh_CN"))
        self.addCleanup(toolbar.close)
        self.assertIn("pin", toolbar.buttons)
        self.assertNotIn("scroll", toolbar.buttons)
        self.assertFalse(toolbar.actions["scroll"].isEnabled())
        self.assertNotIn("text", toolbar.buttons)
        self.assertIn(toolbar.actions["text"], toolbar.more.actions())

    def test_removed_tools_are_absent_and_help_keeps_existing_marks(self):
        s = self.make()
        self.select(s)
        for key in ("number", "reset_crop"):
            self.assertNotIn(key, s._actions)
        self.assertIn("select", s.toolbar.buttons)
        s.document.add(Annotation("arrow", ((450, 50), (490, 90))))
        original_annotations = s.document.annotations
        rect = s._selection_global_rect()
        s.toolbar.actions["help"].trigger()
        self.assertEqual(s._selection_global_rect(), rect)
        self.assertEqual(s.document.annotations, original_annotations)
        self.assertIn("Ctrl+Enter", s.hint.text())
        self.assertIn("右键", s.hint.text())
        editor = ScreenshotEditor(pil_image_to_qimage(capture().image), SCREENSHOT_REGION_CLIP)
        self.addCleanup(editor.close)
        for key in ("number", "reset_crop"):
            self.assertNotIn(key, editor._actions)

    def test_uniform_buttons_and_menu_centers_across_languages(self):
        locale = LocaleManager("zh_CN")
        toolbar = CaptureToolbar(locale, scroll_enabled=True)
        self.addCleanup(toolbar.close)
        toolbar.show()
        for language in ("zh_CN", "en", "zh_TW"):
            locale.setLanguage(language)
            self.app.processEvents()
            buttons = list(toolbar.buttons.values())
            self.assertTrue(all(b.size() == QSize(34, 34) for b in buttons))
            self.assertTrue(all(b.iconSize() == QSize(22, 22) for b in buttons))
            self.assertEqual(len({b.geometry().center().y() for b in buttons}), 1)
            for left, right in zip(buttons, buttons[1:]):
                self.assertEqual(right.x() - left.x(), 36)
            self.assertTrue(all(b.accessibleName() for b in buttons))

    def test_icons_are_not_clipped_and_have_native_hidpi_variants(self):
        for key in ("select", "hand", "shape", "arrow", "pen", "mosaic", "undo", "scroll",
                    "pin", "save", "more", "cancel", "done", "text", "text_select", "help"):
            for dpr in (1, 1.25, 1.5, 2, 3):
                with self.subTest(key=key, dpr=dpr):
                    pix = tool_icon(key).pixmap(QSize(22, 22), dpr, QIcon.Mode.Normal)
                    self.assertGreaterEqual(pix.width(), round(22 * dpr) - 1)
                    image = pix.toImage()
                    self.assertTrue(any(image.pixelColor(x, y).alpha()
                                        for x in range(image.width())
                                        for y in range(image.height())))
                    for x in range(image.width()):
                        self.assertEqual(image.pixelColor(x, 0).alpha(), 0)
                        self.assertEqual(image.pixelColor(x, image.height() - 1).alpha(), 0)
                    for y in range(image.height()):
                        self.assertEqual(image.pixelColor(0, y).alpha(), 0)
                        self.assertEqual(image.pixelColor(image.width() - 1, y).alpha(), 0)

    def test_switch_tool_does_not_recompose_desktop_but_clears_draft(self):
        s = self.make()
        self.select(s)
        before = s._frozen_images
        with patch.object(s.document, "render", wraps=s.document.render) as render:
            s.toolbar.actions["arrow"].trigger()
            s.toolbar.actions["pen"].trigger()
            s.toolbar.actions["pen"].trigger()
            render.assert_not_called()
        self.assertIs(s._frozen_images, before)
        self.assertEqual(s.tool, "select")
        self.assertTrue(s.toolbar.options.isHidden())
        s.tool = "arrow"
        s._points = [QPointF(450, 60), QPointF(550, 120)]
        s._refresh_images(s._annotation(s._points))
        with patch.object(s.document, "render", wraps=s.document.render) as render:
            s.toolbar.select_tool("select")
            render.assert_called_once_with(None)
        self.assertEqual(s._points, [])
        self.assertEqual(s._frozen_images, before)

    def test_right_click_returns_to_selection_and_handles_still_resize(self):
        s = self.make()
        self.select(s)
        pane = s._panes[1]
        s.toolbar.actions["pen"].trigger()
        s._pane_mouse_press_event(pane, self.event(
            QMouseEvent.Type.MouseButtonPress, QPoint(70, 80), Qt.MouseButton.RightButton))
        self.assertEqual(s.tool, "select")
        s.toolbar.actions["arrow"].trigger()
        s._pane_mouse_press_event(pane, self.event(
            QMouseEvent.Type.MouseButtonPress, QPoint(20, 30)))
        s._pane_mouse_release_event(self.event(
            QMouseEvent.Type.MouseButtonRelease, QPoint(10, 15)))
        self.assertEqual(s.document.annotations, ())
        self.assertEqual(s._selection_global_rect().topLeft(), QPoint(10, 15))

    def test_result_editor_can_leave_drawing_with_default_select_or_right_click(self):
        editor = ScreenshotEditor(pil_image_to_qimage(capture().image), SCREENSHOT_REGION_CLIP)
        self.addCleanup(editor.close)
        editor.toolbar.actions["pen"].trigger()
        self.assertEqual(editor.canvas.tool, "pen")
        editor.canvas.mousePressEvent(self.event(
            QMouseEvent.Type.MouseButtonPress, QPoint(70, 80), Qt.MouseButton.RightButton))
        self.assertEqual(editor.canvas.tool, "select")
        self.assertTrue(editor.toolbar.options.isHidden())
        editor.toolbar.buttons["pen"].click()
        editor.toolbar.buttons["select"].click()
        self.assertEqual(editor.canvas.tool, "select")

    def test_inline_text_enter_does_not_finish_and_escape_only_discards_text(self):
        s = self.make()
        self.select(s)
        s.tool = "text"
        s._edit_text(s._panes[1], QPoint(60, 80), QPointF(460, 80))
        box = s._text_box
        box.setPlainText("第一次文字")
        box.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
        self.assertFalse(s._closing)
        self.assertEqual(s.document.annotations, ())
        self.assertIsNone(s._text_box)
        s._edit_text(s._panes[1], QPoint(60, 80), QPointF(460, 80))
        s._text_box.setPlainText("确认文字")
        s._text_box.commit()
        self.assertEqual(s.document.annotations[0].text, "确认文字")
        self.assertIsNone(self.clipboard.image)
        self.assertIsNone(s._text_box)

    def test_existing_text_replacement_is_one_undoable_edit(self):
        s = self.make()
        self.select(s)
        s.document.add(Annotation("text", ((450, 80),), text="旧内容"))
        s._edit_text(s._panes[1], QPoint(50, 80), QPointF(450, 80), 0)
        s._text_box.setPlainText("新内容")
        s._text_box.commit()
        self.assertEqual(len(s.document.annotations), 1)
        self.assertEqual(s.document.annotations[0].text, "新内容")
        s._history(False)
        self.assertEqual(s.document.annotations[0].text, "旧内容")

    def test_finish_routes_destination_without_changing_mapping(self):
        for action, method in ((SCREENSHOT_REGION_CLIP, "copy_image"), (SCREENSHOT_FULL_FILE, "save_image")):
            s = self.make(action)
            self.select(s)
            with patch.object(s, method, return_value=True) as deliver:
                s.finish()
                deliver.assert_called_once()

    def test_close_releases_toolbar_and_selection_worker_without_any_output(self):
        s = self.make()
        self.select(s)
        closed = []
        s.closed.connect(closed.append)
        with patch.object(s, "copy_image") as copy, patch.object(s, "save_image") as save:
            s.close()
            s.close()
            copy.assert_not_called()
            save.assert_not_called()
        self.assertEqual(closed, [s])
        self.assertEqual(s._panes, [])

    def test_failed_save_keeps_selection_and_toolbar_available(self):
        s = self.make(SCREENSHOT_FULL_FILE, path_factory=lambda: (_ for _ in ()).throw(OSError("synthetic failure")))
        self.select(s)
        s.finish()
        self.assertFalse(s._closing)
        self.assertFalse(s._completed)
        self.assertIn("synthetic failure", s.hint.text())

    def test_text_selection_gets_only_selected_flattened_image(self):
        s = self.make()
        self.select(s)
        s.document.add(Annotation("redact", ((450, 70), (490, 100)), color="#000000"))
        from core import text_selection
        from ui.screenshot_text_selection import TextSelectionController
        with patch.object(text_selection, "checked_runtime", return_value=Path("fake")), \
                patch.object(TextSelectionController, "start") as start:
            s._start_text_selection()
            sent = start.call_args.args[0]
            self.assertEqual(sent, s._output_image())
            self.assertEqual(sent.pixelColor(40, 50), QColor("black"))
            self.assertEqual(sent.size(), QSize(200, 180))

    def test_missing_text_selection_offers_component_manager_without_recognizing(self):
        s = self.make()
        self.select(s)
        from core import text_selection
        from ui.screenshot_text_selection import TextSelectionController
        with patch.object(text_selection, "checked_runtime", return_value=None), \
                patch("ui.screenshot_components.ensure_component", return_value=False) as manager, \
                patch.object(QMessageBox, "exec") as dialog, \
                patch.object(TextSelectionController, "start") as start:
            s._invoke("text_select")
            dialog.assert_not_called()
            manager.assert_called_once()
            start.assert_not_called()
            self.assertIsNone(s._selection_worker)
            self.assertIn("文字选择组件", s.hint.text())

    def test_long_capture_rejects_cross_monitor_or_annotated_region(self):
        s = self.make()
        delivered = []
        s.scrollRequested.connect(delivered.append)
        self.select(s, QRect(-30, 20, 100, 70))
        s._start_scroll()
        self.assertEqual(delivered, [])
        self.assertFalse(s._closing)
        self.select(s)
        s.document.add(Annotation("arrow", ((450, 50), (490, 90))))
        s._start_scroll()
        self.assertEqual(delivered, [])
        self.assertIn("先长截图", s.hint.text())

    def test_controller_same_surface_for_full_and_region_busy_cleanup(self):
        for action in (SCREENSHOT_REGION_CLIP, SCREENSHOT_FULL_FILE):
            controller = WindowsScreenshotController(editor_enabled=lambda: True, settle_delay_ms=0)
            with patch("ui.windows_screenshot.capture_virtual_desktop", return_value=capture()), \
                    patch("ui.windows_screenshot.visible_window_rects", return_value=()), \
                    patch.object(ScreenshotSession, "show"):
                controller._begin_capture_request(action)
                self.assertIsInstance(controller._overlay, ScreenshotSession)
                self.assertIsNone(controller._editor)
                controller._handle_request(action)
                controller._overlay.close()
                self.assertIsNone(controller._overlay)
                self.assertIsNone(controller._pending_capture)
            self.app.processEvents()

    def test_annotation_drag_and_undo_do_not_change_selection(self):
        s = self.make()
        self.select(s)
        rect = s._selection_global_rect()
        s.toolbar.select_tool("arrow")
        s._pane_mouse_press_event(s._panes[1], self.event(QMouseEvent.Type.MouseButtonPress, QPoint(70, 70)))
        s._pane_mouse_release_event(self.event(QMouseEvent.Type.MouseButtonRelease, QPoint(180, 160)))
        self.assertEqual(len(s.document.annotations), 1)
        self.assertEqual(s._selection_global_rect(), rect)
        s._history(False)
        self.assertEqual(s.document.annotations, ())
        self.assertEqual(s._selection_global_rect(), rect)


if __name__ == "__main__":
    unittest.main()
