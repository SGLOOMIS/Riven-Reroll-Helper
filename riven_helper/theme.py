"""The player's UI theme, read off the screen, and the panel colours that go with it.

Every menu screen has a header like "INVENTORY/MODS" or "UPGRADES/SPECTRA VANDAL [30]": the first
part in the theme's main colour, the last part in its accent colour. Those two are sampled from the
header's letters (upgrade_screen.header_pixels). The panels' background is the fill of the riven
screen's buttons (LOCK TRAIT, CONFIRM), sampled around their labels (button_colour); until those
have been seen, the header bar behind the text stands in. The colours become a Palette for drawing
the panels (style.py). Without a readable header (in a mission, or a screen without one) nothing is
detected and the last theme seen is kept.
"""

import json
import re
from dataclasses import dataclass, replace
from functools import lru_cache

import cv2
import numpy as np

from .gamedata import DATA_DIR
from .upgrade_screen import header_pixels


@dataclass(frozen=True)
class Theme:
    primary: tuple       # header text colour: labels and outlines
    accent: tuple        # the header's last word: highlights (the BETTER badge)
    background: tuple    # panel fill: the buttons' fill (or the header bar's, before a button is seen)

    def close_to(self, other, tolerance=24):
        return other is not None and all(
            max(abs(a - b) for a, b in zip(x, y)) <= tolerance
            for x, y in ((self.primary, other.primary), (self.accent, other.accent),
                         (self.background, other.background)))


# Vitruvian, the default theme: its header colours, and its buttons' fill (the panels' background).
DEFAULT = Theme(primary=(188, 170, 106), accent=(243, 227, 176), background=(19, 16, 26))
DEFAULT_NAME = "Vitruvian"


@lru_cache(maxsize=1)
def named_themes():
    """{name: Theme} for Warframe's UI themes (data/themes.json), e.g. for the roll editor's colours."""
    data = json.loads((DATA_DIR / "themes.json").read_text(encoding="utf-8"))["themes"]
    return {name: Theme(tuple(t["text"]), tuple(t["accent"]), tuple(t["background"])) for name, t in data.items()}


def detect(img, lines=(), button=None):
    """The Theme whose header is on this screenshot (PIL image), or None when there's no header.

    Its background is the LOCK TRAIT / CONFIRM button's fill when lines (the frame's OCR) show one,
    else button (one seen before), else the header bar's."""
    theme = _from_header(img)
    fill = button_colour(img, lines) or button
    return replace(theme, background=fill) if theme and fill else theme


