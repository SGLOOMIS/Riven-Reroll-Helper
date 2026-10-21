"""The chance that the next cycle of a riven rates higher than it does now, and that it reaches a rating
(for the Kuva it's expected to take, kuva.py).

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
from .riven_math import RivenEval, StatResult, W_MAX, W_MIN, _value_at_w1, quality_of
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
    scores = next_cycle_scores(result, analyzer, samples)
    return None if scores is None else sum(s > result.rating.score for s in scores) / len(scores)


def chance_of_at_least(result, analyzer, target, samples=SAMPLES):
    """The share (0 - 1) of possible next cycles that rate target (a percentage) or higher, or None."""
    scores = next_cycle_scores(result, analyzer, samples)
    return None if scores is None else sum(s >= target for s in scores) / len(scores)


def next_cycle_scores(result, analyzer, samples=SAMPLES):
    """The ratings of simulated next cycles of this riven (worked out once per riven), or None."""
    if result.rating is None:
        return None
    cycles = next_cycles(result.ev, analyzer, samples)
    return None if cycles is None else [score for score, _ in cycles]


def next_cycles(ev, analyzer, samples=SAMPLES):
    """[(rating, stats)] of simulated next cycles of a worked-out riven (once per riven), or None. ev can
    also be a riven that isn't on screen (kuva.py: one with a stat spliced)."""
    if ev is None or not ev.consistent:
        return None
    rolls = analyzer.rolls_for(ev.weapon)
    if not rolls:
        return None
    # Only what a cycle keeps decides what it can roll: the weapon, rank, the locked and spliced stats and,
    # with any of those, the shape. Rivens alike in that (both cards on the cycle screen, the same stat
    # locked) share one simulation, so they get the same answers, not two samples' worth of noise apart.
    spliced = spliced_stats()
    kept = tuple(sorted((s.name, round(s.magnitude, 4), s.is_negative) for s in ev.stats
                        if s.locked or s.name in spliced))
    riven = (ev.weapon.name, ev.rank, kept, (len(ev.positives), ev.negative is not None) if kept else None)
    key = (id(analyzer.library), tuple(map(id, rolls)), riven, samples)
    if key not in _cache:
        if len(_cache) > 64:
            _cache.clear()
        # The same riven always gives the same answer. The seed leaves out the kept stats' values, so two
        # rivens keeping the same stat at a hair's different value (108.5% read as 1.0850 and 1.0857) roll
        # the same cycles, and differ only by what that value changes.
        seed = zlib.crc32(repr((riven[0], riven[1], [k[0::2] for k in kept], riven[3])).encode())
        _cache[key] = _simulate(ev, rolls, analyzer, samples, random.Random(seed))
    return _cache[key]


def _simulate(ev, rolls, analyzer, samples, rng):
    gamedata, weapon = analyzer.gamedata, ev.weapon
    spliced = spliced_stats()
    kept = [s for s in ev.stats if s.locked or s.name in spliced]
    pool = [name for name, sd in gamedata.stats.items() if sd.base.get(weapon.cls) is not None
            and name not in spliced]
    never_negative = POSITIVE_ONLY | ({"Damage"} if weapon.cls == "melee" else set())   # Melee Damage
    shape = (len(ev.positives), ev.negative is not None)
    cycles = []
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
        cycles.append((rate(new, rolls, gamedata, analyzer.cfg["rating"]).score, stats))
    return cycles


def _roll(rng, choices, is_negative, weapon, rank, n, has_negative, gamedata, taken):
    name = rng.choice(choices)
    taken.add(name)
    W = rng.uniform(W_MIN, W_MAX)
    value = _value_at_w1(gamedata.stats[name], weapon, rank, n, has_negative, is_negative) * W
    return StatResult(name, value, is_negative, W, quality_of(W))
