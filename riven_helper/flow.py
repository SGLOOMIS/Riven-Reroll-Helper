"""The reroll strategy (a flowchart), and the Kuva it's expected to take, worked out exactly.

The strategy, for the roll a riven is rated against:

    a spliced stat the roll doesn't want      -> unlock it (and any lock), cycle: the riven starts over
    shape wrong?                     -> cycle without a lock, until it's right
    the roll wants a spliced stat (Blast), and the riven has none spliced:
      no trait of it (Heat, Cold) over X       -> lock the most useful stat, cycle
      one over X, its partner not there yet    -> lock that trait, cycle
      both there, one over X                   -> splice them (the spliced stat stays locked for free)
    otherwise:
      a wanted stat on the riven               -> lock the most wanted one, cycle
      none                                     -> lock the most useful stat, cycle
    rated kuva_target or more (at any point)   -> done

"The most useful stat": a harmless negative (it keeps the riven's shape, negative included, and leaves
every positive slot free), then a wanted stat, then a trait of the spliced stat, then the best-rolled
other stat. "The most wanted": the highest weight (Required before others), keeping the current lock
between equals. X is the setting splice_min (50%: how far up its range the trait rolled).

The Kuva is worked out, not simulated. A cycle keeps the riven's shape and its locked and spliced stats,
and draws the rest evenly from the weapon class's pool without repeats (the same rules as odds.py), each
rolling evenly over 90 - 110%. Stats that play the same part for the roll (all the unwanted ones, say)
are counted together, so the chance of every kind of outcome is a quick count; the chance an outcome
rates high enough is an exact integral over the rolls (a sum of evenly spread values). The strategy
then makes a small Markov chain: each state is what the next cycle keeps, each cycle costs its Kuva
(the base rate, doubled with a stat that isn't spliced locked), and the expected total is solved from
it, base rate rising cycle by cycle up to 3,500.

Kept stats keep their rolls exactly; in the chain's later states a stat locked from a cycle yet to come
(and a trait the splice keeps) is counted by third of its range (BANDS), each third its own state.
"""

import itertools
import math
import threading
from dataclasses import dataclass, replace

import numpy as np

from .advice import CLOSE_ENOUGH, shape_value, spliced_stats, splices
from .kuva import CAP, COSTS, kuva_amount, stat_label
from .odds import NEGATIVE_ONLY, POSITIVE_ONLY
from .riven_math import RivenEval, StatResult, _value_at_w1, quality_of, roll_of
from .rolls import DEFAULT_RATING

Q0 = 0.0                             # the lowest quality a stat can roll (the highest: 1)
SHAPES = [(2, False), (2, True), (3, False), (3, True)]
MAX_STATES = 2000                    # a strategy with more states than this isn't worked out
BANDS = 3                            # a kept stat's roll is counted by third of its range (see _bands, _qualities)


@dataclass
class Action:
    """What the strategy does with a riven."""
    kind: str                        # "cycle", "splice" or "done"
    stage: str                       # "unsplice", "shape", "trait", "partner", "splice", "wanted", "useful", "done"
    lock: object = None              # the stat to have locked while cycling (a StatResult), or None
    pair: tuple = None               # the two traits to splice
    into: str = None                 # the spliced stat
    unlock: object = None            # "unsplice": the unwanted spliced stat to unlock


def settings_of(cfg):
    """(the target rating, X as a quality 0 - 1) from the settings."""
    return cfg.get("kuva_target", 90), cfg.get("splice_min", 50) / 100