def _from_header(img):
    rgb, letters = header_pixels(img)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(letters.astype(np.uint8), connectivity=8)
    glyphs = sorted((x, i) for i, (x, y, w, h, _) in enumerate(stats) if i)
    if len(glyphs) < 8:
        return None
    colours = []
    for _, i in glyphs:
        pixels = rgb[labels == i].astype(int)
        core = pixels[np.argsort(_distance(pixels, _surround(rgb, labels == i)))[len(pixels) // 2:]]
        colours.append(np.median(core, axis=0))
    primary = np.median(colours[:4], axis=0)
    accent = np.median(colours[-4:], axis=0)
    # The bar behind the text: the rows of the letters, from the first letter to the last, minus the letters.
    rows = np.where(letters.any(axis=1))[0]
    x0, x1 = glyphs[0][0], glyphs[-1][0]
    band = rgb[rows.min():rows.max() + 1, x0:x1]
    around = ~cv2.dilate(letters.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    background = np.median(band[around[rows.min():rows.max() + 1, x0:x1]], axis=0)
    primary, accent, background = (tuple(int(round(c)) for c in col) for col in (primary, accent, background))
    if abs(luminance(primary) - luminance(background)) < 0.2:
        # No header bar behind the text, only bright art (the cycle animation): every theme's text
        # stands out from its background, so this isn't the theme's. Use a plain one for the text.
        background = DEFAULT.background if luminance(primary) > 0.45 else (225, 225, 228)
    return Theme(primary, accent, background)


BUTTON_LABELS = re.compile(r"LOCK\s*TRAIT|CONFIRM", re.I)


def button_colour(img, lines):
    """The fill of the LOCK TRAIT / CONFIRM button (RGB), sampled just above and below its label, or None.

    lines: the frame's OCR lines (words of (text, x, y, w, h))."""
    for line in lines:
        if not BUTTON_LABELS.search(" ".join(w[0] for w in line)):
            continue
        x0, y0 = min(w[1] for w in line), min(w[2] for w in line)
        x1, y1 = max(w[1] + w[3] for w in line), max(w[2] + w[4] for w in line)
        h = y1 - y0
        top, bottom = int(max(0, y0 - 0.6 * h)), int(y1 + 0.6 * h)
        rgb = np.asarray(img.crop((int(x0), top, int(x1), bottom)).convert("RGB"))   # just around the label
        strips = [rgb[int(y0 - 0.6 * h) - top:int(y0 - 0.25 * h) - top],
                  rgb[int(y1 + 0.25 * h) - top:int(y1 + 0.6 * h) - top]]
        pixels = np.vstack([s.reshape(-1, 3) for s in strips if s.size])
        if len(pixels):
            return tuple(int(c) for c in np.median(pixels, axis=0))
    return None


def _surround(rgb, inside):
    ring = cv2.dilate(inside.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & ~inside
    return np.median(rgb[ring].astype(int), axis=0)


def _distance(pixels, colour):
    return np.abs(pixels - colour).max(axis=1)


# -- the panel palette ----------------------------------------------------------------------------
def mix(a, b, t):
    """a moved a share t of the way towards b."""
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def luminance(c):
    r, g, b = c
    return (0.299 * r + 0.587 * g + 0.114 * b) / 255


def _readable(colour, background, minimum=0.38):
    """colour, pushed darker or lighter until it stands out from background."""
    dark_bg = luminance(background) < 0.5
    target = (255, 255, 255) if dark_bg else (0, 0, 0)
    for t in (0, 0.2, 0.4, 0.6):
        c = mix(colour, target, t)
        if abs(luminance(c) - luminance(background)) >= minimum:
            return c
    return mix(colour, target, 0.7)


@dataclass(frozen=True)
class Palette:
    label: tuple          # headings, "RIVEN RATING", outline
    label_dim: tuple      # the "~" mark of a nice-to-have stat
    highlight: tuple      # the BETTER badge and the better card's outline
    fill: tuple           # panel background
    fill_top: tuple       # the slightly lighter top of the panel
    text: tuple           # values
    grey: tuple           # notes, unwanted stats
    stat: tuple           # stat names (the riven's lavender)
    stat_hi: tuple        # wanted stat names
    good: tuple
    fine: tuple           # a "good" (not great) grade
    ok: tuple
    bad: tuple
    harmless: tuple


def palette(theme=None):
    """Panel colours for a theme: its colours for the frame and labels, and the riven's own lavender and
    the green / yellow / red grades kept, adjusted so they stay readable on the theme's background."""
    theme = theme or DEFAULT
    fill = theme.background
    dark = luminance(fill) < 0.5
    on = lambda c: _readable(c, fill)
    label = on(theme.primary)
    return Palette(
        label=label, label_dim=mix(label, fill, 0.35), highlight=on(theme.accent),
        fill=fill, fill_top=mix(fill, (255, 255, 255) if dark else (0, 0, 0), 0.06),
        text=(222, 222, 232) if dark else (28, 28, 36), grey=_readable((128, 130, 148), fill, 0.22),
        stat=on((172, 131, 213)), stat_hi=on((205, 180, 250)) if dark else on((120, 70, 180)),
        good=on((126, 226, 160)), fine=on((196, 228, 112)), ok=on((253, 190, 60)), bad=on((240, 88, 80)),
        harmless=on((150, 196, 230)))
