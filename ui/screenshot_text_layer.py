"""Text coordinates over a frozen bitmap. Never forwards input to other apps."""
from PySide6.QtCore import QPointF, QRectF


class FrozenTextLayer:
    def __init__(self, glyphs, origin):
        self.glyphs = tuple(glyphs)
        self.boxes = tuple(QRectF(g["box"][0] + origin.x(), g["box"][1] + origin.y(),
                                 g["box"][2]-g["box"][0], g["box"][3]-g["box"][1])
                           for g in glyphs)
        self.anchor = self.caret = None

    def clear(self):
        self.anchor = self.caret = None

    def hit(self, point):
        if point is None:
            return None
        return next((i for i, box in enumerate(self.boxes) if box.contains(point)), None)

    def _caret(self, point, index):
        return index + (point.x() > self.boxes[index].center().x())

    def begin(self, point):
        self.clear()
        index = self.hit(point)
        if index is None:
            return False
        self.anchor = self.caret = self._caret(point, index)
        return True

    def extend(self, point):
        if self.anchor is None or point is None or not self.boxes:
            return
        index = self.hit(point)
        if index is None:
            def distance(box):
                dx = max(box.left()-point.x(), 0, point.x()-box.right())
                dy = max(box.top()-point.y(), 0, point.y()-box.bottom())
                return dx*dx + dy*dy
            index = min(range(len(self.boxes)), key=lambda i: distance(self.boxes[i]))
        self.caret = self._caret(point, index)

    def select_all(self):
        self.anchor, self.caret = 0, len(self.glyphs)

    def selected_range(self):
        return (0, 0) if self.anchor is None else sorted((self.anchor, self.caret))

    def selected_boxes(self):
        start, end = self.selected_range()
        return self.boxes[start:end]

    def selected_text(self):
        start, end = self.selected_range()
        return "".join(("" if i == start else g["prefix"]) + g["text"]
                       for i, g in enumerate(self.glyphs[start:end], start))


def logical_fragments(box, capture):
    """Split physical glyph highlights on monitor boundaries, including mixed DPI."""
    for monitor in capture.monitor_maps:
        physical = monitor.physical.translated(-capture.physical_rect.left,
                                               -capture.physical_rect.top)
        piece = box.intersected(QRectF(physical.left, physical.top, physical.width, physical.height))
        if piece.isEmpty():
            continue
        sx, sy = monitor.logical.width/physical.width, monitor.logical.height/physical.height
        yield QRectF(monitor.logical.left+(piece.left()-physical.left)*sx,
                     monitor.logical.top+(piece.top()-physical.top)*sy,
                     piece.width()*sx, piece.height()*sy)