class Model:
    """One weapon, rank and roll: the strategy, and exact cycle outcomes for it."""

    def __init__(self, gamedata, weapon, rank, roll, cfg):
        self.gd, self.weapon, self.rank, self.roll = gamedata, weapon, rank, roll
        self.target, self.x = settings_of(cfg)
        self.rating = {**DEFAULT_RATING, **(cfg.get("rating") or {})}
        cls = weapon.cls
        spliced = spliced_stats()
        self.pool = sorted(n for n, sd in gamedata.stats.items() if sd.base.get(cls) is not None and n not in spliced)
        self.weights = {s: w for s, w in roll.positives.items() if w > 0 and gamedata.stats[s].base.get(cls) is not None}
        # The spliced stat the roll wants most (and can be made on this weapon), and its trait pairs.
        wanted = [(w, s) for s, w in self.weights.items() if s in spliced]
        self.into, self.pairs = None, []
        for w, into in sorted(wanted, key=lambda ws: (-ws[0], ws[1])):
            pairs = [(a, b) for a, b, i, classes in splices() if i == into and cls in classes
                     and a in self.pool and b in self.pool]
            if pairs:
                self.into, self.pairs = into, pairs
                break
        self.traits = {t for pair in self.pairs for t in pair}
        # The shapes the strategy accepts: within CLOSE_ENOUGH of the one holding the most wanted value.
        shapes = [s for s in SHAPES if s[1] is False or roll.negatives]
        best = max(shape_value(s, self.weights) for s in shapes) if self.weights else 0
        self.good_shapes = {s for s in shapes if best and shape_value(s, self.weights) >= CLOSE_ENOUGH * best}
        never_negative = POSITIVE_ONLY | ({"Damage"} if cls == "melee" else set())
        self._classes(never_negative)
        self._transitions = {}
        self.kept_of = {}                     # state key -> (kept stats, shape)
        self._bad_fixed = {}
        self._spliced = spliced_stats()
        self._w1 = {}                         # (stat, shape, is negative) -> its value at W = 1
        self.canon_name = {n: names[0] for names in self.classes for n in names}
        # Per number of positives: the rating's denominator (the best weights it has room for, plus the
        # negative's slot) and that slot, for the quick bound in chance_rated.
        weights = sorted(self.weights_all(), reverse=True)
        self._denoms = {}
        for n in range(0, 4):
            top = weights[:n]
            slot = sum(top) / len(top) if roll.negatives and top else 0.0
            self._denoms[n] = ((sum(top) + slot) or 1.0, slot)
        self.plans = {}

    # -- stats that play the same part are counted together ---------------------------------------
    def _classes(self, never_negative):
        roll = self.roll

        def key(name):
            valued = any(r.stat == name and r.op for r in roll.bad + roll.dealbreakers)
            if valued or name in self.traits:
                return ("own", name)              # judged by its value, or a trait the strategy looks for
            plain = lambda rules: tuple(sorted(r.sign or "" for r in rules if r.stat == name and not r.op))
            return (name not in NEGATIVE_ONLY, name not in never_negative, self.weights.get(name, 0),
                    name in roll.required, name in roll.negatives, plain(roll.bad), plain(roll.dealbreakers))

        groups = {}
        for name in self.pool:
            groups.setdefault(key(name), []).append(name)
        self.classes = [sorted(names) for names in groups.values()]
        self.class_of = {n: i for i, names in enumerate(self.classes) for n in names}
        self.pos_ok = [names[0] not in NEGATIVE_ONLY for names in self.classes]
        self.neg_ok = [names[0] not in never_negative for names in self.classes]

    def canonical(self, stat):
        """The stat renamed to the first of its kind (all of them play the same part)."""
        if stat.name not in self.class_of:
            return stat                           # a spliced stat
        return replace(stat, name=self.classes[self.class_of[stat.name]][0])

    def make(self, name, is_negative, quality, shape, locked=False):
        """A stat at this quality, with its value for this weapon, rank and shape."""
        key = (name, shape, is_negative)
        w1 = self._w1.get(key)
        if w1 is None:
            w1 = self._w1[key] = _value_at_w1(self.gd.stats[name], self.weapon, self.rank, *shape, is_negative)
        W = roll_of(quality)
        return StatResult(name, w1 * W, is_negative, W, quality, locked)

    # -- the rating, exactly ----------------------------------------------------------------------------
    def score(self, stats):
        """The rating (0 - 100) of a riven with these stats, against the roll (as rolls.rate)."""
        mult, const, denom, coeffs = self._affine(stats, [])
        return round(100 * mult * min(const / denom, 1.0), 1)

    def _is_bad(self, stat):
        key = (stat.name, stat.is_negative)
        fixed = self._bad_fixed.get(key)
        if fixed is None:
            rules = [r for r in self.roll.bad if r.stat == stat.name
                     and (not r.sign or (r.sign == "-") == stat.is_negative)]
            wanted = stat.is_negative and self.weights.get(stat.name, 0) > 0   # the roll wants it positive
            fixed = (wanted or any(not r.op for r in rules), [r for r in rules if r.op])
            self._bad_fixed[key] = fixed
        bad, valued = fixed
        return bad or any(r.matches(stat, self.gd.stats[stat.name]) for r in valued)

    def harmless(self, stat):
        return (stat.is_negative and stat.name in self.roll.negatives and not self._is_bad(stat))

    def _affine(self, stats, free):
        """The rating as mult * (const + sum(coeffs[i] * q_i)) / denom, q_i the qualities of the stats at
        the indices in free (the others' qualities are in const). Rule outcomes are taken at the stats'
        qualities as given."""
        roll, type_w = self.roll, self.rating["type_weight"]
        positives = [s for s in stats if not s.is_negative]
        negative = next((s for s in stats if s.is_negative), None)
        top = sorted(self.weights_all(), reverse=True)[:len(positives)]
        const, coeffs = 0.0, []
        for i, s in enumerate(stats):
            if s.is_negative:
                continue
            w = roll.positives.get(s.name, 0.0)
            const += w * type_w
            if i in free:
                coeffs.append(w * (1 - type_w))
            else:
                const += w * (1 - type_w) * s.quality
        bad = sum(self._is_bad(s) for s in stats)
        slot = sum(top) / len(top) if roll.negatives and top else 0.0
        if negative is not None and self.harmless(negative):
            const += slot
        mult = self.rating["bad_stat_score"] ** bad
        have = {s.name for s in positives}
        mult *= self.rating["missing_required_score"] ** sum(r not in have for r in roll.required)
        if any(r.matches(s, self.gd.stats[s.name]) for s in stats for r in roll.dealbreakers):
            mult = 0.0
        return mult, const, (sum(top) + slot) or 1.0, coeffs

    def _out_of_reach(self, stats, ranges, t):
        """Whether even the best rolls can't make this riven rate t (0 - 1): a quick upper bound (no rule
        judged by value counted against it), so most outcomes are ruled out without the integral."""
        roll, type_w = self.roll, self.rating["type_weight"]
        earned, names, bad, n = 0.0, set(), 0, 0
        negative = None
        for i, st in enumerate(stats):
            if st.is_negative:
                negative = st
            else:
                n += 1
                names.add(st.name)
                best = ranges[i][1] if i in ranges else st.quality
                earned += roll.positives.get(st.name, 0.0) * (type_w + (1 - type_w) * best)
            if self._bad_fixed.get((st.name, st.is_negative)) is None:
                self._is_bad(st)                  # works out (and keeps) its badness by rules without values
            bad += self._bad_fixed[(st.name, st.is_negative)][0]
        denom, slot = self._denoms[n]
        if negative is not None and negative.name in roll.negatives and not self._bad_fixed[
                (negative.name, True)][0]:
            earned += slot
        mult = self.rating["bad_stat_score"] ** bad
        mult *= self.rating["missing_required_score"] ** sum(r not in names for r in roll.required)
        return mult * earned / denom < t - 1e-12

    def _shape_out_of_reach(self, shape):
        """Whether no riven of this shape, fresh from a cycle (nothing spliced), could rate the target: its
        best possible stats at their best rolls, a harmless negative if it has one, still fall short."""
        n, has_negative = shape
        rollable = sorted((self.weights.get(nm, 0) for nm in self.pool if nm not in NEGATIVE_ONLY), reverse=True)
        earned = sum(rollable[:n])
        denom, slot = self._denoms[n]
        if has_negative and any(nm in self.roll.negatives and self.weights.get(nm, 0) <= 0 for nm in self.pool):
            earned += slot
        # Required stats a cycle can't roll (a spliced one) are missing for sure.
        missing = sum(r not in self.pool for r in self.roll.required)
        mult = self.rating["missing_required_score"] ** missing
        return mult * earned / denom < (self.target - 0.05) / 100 - 1e-12

    def weights_all(self):
        return [w for w in self.roll.positives.values() if w > 0]

    def chance_rated(self, stats, ranges, target=None):
        """The chance a riven with these stats rates target (the model's, unless given) or more, the stats at
        the indices in ranges rolling evenly over their (low, high) quality range (the others as they are)."""
        t = ((self.target if target is None else target) - 0.05) / 100   # the rating is rounded to 0.1
        if self._out_of_reach(stats, ranges, t):
            return 0.0
        free = sorted(ranges)
        shape = (sum(not s.is_negative for s in stats), any(s.is_negative for s in stats))
        # A rule judged by value splits a stat's range where its outcome changes.
        cuts = []
        for i in free:
            lo, hi = ranges[i]
            points = {lo, hi}
            s = stats[i]
            for r in self.roll.bad + self.roll.dealbreakers:
                if r.stat == s.name and r.op and (not r.sign or (r.sign == "-") == s.is_negative):
                    sd = self.gd.stats[s.name]
                    shown_w1 = _value_at_w1(sd, self.weapon, self.rank, *shape, s.is_negative) \
                        * (1 if sd.unit == "flat" else 100)
                    q = quality_of(r.value / shown_w1)   # the quality at which the shown value is the rule's
                    if lo < q < hi:
                        points.add(q)
            cuts.append(sorted(points))
        total = 0.0
        for cell in itertools.product(*[list(zip(c, c[1:])) for c in cuts]):
            weight = 1.0
            trial = list(stats)
            for i, (lo, hi) in zip(free, cell):
                full = ranges[i][1] - ranges[i][0]
                weight *= (hi - lo) / full if full > 0 else 1.0
                trial[i] = self.make(stats[i].name, stats[i].is_negative, (lo + hi) / 2, shape, stats[i].locked)
            if weight <= 0:
                continue
            positive_free = [i for i in free if not stats[i].is_negative]
            mult, const, denom, coeffs = self._affine(trial, positive_free)
            if mult <= 0:
                continue
            need = t * denom / mult - const                    # sum(coeffs * q) must reach this
            bounds = [cell[free.index(i)] for i in positive_free]
            total += weight * _uniform_sum_at_least(coeffs, bounds, need)
        return min(max(total, 0.0), 1.0)

    # -- the strategy ---------------------------------------------------------------------------------
    def step(self, stats, check_done=True):
        """The strategy's Action for a riven with these stats (StatResults; the locked flag says what's
        locked now, which is kept between equals)."""
        positives = [s for s in stats if not s.is_negative]
        negative = next((s for s in stats if s.is_negative), None)
        shape = (len(positives), negative is not None)
        spliced = [s for s in positives if s.name in self._spliced]
        current = next((s for s in stats if s.locked and s.name not in self._spliced), None)
        if check_done and self.score(stats) >= self.target:
            return Action("done", "done")
        unwanted = [s for s in spliced if self.weights.get(s.name, 0) <= 0]
        if unwanted:                              # kept for good, it can't be part of the roll: start over
            return Action("cycle", "unsplice", unlock=unwanted[0])
        if not spliced and shape not in self.good_shapes:
            return Action("cycle", "shape")
        if self.into and not spliced:
            traits = [s for s in positives if s.name in self.traits]
            over = [s for s in traits if s.quality >= self.x]
            if not over:
                return Action("cycle", "trait", self._most_useful(stats, current))
            names = {s.name: s for s in positives}
            ready = [(max(names[a].quality, names[b].quality), a, b) for a, b in self.pairs
                     if a in names and b in names and max(names[a].quality, names[b].quality) >= self.x]
            if ready:
                _, a, b = max(ready)
                return Action("splice", "splice", current, (a, b), self.into)
            return Action("cycle", "partner", max(over, key=lambda s: (s.quality, s is current)))
        wanted = [s for s in positives if s.name not in self._spliced and self.weights.get(s.name, 0) > 0]
        if wanted:
            return Action("cycle", "wanted", self._pick(wanted, current, lambda s: self._tier(s)))
        return Action("cycle", "useful", self._most_useful(stats, current))

    def _tier(self, s):
        return (self.weights.get(s.name, 0), s.name in self.roll.required)

    def _pick(self, choices, current, rank):
        """The best of choices by rank, the current lock first between equals, then the better roll."""
        best = max(rank(s) for s in choices)
        equal = [s for s in choices if rank(s) == best]
        return next((s for s in equal if s is current), None) or max(equal, key=lambda s: s.quality)

    def _most_useful(self, stats, current):
        choices = [s for s in stats if s.name not in self._spliced]
        if not choices:
            return None

        def rank(s):
            if self.harmless(s):
                return (5, 0, False)
            if not s.is_negative and self.weights.get(s.name, 0) > 0:
                return (4, *self._tier(s))
            if not s.is_negative and s.name in self.traits:
                return (3, 0, False)
            if not self._is_bad(s):
                return (2 if not s.is_negative else 1, 0, False)
            return (0, 0, False)
        return self._pick(choices, current, rank)

    # -- cycles ---------------------------------------------------------------------------------------
    def kept_after(self, stats, action):
        """What the next cycle keeps: the spliced stat, and the lock (canonical names, locked flags set)."""
        spliced = [replace(self.canonical(s), locked=False) for s in stats if s.name in self._spliced]
        lock = [replace(self.canonical(action.lock), locked=True)] if action.lock is not None else []
        return tuple(spliced + lock)

    def state_key(self, kept, shape):
        return (shape if kept else None,
                tuple(sorted((s.name, s.is_negative, round(s.quality, 4), s.locked) for s in kept)))

    def outcomes(self, kept, shape):
        """[(chance, stats, ranges)]: every kind of riven the next cycle can make, keeping kept (on this
        shape; with nothing kept the shape rolls too, each equally likely). ranges: {index: (low, high)}
        of the stats freshly rolled, whose qualities are still to be integrated over."""
        if not kept:
            return [(c / len(SHAPES), st, rg) for sh in SHAPES for c, st, rg in self._fill((), sh)]
        return self._fill(kept, shape)

    def _fill(self, kept, shape):
        n, has_negative = shape
        used = {}
        for s in kept:
            if s.name in self.class_of:
                c = self.class_of[s.name]
                used[c] = used.get(c, 0) + 1
        avail = [len(names) - used.get(i, 0) for i, names in enumerate(self.classes)]
        free_pos = n - sum(not s.is_negative for s in kept)
        free_neg = has_negative and not any(s.is_negative for s in kept)
        pos_classes = [i for i in range(len(self.classes)) if self.pos_ok[i] and avail[i] > 0]
        total_pos = sum(avail[i] for i in pos_classes)
        out = []
        for counts in _multisets(pos_classes, [avail[i] for i in pos_classes], free_pos):
            chance = math.prod(math.comb(avail[c], m) for c, m in counts.items()) / math.comb(total_pos, free_pos)
            names = []
            for c, m in counts.items():
                taken = {s.name for s in kept}
                names += [nm for nm in self.classes[c] if nm not in taken][:m]
            negs = [(None, 1.0)]
            if free_neg:
                left = {i: avail[i] - counts.get(i, 0) for i in range(len(self.classes)) if self.neg_ok[i]}
                total_neg = sum(left.values())
                taken = {s.name for s in kept} | set(names)
                negs = [(next(nm for nm in self.classes[c] if nm not in taken), k / total_neg)
                        for c, k in left.items() if k > 0]
            for neg, p_neg in negs:
                fresh = [(nm, False) for nm in names] + ([(neg, True)] if neg else [])
                for stats, ranges, p_q in self._qualities(kept, fresh, shape):
                    out.append((chance * p_neg * p_q, stats, ranges))
        return out

    def _qualities(self, kept, fresh, shape):
        """The fresh stats at representative qualities: [(stats, ranges, chance)]. A trait of the spliced
        stat is split at X (the strategy treats them differently), and into BANDS bands above it: the splice
        keeps its roll for good, so it's counted by band, not at the average."""
        options = []
        for name, is_negative in fresh:
            if not is_negative and name in self.traits:
                cuts = sorted({Q0, 1.0} | ({self.x} if Q0 < self.x < 1 else set())
                              | {self.x + (1 - self.x) * k / BANDS for k in range(1, BANDS)})
                options.append([((lo, hi), (hi - lo) / (1 - Q0)) for lo, hi in zip(cuts, cuts[1:])])
            else:                                 # (a wanted stat is split later, if it's locked: _bands)
                options.append([((Q0, 1.0), 1.0)])
        out = []
        for choice in itertools.product(*options):
            stats = list(kept)
            ranges = {}
            chance = 1.0
            for (name, is_negative), ((lo, hi), p) in zip(fresh, choice):
                ranges[len(stats)] = (lo, hi)
                stats.append(self.make(name, is_negative, (lo + hi) / 2, shape))
                chance *= p
            out.append((stats, ranges, chance))
        return out

    def splice(self, stats, action):
        """[(chance, stats, ranges)] after splicing: the two traits become the spliced stat (keeping the
        better roll, for good) and a random trait takes the freed positive slot."""
        shape = (sum(not s.is_negative for s in stats), any(s.is_negative for s in stats))
        a, b = action.pair
        keeps = max(s.quality for s in stats if s.name in (a, b))
        rest = [s for s in stats if s.name not in (a, b)]
        into = self.make(action.into, False, keeps, shape)
        rest = [replace(s, locked=action.lock is not None and s.name == action.lock.name
                        and s.is_negative == action.lock.is_negative) for s in rest]
        taken = {s.name for s in rest} | {a, b}
        groups = {}
        for nm in self.pool:
            if nm not in taken and nm not in NEGATIVE_ONLY:
                groups.setdefault(self.class_of[nm], []).append(nm)
        total = sum(len(names) for names in groups.values())
        out = []
        for names in groups.values():
            for stats2, ranges, p in self._qualities(rest + [into], [(names[0], False)], shape):
                out.append((len(names) / total * p, stats2, ranges))
        return out

    def transitions(self, kept, shape):
        """{next state key: chance}, chance done, for one cycle keeping kept (memoised). The next states'
        kept stats are in self.kept_of."""
        key = self.state_key(kept, shape)
        if key in self._transitions:
            return self._transitions[key]
        moves, done = {}, 0.0
        if kept:
            outcomes = self.outcomes(kept, shape)
        else:
            # Nothing kept: the shape rolls too. A shape the strategy doesn't accept, where no riven could
            # rate the target, just means cycling again: no need to go through its outcomes one by one.
            outcomes = []
            for sh in SHAPES:
                if sh not in self.good_shapes and self._shape_out_of_reach(sh):
                    moves[(None, ())] = moves.get((None, ()), 0.0) + 1 / len(SHAPES)
                    self.kept_of.setdefault((None, ()), ((), sh))
                else:
                    outcomes += [(c / len(SHAPES), st, rg) for c, st, rg in self._fill((), sh)]
        for chance, stats, ranges in outcomes:
            if chance > 0:
                done += self._settle(stats, ranges, chance, moves)
        result = (moves, done)
        self._transitions[key] = result
        return result

    def _settle(self, stats, ranges, chance, moves):
        """Where a riven fresh from a cycle (or a splice) goes: done, with its chance of rating the target;
        otherwise the strategy's next state, added to moves (a splice first, if that's the step). Returns the
        chance it's done."""
        action = self.step(stats, check_done=False)
        done = 0.0
        for share, stats2, ranges2, action2 in self._bands(stats, ranges, action):
            p_done = self.chance_rated(stats2, ranges2)
            done += chance * share * p_done
            rest = chance * share * (1 - p_done)
            if rest <= 0:
                continue
            if action2.kind == "splice":
                for p, stats3, ranges3 in self.splice(stats2, action2):
                    done += self._settle(stats3, ranges3, rest * p, moves)
            else:
                self._add(moves, stats2, action2, rest)
        return done

    def _bands(self, stats, ranges, action):
        """[(share, stats, ranges, action)]: the outcome as it is, or, when the strategy locks a wanted stat
        that was just rolled, that stat split into BANDS bands of its range. Its roll counts for every cycle
        it stays locked, so it's counted by band, not at the average (and the rivens still going are the
        ones that rolled worse)."""
        lock = action.lock
        i = next((k for k, st in enumerate(stats) if st is lock), None)
        if (i is None or i not in ranges or lock.is_negative or lock.name in self.traits
                or self.weights.get(lock.name, 0) <= 0):
            return [(1.0, stats, ranges, action)]
        lo, hi = ranges[i]
        shape = (sum(not st.is_negative for st in stats), any(st.is_negative for st in stats))
        out = []
        for k in range(BANDS):
            a, b = lo + (hi - lo) * k / BANDS, lo + (hi - lo) * (k + 1) / BANDS
            banded = self.make(lock.name, False, (a + b) / 2, shape, lock.locked)
            stats2 = stats[:i] + [banded] + stats[i + 1:]
            out.append((1 / BANDS, stats2, {**ranges, i: (a, b)}, replace(action, lock=banded)))
        return out

    def _add(self, moves, stats, action, chance):
        shape = (sum(not s.is_negative for s in stats), any(s.is_negative for s in stats))
        if action.stage in ("shape", "unsplice"):
            key = (None, ())
            if key not in self.kept_of:
                self.kept_of[key] = ((), shape)
        else:
            # The key straight from the stats (as state_key would make it), the kept stats built only once.
            items = [(s.name, s.is_negative, round(s.quality, 4), False) for s in stats if s.name in self._spliced]
            lock = action.lock
            if lock is not None:
                items.append((self.canon_name.get(lock.name, lock.name), lock.is_negative, round(lock.quality, 4),
                              True))
            key = (shape, tuple(sorted(items))) if items else (None, ())
            if key not in self.kept_of:
                self.kept_of[key] = (self.kept_after(stats, action), shape)
        moves[key] = moves.get(key, 0.0) + chance

    # -- the expected Kuva ---------------------------------------------------------------------------
    def expected(self, stats, next_base=None):
        """(expected Kuva to reach the target following the strategy from a riven with these stats, the
        strategy's Action for it now); Kuva None when the strategy can't get there."""
        action = self.step(stats)
        if action.kind == "done":
            return 0.0, action
        start, finished = {}, 0.0
        if action.kind == "splice":
            for p, stats2, ranges2 in self.splice(stats, action):
                finished += self._settle(stats2, ranges2, p, start)
        else:
            self._add(start, stats, action, 1.0)
        if not start:
            return (0.0 if finished > 0 else None), action
        # Every state the strategy can reach.
        order, todo, edges = [], list(start), {}
        index = {}
        while todo:
            key = todo.pop()
            if key in index:
                continue
            if len(index) >= MAX_STATES:
                return None, action
            index[key] = len(order)
            order.append(key)
            kept, shape = self.kept_of[key]
            moves, done = self.transitions(kept, shape)
            edges[key] = (moves, done)
            todo += [k for k in moves if k != ("done",) and k not in index]
        size = len(order)
        Q = np.zeros((size, size))
        absorb = np.zeros(size)
        for key, (moves, done) in edges.items():
            i = index[key]
            absorb[i] = done + moves.get(("done",), 0.0)
            for k, p in moves.items():
                if k != ("done",):
                    Q[i, index[k]] += p
        # States from which the strategy never finishes make the expected Kuva infinite.
        can_finish = absorb > 1e-15
        for _ in range(size):
            grown = can_finish | (Q[:, can_finish].sum(axis=1) > 0)
            if (grown == can_finish).all():
                break
            can_finish = grown
        v = np.zeros(size)
        for key, p in start.items():
            v[index[key]] += p
        reach = v > 0
        for _ in range(size):
            grown = reach | (reach @ (Q > 0))
            if (grown == reach).all():
                break
            reach = grown
        if (reach & ~can_finish).any():
            return None, action
        double = np.array([2.0 if any(s.locked for s in self.kept_of[k][0]) else 1.0 for k in order])
        first = COSTS.index(next_base) if next_base in COSTS else len(COSTS) - 1
        total = 0.0
        for base in COSTS[first:-1]:              # the rising base rates, one cycle each
            total += base * (v @ double)
            v = v @ Q
        try:
            visits = np.linalg.solve(np.eye(size) - Q.T, v)   # expected cycles in each state from here on
        except np.linalg.LinAlgError:
            return None, action
        total += CAP * (visits @ double)
        return float(total), action


