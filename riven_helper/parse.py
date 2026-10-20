"""Turn the OCR'd text of a riven screen into riven cards.

A card has a title ("<riven family> <suffix>", e.g. "Rubico Crita-visitis"), 2-4 stat lines
("+135.2% Critical Damage", "x1.32 Damage to Grineer", "-45.1% Zoom") and an "MR 12" footer. On
the cycle screen two cards sit side by side. Steps:

  1. split OCR lines into segments (OCR merges text from both cards on one row)
  2. find the stat lines, joining a stat name that wrapped onto a second line
  3. group the stat lines into columns, one per card
  4. for each card: its box (down to the footer), its title, and stat names OCR read without a number
  5. the weapon under FITS IN (whose disposition the numbers use), and whether this is a riven screen

OCR quirks handled along the way are noted where they're handled.
"""

import difflib
import math
import re
from dataclasses import dataclass, field

from .gamedata import norm
from .riven_math import RivenStat

# A stat line: optional icon junk, optional "x", sign, number, unit, then the stat name.
VALUE_RE = re.compile(
    r"^[^\w+\-−–—×%]*"                                  # element icons before the number
    r"(?:[^\s+\-−–—]{1,2}\s*(?=[+\-−–—~]|[xX×]\s*\d))?"  # an icon read as a letter: "O +224.4%", "0+111.1%"
    r"(?P<x>[xX×])?\s*"                                 # (the lock icon), "N x 1.26" (on the dimmed card)
    r"(?P<sign>[+\-−–—~])?\s*"
    r"(?P<num>\d{1,4}(?:[.,]\d{1,3})?)\s*"
    r"(?P<unit>%|s(?=\s)|m(?=\s))?\s*"
    r"[^A-Za-z]*"                                       # an element icon between number and name: "+41.9% *Cold"
    r"(?P<name>[A-Za-z].*)$")
PERCENT_MISREAD_RE = re.compile(r"(\d)\s*[0oO°]\s*/\s*[0oO°]")   # "%" read as "0/0": "41.90/0" -> "41.9%"
MULTIPLIER_MISREAD_RE = re.compile(r"^(\W*[xX×])\s*[lI|1]\s*[.,]\s*(?=\d)")  # "xl .32" / "x1 .32" -> "x1.32"
FOOTER_RE = re.compile(r"^\W*MR\s*\d+", re.I)                     # "MR 12" at the bottom of a card
FITS_IN_RE = re.compile(r"fits\s*in", re.I)
# Labels only the riven and cycle screens have (the inventory grid has none of these).
RIVEN_SCREEN_RE = re.compile(r"fits\s*in|cycle\s*for|confirm|lock\s*trait|show\s*ranked", re.I)


@dataclass
class Segment:
    """A run of OCR'd words with its box."""
    text: str
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def bottom(self):
        return self.y + self.h


@dataclass
class Card:
    stats: list                                  # [RivenStat]
    box: tuple = (0, 0, 0, 0)                    # x, y, w, h: the stat lines, down to the MR footer
    text_h: float = 0.0                          # height of one stat line (the selected card's is larger)
    title_name: str = None                       # riven family from the title (normalized)
    shown_weapon: str = None                     # weapon under FITS IN (normalized)
    riven_screen: bool = False                   # the riven / cycle screen's labels were on screen
    orphans: list = field(default_factory=list)  # stat names OCR read without their number
    problems: list = field(default_factory=list) # warnings for the panel

    @property
    def geometry(self):
        """The box plus the line height, as the layout and tracker take it."""
        return tuple(self.box) + (self.text_h,)


def match_value(text):
    text = PERCENT_MISREAD_RE.sub(lambda m: m.group(1) + "%", text.strip())
    return VALUE_RE.match(MULTIPLIER_MISREAD_RE.sub(lambda m: m.group(1) + "1.", text))


