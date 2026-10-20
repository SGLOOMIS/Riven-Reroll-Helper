"""The NEXT STEP advice: shape first, one lock, one splice, roll values last."""

import unittest

from riven_helper.advice import next_step, progress, splices
from riven_helper.analyze import CardResult
from riven_helper.rolls import rate

from tests.helpers import G, analyzer, riven, roll_library, saved_ocr

ROLLS = roll_library({"weapons": {
    # 3 positives + a negative is the best shape for this roll (three stats wanted fully).
    "Soma": {"positives": {"CD": 1, "MS": 1, "CC": 0.8, "Damage": 0.5}, "negatives": ["Zoom"]},
    # Weak Point Critical Chance (spliced from Critical Chance + Multishot) is wanted more than either.
    "Rubico": {"positives": {"Weak Point Critical Chance": 1, "CD": 1, "Damage": 1, "CC": 0.5, "MS": 0.5},
               "negatives": ["Zoom"]}}})


def step_with(library, weapon, positives, negative=None, locked=(), W=1.1):
    """The advice for a made-up riven (all stats rolled at W), rated against library's rolls."""
    ev = riven(weapon, positives, negative, W)
    for s in ev.stats:
        s.locked = s.name in locked
    rating = rate(ev, library.rolls_for(G.weapon_by_name(weapon)), G)
    return next_step(CardResult(None, ev, rating), G)


def step(weapon, positives, negative=None, locked=(), W=1.1):
    return step_with(ROLLS, weapon, positives, negative, locked, W)


