"""The reroll strategy (flowchart) and its exact Kuva (flow.py), checked against rolls.rate and against
playing the strategy out cycle by cycle."""

import random
import statistics
import unittest
from dataclasses import replace

from riven_helper import flow
from riven_helper.advice import next_step
from riven_helper.analyze import CardResult
from riven_helper.kuva import COSTS
from riven_helper.odds import NEGATIVE_ONLY, POSITIVE_ONLY
from riven_helper.riven_math import RivenEval
from riven_helper.rolls import rate

from tests.helpers import G, analyzer, riven, roll_library, saved_ocr

BLAST_CRIT = {"label": "Blast Crit", "positives": {"Blast": 1, "CD": 0.75, "CC": 0.75, "Damage": 0.5, "MS": 0.5},
              "required": ["Blast"], "negatives": ["Zoom", "Slash", "Impact", "Puncture"]}
WISHLIST = {"bad": ["+Zoom", "+Slash", "+Impact", "+Puncture"], "dealbreakers": ["-Damage >= 100"]}


def gaze(target=75, splice_min=50):
    """The Gaze (Secondary) snapshot, rated against the wishlist's Blast Crit roll."""
    an = analyzer()
    an.library = roll_library({**WISHLIST, "weapons": {"Gaze": BLAST_CRIT}})
    an.cfg = dict(an.cfg, kuva_target=target, splice_min=splice_min)
    (res,) = an.analyze_lines(saved_ocr("ocr_gaze_kitgun.json"), 1920)
    return an, res, flow.model_for(an, res.ev.weapon, res.ev.rank, res.rating.roll)


def play(model, stats, base, rng):
    """The Kuva to reach the target following the strategy, by playing it out with random cycles (the
    same rules odds.py simulates), for checking the exact answer."""
    never_negative = POSITIVE_ONLY | ({"Damage"} if model.weapon.cls == "melee" else set())
    k, kuva = COSTS.index(base) if base in COSTS else len(COSTS) - 1, 0.0
    for _ in range(100000):
        action = model.step(stats)
        if action.kind == "done":
            return kuva
        shape = (sum(not s.is_negative for s in stats), any(s.is_negative for s in stats))
        if action.kind == "splice":
            keeps = max(s.quality for s in stats if s.name in action.pair)
            rest = [s for s in stats if s.name not in action.pair]
            taken = {s.name for s in rest} | set(action.pair)
            new = rng.choice([p for p in model.pool if p not in taken and p not in NEGATIVE_ONLY])
            stats = rest + [model.make(action.into, False, keeps, shape),
                            model.make(new, False, rng.random(), shape)]
            continue
        lock = action.lock
        stats = [replace(s, locked=lock is not None and s.name == lock.name and s.is_negative == lock.is_negative)
                 for s in stats]
        kept = [s for s in stats if s.locked or s.name in flow.spliced_stats()]
        kuva += COSTS[min(k, len(COSTS) - 1)] * (2 if any(s.locked for s in kept) else 1)
        k += 1
        n, has_negative = shape if kept else rng.choice(flow.SHAPES)
        stats, taken = list(kept), {s.name for s in kept}
        for _ in range(n - sum(not s.is_negative for s in kept)):
            name = rng.choice([p for p in model.pool if p not in taken and p not in NEGATIVE_ONLY])
            taken.add(name)
            stats.append(model.make(name, False, rng.random(), (n, has_negative)))
        if has_negative and not any(s.is_negative for s in kept):
            name = rng.choice([p for p in model.pool if p not in taken and p not in never_negative])
            stats.append(model.make(name, True, rng.random(), (n, has_negative)))
    return None


