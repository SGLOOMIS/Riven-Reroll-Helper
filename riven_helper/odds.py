"""The chance that the next cycle of a riven rates higher than it does now.

Worked out by simulating cycles: each one keeps the riven's weapon and rank, and the stats that are
locked or spliced (which also keep its shape); everything else rolls again, and each simulated
riven is rated against the same rolls. What a cycle does, as far as the Warframe Wiki and common
player knowledge go:

  * The shape is one of 2 or 3 positives, with or without a negative, each taken as equally likely
    (the wiki gives no odds). A locked or spliced stat keeps the current shape.
  * Stats are drawn evenly from the weapon class's pool (data/stats.json), without repeats; spliced
    stats only come from splicing, never from a cycle.
  * Some stats are never the negative (POSITIVE_ONLY) and one only ever is (NEGATIVE_ONLY).
  * Each stat's roll W is spread evenly over 0.9 - 1.1.
"""

import random
import zlib

from .advice import spliced_stats
from .riven_math import RivenEval, StatResult, W_MAX, W_MIN, _value_at_w1
from .rolls import rate

SAMPLES = 3000
SHAPES = [(2, False), (2, True), (3, False), (3, True)]
POSITIVE_ONLY = {"Additional Combo Count Chance", "Cold", "Electricity", "Heat", "Toxin", "Punch Through",
                 "Initial Combo"}
NEGATIVE_ONLY = {"Chance to Gain Combo Count"}
_cache = {}


def chance_of_better(result, analyzer, samples=SAMPLES):
    """The share (0 - 1) of possible next cycles that rate higher than this riven, or None when it can't
    be worked out (an unreadable card, or no rolls for the weapon)."""
    ev, rating = result.ev, result.rating
    if ev is None or rating is None or not ev.consistent:
        return None
    rolls = analyzer.library.rolls_for(ev.weapon)
    if not rolls:
        return None
    riven = (ev.weapon.name, ev.rank, rating.score,
             tuple((s.name, round(s.magnitude, 4), s.is_negative, s.locked) for s in ev.stats))
    key = (id(analyzer.library), riven)
    if key not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        seed = zlib.crc32(repr(riven).encode())     # the same riven always gives the same answer
        _cache[key] = _simulate(ev, rating.score, rolls, analyzer, samples, random.Random(seed))
    return _cache[key]


def _simulate(ev, score, rolls, analyzer, samples, rng):
    gamedata, weapon = analyzer.gamedata, ev.weapon
    spliced = spliced_stats()
    kept = [s for s in ev.stats if s.locked or s.name in spliced]
    pool = [name for name, sd in gamedata.stats.items() if sd.base.get(weapon.cls) is not None
            and name not in spliced]
    never_negative = POSITIVE_ONLY | ({"Damage"} if weapon.cls == "melee" else set())   # Melee Damage
    shape = (len(ev.positives), ev.negative is not None)
    better = 0
    for _ in range(samples):
        n, has_negative = shape if kept else rng.choice(SHAPES)
        stats = list(kept)
        taken = {s.name for s in kept}
        for _ in range(n - sum(not s.is_negative for s in kept)):
            stats.append(_roll(rng, [p for p in pool if p not in taken and p not in NEGATIVE_ONLY],
                               False, weapon, ev.rank, n, has_negative, gamedata, taken))
        if has_negative and not any(s.is_negative for s in kept):
            stats.append(_roll(rng, [p for p in pool if p not in taken and p not in never_negative],
                               True, weapon, ev.rank, n, has_negative, gamedata, taken))
        new = RivenEval(weapon, ev.rank, stats, consistent=True)
        better += rate(new, rolls, gamedata, analyzer.cfg["rating"]).score > score
    return better / samples


def _roll(rng, choices, is_negative, weapon, rank, n, has_negative, gamedata, taken):
    name = rng.choice(choices)
    taken.add(name)
    W = rng.uniform(W_MIN, W_MAX)
    value = _value_at_w1(gamedata.stats[name], weapon, rank, n, has_negative, is_negative) * W
    return StatResult(name, value, is_negative, W, W / W_MAX)