def _multisets(classes, limits, k):
    """Every way to take k items from the classes, at most limits[i] from each: [{class: count}]."""
    out = []

    def go(i, left, acc):
        if left == 0:
            out.append(dict(acc))
            return
        if i == len(classes):
            return
        for m in range(min(left, limits[i]), -1, -1):
            if m:
                acc[classes[i]] = m
            go(i + 1, left - m, acc)
            acc.pop(classes[i], None)
    go(0, k, {})
    return out


def _uniform_sum_at_least(coeffs, bounds, need):
    """P(sum(coeffs[i] * q_i) >= need) with q_i spread evenly over bounds[i] = (low, high)."""
    base = sum(c * lo for c, (lo, hi) in zip(coeffs, bounds))
    spans = [c * (hi - lo) for c, (lo, hi) in zip(coeffs, bounds) if c * (hi - lo) > 1e-12]
    s = need - base
    if s <= 0:
        return 1.0
    if s >= sum(spans):
        return 0.0
    n = len(spans)
    # The CDF of a sum of evenly spread values: sum over subsets of (-1)^|S| (s - sum_S)^n / (n! prod).
    cdf = 0.0
    for size in range(n + 1):
        for subset in itertools.combinations(spans, size):
            x = s - sum(subset)
            if x > 0:
                cdf += (-1) ** size * x ** n
    cdf /= math.factorial(n) * math.prod(spans)
    return min(max(1.0 - cdf, 0.0), 1.0)