class TestExact(unittest.TestCase):
    def test_rating_is_rolls_rate(self):
        # The model's own rating (which the exact chances integrate) is rolls.rate's, on every kind of riven,
        # value-judged rules (a dealbreaker on -Damage >= 100) included.
        an, res, model = gaze()
        rng = random.Random(3)
        for _ in range(3000):
            shape = rng.choice(flow.SHAPES)
            names = rng.sample(model.pool + ["Blast"], shape[0] + shape[1])
            stats = [model.make(nm, i >= shape[0] and nm not in POSITIVE_ONLY | {"Blast"},
                                rng.random(), shape) for i, nm in enumerate(names)]
            stats = [s for s in stats if not (s.is_negative and s.name in NEGATIVE_ONLY | {"Blast"})]
            expected = rate(RivenEval(model.weapon, model.rank, stats, True), [model.roll], G, an.cfg["rating"])
            self.assertAlmostEqual(model.score(stats), expected.score, places=1, msg=[s.name for s in stats])

    def test_every_outcome_counted_once(self):
        an, res, model = gaze()
        flow.plan(res, an)
        self.assertGreater(len(model.kept_of), 3)
        for kept, shape in list(model.kept_of.values()) + [((), None)]:
            self.assertAlmostEqual(sum(c for c, _, _ in model.outcomes(kept, shape)), 1.0, places=9)

    def test_chance_of_the_target_is_exact(self):
        # Where the rolls decide it: the three wanted stats score 90 - 100% by how well they rolled.
        an = analyzer()
        roll = roll_library({"weapons": {"Soma": {"positives": ["CD", "MS", "CC"], "negatives": ["Zoom", "Damage"],
                                                  "dealbreakers": ["-Damage >= 140"]}}}).rolls_for(
            G.weapon_by_name("Soma"))[0]
        an.cfg = dict(an.cfg, kuva_target=97)
        model = flow.Model(G, G.weapon_by_name("Soma"), 8, roll, an.cfg)
        shape = (3, True)
        rng = random.Random(5)
        # -Damage rolls 128 - 157% here: over 140% the riven scores 0, a rule judged by value.
        for negative in ("Zoom", "Damage"):
            stats = [model.make(n, False, 0.9, shape) for n in ("Critical Damage", "Multishot", "Critical Chance")]
            stats.append(model.make(negative, True, 0.9, shape))
            ranges = {0: (flow.Q0, 1.0), 1: (flow.Q0, 1.0), 2: (flow.Q0, 1.0), 3: (flow.Q0, 1.0)}
            exact = model.chance_rated(stats, ranges)
            hits = 0
            for _ in range(20000):
                trial = [model.make(s.name, s.is_negative, rng.uniform(lo, hi), shape)
                         for s, (lo, hi) in zip(stats, ranges.values())]
                hits += rate(RivenEval(model.weapon, 8, trial, True), [roll], G, an.cfg["rating"]).score >= 97
            self.assertTrue(0.05 < exact < 0.95, (negative, exact))
            self.assertAlmostEqual(exact, hits / 20000, delta=0.015, msg=negative)

    def test_kuva_is_what_playing_the_strategy_out_costs(self):
        an, res, model = gaze()
        kuva, action = flow.plan(res, an)
        rng = random.Random(11)
        runs = [play(model, list(res.ev.stats), an.cycle_base, rng) for _ in range(500)]
        mean, error = statistics.mean(runs), statistics.stdev(runs) / len(runs) ** 0.5
        self.assertLess(abs(kuva - mean), 4 * error, (kuva, mean, error))


