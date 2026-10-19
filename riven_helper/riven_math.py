"""Riven stat math, from https://wiki.warframe.com/w/Riven_Mods:

    value = b * 10 * (rank + 1) * D * L * W        W is the random roll, 0.9 .. 1.1

    b  base value of the stat for the weapon class   (data/stats.json)
    D  the weapon's disposition                      (data/dispositions.json)
    L  multiplier for the riven's layout: how many positives, and whether it has a negative

A stat's quality is how close it rolled to its maximum: value / maximum, which is W / 1.1.
"""

from dataclasses import dataclass, field

W_MIN, W_MAX = 0.9, 1.1

# L for each positive, by (number of positives, has a negative)
BONUS_L = {(2, False): 0.99, (2, True): 1.2375, (3, False): 0.75, (3, True): 0.9375}
# L for the negative, by number of positives
MALUS_L = {2: 0.495, 3: 0.75}

# The game rounds what it shows; allow this much slack (as a fraction of W) when checking a fit.
TOLERANCE = 0.02
# Ranks tried when working out a riven's rank, most likely first (maxed rivens are the common case).
RANK_ORDER = [8, 7, 6, 5, 4, 3, 2, 1, 0]


@dataclass
class RivenStat:
    """One stat line read off a riven card."""
    name: str                 # canonical stat name, e.g. "Critical Damage"
    magnitude: float          # size of the value as a fraction: 0.952 for +95.2%, 2.7 for +2.7 Punch Through
    is_negative: bool         # True for the riven's negative (the curse)
    text: str = ""            # the line as OCR read it


@dataclass
class StatResult:
    """A stat once the weapon and rank are known."""
    name: str
    magnitude: float
    is_negative: bool
    roll: float               # W, 0.9 .. 1.1
    quality: float            # value / maximum possible value, 0.82 .. 1.0


@dataclass
class RivenEval:
    """A riven worked out: which weapon's numbers it shows, its rank, and every stat's roll."""
    weapon: object
    rank: int
    stats: list               # [StatResult]
    consistent: bool          # every stat landed inside its possible range
    notes: list = field(default_factory=list)   # warnings shown on the panel

    @property
    def positives(self):
        return [s for s in self.stats if not s.is_negative]

    @property
    def negative(self):
        return next((s for s in self.stats if s.is_negative), None)


def _value_at_w1(stat_def, weapon, rank, n_positives, has_negative, is_negative):
    """b * 10 * (rank + 1) * D * L, the value when W = 1. None if the stat can't roll on this weapon."""
    b = stat_def.base.get(weapon.cls)
    if b is None:
        return None
    if stat_def.name == "Fire Rate" and weapon.is_bow:
        b *= 2                                  # bows get double fire rate
    L = MALUS_L[n_positives] if is_negative else BONUS_L[(n_positives, has_negative)]
    return abs(b) * 10 * (rank + 1) * weapon.disposition * L


def max_value(stat_def, weapon, rank, n_positives=3, has_negative=True):
    """The highest value a positive stat can roll for this weapon, rank and layout (or None)."""
    base = _value_at_w1(stat_def, weapon, rank, n_positives, has_negative, False)
    return None if base is None else base * W_MAX


def format_value(stat_def, value):
    """A positive value the way the riven card shows it: +95.2%, +2.7, +8.1s, x1.32."""
    sign = "-" if stat_def.good_sign < 0 else "+"
    if stat_def.unit == "multiplier":
        return f"x{1 + value:.2f}"
    if stat_def.unit == "flat":
        return f"{sign}{value:.1f}{'s' if stat_def.name == 'Combo Duration' else ''}"
    return f"{sign}{value * 100:.1f}%"


def evaluate(stats, weapon, rank, gamedata):
    """Every stat's roll for one guess of weapon and rank.

    Returns (RivenEval, how far the worst stat is outside its range) or (None, inf) if the
    layout is impossible (a riven has 2 or 3 positives and at most one negative).
    """
    n_positives = sum(not s.is_negative for s in stats)
    has_negative = any(s.is_negative for s in stats)
    if n_positives not in (2, 3) or sum(s.is_negative for s in stats) > 1:
        return None, float("inf")

    results, worst = [], 0.0
    for s in stats:
        base = _value_at_w1(gamedata.stats[s.name], weapon, rank, n_positives, has_negative, s.is_negative)
        if not base:
            return None, float("inf")
        W = s.magnitude / base
        worst = max(worst, W_MIN - W, W - W_MAX, 0.0)
        quality = min(max(W, W_MIN), W_MAX) / W_MAX
        results.append(StatResult(s.name, s.magnitude, s.is_negative, W, quality))
    return RivenEval(weapon, rank, results, consistent=worst == 0.0), worst


def infer(stats, candidates, gamedata, ranks=RANK_ORDER):
    """Work out which weapon's disposition and which rank explain the numbers on a card.

    Neither is shown on screen in a readable way, so each candidate weapon (most likely first)
    is tried at each rank, and the first where every stat fits inside 0.9 .. 1.1 wins. If none
    fits, the closest guess is returned with a note.
    """
    best, best_off = None, float("inf")
    for weapon in candidates:
        for rank in ranks:
            ev, off = evaluate(stats, weapon, rank, gamedata)
            if ev is None:
                continue
            if off <= TOLERANCE * W_MAX:
                ev.consistent = True
                if weapon is not candidates[0]:
                    ev.notes.append(f"doesn't fit {candidates[0].name}: a stat line may have been misread")
                return ev
            if off < best_off:
                best, best_off = ev, off
    if best is not None:
        best.notes.append("numbers don't fit any rank/disposition - check dispositions.json")
    return best
