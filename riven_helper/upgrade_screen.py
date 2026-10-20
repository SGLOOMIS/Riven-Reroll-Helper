"""The weapon upgrade screen ("UPGRADES/ SPECTRA VANDAL [30]"): is it on screen, and for which weapon?

The screen itself is recognised by its CAPACITY and CONFIG A/B/C labels, which OCR reads reliably.
The weapon's name is in the header, in a wide letter-spaced display font that OCR reads badly
("QIJPGRADES/", or just "[30]"). When the normal OCR text doesn't contain it, the header is read
on its own: its letters are picked out (whatever the UI theme's colours), the extra letter
spacing removed, and the result read a few ways; the weapon name found most often wins.

UpgradeScreen keeps the answer steady: once the weapon is known it's kept for as long as the
screen is, and the header is only read again when its pixels change (another weapon selected).
"""

import difflib
import re
from collections import Counter

import cv2
import numpy as np
from PIL import Image

from .gamedata import norm

# "UPGRADES/ <name>": anchored on "PGRADES" because the "U" is often misread, slash optional.
UPGRADE_RE = re.compile(r"P\s*G\s*R\s*A\s*D\s*E\s*S?\s*[/|\\]?\s*(?P<name>.+)", re.I)
CAPACITY_RE = re.compile(r"\bCAPACITY\b", re.I)
CONFIG_RE = re.compile(r"\bCONFIG\s*[ABC]\b", re.I)
HEADER_AREA = (0.097, 0.025, 0.62, 0.095)        # the header text, as fractions of the window (x0, y0, x1, y1)


COUNT_RE = re.compile(r"^\W*\d+\s*/\s*\d+\W*$")      # the capacity count beside CAPACITY ("3/60")


def selected_config(img, lines):
    """The name of the selected config tab ("CONFIG A", or a name the player gave it, like "Main"), or None.

    The tabs sit in a row with the "CONFIG B" / "CONFIG C" labels; the selected one has a bar under
    its name. That bar is found as pixels standing out from the strip just below each name.
    """
    from .parse import _segments
    labels = [s for s in _segments(lines) if CONFIG_RE.search(s.text)]
    if not labels:
        return None
    y = float(np.median([s.y for s in labels]))
    h = float(np.median([s.h for s in labels]))
    tabs = [s for s in _segments(lines) if abs(s.y - y) < 0.8 * h
            and not CAPACITY_RE.search(s.text) and not COUNT_RE.match(s.text)]
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    scores = []
    for tab in tabs:
        strip = rgb[int(tab.bottom + 2):int(tab.bottom + 0.9 * h), int(tab.x):int(tab.x + tab.w)]
        if not strip.size:
            continue
        background = np.median(strip.reshape(-1, 3), axis=0)
        scores.append((float(np.mean(np.abs(strip - background).max(axis=2) > 60)), tab.text.strip()))
    scores.sort(reverse=True)
    if not scores or scores[0][0] < 0.08 or (len(scores) > 1 and scores[1][0] > scores[0][0] / 2):
        return None
    return scores[0][1]


def _texts(lines):
    return [" ".join(w[0] for w in line) for line in lines]


def is_upgrade_screen(lines):
    texts = _texts(lines)
    return any(CAPACITY_RE.search(t) for t in texts) and any(CONFIG_RE.search(t) for t in texts)


def weapon_in(text, gamedata):
    """A weapon named in header text (normalized), ignoring the "[30]" rank; loose match as a last resort."""
    text = re.sub(r"\[\s*\d+\s*\]", " ", text)
    name = gamedata.find_weapon_in_text(text)
    if name:
        return name
    close = difflib.get_close_matches(norm(text), gamedata.weapon_names, n=1, cutoff=0.84)
    return close[0] if close else None


def weapon_from_text(lines, gamedata):
    """The weapon after "UPGRADES/" in already OCR'd lines, or None."""
    for text in _texts(lines):
        m = UPGRADE_RE.search(text)
        name = weapon_in(m.group("name"), gamedata) if m else None
        if name:
            return name
    return None