class TestFlowchart(unittest.TestCase):
    def test_lock_the_harmless_negative_while_looking_for_a_trait(self):
        # Blast is wanted (required): no Heat or Cold yet, so lock the most useful stat, the harmless -Puncture.
        an, res, model = gaze()
        action, why = next_step(res, G, an)
        self.assertEqual(action, "Lock -Puncture")
        self.assertIn("Cold or Heat over 50% (to splice into Blast)", why)
        self.assertIn("Kuva to 75%+", why)

    def test_a_trait_over_x_waits_for_its_partner(self):
        # Both cards of the next snapshot have Cold locked, rolled 10% up its range: over an X of 5%, so wait
        # for Heat. Under the X of 50% it isn't: then the most useful lock (card 1's harmless -Zoom) while
        # looking for a trait.
        def cards(splice_min):
            an = analyzer()
            an.library = roll_library({**WISHLIST, "weapons": {"Larkspur": BLAST_CRIT}})
            an.cfg = dict(an.cfg, kuva_target=75, splice_min=splice_min)
            return an, an.analyze_lines(saved_ocr("ocr_cycle_larkspur_cold_locked.json"), 1920)
        an, (one, two) = cards(5)
        self.assertEqual(next_step(one, G, an)[0], "Keep Cold locked")
        self.assertIn("for Heat to splice into Blast", next_step(one, G, an)[1])
        an, (one, two) = cards(50)
        self.assertEqual(next_step(one, G, an)[0], "Lock -Zoom instead")
        self.assertIn("over 50%", next_step(one, G, an)[1])

    def test_splice_when_both_traits_are_there(self):
        an, res, model = gaze()
        stats = [model.make("Heat", False, 0.85, (3, True)), model.make("Cold", False, 0.95, (3, True)),
                 model.make("Toxin", False, 0.9, (3, True)), model.make("Zoom", True, 0.9, (3, True))]
        ev = RivenEval(model.weapon, model.rank, stats, True)
        card = CardResult(None, ev, rate(ev, [model.roll], G))
        self.assertEqual(next_step(card, G, an), ("Splice Heat + Cold", "into Blast, keeps 95%"))

    def test_wrong_shape_cycles_without_a_lock(self):
        an, res, model = gaze()
        stats = [model.make("Critical Damage", False, 0.9, (3, False), locked=True),
                 model.make("Toxin", False, 0.9, (3, False)), model.make("Ammo Maximum", False, 0.9, (3, False))]
        ev = RivenEval(model.weapon, model.rank, stats, True)
        card = CardResult(None, ev, rate(ev, [model.roll], G))
        action, why = next_step(card, G, an)
        self.assertEqual(action, "Unlock Critical Damage")
        self.assertIn("for 3 pos + neg (has 3 pos, no neg)", why)

    def test_unwanted_spliced_stat_is_unlocked(self):
        # A spliced stat the roll doesn't want (Gas, for Blast Crit) stays for good, so the strategy could
        # never get there with it: unlock it (and the lock) and cycle, starting the riven over.
        an, res, model = gaze()
        shape = (3, True)
        stats = [model.make("Gas", False, 0.9, shape), model.make("Critical Damage", False, 0.9, shape, locked=True),
                 model.make("Toxin", False, 0.5, shape), model.make("Zoom", True, 0.5, shape)]
        ev = RivenEval(model.weapon, model.rank, stats, True)
        card = CardResult(None, ev, rate(ev, [model.roll], G))
        action, why = next_step(card, G, an)
        self.assertEqual(action, "Unlock Gas and Critical Damage")
        self.assertIn("start the riven over", why)
        kuva, _ = flow.plan(card, an)
        self.assertIsNotNone(kuva)
        # Starting over is a fresh riven: the same Kuva as one with nothing locked and the wrong shape.
        fresh = [model.make("Toxin", False, 0.5, (3, False)), model.make("Ammo Maximum", False, 0.5, (3, False)),
                 model.make("Reload Speed", False, 0.5, (3, False))]
        ev2 = RivenEval(model.weapon, model.rank, fresh, True)
        self.assertAlmostEqual(kuva, flow.plan(CardResult(None, ev2, rate(ev2, [model.roll], G)), an)[0], delta=1)

    def test_out_of_reach(self):
        from riven_helper.panel_text import kuva_text
        an, res, model = gaze(target=100.1)
        self.assertIsNone(flow.plan(res, an)[0])
        self.assertEqual(kuva_text(res, an), ("100.1%+ is out of reach with this roll's strategy", None))

    def test_planned_within_a_second(self):
        # Rerolling is constant, so a plan should take well under a second, even the first for a weapon
        # (nothing worked out yet): the slowest saved riven, a Larkspur of the wrong shape, and the Gaze.
        import time
        an = analyzer()
        an.library = roll_library({**WISHLIST, "weapons": {"Larkspur": BLAST_CRIT, "Gaze": BLAST_CRIT}})
        an.cfg = dict(an.cfg, kuva_target=90, splice_min=50)
        for name, card in (("ocr_cycle_larkspur.json", 0), ("ocr_gaze_kitgun.json", 0)):
            res = an.analyze_lines(saved_ocr(name), 1920)[card]
            flow._models.clear()
            start = time.time()
            self.assertIsNotNone(flow.plan(res, an)[0])
            self.assertLess(time.time() - start, 1.0, name)


if __name__ == "__main__":
    unittest.main()