def parse_stat(text, gamedata):
    """"+135.2% Critical Damage" -> RivenStat, or None if it isn't a stat line."""
    m = match_value(text)
    if not m:
        return None
    name = gamedata.match_stat(m.group("name"))
    if name is None:                             # an icon read as a short word before the name: "X Cold"
        head, _, rest = m.group("name").partition(" ")
        name = gamedata.match_stat(rest) if len(head) <= 2 and rest else None
    if name is None:
        return None
    sd = gamedata.stats[name]
    num = float(m.group("num").replace(",", "."))
    negative_sign = bool(m.group("sign")) and m.group("sign") not in "+~"

    dropped_x = sd.unit == "multiplier" and not m.group("unit") and not m.group("sign") and 0 < num < 3
    if m.group("x") or dropped_x:                # "x1.32 Damage to Grineer" (OCR sometimes loses the "x")
        negative_sign = num < 1
        magnitude = abs(num - 1.0)
    elif sd.unit == "flat":                      # shown with one decimal: "+9.36" is "+9.3s" with the s misread
        magnitude = math.floor(num * 10 + 1e-6) / 10
    else:
        magnitude = num / 100.0
    if magnitude <= 0:
        return None
    # A minus sign is the negative, except for stats where minus is good (Weapon Recoil).
    is_negative = negative_sign != (sd.good_sign < 0)
    return RivenStat(name, magnitude, is_negative, text.strip())


def _segments(lines, gap_factor=2.2):
    """Split OCR lines (lists of (text, x, y, w, h) words) wherever words are far apart."""
    out = []
    for words in lines:
        if not words:
            continue
        runs, cur = [], [sorted(words, key=lambda w: w[1])[0]]
        for wd in sorted(words, key=lambda w: w[1])[1:]:
            prev = cur[-1]
            if wd[1] - (prev[1] + prev[3]) > gap_factor * max(prev[4], wd[4]):
                runs.append(cur)
                cur = [wd]
            else:
                cur.append(wd)
        runs.append(cur)
        for run in runs:
            x0, y0 = min(w[1] for w in run), min(w[2] for w in run)
            x1, y1 = max(w[1] + w[3] for w in run), max(w[2] + w[4] for w in run)
            out.append(Segment(" ".join(w[0] for w in run), x0, y0, x1 - x0, y1 - y0))
    return out


def _stat_lines(segments, gamedata):
    """[(segment, RivenStat)] for every stat line, and the indexes of the segments they used.

    A long stat name can wrap onto the next line ("+9.7% Critical Chance on" / "Slide Attack", or
    "+125.2% Finisher" / "Damage"); the wrapped part is joined so it isn't left over as a stray name.
    """
    used, found = set(), []
    order = sorted(range(len(segments)), key=lambda i: (segments[i].y, segments[i].x))
    for i in order:
        seg = segments[i]
        if i in used or not match_value(seg.text):
            continue
        stat = parse_stat(seg.text, gamedata)
        below = next((j for j in order if j != i and j not in used
                      and 0 < segments[j].y - seg.y < 1.9 * seg.h
                      and abs(segments[j].cx - seg.cx) < max(seg.w, segments[j].w)
                      and not match_value(segments[j].text)), None)
        if below is not None:
            nxt = segments[below]
            joined = parse_stat(seg.text + " " + nxt.text, gamedata)
            completes = joined and (stat is None or len(joined.name) > len(stat.name))
            repeats = joined and stat and joined.name == stat.name \
                and set(norm(nxt.text).split()) <= set(norm(stat.name).split())
            if completes or repeats:
                stat = joined
                used.add(below)
                x0 = min(seg.x, nxt.x)
                seg = Segment(seg.text + " " + nxt.text, x0, seg.y, max(seg.x + seg.w, nxt.x + nxt.w) - x0,
                              nxt.bottom - seg.y)
        if stat:
            used.add(i)
            found.append((seg, stat))
    return found, used


def _columns(found, image_width):
    """Group stat lines into cards: a new card starts at a large horizontal gap (6% of the width)."""
    found = sorted(found, key=lambda f: f[0].cx)
    columns = []
    for f in found:
        if columns and f[0].cx - columns[-1][-1][0].cx <= image_width * 0.06:
            columns[-1].append(f)
        else:
            columns.append([f])
    return columns