def describe(found, result, analyzer):
    """(what to do, why) for NEXT, from plan()'s (Kuva, Action)."""
    kuva, action = found
    target, x = settings_of(analyzer.cfg)
    ev = result.ev
    model = model_for(analyzer, ev.weapon, ev.rank, result.rating.roll)
    current = next((s for s in ev.stats if s.locked and s.name not in spliced_stats()), None)
    amount = (f"about {kuva_amount(kuva)} Kuva to {target:g}%+" if kuva is not None
              else f"{target:g}%+ is out of reach this way")
    if action.kind == "done":
        return "Done", f"rated {target:g}%+"
    if action.kind == "splice":
        keeps = max(s.quality for s in ev.stats if s.name in action.pair)
        return f"Splice {action.pair[0]} + {action.pair[1]}", f"into {action.into}, keeps {keeps * 100:.0f}%"
    if action.stage == "unsplice":
        what = f"Unlock {action.unlock.name}" + (f" and {stat_label(current)}" if current else "")
        return what, f"(the roll doesn't want it), then cycle without a lock to start the riven over; {amount}"
    if action.stage == "shape":
        from .advice import shape_text
        shape = (len(ev.positives), ev.negative is not None)
        aim = max(model.good_shapes, key=lambda sh: shape_value(sh, model.weights))
        why = f"for {shape_text(*aim)} (has {shape_text(*shape)}); {amount}"
        return (f"Unlock {stat_label(current)}", "then cycle " + why) if current else ("Cycle without a lock", why)
    traits = " or ".join(sorted(model.traits))
    if action.stage == "trait":
        why = f"for {traits} over {x * 100:.0f}% (to splice into {model.into})"
    elif action.stage == "partner":
        partners = sorted({b if a == action.lock.name else a for a, b in model.pairs if action.lock.name in (a, b)})
        why = f"for {' or '.join(partners)} to splice into {model.into}"
    elif action.stage == "wanted":
        why = "for the other wanted stats"
    else:
        why = "for a wanted stat"
    why += f"; {amount}"
    lock = action.lock
    if lock is None:
        return "Cycle", why
    same = current is not None and current.name == lock.name and current.is_negative == lock.is_negative
    if same:
        return f"Keep {stat_label(lock)} locked", "and cycle " + why
    if current is not None:
        return f"Lock {stat_label(lock)} instead", f"of {stat_label(current)}, then cycle {why}"
    return f"Lock {stat_label(lock)}", "then cycle " + why


