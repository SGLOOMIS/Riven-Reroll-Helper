"""The next step towards the roll a riven is being rerolled for: cycle, lock a stat, splice, or done.

The rules it follows (Riven Mods on the Warframe Wiki, Splicing and Trait Locking):

  * Locking a stat also locks the riven's shape (how many positives, and whether it has a negative).
    So the shape comes first: while it's wrong, cycle without a lock.
  * Only one stat can be locked at a time (a spliced stat doesn't count). Lock the wanted stat that's
    most important to keep: the highest weight, then the better roll, even when another wanted stat
    is locked already (moving the lock costs nothing).
  * Splicing turns two particular stats on the riven (data/splices.json) into one spliced stat, which
    keeps the higher of their two rolls and stays locked for good: changing it takes another Riven
    Splicer, which is rare, so a riven gets one splice at most. A splice into a stat of the ideal roll
    is only skipped when it would keep less than 80% of that stat's maximum; into another wanted stat,
    only when that's wanted at least as much as the stats used up. A spliced stat keeps the shape too.
  * A stat that splices into a wanted stat (Cold, for Blast with Heat) is worth that stat: the one to lock
    while its partner rolls. Rolled well enough to splice (80%), it comes before equally wanted stats,
    because the splice keeps its roll for good.
  * How well each stat rolled (the 0.9 - 1.1 variance) matters least: once the stats are right the
    riven is done, and a low roll on an unspliced stat is only mentioned.

Every shape can reach a 100% rating, so the shape aimed for is the one that holds the most wanted
stat value: the layout's L multiplier (riven_math.BONUS_L) times the weights of the best stats it
has room for. Shapes with a negative only count when the roll lists negatives it accepts, and the
riven's current shape is kept when it's within 5% of the best.
"""

import json
from dataclasses import replace
from functools import lru_cache

from .gamedata import DATA_DIR
from .riven_math import BONUS_L

GOOD_ROLL = 0.95          # quality (value / max) below which a stat's roll is mentioned as low
SPLICE_MIN = 0.80         # a splice into a stat of the ideal roll is only skipped when it would keep less than
                          # this share of the spliced stat's maximum (its quality: value / max)
CLOSE_ENOUGH = 0.95       # a shape within this share of the best shape's value is kept (no cycles wasted)


@lru_cache(maxsize=1)
def splices():
    """[(trait 1, trait 2, spliced stat, weapon classes)] from data/splices.json."""
    data = json.loads((DATA_DIR / "splices.json").read_text(encoding="utf-8"))
    return [(*s["traits"], s["result"], frozenset(s["classes"])) for s in data["splices"]]


def spliced_stats():
    return {result for _, _, result, _ in splices()}


def shape_text(n_positives, has_negative):
    return f"{n_positives} pos" + (" + neg" if has_negative else ", no neg")


def shape_value(shape, weights):
    """How much wanted stat value a shape can hold: its L multiplier times the best weights it has room for."""
    return BONUS_L[shape] * sum(sorted(weights.values(), reverse=True)[:shape[0]])


def target_shape(current, weights, accepts_negative):
    """The shape to aim for: the one holding the most wanted value, unless the current one is close to it."""
    shapes = [(n, neg) for n in (3, 2) for neg in ((True, False) if accepts_negative else (False,))]
    best = max(shapes, key=lambda s: shape_value(s, weights))
    if current in shapes and shape_value(current, weights) >= CLOSE_ENOUGH * shape_value(best, weights):
        return current
    return best


