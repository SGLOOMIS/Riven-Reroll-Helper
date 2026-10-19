"""Find riven cards again in each new frame, between OCR reads (from screenshots only).

After a read, each card's title + stats area is kept as a small greyscale template. In every
frame it's searched for near where the card last was, at sizes close to its last size (on the
cycle screen cards shrink and grow as they slide), using normalised correlation so the dimmed
unselected card still matches. That tells the session where each card is, whether it moved, and
whether it's still the same riven (a reroll replaces it, and its template stops matching).
"""

from dataclasses import dataclass

import cv2
import numpy as np

DOWNSCALE = 0.5          # search on a half-size frame: plenty for text blocks, 4x cheaper
MATCH = 0.62             # correlation needed to count as "the same card"


def to_gray_small(img):
    """PIL RGB image (or BGRA numpy array) -> half-size greyscale numpy array."""
    if not isinstance(img, np.ndarray):
        img = np.asarray(img.convert("L"))
    elif img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY if img.shape[2] == 4 else cv2.COLOR_RGB2GRAY)
    return cv2.resize(img, None, fx=DOWNSCALE, fy=DOWNSCALE, interpolation=cv2.INTER_AREA)


@dataclass
class Track:
    template: np.ndarray       # small greyscale
    origin: tuple              # (x, y) full-res top-left of the template at read time
    size: tuple                # (w, h) full-res
    x: float = 0.0             # where it is now (full-res top-left)
    y: float = 0.0
    scale: float = 1.0         # current size relative to read time
    score: float = 1.0
    lost: int = 0              # consecutive frames without a match
    bright: float = 0.0        # 95th-percentile brightness of the template (the card's text)
    dim: float = 1.0           # current text brightness relative to that (a dialog over the card: ~0.25)


class CardTracker:
    def __init__(self, match=MATCH):
        self.match = match
        self.tracks = []

    def set_cards(self, img, boxes):
        """Start following cards. boxes: each card's geometry (x, y, w, h, line height) from the read."""
        gray = to_gray_small(img)
        self.tracks = []
        for b in boxes:
            x, y, w, h = b[:4]
            line = b[4] if len(b) > 4 and b[4] else h / 4
            x0, y0 = max(0, x - line * 0.6), max(0, y - line * 2.6)   # include the riven's title
            x1, y1 = x + w + line * 0.6, y + h
            s = DOWNSCALE
            tpl = gray[int(y0 * s):int(y1 * s), int(x0 * s):int(x1 * s)]
            if tpl.size == 0 or min(tpl.shape) < 8:
                self.tracks.append(None)
                continue
            self.tracks.append(Track(tpl.copy(), (x0, y0), (x1 - x0, y1 - y0), x0, y0,
                                     bright=float(np.percentile(tpl, 95)) or 1.0))

    def clear(self):
        self.tracks = []

    def _search(self, t, gray, scales, window):
        """Best (score, x, y, scale) for track t; window=None searches the whole frame."""
        H, W = gray.shape
        s = DOWNSCALE
        best = (-1.0, t.x, t.y, t.scale)
        for k in scales:
            k = min(max(k, 0.55), 1.6)
            tw, th = int(t.template.shape[1] * k), int(t.template.shape[0] * k)
            if tw < 8 or th < 8 or tw > W or th > H:
                continue
            tpl = cv2.resize(t.template, (tw, th), interpolation=cv2.INTER_AREA)
            if window:
                # Around the last position; cards slide sideways much more than vertically.
                cx, cy = t.x * s, t.y * s
                mx, my = max(tw, W * window[0]), max(th, H * window[1])
                x0, y0 = int(max(0, cx - mx)), int(max(0, cy - my))
                x1, y1 = int(min(W, cx + tw + mx)), int(min(H, cy + th + my))
            else:
                x0, y0, x1, y1 = 0, 0, W, H
            region = gray[y0:y1, x0:x1]
            if region.shape[0] < th or region.shape[1] < tw:
                continue
            _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED))
            if score > best[0]:
                best = (score, (x0 + loc[0]) / s, (y0 + loc[1]) / s, k)
        return best

    def _wide(self, t, gray):
        """Find a card that jumped: coarse search along its row at quarter size, then refine.

        Cards slide sideways and change size, so the coarse pass covers the full
        width in a band around the card's height, at sizes 70-130% in 4% steps.
        """
        H, W = gray.shape
        s = DOWNSCALE
        band = int(H * 0.15)
        cy = int(t.y * s)
        y0, y1 = max(0, cy - band), min(H, cy + int(t.template.shape[0] * t.scale) + band)
        q = cv2.resize(gray[y0:y1], None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        tq = cv2.resize(t.template, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        coarse = (-1.0, 0, 0, 1.0)
        for k in np.arange(0.70, 1.31, 0.04):
            tw, th = int(tq.shape[1] * k), int(tq.shape[0] * k)
            if tw < 6 or th < 6 or tw > q.shape[1] or th > q.shape[0]:
                continue
            res = cv2.matchTemplate(q, cv2.resize(tq, (tw, th), interpolation=cv2.INTER_AREA), cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(res)
            if score > coarse[0]:
                coarse = (score, loc[0] * 2 / s, (y0 + loc[1] * 2) / s, float(k))
        if coarse[0] < 0:
            return coarse
        # Refine at the normal search size around the coarse hit.
        probe = Track(t.template, t.origin, t.size, coarse[1], coarse[2], coarse[3])
        return self._search(probe, gray, [round(coarse[3] * f, 3) for f in (0.975, 1.0, 1.025)], (0.02, 0.02))

    def update(self, gray_small):
        """Find every card in a new frame (from to_gray_small). Returns the list of tracks.

        Normally a card is looked for near where it was, at sizes close to its
        last one (cheap, and enough at animation frame rates). If that misses,
        the whole frame is searched at a wider range of sizes before giving up.
        """
        for t in self.tracks:
            if t is None:
                continue
            # Between animation frames a card moves a few dozen pixels and changes size by a few %.
            near = [round(t.scale * f, 3) for f in (0.965, 1.0, 1.035)]
            best = self._search(t, gray_small, near, (0.06, 0.05))
            if best[0] < self.match:
                best = max(best, self._wide(t, gray_small), key=lambda b: b[0])
            t.score = best[0]
            if t.score >= self.match:
                t.x, t.y, t.scale, t.lost = best[1], best[2], best[3], 0
            else:
                t.lost += 1
            # How bright the card's text is now: a dialog dims the whole screen behind it.
            s = DOWNSCALE
            h, w = int(t.template.shape[0] * t.scale), int(t.template.shape[1] * t.scale)
            region = gray_small[int(t.y * s):int(t.y * s) + h, int(t.x * s):int(t.x * s) + w]
            t.dim = float(np.percentile(region, 95)) / t.bright if region.size else 1.0
        return self.tracks

    def map_box(self, i, geometry):
        """A card's read-time geometry (x, y, w, h[, line height]) moved and scaled to where it is now."""
        t = self.tracks[i]
        x, y = t.x + (geometry[0] - t.origin[0]) * t.scale, t.y + (geometry[1] - t.origin[1]) * t.scale
        return (x, y) + tuple(v * t.scale for v in geometry[2:])
