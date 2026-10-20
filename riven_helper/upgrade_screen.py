"""The weapon upgrade screen ("UPGRADES/ SPECTRA VANDAL [30]"): is it on screen, and for which weapon?

The screen itself is recognised by its CAPACITY and CONFIG A/B/C labels, which OCR reads reliably.
The weapon's name is in the header, in a wide letter-spaced display font that OCR reads badly
("QIJPGRADES/", or just "[30]"). When the normal OCR text doesn't contain it, the header is read
on its own: its text (in the UI theme's colour) is isolated, the extra letter spacing removed,
and the result read a few ways; the weapon name found most often wins.

UpgradeScreen keeps the answer steady: once the weapon is known it's kept for as long as the
screen is, and the header is only read again when its pixels change (another weapon selected).
"""

import difflib
import re
from collections import Counter

import numpy as np
from PIL import Image

from .gamedata import norm

# "UPGRADES/ <name>": anchored on "PGRADES" because the "U" is often misread, slash optional.
UPGRADE_RE = re.compile(r"P\s*G\s*R\s*A\s*D\s*E\s*S?\s*[/|\\]?\s*(?P<name>.+)", re.I)
CAPACITY_RE = re.compile(r"\bCAPACITY\b", re.I)
CONFIG_RE = re.compile(r"\bCONFIG\s*[ABC]\b", re.I)
HEADER_AREA = (0.097, 0.025, 0.62, 0.095)        # the header text, as fractions of the window (x0, y0, x1, y1)


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
    """The header's text as a boolean array, trimmed to the text rows.

    The text's colour depends on the player's UI theme (orange by default, pale gold, ...) and the
    weapon's name can differ from "UPGRADES/" (red-orange), so text is any bright pixel on the dark
    header bar that's warm (red over blue, unlike the grey-blue background art) or the colour of the
    header's brightest pixels (for other themes).
    """
    W, H = img.size
    x0, y0, x1, y1 = HEADER_AREA
    crop = np.asarray(img.crop((int(W * x0), int(H * y0), int(W * x1), int(H * y1)))).astype(np.int16)
    value = crop.max(axis=2)
    top = np.percentile(value, 99.5)
    text_colour = np.median(crop[value >= top * 0.9], axis=0)
    warm = crop[..., 0] - crop[..., 2] > 40
    mask = (value >= top * 0.55) & (warm | (np.abs(crop - text_colour).max(axis=2) < 70))
    rows = np.where(mask.any(axis=1))[0]
    return mask[rows.min():rows.max() + 1] if len(rows) else mask


def _glyphs(mask):
    """Each glyph as (first column, last column + 1). Specks from the icons beside the text are dropped:
    they're much shorter than a letter (narrow letters like "I" are full height, so height is the test)."""
    cols = mask.any(axis=0)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], cols.astype(np.int8), [0]))))
    runs = list(zip(edges[::2], edges[1::2]))
    heights = [int(mask[:, s:e].any(axis=1).sum()) for s, e in runs]
    tall = float(np.median(heights)) if heights else 0.0
    return [r for r, h in zip(runs, heights) if h >= tall * 0.6]


def _respaced(mask, runs, letter_gap=3, word_gap=14):
    """The glyphs with normal letter spacing (keeping word gaps), black on white, or None."""
    if not runs:
        return None
    gaps = [b[0] - a[1] for a, b in zip(runs, runs[1:])]
    median = float(np.median(gaps)) if gaps else 0.0
    pieces = []
    for i, (s, e) in enumerate(runs):
        if i:
            pieces.append(np.zeros((mask.shape[0], word_gap if gaps[i - 1] > 1.8 * median else letter_gap), bool))
        pieces.append(mask[:, s:e])
    out = np.pad(np.hstack(pieces), 12)
    return Image.fromarray(np.where(out, 0, 255).astype(np.uint8)).convert("RGB")


def weapon_from_header(img, ocr, gamedata):
    """Read the weapon name from the header image (normalized), or None.

    Readings: the whole header; the glyphs after "UPGRADES/" (always the first 9); those up to a
    taller "[" (the rank); and those without the last word. Each at a few sizes. An exact name
    scores 2 votes, a loose match 1; a reading of just the first word ("SPECTRA") also counts for
    the full name ("SPECTRA VANDAL").
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
    for runs_ in readings:
        image = _respaced(mask, runs_)
        for scale in (1.0, 1.25, 1.5, 2.0):
            text = " ".join(_texts(ocr.read(image, scale)))
            m = UPGRADE_RE.search(text)
            text = m.group("name") if m else text
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
        self._fingerprint = None
        self._misses = 0

    def update(self, img, lines, ocr, gamedata):
        if not is_upgrade_screen(lines):
            self._misses += 1
            if self._misses >= 2:
                self.weapon = None
            return self.weapon
        self._misses = 0
        fingerprint = _fingerprint(img)
        same = (self._fingerprint is not None and fingerprint is not None
                and self._fingerprint.shape == fingerprint.shape
                and float(np.mean(self._fingerprint != fingerprint)) < 0.04)
        if self.weapon is None or not same:
            self.weapon = detect_weapon(img, lines, ocr, gamedata)
            self._fingerprint = fingerprint if self.weapon else None
        return self.weapon

    def clear(self):
        self.weapon, self._fingerprint, self._misses = None, None, 0