def next_step(result, gamedata):
    """(what to do, why) for one rated card, or None when there's no advice (unreadable card, no roll)."""
    ev, rating = result.ev, result.rating
    roll = rating.roll if rating else None
    if ev is None or roll is None or not ev.consistent:
        return None
    cls = ev.weapon.cls
    weights = {s: w for s, w in roll.positives.items() if w > 0 and gamedata.stats[s].base.get(cls) is not None}
    if not weights:
        return None
    positives, negative = ev.positives, ev.negative
    spliced = next((s for s in positives if s.name in spliced_stats()), None)
    locked = next((s for s in ev.stats if s.locked and s is not spliced), None)
    shape = (len(positives), negative is not None)

    # 1. The shape. A spliced stat fixes it, so then the best is made of the shape there is.
    target = shape if spliced else target_shape(shape, weights, bool(roll.negatives))
    if shape != target:
        if locked:
            return f"Unlock {locked.name}", f"then cycle for {shape_text(*target)} (has {shape_text(*shape)})"
        return "Cycle without a lock", f"aim for {shape_text(*target)} (has {shape_text(*shape)})"

    # 2. Done: every positive is one of the best stats for the shape, and the negative is fine.
    n = target[0]
    nth_best = sorted(weights.values(), reverse=True)[:n][-1]
    right = [s for s in positives if weights.get(s.name, 0) >= nth_best]
    negative_ok = negative is None or rating.tags.get(negative.name) in ("harmless", "neutral")
    if len(right) == n and negative_ok and not rating.dealbreaker and not rating.bad:
        low = [s for s in positives if s is not spliced and s.quality < GOOD_ROLL]
        if low:
            worst = min(low, key=lambda s: s.quality)
            return "Done", f"only roll values left: {worst.name} {worst.quality * 100:.0f}%"
        return "Done", "the stats you want, rolled well"

    # 3. Splice: once per riven. Into a stat of the ideal roll (one of the best stats for the shape)
    #    whenever it keeps at least SPLICE_MIN of that stat's maximum; into another wanted stat only when
    #    it's wanted at least as much as the stats used up. Of several possible, the one using up the
    #    least wanted weight; then one that keeps a harmless negative.
    if spliced is None:
        names = {s.name: s for s in ev.stats}
        options = []
        for a, b, into, classes in splices():
            if cls not in classes or a not in names or b not in names or into in names:
                continue
            used = [weights.get(t, 0) for t in (a, b) if not names[t].is_negative]
            uses_harmless = any(names[t].is_negative and rating.tags.get(t) == "harmless" for t in (a, b))
            keeps = max(names[a].quality, names[b].quality)
            ideal = weights.get(into, 0) >= nth_best
            worth_it = ideal or (weights.get(into, 0) > 0 and weights[into] >= max(used, default=0))
            if worth_it and keeps >= SPLICE_MIN:
                options.append((sum(used), uses_harmless, a, b, into, keeps))
        if options:
            _, _, a, b, into, keeps = min(options)
            return f"Splice {a} + {b}", f"into {into}, keeps {keeps * 100:.0f}%"

    # 4. Lock the most important stat to keep, and cycle for the rest. A stat that splices (with a partner
    #    still to roll) into a wanted stat counts as that stat; with a high roll it comes first among
    #    equals, since the splice keeps that roll for good.
    ingredient = {} if spliced else _ingredients(ev, weights, cls)
    candidates = []
    for s in positives:
        if s is spliced:
            continue
        own = weights.get(s.name, 0)
        via = ingredient.get(s.name)
        value = max(own, via[0] if via else 0)
        if value <= 0:
            continue
        via = via if via and via[0] >= own else None
        # Among equals: a splice ingredient worth splicing (SPLICE_MIN), then an ordinary stat, then one
        # rolled too low to splice.
        order = (2 if s.quality >= SPLICE_MIN else 0) if via else 1
        candidates.append(((value, order, s.quality), s, via))
    if not candidates:
        if locked:
            return f"Unlock {locked.name}", "then cycle: no wanted stat to keep yet"
        return "Cycle", "no wanted stat to keep yet"
    _, keep, via = max(candidates, key=lambda c: c[0])
    plan = (f"{keep.quality * 100:.0f}% {keep.name}, to splice with {' or '.join(via[2])} into {via[1]}"
            if via else None)
    if locked is keep:
        return f"Keep {keep.name} locked", f"and cycle for {' or '.join(via[2])} to splice into {via[1]}"             if via else "and cycle for the other stats"
    if locked is not None:
        return f"Lock {keep.name} instead", f"of {locked.name}: {plan}" if plan else f"of {locked.name}, then cycle"
    return f"Lock {keep.name}", plan or "then cycle (locked cycles cost double Kuva)"


def _ingredients(ev, weights, cls):
    """{stat on the riven: (wanted weight of what it splices into, that stat, [partners still to roll])}
    for positives that could be spliced into a wanted stat once a partner rolls."""
    names = {s.name: s for s in ev.stats}
    options = {}                                  # stat -> [(weight, splices into, partner)]
    for a, b, into, classes in splices():
        if cls not in classes or weights.get(into, 0) <= 0 or into in names:
            continue
        for have, partner in ((a, b), (b, a)):
            if have in names and not names[have].is_negative and partner not in names:
                options.setdefault(have, []).append((weights[into], into, partner))
    found = {}
    for have, opts in options.items():
        weight, into, _ = max(opts)
        found[have] = (weight, into, sorted(p for w, i, p in opts if i == into))
    return found


def progress(result, analyzer):
    """(how far the riven is towards the ideal roll, why it's further than its rating) for picking between
    the two cards on the cycle screen; the larger first value is the better card.

    When the roll's most wanted stats include one only splicing makes (Blast, from Heat + Cold), the
    splice comes first, since it's the part that stays: a riven with it spliced is furthest, then one
    that can splice it now, then one with an ingredient waiting for its partner (each only when the
    splice would keep at least SPLICE_MIN of the stat's maximum). Within
    each, the roll the splice keeps, then the rating (counting a waiting ingredient as what it becomes).
    Otherwise it's just the rating. why is None when the rating says it all.
    """
    ev, rating = result.ev, result.rating
    if ev is None or rating is None or rating.roll is None or not ev.consistent:
        return (0, 0.0, rating.score if rating else 0.0), None
    cls = ev.weapon.cls
    weights = {s: w for s, w in rating.roll.positives.items()
               if w > 0 and analyzer.gamedata.stats[s].base.get(cls) is not None}
    if not weights:
        return (0, 0.0, rating.score), None
    top = max(weights.values())
    names = {s.name: s for s in ev.stats}

    spliced = [s for s in ev.positives if s.name in spliced_stats()]
    if spliced:
        best = max(spliced, key=lambda s: s.quality)
        stage = 3 if weights.get(best.name, 0) >= top else 0
        return (stage, best.quality if stage else 0.0, rating.score), None

    ready = [(max(names[a].quality, names[b].quality), a, b, into) for a, b, into, classes in splices()
             if cls in classes and a in names and b in names and into not in names and weights.get(into, 0) >= top
             and max(names[a].quality, names[b].quality) >= SPLICE_MIN]
    if ready:
        keeps, a, b, into = max(ready)
        return (2, keeps, rating.score), f"{a} + {b} can splice into {into} now ({keeps * 100:.0f}%)"

    ingredient = _ingredients(ev, weights, cls)
    waiting = [(s, ingredient[s.name][1]) for s in ev.positives if s.name in ingredient
               and ingredient[s.name][0] >= top and s.quality >= SPLICE_MIN]
    if waiting:
        s, into = max(waiting, key=lambda w: w[0].quality)
        projected = analyzer.rate(replace(ev, stats=[replace(x, name=into) if x is s else x for x in ev.stats],
                                          notes=[]))
        return (1, s.quality, max(projected.score, rating.score)), f"{s.quality * 100:.0f}% {s.name} splices into {into}"
    return (0, 0.0, rating.score), None
