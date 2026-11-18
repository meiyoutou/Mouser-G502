"""Frozen-image magnification and conservative, downward-only scrolling stitch."""
from __future__ import annotations

import hashlib

from PIL import Image, ImageChops, ImageStat
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QColor, QPainter, QPen
from core.scroll_compute import StitchError


def magnifier_patch(image, point, radius=7):
    """Return source pixels without resampling or changing their coordinate space."""
    x = max(0, min(image.width() - 1, int(point.x())))
    y = max(0, min(image.height() - 1, int(point.y())))
    area = QRect(x - radius, y - radius, radius * 2 + 1, radius * 2 + 1)
    area = area.intersected(image.rect())
    return image.copy(area), QPoint(x - area.x(), y - area.y()), QPoint(x, y)


def draw_magnifier(painter: QPainter, image, source_point, local_point, bounds):
    patch, center, pixel = magnifier_patch(image, source_point)
    side, height = 150, 182
    x, y = local_point.x() + 22, local_point.y() + 24
    if x + side > bounds.right():
        x = local_point.x() - side - 22
    if y + height > bounds.bottom():
        y = local_point.y() - height - 22
    x, y = max(bounds.left(), x), max(bounds.top(), y)
    box = QRect(x, y, side, side)
    painter.save()
    painter.fillRect(QRect(x, y, side, height), QColor("#101826"))
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
    painter.drawImage(box, patch)
    px = x + (center.x() + .5) * side / patch.width()
    py = y + (center.y() + .5) * side / patch.height()
    painter.setPen(QPen(QColor("#ef4444"), 1))
    painter.drawLine(int(px), y, int(px), y + side)
    painter.drawLine(x, int(py), x + side, int(py))
    color = image.pixelColor(pixel).name().upper()
    painter.setPen(QColor("white"))
    painter.drawRect(box.adjusted(0, 0, -1, -1))
    painter.drawText(QRect(x + 4, y + side + 2, side - 8, 28),
                     f"{pixel.x()}, {pixel.y()}  {color}")
    painter.restore()