# -- reading the header image itself ---------------------------------------------------------
def header_mask(img):
    """The header's letters as a boolean array, trimmed to the text rows.

    Works for every UI theme: light or dark, one colour or two ("UPGRADES/" and the weapon's name
    can differ). A pixel is text when it stands out from its local background (the median of the
    area around it, which the thin letters barely change), in either direction. Of what stands out,
    only letter-like shapes on one line are kept: not the underline, icons or background art.
    The header is first scaled to its size at 1080p, which the sizes here are measured for.
    """
    _, letters = header_pixels(img)
    rows = np.where(letters.any(axis=1))[0]
    return letters[rows.min():rows.max() + 1] if len(rows) else letters[:1]


def header_pixels(img):
    """(the header as an RGB array at 1080p size, its letters as a boolean array of the same size)."""
    W, H = img.size
    x0, y0, x1, y1 = HEADER_AREA
    crop = img.crop((int(W * x0), int(H * y0), int(W * x1), int(H * y1)))
    if abs(H - 1080) > 20:
        crop = crop.resize((round(crop.width * 1080 / H), round(crop.height * 1080 / H)), Image.LANCZOS)
    rgb = np.asarray(crop.convert("RGB"))
    background = cv2.medianBlur(rgb, 41)
    contrast = np.abs(rgb.astype(np.int16) - background.astype(np.int16)).max(axis=2)
    # Clearly different, and at least half as different as the strongest text: this leaves out the
    # letters' soft edges, which would make them too bold for OCR.
    mask = (contrast > 45) & (contrast > 0.5 * np.percentile(contrast, 99.5))
    mask[mask.mean(axis=1) > 0.5] = False                 # the header's underline
    return rgb, _letters(mask)


def _letters(mask):
    """Keep the connected shapes that are letter-sized and sit on the same line as the first words."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    shapes = [(i, x, y, w, h) for i, (x, y, w, h, _) in enumerate(stats) if i and h >= 12]
    first = [sh for sh in shapes if sh[1] < mask.shape[1] * 0.4]
    if not first:
        return np.zeros_like(mask)
    letter_h = float(np.median([h for *_, h in first]))
    top = float(np.median([y for _, _, y, _, h in first if abs(h - letter_h) <= 0.15 * letter_h] or [0]))
    keep = [i for i, x, y, w, h in shapes
            if x > 0                                      # not the "+" button's edge at the far left
            and 0.75 * letter_h <= h <= 1.35 * letter_h and w <= 1.3 * letter_h
            and abs(y - top) <= 0.2 * letter_h + 2]
    return np.isin(labels, keep)


def _glyphs(mask):
    """Each glyph as (first column, last column + 1). Specks from the icons beside the text are dropped:
    they're much shorter than a letter (narrow letters like "I" are full height, so height is the test)."""
    cols = mask.any(axis=0)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], cols.astype(np.int8), [0]))))
    runs = list(zip(edges[::2], edges[1::2]))
    heights = [int(mask[:, s:e].any(axis=1).sum()) for s, e in runs]
    tall = float(np.median(heights)) if heights else 0.0
    return [r for r, h in zip(runs, heights) if h >= tall * 0.6]


def _respaced(mask, runs, letter_gap=3, word_gap=14, widen=False):
    """The glyphs with normal letter spacing (keeping word gaps), black on white, or None.

    widen: also make the letters wider and their strokes thicker. The header font is so condensed
    (tall thin letters, "A" drawn as a bare "Λ") that OCR often can't read it as it is.
    """
    if not runs:
        return None
    gaps = [b[0] - a[1] for a, b in zip(runs, runs[1:])]
    median = float(np.median(gaps)) if gaps else 0.0
    pieces = []
    for i, (s, e) in enumerate(runs):
        if i:
            pieces.append(np.zeros((mask.shape[0], word_gap if gaps[i - 1] > 1.8 * median else letter_gap), bool))
        pieces.append(mask[:, s:e])
    out = np.pad(np.hstack(pieces), 12).astype(np.uint8) * 255
    if widen:
        h = mask.shape[0]
        out = cv2.resize(out, (int(out.shape[1] * 1.75), out.shape[0]), interpolation=cv2.INTER_LINEAR)
        stroke = max(2, round(h / 14))
        out = cv2.dilate(out, np.ones((stroke, stroke), np.uint8))
    return Image.fromarray(255 - out).convert("RGB")