def splice_note(result, analyzer):
    """"splicing Heat + Cold into Blast on the way" when the strategy goes through a splice, else None."""
    ev = result.ev
    model = model_for(analyzer, ev.weapon, ev.rank, result.rating.roll)
    if not model.into or any(s.name in spliced_stats() for s in ev.stats):
        return None
    pairs = " or ".join(f"{a} + {b}" for a, b in model.pairs)
    return f"splicing {pairs} into {model.into} on the way"


_models = {}
_models_lock = threading.Lock()      # the planning thread and the panels both look models up


def model_for(analyzer, weapon, rank, roll):
    """The Model for a weapon, rank and roll under the current settings (made once)."""
    cfg = analyzer.cfg
    key = (id(analyzer.library), weapon.name, rank, id(roll), settings_of(cfg), str(cfg.get("rating")))
    with _models_lock:
        if key not in _models:
            if len(_models) > 32:
                _models.clear()
            _models[key] = Model(analyzer.gamedata, weapon, rank, roll, cfg)
        return _models[key]


def plan(result, analyzer, compute=None):
    """(expected Kuva to reach the target, the strategy's Action now) for a rated card, or None when there's
    no plan (no target, an unreadable card, no roll), or when it hasn't been worked out yet and compute is
    false. compute defaults to true, except in the overlay (analyzer.plan_ahead set): there the worker
    thread works plans out (warm) and the panels only use those, so drawing never waits on one. Kuva is
    None when the strategy can't get there."""
    found = _model_and_key(result, analyzer)
    if found is None:
        return None
    model, stats, key = found
    known = model.plans.get(key)                  # once: the planning thread may clear the cache meanwhile
    if known is None:
        if not (compute if compute is not None else not getattr(analyzer, "plan_ahead", False)):
            return None
        if len(model.plans) > 64:
            model.plans.clear()
        kuva, _ = model.expected(stats, analyzer.cycle_base)
        known = model.plans[key] = (kuva, model.step(list(result.ev.stats)))   # the Action, names as on the card
    return known