class TestNextStep(unittest.TestCase):
    def test_wrong_shape_cycles_without_a_lock(self):
        action, why = step("Soma", ["Critical Damage", "Status Chance"])
        self.assertEqual(action, "Cycle without a lock")
        self.assertIn("3 pos + neg", why)
        action, _ = step("Soma", ["Critical Damage", "Status Chance"], locked=["Critical Damage"])
        self.assertEqual(action, "Unlock Critical Damage")        # the lock would keep the wrong shape

    def test_lock_the_most_wanted_stat(self):
        self.assertEqual(step("Soma", ["Critical Chance", "Critical Damage", "Impact"], "Zoom")[0],
                         "Lock Critical Damage")                     # weight 1 beats Critical Chance's 0.8
        self.assertEqual(step("Soma", ["Critical Damage", "Status Chance", "Impact"], "Zoom",
                              locked=["Critical Damage"])[0], "Keep Critical Damage locked")
        self.assertEqual(step("Soma", ["Critical Damage", "Status Chance", "Multishot"], "Zoom",
                              locked=["Status Chance"])[0], "Lock Critical Damage instead")
        self.assertEqual(step("Soma", ["Impact", "Status Chance", "Puncture"], "Zoom")[0], "Cycle")

    def test_lock_moves_to_the_better_stat(self):
        # From a snapshot: Torid, Critical Chance locked (87%) and Critical Damage (92%), both weight 1.
        # Either gets to the baseline, but the best riven builds on the better roll.
        lib = roll_library({"weapons": {"Torid": {"positives": ["Critical Damage", "Blast", "Critical Chance"],
                                                  "negatives": ["Zoom", "Impact"]}}})
        an = analyzer()
        an.library = lib
        (torid,) = an.analyze_lines(saved_ocr("ocr_torid_locked.json"), 1920)
        self.assertEqual([s.name for s in torid.ev.stats if s.locked], ["Critical Chance"])
        self.assertEqual(next_step(torid, G), ("Lock Critical Damage instead", "of Critical Chance, then cycle"))

    def test_lock_a_high_rolled_splice_ingredient(self):
        # From a snapshot: the roll wants Critical Damage, Blast and Critical Chance equally. The riven has
        # Critical Damage locked and Cold rolled at 99%: Cold + Heat splices into Blast, which keeps that roll
        # for good, so locking Cold comes first.
        lib = roll_library({"weapons": {"Torid": {"positives": ["Critical Damage", "Blast", "Critical Chance"],
                                                  "negatives": ["Zoom", "Impact"]}}})
        stats = (["Cold", "Damage to Grineer", "Critical Damage"], "Damage to Infested")
        self.assertEqual(step_with(lib, "Torid", *stats, locked=["Critical Damage"], W=1.09),
                         ("Lock Cold instead", "of Critical Damage: 99% Cold, to splice with Heat into Blast"))
        self.assertEqual(step_with(lib, "Torid", *stats, W=1.09)[0], "Lock Cold")
        # Cold locked with no partner yet: keep it, and cycle for Heat.
        self.assertEqual(step_with(lib, "Torid", *stats, locked=["Cold"], W=1.09),
                         ("Keep Cold locked", "and cycle for Heat to splice into Blast"))
        # Any roll keeping 80% of the spliced stat's maximum is worth it: an 86% Cold still comes first.
        self.assertEqual(step_with(lib, "Torid", *stats, W=0.95)[0], "Lock Cold")

    def test_splice_skipped_only_below_80_percent(self):
        lib = roll_library({"weapons": {"Torid": {"positives": ["Critical Damage", "Blast", "Critical Chance"],
                                                  "negatives": ["Zoom", "Impact"]}}})
        rolls = lib.rolls_for(G.weapon_by_name("Torid"))

        def advice(quality):
            ev = riven("Torid", ["Cold", "Heat", "Critical Damage"], "Zoom")
            for s in ev.stats:
                s.quality = quality if s.name in ("Cold", "Heat") else 0.95
            return next_step(CardResult(None, ev, rate(ev, rolls, G)), G)[0]
        self.assertEqual(advice(0.82), "Splice Heat + Cold")          # the lowest roll there is still splices
        self.assertEqual(advice(0.79), "Lock Critical Damage")        # below 80% of Blast's maximum: skipped

    def test_splice_into_a_wanted_stat(self):
        # Critical Chance + the negative Zoom uses up less wanted weight than Critical Chance + Multishot.
        action, why = step("Rubico", ["Critical Chance", "Multishot", "Impact"], "Zoom")
        self.assertEqual(action, "Splice Critical Chance + Zoom")
        self.assertIn("Weak Point Critical Chance", why)
        self.assertEqual(step("Rubico", ["Critical Chance", "Multishot", "Impact"], "Puncture")[0],
                         "Splice Critical Chance + Multishot")
        # Not into a stat wanted less than what it uses up: Soma wants Multishot more than Weak Point Damage.
        self.assertFalse(step("Soma", ["Damage", "Multishot", "Impact"], "Zoom")[0].startswith("Splice"))

    def test_spliced_stat_fixes_the_shape_and_isnt_the_lock(self):
        # A spliced stat (shown with a lock icon) on a 2-positive riven: the shape stays, no second splice,
        # and the one lock is still free for Critical Damage.
        action, _ = step("Rubico", ["Weak Point Critical Chance", "Critical Damage"], "Zoom",
                         locked=["Weak Point Critical Chance"])
        self.assertEqual(action, "Done")
        action, _ = step("Rubico", ["Weak Point Critical Chance", "Impact", "Critical Damage"], "Zoom",
                         locked=["Weak Point Critical Chance"])
        self.assertEqual(action, "Lock Critical Damage")

    def test_roll_values_come_last(self):
        self.assertEqual(step("Soma", ["Critical Damage", "Multishot", "Critical Chance"], "Zoom"),
                         ("Done", "the stats you want, rolled well"))
        action, why = step("Soma", ["Critical Damage", "Multishot", "Critical Chance"], "Zoom", W=0.95)
        self.assertEqual(action, "Done")
        self.assertIn("only roll values left", why)

    def test_splice_table_uses_known_stats(self):
        for a, b, into, classes in splices():
            self.assertTrue({a, b, into} <= set(G.stats), (a, b, into))
            self.assertTrue(classes <= {"rifle", "shotgun", "pistol", "archgun", "melee"})