def _capitals(text):
    """The header is all capitals, so lower-case letters OCR returns for it are misread capitals:
    the font's bare "Λ" comes out as "h", and "I" as "l" (or "1" between letters)."""
    text = re.sub(r"(?<=[A-Za-z])1|1(?=[A-Za-z])", "I", text)
    return text.translate(str.maketrans({"h": "A", "l": "I"}))


def weapon_from_header(img, ocr, gamedata):
    """Read the weapon name from the header image (normalized), or None.

    Readings: the whole header; the glyphs after "UPGRADES/" (always the first 9); those up to a
    taller "[" (the rank); and those without the last word. Each as it is and widened, at a few
    sizes. An exact name scores 2 votes, a loose match 1; a reading of just the first word
    ("SPECTRA") also counts for the full name ("SPECTRA VANDAL").
    """
    mask = header_mask(img)
    runs = _glyphs(mask)
    if len(runs) < 10:
        return None
    letter_h = float(np.median([int(mask[:, s:e].any(axis=1).sum()) for s, e in runs[:8]]))
    name = runs[9:]
    readings = [runs, name]
    rank_at = next((i for i, (s, e) in enumerate(name) if mask[:, s:e].any(axis=1).sum() > letter_h + 1), None)
    if rank_at:
        readings.append(name[:rank_at])
    gaps = [b[0] - a[1] for a, b in zip(name, name[1:])]
    word_breaks = [i + 1 for i, g in enumerate(gaps) if gaps and g > 1.8 * float(np.median(gaps))]
    if word_breaks:
        readings.append(name[:word_breaks[-1]])

    votes = Counter()
    for runs_, widen in [(r, w) for r in readings for w in (False, True)]:
        image = _respaced(mask, runs_, widen=widen)
        for scale in ((1.0, 1.5) if widen else (1.0, 1.25, 1.5, 2.0)):
            text = " ".join(_texts(ocr.read(image, scale)))
            m = UPGRADE_RE.search(text)
            text = _capitals(m.group("name") if m else text)
            exact = gamedata.find_weapon_in_text(text)
            if exact:
                votes[exact] += 2
            else:
                close = weapon_in(text, gamedata)
                if close:
                    votes[close] += 1
    if not votes:
        return None
    merged = Counter(votes)
    for short in votes:
        for long in votes:
            if long != short and long.startswith(short + " "):
                merged[long] += votes[short]
    return max(merged, key=lambda n: (merged[n], len(n)))


def detect_weapon(img, lines, ocr, gamedata):
    """The weapon on the upgrade screen in this frame (normalized name), or None."""
    name = weapon_from_text(lines, gamedata)
    if name or not is_upgrade_screen(lines):
        return name
    return weapon_from_header(img, ocr, gamedata)


def _fingerprint(img):
    """A small picture of the header, to notice when another weapon is selected."""
    mask = header_mask(img)
    if mask.size == 0:
        return None
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((160, 12))) > 127


class UpgradeScreen:
    """Which weapon's upgrade screen is open, kept steady across frames.

    update() returns the weapon (normalized name) or None. Reading the header can fail on a given
    frame, so a known weapon is kept while the CAPACITY / CONFIG labels are there, and only cleared
    after two frames without them.
    """

    def __init__(self):
        self.weapon = None
        self.config = None               # the selected config tab's name
        self._fingerprint = None
        self._misses = 0

    def update(self, img, lines, ocr, gamedata):
        if not is_upgrade_screen(lines):
            self._misses += 1
            if self._misses >= 2:
                self.weapon = self.config = None
            return self.weapon
        self._misses = 0
        self.config = selected_config(img, lines) or self.config
        fingerprint = _fingerprint(img)
        same = (self._fingerprint is not None and fingerprint is not None
                and self._fingerprint.shape == fingerprint.shape
                and float(np.mean(self._fingerprint != fingerprint)) < 0.04)
        if self.weapon is None or not same:
            self.weapon = detect_weapon(img, lines, ocr, gamedata)
            self._fingerprint = fingerprint if self.weapon else None
        return self.weapon

    def clear(self):
        self.weapon, self.config, self._fingerprint, self._misses = None, None, None, 0