def chance_of_better(result, analyzer, compute=None):
    """The chance (0 - 1) that the next cycle, of the riven as it is (its lock kept), rates higher than it does
    now against the same roll, worked out exactly like plan() (and compute as there); or None."""
    found = _model_and_key(result, analyzer, need_target=False)
    if found is None:
        return None
    model, stats, key = found
    key = ("better",) + key
    known = model.plans.get(key)
    if known is None:
        if not (compute if compute is not None else not getattr(analyzer, "plan_ahead", False)):
            return None
        score = model.score(stats)
        shape = (sum(not s.is_negative for s in stats), any(s.is_negative for s in stats))
        kept = tuple(replace(s, locked=s.locked and s.name not in spliced_stats()) for s in stats
                     if s.locked or s.name in spliced_stats())
        known = model.plans[key] = sum(chance * model.chance_rated(st, rg, score + 0.1)
                                       for chance, st, rg in model.outcomes(kept, shape) if chance > 0)
    return known


def warm(results, analyzer):
    """Work out the plans (and the next-cycle odds of a lone card) for these results ahead of drawing.
    Returns whether anything was new (then the panels are worth drawing again)."""
    new = False
    for result in results:
        if plan(result, analyzer, compute=False) is None and result.ev is not None:
            new = plan(result, analyzer, compute=True) is not None or new
    if len(results) == 1 and chance_of_better(results[0], analyzer, compute=False) is None:
        new = chance_of_better(results[0], analyzer, compute=True) is not None or new
    return new


def warm_ahead(results, analyzer, stop=lambda: False):
    """Work out the plans for each card against every other roll of its weapon too, so switching rolls
    (the cycle-roll hotkey) finds them ready. Stops early when stop() says something newer is waiting."""
    from .rolls import rate
    for result in results:
        ev = result.ev
        if ev is None or not ev.consistent:
            continue
        for roll in analyzer.library.rolls_for(ev.weapon):
            if stop():
                return
            other = replace(result, rating=rate(ev, [roll], analyzer.gamedata, analyzer.cfg["rating"]))
            plan(other, analyzer, compute=True)
            if len(results) == 1:
                chance_of_better(other, analyzer, compute=True)


def _model_and_key(result, analyzer, need_target=True):
    target, _ = settings_of(analyzer.cfg)
    ev, rating = result.ev, result.rating
    if (need_target and not target) or ev is None or rating is None or rating.roll is None or not ev.consistent:
        return None
    model = model_for(analyzer, ev.weapon, ev.rank, rating.roll)
    stats = [model.canonical(s) for s in ev.stats]
    key = (tuple((s.name, round(s.magnitude, 4), s.is_negative, s.locked) for s in stats), analyzer.cycle_base)
    return model, stats, key
