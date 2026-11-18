"""Incremental, verified image registration for live scrolling capture.

OpenCV is imported only when a scrolling session starts. Proposal generation
and validation are deliberately separate: feature/template matches never by
themselves authorize adding pixels. No OCR, model, network or mouse hooks.

See THIRD_PARTY_NOTICES.md for the MIT ScrollSnap design reference.
"""
from __future__ import annotations

from PIL import Image

from core.compute_limits import registration_libraries
from core.scroll_compute import ScrollComputeClient, StitchError


class RegistrationStitcher:
    MAX_PIXELS = 32_000_000
    MAX_HEIGHT = 20_000
    MAX_FRAMES = 500
    PREVIEW_WIDTH = 232
    PREVIEW_HEIGHT = 300

    def __init__(self, frame, *, detect_content=False, isolated=False):
        # Lazy, headless builds avoid Qt plugin conflicts and ASR dependencies.
        self._compute = ScrollComputeClient() if isolated else None
        if not isolated:
            self.cv, self.np = registration_libraries()
        frame = frame.convert("RGB")
        if frame.width < 40 or frame.height < 80:
            raise StitchError("scroll_small")
        if frame.width * frame.height > self.MAX_PIXELS:
            raise StitchError("scroll_limit")
        self.parts = [frame.copy()]
        self.source_size = frame.size
        self.width, self.viewport_height = frame.size
        self.content_rect = None
        self.detect_content = detect_content
        self._reference = frame.copy()
        self._position = self._extent = self._append_count = 0
        self._undo_states = ()
        self.preview_revision = 0
        self._thumbnail = None

    @property
    def height(self):
        return sum(p.height for p in self.parts)

    def render(self):
        result = Image.new("RGB", (self.width, self.height))
        y = 0
        for part in self.parts:
            result.paste(part, (0, y))
            y += part.height
        return result

    def last_frame(self):
        return self._reference.copy()

    def preview_image(self):
        """Bounded thumbnail; never materialize the full-resolution long image."""
        if self._thumbnail is not None:
            return self._thumbnail
        scale = min(self.PREVIEW_WIDTH / self.width, self.PREVIEW_HEIGHT / self.height, 1)
        width, height = max(1, round(self.width * scale)), max(1, round(self.height * scale))
        result = Image.new("RGB", (width, height), "white")
        y = 0
        for part in self.parts:
            end = min(height, round((y + part.height) * scale))
            start = round(y * scale)
            if end > start:
                # Resize directly into a tiny patch, not a full-sized montage.
                result.paste(part.resize((width, end - start), Image.Resampling.BILINEAR), (0, start))
            y += part.height
        self._thumbnail = result
        return result

    def _arrays(self, image):
        rgb = self.np.asarray(image)
        # Retain ALL vertical pixels: short repeated lines and numeric suffixes
        # must not disappear on a 2512px portrait screen.
        width = min(320, image.width)
        small = self.cv.resize(rgb, (width, image.height), interpolation=self.cv.INTER_AREA)
        gray = self.cv.cvtColor(small, self.cv.COLOR_RGB2GRAY)
        return small, gray

    def _motion_rect(self, previous, current):
        """Infer bounds from same-coordinate changes, NOT a convenient match.

        Static detailed chrome outside the moving body is positive evidence
        for cropping. Without that evidence the entire selection is retained.
        Small blinking cursors and the outer scrollbar cannot define a body.
        """
        if self._compute is not None:
            rect = self._compute.query("motion", previous, current)
            return tuple(rect) if rect is not None else None
        np, cv = self.np, self.cv
        old, new = np.asarray(previous), np.asarray(current)
        delta = np.max(cv.absdiff(old, new), axis=2)
        h, w = delta.shape
        changed = delta > 8
        margin = min(12, max(1, w // 100))
        changed[:, :margin] = False
        changed[:, -margin:] = False
        # A blinking input caret is not part of the scrolling viewport.
        # Join neighboring glyph fragments before discarding tiny isolated
        # components; do not make a whole animated panel disappear.
        joined = cv.morphologyEx(changed.astype(np.uint8), cv.MORPH_CLOSE,
                                cv.getStructuringElement(cv.MORPH_RECT, (9, 3)))
        count, labels, stats, _ = cv.connectedComponentsWithStats(joined, connectivity=8)
        keep = np.zeros(count, dtype=np.uint8)
        minimum_area = max(60, w * h * .00004)
        for label in range(1, count):
            if stats[label, cv.CC_STAT_AREA] >= minimum_area and stats[label, cv.CC_STAT_WIDTH] > 4:
                keep[label] = 1
        changed &= keep[labels].astype(bool)
        rows = np.flatnonzero(changed.sum(axis=1) >= max(3, w * .003))
        cols = np.flatnonzero(changed.sum(axis=0) >= max(5, h * .008))
        if len(rows) < 24 or len(cols) < 24:
            return None
        top, bottom = int(rows[0]), int(rows[-1] + 1)
        left, right = int(cols[0]), int(cols[-1] + 1)
        gray = cv.cvtColor(old, cv.COLOR_RGB2GRAY)
        edge = cv.absdiff(gray, cv.GaussianBlur(gray, (5, 5), 0)) > 8
        fixed = edge & (delta <= 3)
        # Ignore a few stray pixels; require an actual detailed fixed panel.
        crop_y = (fixed[:max(0, top - 4)].sum() + fixed[min(h, bottom + 4):].sum()) > max(80, w * .15)
        crop_x = (fixed[:, :max(0, left - 12)].sum() + fixed[:, min(w, right + 12):].sum()) > max(100, h * .2)
        if not crop_x and not crop_y:
            return None
        x0, x1 = (max(0, left - 4), min(w, right + 4)) if crop_x else (0, w)
        y0, y1 = (top, bottom) if crop_y else (0, h)
        if x1 - x0 < 40 or y1 - y0 < 80:
            return None
        return x0, y0, x1, y1

    def _proposals(self, old, new):
        """Independent multi-column templates + ORB translation hypotheses."""
        cv, np = self.cv, self.np
        h, w = old.shape
        candidates = set()
        # A template excludes most fixed chrome; several columns allow narrow
        # text and a changing sidebar without letting an empty column vote.
        block = max(24, min(96, h // 7))
        for x0, x1 in ((w // 30, w * 29 // 30),
                       (w // 12, w // 2), (w // 3, w * 11 // 12)):
            before, after = old[:, x0:x1], new[:, x0:x1]
            for fraction in (.12, .38, .64, .82):
                y = min(h - block, int(h * fraction))
                template = after[y:y + block]
                if float(template.std()) < 2:
                    continue
                # SQDIFF retains absolute appearance and rejects inversion.
                errors = cv.matchTemplate(before, template, cv.TM_SQDIFF)
                for _ in range(4):
                    _, _, (x, row), _ = cv.minMaxLoc(errors)
                    d = row - y
                    if abs(d) <= h - max(40, h // 10):
                        candidates.add(d)
                    errors[max(0, row - 2):row + 3] = float("inf")
        # ORB is useful when text rendering changes between captured frames.
        # It is a proposer only: repetitive glyph matches are verified below.
        factor = min(1., 1100 / h)
        a = cv.resize(old, None, fx=factor, fy=factor, interpolation=cv.INTER_AREA) if factor < 1 else old
        b = cv.resize(new, (a.shape[1], a.shape[0]), interpolation=cv.INTER_AREA)
        orb = cv.ORB_create(nfeatures=1200, fastThreshold=12)
        ka, da = orb.detectAndCompute(a, None)
        kb, db = orb.detectAndCompute(b, None)
        if da is not None and db is not None and len(da) >= 2:
            votes = {}
            for pair in cv.BFMatcher(cv.NORM_HAMMING).knnMatch(db, da, k=2):
                if len(pair) != 2 or pair[0].distance >= .72 * pair[1].distance:
                    continue
                match = pair[0]
                bx, by = kb[match.queryIdx].pt
                ax, ay = ka[match.trainIdx].pt
                if abs(ax - bx) > 1.5:
                    continue
                d = round((ay - by) / factor)
                if abs(d) <= h - max(40, h // 10):
                    votes[d] = votes.get(d, 0) + 1
            for d, votes_count in sorted(votes.items(), key=lambda item: -item[1])[:10]:
                if votes_count >= 2:
                    candidates.update((d - 1, d, d + 1))
        return candidates

    def _score(self, old, new, edge_old, edge_new, d):
        np, cv = self.np, self.cv
        h = old.shape[0]
        a = old[max(0, d):min(h, h + d)]
        b = new[max(0, -d):min(h, h - d)]
        if len(a) < max(40, h // 10):
            return None
        informative = (edge_old[max(0, d):min(h, h + d)]
                       | edge_new[max(0, -d):min(h, h - d)])
        margin = max(1, old.shape[1] // 65)
        informative[:, :margin] = False
        informative[:, -margin:] = False
        row_info = informative.sum(axis=1)
        rows = row_info >= max(2, a.shape[1] // 100)
        if rows.sum() < min(24, len(a) * .15) or informative.sum() < 80:
            return None  # whitespace is never positive evidence
        delta = cv.absdiff(a, b).astype(np.float32)
        # Permit a small caret/animation but never drop a whole text column.
        errors = (np.maximum(delta - 3, 0) * informative).sum(axis=1) / np.maximum(row_info, 1)
        active = errors[rows]
        # Outliers are bounded at 8%, not the majority of the viewport.
        keep = max(1, int(len(active) * .92))
        trimmed = np.partition(active, keep - 1)[:keep]
        score = float(trimmed.mean())
        good = float(((delta <= 20) & informative).sum() / informative.sum())
        if score > 12 or good < .80:
            return None
        # Retain an untrimmed term so wrong repeated paragraphs with different
        # small line numbers cannot tie after discarding all distinguishing rows.
        return score + float(np.minimum(delta[informative], 60).mean()) * .25

    def _register(self, previous, current):
        if self._compute is not None:
            return self._compute.query("register", previous, current)
        old_rgb, old = self._arrays(previous)
        new_rgb, new = self._arrays(current)
        edge_old = self.cv.absdiff(old, self.cv.GaussianBlur(old, (3, 3), 0)) > 4
        edge_new = self.cv.absdiff(new, self.cv.GaussianBlur(new, (3, 3), 0)) > 4
        candidates = self._proposals(old, new)
        candidates.add(0)
        scores = []
        for d in candidates:
            score = self._score(old, new, edge_old, edge_new, d)
            if score is not None:
                scores.append((score, d))
        if not scores:
            raise StitchError("scroll_overlap")
        scores.sort()
        best, d = scores[0]
        # Neighboring integer estimates from antialiasing are one hypothesis;
        # a genuinely repeated page has several equally convincing positions.
        rivals = [(s, offset) for s, offset in scores[1:] if abs(offset - d) > 2]
        if rivals and rivals[0][0] <= best + max(.025, best * .08):
            raise StitchError("scroll_overlap")
        # A same-luminance but different-color page must not pass gray scoring.
        h = len(old)
        a = old_rgb[max(0, d):min(h, h + d)]
        b = new_rgb[max(0, -d):min(h, h - d)]
        if float(self.np.minimum(self.cv.absdiff(a, b), 60).mean()) > 10:
            raise StitchError("scroll_overlap")
        return d

    def append(self, frame):
        frame = frame.convert("RGB")
        if frame.size != self.source_size:
            raise StitchError("scroll_size")
        rect = self.content_rect
        previous = self._reference
        if rect is not None:
            current = frame.crop(rect)
        else:
            current = frame
            if self.detect_content and self._append_count == 0:
                rect = self._motion_rect(previous, current)
                if rect is not None:
                    previous, current = previous.crop(rect), current.crop(rect)
        if previous.tobytes() == current.tobytes():
            raise StitchError("scroll_unchanged")
        d = self._register(previous, current)
        position = self._position + d
        # Never prepend content above the initial selection or fabricate a gap.
        if position < 0:
            raise StitchError("scroll_overlap")
        if d == 0:
            raise StitchError("scroll_unchanged")
        extent = max(self._extent, position)
        width, viewport_height = current.size
        extra = extent - self._extent
        height = viewport_height + extent
        if (height > self.MAX_HEIGHT or height * width > self.MAX_PIXELS
                or self._append_count >= self.MAX_FRAMES):
            raise StitchError("scroll_limit")
        # Only commit after validation. References/parts are immutable, so the
        # GUI can copy a snapshot into a worker without pixel-data races.
        state = (tuple(self.parts), self._reference, self._position, self._extent,
                 self.content_rect, self.width, self.viewport_height, self._append_count)
        self._undo_states = (self._undo_states + (state,))[-2:]
        self._reference, self._position = current, position
        self.content_rect = rect
        if rect is not None and self._append_count == 0:
            self.parts = [previous]
            self.width, self.viewport_height = width, viewport_height
        if extra:
            # Join inside the VERIFIED overlap, rather than retaining the
            # entire old bottom edge forever. A floating "jump to bottom"
            # button otherwise gets frozen into every appended strip.
            # The next frame reveals the unobscured pixels behind its older
            # position. Refresh the old tail from those real pixels; do not
            # inpaint, stretch, erase, or guess any covered text.
            overlap = viewport_height - extra
            seam = overlap // 2
            retained_height = position + seam
            parts, retained = [], 0
            for part in self.parts:
                available = retained_height - retained
                if available <= 0:
                    break
                if part.height <= available:
                    parts.append(part)
                    retained += part.height
                else:
                    parts.append(part.crop((0, 0, width, available)))
                    retained += available
            parts.append(current.crop((0, seam, width, viewport_height)))
            self.parts = parts
        self._extent = extent
        self._append_count += 1
        self.preview_revision += 1
        self._thumbnail = None
        return extra

    def undo(self):
        if not self._undo_states:
            return False
        (parts, self._reference, self._position, self._extent, self.content_rect,
         self.width, self.viewport_height, self._append_count) = self._undo_states[-1]
        self.parts = list(parts)
        self._undo_states = self._undo_states[:-1]
        self.preview_revision += 1
        self._thumbnail = None
        return True

    def close(self):
        if self._compute is not None:
            self._compute.close()
