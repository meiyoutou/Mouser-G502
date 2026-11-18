"""Infer a scrolling pixel rectangle when accessibility provides no viewport.

Only the two user-selected images are examined. No desktop, UIA, text/OCR,
third-party imaging runtime or target-window input is used here.
"""
from collections import Counter, defaultdict
import hashlib

from PIL import ImageChops, ImageStat


def _tokens(image):
    data = memoryview(image.tobytes())
    stride = image.width * 3
    return [hashlib.blake2b(data[i:i + stride], digest_size=12).digest()
            for i in range(0, len(data), stride)]


def _mask(before, after):
    channels = ImageChops.difference(before, after).split()
    maximum = ImageChops.lighter(ImageChops.lighter(channels[0], channels[1]), channels[2])
    return maximum.point([0] * 4 + [255] * 252)


def _runs(values):
    start = None
    for index, bad in enumerate(list(values) + [True]):
        if not bad and start is None:
            start = index
        elif bad and start is not None:
            yield start, index
            start = None


def infer_scroll_crop(previous, current, *, exact_overlap):
    """Return one unambiguous (rectangle, shift), or None.

    Internal stripe anchors propose translations, then a large rectangle of
    actual aligned pixels must verify them. The existing exact matcher also
    rejects periodic/repeated content. No error threshold is loosened.
    """
    w, h = previous.size
    minimum = max(100, h // 4)
    if current.size != previous.size or w < 160 or h < 180:
        return None
    votes, bands = Counter(), []
    for index in range(12):
        left, right = w * index // 12, w * (index + 1) // 12
        a = _tokens(previous.crop((left, 0, right, h)))
        b = _tokens(current.crop((left, 0, right, h)))
        locations = defaultdict(list)
        for y, token in enumerate(a):
            locations[token].append(y)
        counts = Counter(b)
        for y, token in enumerate(b):
            places = locations.get(token, ())
            # White rows and repeating glyph patterns are not anchors.
            if 0 < len(places) <= 4 and counts[token] <= 4:
                for old_y in places:
                    shift = old_y - y
                    if 0 < shift <= h - minimum:
                        votes[shift] += 1
        bands.append((left, right))
    confirmed = {}
    motion = _mask(previous, current)
    total_motion = motion.histogram()[255]
    for shift, count in votes.most_common(6):
        if count < 12:
            continue
        overlap = h - shift
        aligned = _mask(previous.crop((0, shift, w, h)),
                        current.crop((0, 0, w, overlap)))
        candidates = []
        for left, right in bands:
            for top, end in _runs(aligned.crop((left, 0, right, overlap)).getprojection()[1]):
                if end - top < minimum:
                    continue
                patch = current.crop((left, top, right, end))
                if sum(ImageStat.Stat(patch).stddev) / 3 < 8:
                    continue
                # Exclude an unchanged fixed panel, even if its texture repeats.
                moved = motion.crop((left, top, right, end))
                if ImageStat.Stat(moved).mean[0] < 2:
                    continue
                cols = aligned.crop((0, top, w, end)).getprojection()[0]
                span = next(((a, b) for a, b in _runs(cols)
                             if a <= left and b >= right), None)
                if span is None or span[1] - span[0] < max(120, w // 4):
                    continue
                x0, x1 = span
                rows = aligned.crop((x0, 0, x1, overlap)).getprojection()[1]
                extent = next(((a, b) for a, b in _runs(rows)
                               if a <= top and b >= end), None)
                if extent is None:
                    continue
                y0, y1 = extent[0], extent[1] + shift
                if y1 - y0 < max(160, h * .4):
                    continue
                rect = (x0, y0, x1, y1)
                # Never "solve" a mismatch by cropping away moving numbers or
                # other disambiguating content. Almost all motion must be
                # inside the candidate; only a tiny external caret may blink.
                inside_motion = motion.crop(rect).histogram()[255]
                if total_motion - inside_motion > max(96, total_motion * .015):
                    continue
                before, after = previous.crop(rect), current.crop(rect)
                try:
                    matched = exact_overlap(before, after)
                except ValueError:
                    continue
                if matched != after.height - shift:
                    continue
                candidates.append(rect)
        if candidates:
            confirmed[shift] = max(candidates, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    if len(confirmed) != 1:
        return None
    shift, rect = next(iter(confirmed.items()))
    return rect, shift
