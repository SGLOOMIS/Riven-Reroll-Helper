"""Kuva: what a cycle costs. (How much a riven is expected to take to reach a rating: flow.py.)

A cycle's cost is its base rate, which rises with each cycle of the riven up to a cap: 900, 1,000, 1,200,
1,400, 1,700, 2,000, 2,350, 2,750, 3,150, then 3,500 for every cycle after. Locking a stat doubles it,
except locking a spliced stat (which doesn't change the cost). The next cycle's cost is read off the
CYCLE FOR button, so the count picks up where the riven is.

expected_kuva: when each cycle reaches a rating with the same chance p, cycle k is only paid for if the
k - 1 before it all missed:  expected Kuva = sum over k of cost(k) x (1 - p)^(k - 1).
"""

import re

from .advice import spliced_stats

COSTS = [900, 1000, 1200, 1400, 1700, 2000, 2350, 2750, 3150, 3500]
CAP = COSTS[-1]
CYCLE_FOR_RE = re.compile(r"cycle\s*for", re.I)
# What OCR makes of the digits next to the Kuva icon ("CYCLE FOR a,ooo", "goo"), back to digits.
LOOKALIKES = str.maketrans("oOQDgqlI|sSzZB", "00009911155228")
# Reading the number again without the Kuva icon: cut this many text heights off the left of the word
# holding icon and number (much more cuts into the first digit: 2,000 read as 4000).
ICON_CUTS = (1.6, 1.4)


def lock_doubles(ev):
    """Does this riven's lock double the cost (a stat locked that isn't a spliced one)?"""
    return ev is not None and any(s.locked and s.name not in spliced_stats() for s in ev.stats)


def costs_for(locked):
    """The costs a CYCLE FOR button can show: the base rates, doubled with a (non-spliced) stat locked."""
    return [c * 2 for c in COSTS] if locked else COSTS


def read_cycle_cost(lines, locked=False, image=None, ocr=None):
    """(the Kuva the next cycle costs, read from the CYCLE FOR button in OCR lines, or None; whether that's
    certain). locked: whether a lock doubles it (lock_doubles).

    The Kuva icon sits right before the number, and OCR often swallows the first digit into it ("a,500"),
    so the number is matched to the possible costs by what's left. When that leaves more than one (",000":
    1,000 or 2,000), the number is read again without the icon, given the screenshot (image) and OCR;
    failing that, the higher is taken (the estimate then errs on the side of more Kuva)."""
    found = _cost_text(lines)
    if found is None:
        return None, True
    text, box, height = found
    table = costs_for(locked)
    fits = _fits(text, table)
    if len(fits) == 1:
        return fits[0], True
    if image is not None and ocr is not None and box is not None:
        x, y, w, h = box
        for cut in ICON_CUTS:
            crop = image.crop((int(x + cut * height), int(y - 4), int(x + w + 6), int(y + h + 4)))
            again = " ".join(str(word[0]) for line in ocr.read(crop, 2.0) for word in line)
            number = re.sub(r"[,.\s]", "", again.translate(LOOKALIKES))
            if number.isdigit() and int(number) in table:
                return int(number), True
    return (max(fits), False) if fits else (None, True)


def _cost_text(lines):
    """(the text after CYCLE FOR, the box (x, y, w, h) of the word holding the number, the text height)."""
    for line in lines:
        text = " ".join(str(w[0]) for w in line)
        m = CYCLE_FOR_RE.search(text)
        if not m:
            continue
        height = line[0][4]
        rest, box = text[m.end():], tuple(line[-1][1:5]) if len(line) > 2 else None
        if not re.search(r"\d|[oO]{2}", rest):            # the number came out as a line of its own
            x, y, h = line[-1][1] + line[-1][3], line[-1][2], line[-1][4]
            words = [w for other in lines if other is not line for w in other
                     if abs(w[2] - y) < h and x < w[1] < x + 12 * h]
            rest = " ".join(str(w[0]) for w in words)
            box = tuple(words[-1][1:5]) if words else None
        return rest, box, height
    return None


def _fits(text, table):
    found = re.search(r"(\d?)\s*[,.]?\s*(\d{3})\s*$", text.translate(LOOKALIKES).strip())
    if not found:
        return []
    lead, tail = found.groups()
    if lead and int(lead + tail) in table:
        return [int(lead + tail)]
    return [c for c in table if c % 1000 == int(tail)]


def base_rate(cost, locked):
    """The base rate behind a cost read off the button (half of it with a non-spliced stat locked)."""
    return None if cost is None else cost // 2 if locked else cost


def expected_kuva(p, next_base=None, locked=False):
    """The Kuva expected to reach a rating that each cycle reaches with chance p. next_base: the next
    cycle's base rate (None: unknown, so the cap, which most cycled rivens are at); locked: cycling with a
    non-spliced stat locked (double cost). None when p is 0."""
    if p <= 0:
        return None
    start = COSTS.index(next_base) if next_base in COSTS else None
    costs = [c * (2 if locked else 1) for c in (COSTS[start:] if start is not None else [next_base or CAP])]
    if p >= 1:
        return costs[0]
    total, miss = 0.0, 1.0                                  # miss: the chance the cycles so far all missed
    for c in costs[:-1]:
        total += c * miss
        miss *= 1 - p
    return total + costs[-1] * miss / p                     # the rest all cost the last: a geometric series


def kuva_amount(kuva):
    """8,400 / 950k / 5.3M: two significant figures above 10,000 (an average: any one riven varies a lot)."""
    if kuva < 10000:
        return f"{round(kuva, -2):,.0f}"
    rounded = float(f"{kuva:.2g}")
    return f"{rounded / 1e6:g}M" if rounded >= 1e6 else f"{rounded / 1e3:g}k"


def stat_label(stat):
    """A stat as the card shows it: "-Puncture" for the negative."""
    return ("-" if stat.is_negative else "") + stat.name