class ScrollStitcher:
    MAX_PIXELS = 32_000_000
    MAX_HEIGHT = 20_000
    # Automatic capture can append small strips rather than whole viewports.
    # Pixel/height limits still bound image memory independently of strip count.
    MAX_FRAMES = 500

    def __init__(self, frame, *, detect_content=False):
        frame = frame.convert("RGB")
        if frame.width < 40 or frame.height < 80:
            raise StitchError("scroll_small")
        if frame.width * frame.height > self.MAX_PIXELS:
            raise StitchError("scroll_limit")
        self.parts = [frame.copy()]
        self.viewport_height = frame.height
        self.width = frame.width
        self.detect_content = detect_content
        self.content_rect = None
        self.source_size = frame.size
        self._reference = None
        self._undo_states = ()
        self._append_count = 0

    @property
    def height(self):
        return sum(part.height for part in self.parts)

    def render(self):
        result = Image.new("RGB", (self.width, self.height))
        y = 0
        for part in self.parts:
            result.paste(part, (0, y))
            y += part.height
        return result

    def last_frame(self):
        # Recover the last viewport from unique strips, not full-frame history.
        result = Image.new("RGB", (self.width, self.viewport_height))
        remaining = self.viewport_height
        for part in reversed(self.parts):
            take = min(remaining, part.height)
            result.paste(part.crop((0, part.height - take, self.width, part.height)), (0, remaining - take))
            remaining -= take
            if not remaining:
                break
        return result

    @staticmethod
    def _row_tokens(image):
        """Native RGB row fingerprints; don't blur away small text/numbers."""
        rgb = image if image.mode == "RGB" else image.convert("RGB")
        data = memoryview(rgb.tobytes())
        stride = rgb.width * 3
        return [hashlib.blake2b(data[start:start + stride], digest_size=16).digest()
                for start in range(0, len(data), stride)]

    @classmethod
    def _exact_overlap(cls, previous, current):
        """Find all suffix/prefix matches in linear row time, then verify RGB.

        Narrow gray samples can tie on white space even when a full text page
        has one unambiguous alignment. Never treat those sampling ties as proof
        of ambiguity: first compare actual rows, without vertical downsampling.
        """
        old, new = cls._row_tokens(previous), cls._row_tokens(current)
        sequence = new + [None] + old
        prefix = [0] * len(sequence)
        for index in range(1, len(sequence)):
            matched = prefix[index - 1]
            while matched and sequence[index] != sequence[matched]:
                matched = prefix[matched - 1]
            if sequence[index] == sequence[matched]:
                matched += 1
            prefix[index] = matched

        # A few equal blank rows are not evidence of scrolling alignment.
        distinct = set()
        informative = current.height + 1
        for index, token in enumerate(new):
            distinct.add(token)
            if len(distinct) >= 4:
                informative = max(24, index + 1)
                break
        overlap, best = prefix[-1], None
        while overlap >= informative:
            if overlap < current.height:  # no movement is handled by overlap()
                patch = current.crop((0, 0, current.width, overlap))
                before = previous.crop((0, previous.height - overlap,
                                        previous.width, previous.height))
                # Fingerprints only locate candidates. Actual pixels decide.
                if (ImageChops.difference(before, patch).getbbox() is None
                        and sum(ImageStat.Stat(patch).stddev) / 3 >= 4):
                    if best is not None and best - overlap > 5:
                        raise StitchError("scroll_overlap")
                    if best is None:
                        best = overlap
            overlap = prefix[overlap - 1]
        return best

    @classmethod
    def _stripe_overlap(cls, previous, current):
        """Agree on native-pixel alignment in independent horizontal regions.

        A thin scrollbar or blinking caret must not invalidate every full-width
        row fingerprint. This only proposes offsets: actual full-overlap RGB
        error still has to meet the existing conservative validation threshold.
        """
        votes = {}
        w, h = current.size
        for index in range(12):
            left, right = round(w * index / 12), round(w * (index + 1) / 12)
            if right - left < 6:
                continue
            try:
                overlap = cls._exact_overlap(previous.crop((left, 0, right, h)),
                                             current.crop((left, 0, right, h)))
            except StitchError:
                continue
            if overlap is not None:
                votes[overlap] = votes.get(overlap, 0) + 1
        verified = []
        for overlap, count in votes.items():
            before = previous.crop((0, h - overlap, w, h))
            after = current.crop((0, 0, w, overlap))
            diff = ImageChops.difference(before, after)
            difference = sum(ImageStat.Stat(diff).mean) / 3
            margin = min(8, w // 20)
            inner = diff.crop((margin, 0, w - margin, overlap)).getbbox()
            # One unique stripe is sufficient only when the rest is actually
            # identical except for a tiny caret, not just close on average.
            strict = (inner is None or
                      (inner[2] - inner[0] <= 4 and inner[3] - inner[1] <= 40))
            if (difference <= 5 and (count >= 2 or strict)
                    and sum(ImageStat.Stat(after).stddev) / 3 >= 4):
                verified.append(overlap)
        if len(verified) > 1:
            raise StitchError("scroll_overlap")
        return verified[0] if verified else None

    @classmethod
    def overlap(cls, previous, current):
        if previous.size != current.size:
            raise StitchError("scroll_size")
        if ImageChops.difference(previous, current).getbbox() is None:
            raise StitchError("scroll_unchanged")
        exact = cls._exact_overlap(previous, current)
        if exact is not None:
            return exact
        striped = cls._stripe_overlap(previous, current)
        if striped is not None:
            return striped
        h = current.height
        # Preserve every vertical pixel: downsampling rows can lose odd-pixel
        # scroll offsets, especially on mixed-DPI text. Only shrink width.
        scaled_h = h
        old = previous.convert("L").resize((32, scaled_h)).tobytes()
        new = current.convert("L").resize((32, scaled_h)).tobytes()
        minimum = max(16, round(24 * scaled_h / h))
        candidates = []
        for overlap in range(minimum, scaled_h - 7):
            rows = sorted({round(i * (overlap - 1) / 19) for i in range(20)})
            score, count = 0, 0
            for row in rows:
                a, b = (scaled_h - overlap + row) * 32, row * 32
                for col in range(2, 30, 2):
                    score += abs(old[a + col] - new[b + col])
                    count += 1
            candidates.append((score / count, overlap))
        best, guessed = min(candidates)
        # Dissimilar / repeated patterns are never silently accepted.
        alternative = min((score for score, value in candidates if abs(value - guessed) > 5), default=255)
        if best > 8 or alternative - best < .7:
            raise StitchError("scroll_overlap")
        guess = round(guessed * h / scaled_h)
        radius = max(2, round(h / scaled_h) + 1)
        refined = []
        for overlap in range(max(24, guess - radius), min(h - 8, guess + radius) + 1):
            old_patch = previous.crop((0, h - overlap, previous.width, h))
            new_patch = current.crop((0, 0, current.width, overlap))
            difference = sum(ImageStat.Stat(ImageChops.difference(old_patch, new_patch)).mean) / 3
            refined.append((difference, overlap))
        difference, overlap = min(refined)
        patch = current.crop((0, 0, current.width, overlap))
        if difference > 5 or sum(ImageStat.Stat(patch).stddev) / 3 < 4:
            raise StitchError("scroll_overlap")
        return overlap

    def append(self, frame):
        frame = frame.convert("RGB")
        if frame.size != self.source_size:
            raise StitchError("scroll_size")
        if self.content_rect is not None:
            frame = frame.crop(self.content_rect)
        previous = self._reference if self._reference is not None else self.last_frame()
        try:
            if self.content_rect is not None:
                # White padding can conceal a few pixels of a fixed top/bottom
                # panel in the inferred bounds. Match the interior, and replace
                # the previous bottom margin instead of repeating it at seams.
                guard = min(24, frame.height // 8)
                inner_old = previous.crop((0, guard, self.width, previous.height - guard))
                inner_new = frame.crop((0, guard, self.width, frame.height - guard))
                inside = self.overlap(inner_old, inner_new)
                overlap = frame.height - (inner_new.height - inside)
            elif self.detect_content:
                # With unknown fixed chrome, a low *average* gray error is not
                # proof of motion: repainting/hover can look like a short scroll.
                if ImageChops.difference(previous, frame).getbbox() is None:
                    raise StitchError("scroll_unchanged")
                overlap = self._exact_overlap(previous, frame)
                if overlap is None:
                    overlap = self._stripe_overlap(previous, frame)
                    if overlap is not None:
                        from ui.screenshot_motion import _mask
                        changes = _mask(
                            previous.crop((0, previous.height - overlap, self.width, previous.height)),
                            frame.crop((0, 0, self.width, overlap)))
                        if changes.histogram()[255] > self.width * overlap * .015:
                            overlap = None
                if overlap is None:
                    raise StitchError("scroll_overlap")
            else:
                overlap = self.overlap(previous, frame)
        except StitchError as exc:
            if (str(exc) != "scroll_overlap" or not self.detect_content
                    or self.content_rect is not None or len(self.parts) != 1):
                raise
            from ui.screenshot_motion import infer_scroll_crop
            found = infer_scroll_crop(previous, frame, exact_overlap=self._exact_overlap)
            if found is None:
                raise
            rect, shift = found
            previous, frame = previous.crop(rect), frame.crop(rect)
            overlap = frame.height - shift
            if (previous.height + shift > self.MAX_HEIGHT
                    or previous.width * (previous.height + shift) > self.MAX_PIXELS
                    or self._append_count >= self.MAX_FRAMES - 1):
                raise StitchError("scroll_limit")
            # Analysis runs on a private snapshot. Commit crop and append as
            # one successful result, never discard prior accepted fragments.
            self.content_rect = rect
            self.parts = [previous]
            self.width, self.viewport_height = previous.size
        extra = frame.height - overlap
        if (self.height + extra > self.MAX_HEIGHT
                or self.width * (self.height + extra) > self.MAX_PIXELS
                or self._append_count >= self.MAX_FRAMES - 1):
            raise StitchError("scroll_limit")
        if self.content_rect is not None:
            guard = min(24, frame.height // 8)
            self._undo_states = (*self._undo_states, tuple(self.parts))
            remaining = guard
            while remaining:
                tail = self.parts.pop()
                take = min(remaining, tail.height)
                if tail.height > take:
                    self.parts.append(tail.crop((0, 0, self.width, tail.height - take)))
                remaining -= take
            self.parts.append(frame.crop((0, overlap - guard, frame.width, frame.height)))
            self._reference = frame
        else:
            self.parts.append(frame.crop((0, overlap, frame.width, frame.height)))
        self._append_count += 1
        return extra

    def undo(self):
        if self._undo_states:
            self.parts = list(self._undo_states[-1])
            self._undo_states = self._undo_states[:-1]
            self._reference = None
            self._append_count -= 1
            return True
        if len(self.parts) == 1:
            return False
        self.parts.pop()
        self._append_count -= 1
        return True