def _stat_block(column):
    """The card's stat block: the longest run of closely spaced lines, at most 4."""
    column = sorted(column, key=lambda f: f[0].y)
    blocks = [[column[0]]]
    for f in column[1:]:
        if f[0].y - blocks[-1][-1][0].bottom < 2.5 * blocks[-1][-1][0].h:
            blocks[-1].append(f)
        else:
            blocks.append([f])
    return max(blocks, key=len)[:4]


def _card(block, others, gamedata):
    x0, y0 = min(f[0].x for f in block), min(f[0].y for f in block)
    x1, y1 = max(f[0].x + f[0].w for f in block), max(f[0].bottom for f in block)
    line_h = min(f[0].h for f in block)              # one line (a wrapped stat's segment spans two)
    width = x1 - x0

    # Extend the box to the "MR" footer, so a panel placed under it never covers a line OCR missed.
    footer = [s for s in others if FOOTER_RE.match(s.text) and y1 - 2 < s.y < y1 + 4 * line_h
              and x0 - width * 0.25 < s.cx < x1 + width * 0.25]
    y1 = min(footer, key=lambda s: s.y).bottom if footer else y1 + 1.9 * line_h   # unreadable on the dimmed card
    card = Card([f[1] for f in block], (x0, y0, width, y1 - y0), line_h)

    near = [s for s in others if x0 - width * 0.6 < s.cx < x1 + width * 0.6]
    card.orphans = [s.text for s in near if y0 - 1.6 * line_h <= s.y <= y1 and not match_value(s.text)
                    and not FOOTER_RE.match(s.text) and gamedata.match_stat(s.text)]
    above = sorted((s for s in near if s.bottom <= y0 + 2 and y0 - s.y < 12 * line_h), key=lambda s: y0 - s.y)
    card.title_name = next((n for n in (gamedata.find_family_in_text(s.text) for s in above) if n), None)

    if sum(s.is_negative for s in card.stats) > 1:   # only one negative is possible: it's listed last
        for s in card.stats[:-1]:
            s.is_negative = False
        card.problems.append("several minus signs read; assuming last line is the negative")
    return card


def _fits_in(segments, gamedata, family):
    """The weapon under the FITS IN label (normalized), or None.

    OCR sometimes clips the name ("elox Prime"), so without an exact match the text is
    compared loosely with the variants of the riven's family.
    """
    for label in (s for s in segments if FITS_IN_RE.search(s.text)):
        below = sorted((s for s in segments if s is not label and 0 < s.y - label.y < 20 * label.h
                        and abs(s.cx - label.cx) < max(label.w, s.w) * 1.5), key=lambda s: s.y)
        for s in below:
            name = gamedata.find_weapon_in_text(s.text)
            if name:
                return name
        variants = [norm(w.base_name) for w in gamedata.family_members(family)] if family else []
        for s in below:
            close = difflib.get_close_matches(norm(s.text), variants, n=1, cutoff=0.75)
            if close:
                return close[0]
    return None


def parse_cards(lines, image_width, gamedata):
    """The riven cards in a frame's OCR lines, left to right."""
    segments = _segments(lines)
    found, used = _stat_lines(segments, gamedata)
    others = [s for i, s in enumerate(segments) if i not in used]
    cards = [_card(block, others, gamedata)
             for block in map(_stat_block, _columns(found, image_width)) if len(block) >= 2]

    # Both cards are the same riven: share the title if only one was read; if none was, use the
    # longest weapon family named anywhere on screen.
    titles = {c.title_name for c in cards if c.title_name}
    if not titles and cards:
        hits = [n for n in (gamedata.find_family_in_text(s.text) for s in others) if n]
        titles = {max(hits, key=len)} if hits else set()
    if len(titles) == 1:
        for c in cards:
            c.title_name = c.title_name or next(iter(titles))

    shown = _fits_in(others, gamedata, next((c.title_name for c in cards if c.title_name), None))
    on_riven_screen = any(RIVEN_SCREEN_RE.search(s.text) for s in segments)
    for c in cards:
        c.shown_weapon, c.riven_screen = shown, on_riven_screen
    return sorted(cards, key=lambda c: c.box[0])