class TestBetterCard(unittest.TestCase):
    def test_closer_to_the_ideal_wins(self):
        # The snapshot's cycle screen: card 1 rates 66% (Critical Chance 87%, Critical Damage 92%), card 2 33%
        # (Critical Damage 92% and a 99% Cold). Cold splices into the wanted Blast at 99%, which takes card 2
        # further towards the ideal roll, so card 2 is the one to pick.
        from riven_helper.layout import best_flags
        lib = roll_library({"weapons": {"Torid": {"positives": ["Critical Damage", "Blast", "Critical Chance"],
                                                  "negatives": ["Zoom", "Impact"]}}})
        an = analyzer()
        an.library = lib
        rolls = lib.rolls_for(G.weapon_by_name("Torid"))

        def card(positives, negative, quality):
            ev = riven("Torid", positives, negative)
            for s in ev.stats:
                s.quality = quality.get(s.name, 0.85)
            return CardResult(None, ev, rate(ev, rolls, G))
        one = card(["Critical Chance", "Weapon Recoil", "Critical Damage"], "Damage to Corpus",
                   {"Critical Chance": 0.87, "Critical Damage": 0.92})
        two = card(["Cold", "Damage to Grineer", "Critical Damage"], "Damage to Infested",
                   {"Cold": 0.99, "Critical Damage": 0.92})
        self.assertGreater(one.rating.score, two.rating.score)
        self.assertGreater(progress(two, an)[0], progress(one, an)[0])
        self.assertEqual(progress(two, an)[1], "99% Cold splices into Blast")
        self.assertEqual(best_flags([one, two], an), [False, True])
        self.assertIsNone(progress(one, an)[1])                  # nothing to splice: just its rating
        # The next snapshot: card 1 now has Cold 99% (locked), Critical Damage 98% and Damage (33%); card 2
        # has Cold 99% and Heat (0%, with a bad negative). Card 2 can splice Blast now: that's further.
        waiting = card(["Cold", "Critical Damage", "Damage"], "Projectile Speed",
                       {"Cold": 0.99, "Critical Damage": 0.98, "Damage": 0.97})
        ready = card(["Cold", "Projectile Speed", "Heat"], "Multishot", {"Cold": 0.99, "Heat": 0.97})
        self.assertGreater(waiting.rating.score, ready.rating.score)
        self.assertEqual(best_flags([waiting, ready], an), [False, True])
        self.assertEqual(progress(ready, an)[1], "Heat + Cold can splice into Blast now (99%)")


class TestLockIcon(unittest.TestCase):
    def test_lock_icon_read_from_screen(self):
        (locked,) = analyzer().analyze_lines(saved_ocr("ocr_ekhein_locked.json"), 1920)
        self.assertEqual([s.name for s in locked.ev.stats if s.locked], ["Critical Damage"])   # "0+111.1%"
        (spliced,) = analyzer().analyze_lines(saved_ocr("ocr_plinx_tenet.json"), 1920)
        self.assertEqual([s.name for s in spliced.ev.stats if s.locked], ["Weak Point Damage"])
        (amprex,) = analyzer().analyze_lines(saved_ocr("ocr_amprex_locked.json"), 1920)
        self.assertEqual([s.name for s in amprex.ev.stats if s.locked], ["Critical Damage"])
        self.assertEqual(next_step(amprex, G)[0], "Keep Critical Damage locked")
        for fixture in ("ocr_ekhein.json", "ocr_cycle_selected_left.json", "ocr_cycle_selected_right.json"):
            for res in analyzer().analyze_lines(saved_ocr(fixture), 1920):  # the dimmed card's "N x1.26" isn't a lock
                self.assertFalse(any(s.locked for s in res.ev.stats), fixture)


if __name__ == "__main__":
    unittest.main()


class TestLockChange(unittest.TestCase):
    def test_locking_a_stat_is_read(self):
        # Locking only adds a small icon on the card (which still tracks as the same card) and the locked
        # trait above LOCK TRAIT: that change makes the session read again, so the advice follows the lock.
        import cv2
        import numpy as np

        from riven_helper.session import Session
        from tests.helpers import FIXTURES, windows_ocr
        locked = cv2.imread(str(FIXTURES / "img" / "riven_locked_amprex.jpg"))
        unlocked = locked.copy()
        unlocked[825:880, 95:415] = np.median(locked[700:755, 95:415].reshape(-1, 3), axis=0).astype(np.uint8)
        session, t, reads = Session(analyzer(), windows_ocr(self)), 0.0, []
        for frame in [unlocked] * 60 + [locked] * 90:
            events, _ = session.step(frame, now=t)
            reads += [t for kind, _ in events if kind == "results"]
            t += 1 / 30
        self.assertEqual(len(reads), 2, reads)                  # the first reading, then one after the lock
        self.assertTrue(2.0 < reads[1] < 2.8, reads)
