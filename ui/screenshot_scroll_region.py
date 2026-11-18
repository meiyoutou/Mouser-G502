"""Geometry-only, bounded UIA viewport lookup; never reads document text."""
import math
import os
import sys
import threading

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot

from ui.screenshot_overlay import IntRect


def _bounds(control):
    rect = control.BoundingRectangle
    return IntRect(math.ceil(rect.left), math.ceil(rect.top),
                   math.floor(rect.right), math.floor(rect.bottom))


def _children(control):
    """Bounded traversal; one stale sibling must not discard a valid parent."""
    try:
        child = control.GetFirstChildControl()
    except Exception:
        return
    for _ in range(8):
        if child is None:
            break
        yield child
        try:
            child = child.GetNextSiblingControl()
        except Exception:
            break


def _inner_viewport(control, bounds):
    """Prefer a large viewport child over a surrounding frame/scrollbar."""
    choices = []
    for child in _children(control):
        try:
            if child.ControlType in {50026, 50030, 50033} and not child.IsOffscreen:
                part = _bounds(child).intersected(bounds)
                if (part is not None and part.width >= bounds.width * .8
                        and part.height >= bounds.height * .8):
                    choices.append(part)
        except Exception:
            continue
    return max(choices, key=lambda r: r.width * r.height) if choices else bounds


def _scrollbar_viewport(control, bounds):
    """Qt sometimes exposes a viewport + scrollbar but no ScrollPattern.

    Require a large direct viewport and an adjacent, almost full-height
    vertical scrollbar (possibly inside one small wrapper). A scrollbar
    elsewhere in a window must never make that whole window a viewport.
    """
    panes, bars = [], []
    for child in _children(control):
        try:
            if child.IsOffscreen:
                continue
            part = _bounds(child).intersected(bounds)
            if part is None:
                continue
            if (child.ControlType in {50026, 50030, 50033}
                    and part.width >= bounds.width * .8
                    and part.height >= bounds.height * .8):
                panes.append(part)
            if part.width <= min(40, bounds.width * .15) and part.height >= bounds.height * .8:
                if child.ControlType == 50014:
                    bars.append(part)
                else:
                    for grandchild in _children(child):
                        if grandchild.ControlType == 50014 and not grandchild.IsOffscreen:
                            bar = _bounds(grandchild).intersected(part)
                            if bar is not None:
                                bars.append(bar)
        except Exception:
            continue
    choices = [pane for pane in panes for bar in bars
               if bar.height >= pane.height * .9
               and abs(bar.top - pane.top) <= 8 and abs(bar.bottom - pane.bottom) <= 8
               and min(abs(bar.left - pane.right), abs(bar.right - pane.left)) <= 8]
    return max(choices, key=lambda r: r.width * r.height) if choices else None


def detect_scroll_viewport(selection, *, automation=None, ignore_process=None):
    """Return a physical-pixel rectangle contained strictly in the selection.

    UIA is advisory: no patterns are invoked and no text, titles or values are
    fetched. Providers that do not expose scrolling simply return no result.
    """
    if automation is None:
        if sys.platform != "win32":
            return None
        import uiautomation as automation
    if ignore_process is None:
        ignore_process = os.getpid()
    choices = []
    center = (selection.left + selection.width // 2, selection.top + selection.height // 2)
    with automation.UIAutomationInitializerInThread():
        for fx, fy in ((.55, .5), (.7, .3), (.7, .7)):
            try:
                node = automation.ControlFromPoint(
                    selection.left + round(selection.width * fx),
                    selection.top + round(selection.height * fy))
            except Exception:
                continue
            for _ in range(18):
                if node is None:
                    break
                try:
                    if node.ControlType == 50032:  # Never treat a whole Window as a viewport.
                        break
                    if node.ProcessId != ignore_process and not node.IsOffscreen:
                        bounds = _bounds(node)
                        try:
                            pattern = node.GetPattern(10004)  # ScrollPattern
                        except Exception:
                            pattern = None
                        if pattern and pattern.VerticallyScrollable:
                            bounds = _inner_viewport(node, bounds)
                        else:
                            bounds = _scrollbar_viewport(node, bounds)
                        if bounds is not None:
                            part = bounds.intersected(selection)
                            if (part is not None and part.width >= max(40, selection.width * .2)
                                    and part.height >= max(80, selection.height * .25)
                                    and part.width * part.height >= selection.width * selection.height * .12):
                                choices.append(part)
                    node = node.GetParentControl()
                except Exception:
                    # Individual disappearing/unavailable UIA elements are normal.
                    break
    if not choices:
        return None
    return max(choices, key=lambda r: (
        r.left <= center[0] < r.right and r.top <= center[1] < r.bottom,
        r.width * r.height))


class ScrollViewportProbe(QObject):
    """A slow/broken accessibility provider cannot block capture startup."""
    resolved = Signal(object)
    _result = Signal(object)
    _worker_lock = threading.Lock()

    def __init__(self, selection, parent=None, *, resolver=None, timeout_ms=1400):
        super().__init__(parent)
        self.selection = selection
        self.resolver = resolver or detect_scroll_viewport
        self._active = False
        self._cancelled = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(timeout_ms)
        self.timer.timeout.connect(lambda: self._finish(None))
        self._result.connect(self._finish, Qt.ConnectionType.QueuedConnection)

    def start(self):
        if self._cancelled or self._active:
            return
        self._active = True
        self.timer.start()
        threading.Thread(target=self._run, name="MouserScrollViewport", daemon=True).start()

    def _run(self):
        if not self._worker_lock.acquire(blocking=False):
            result = None
        else:
            try:
                result = self.resolver(self.selection)
            except Exception:
                result = None
            finally:
                self._worker_lock.release()
        try:
            self._result.emit(result)
        except RuntimeError:
            pass  # The controller may already have been deleted.

    @Slot(object)
    def _finish(self, result):
        if not self._active:
            return
        self.cancel()
        self.resolved.emit(result)

    def cancel(self):
        self._active = False
        self._cancelled = True
        self.timer.stop()
