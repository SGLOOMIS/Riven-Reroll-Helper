"""The chance that the next cycle rates higher (odds.py)."""

import unittest

from riven_helper.analyze import CardResult
from riven_helper.odds import chance_of_better
from riven_helper.rolls import rate

from tests.helpers import G, analyzer, riven, roll_library


def odds(library, weapon, positives, negative=None, locked=(), W=1.1, samples=2000):
    an = analyzer()
    an.library = library
    ev = riven(weapon, positives, negative, W)
    for s in ev.stats:
        s.locked = s.name in locked
    result = CardResult(None, ev, rate(ev, library.rolls_for(G.weapon_by_name(weapon)), G))
    return chance_of_better(result, an, samples)


class TestOdds(unittest.TestCase):
    CRIT = roll_library({"weapons": {"Soma": {"positives": ["Critical Damage", "Multishot", "Critical Chance"],
                                              "negatives": ["Zoom"]}}})

    def test_perfect_riven_cant_be_beaten(self):
        self.assertEqual(odds(self.CRIT, "Soma", ["Critical Damage", "Multishot", "Critical Chance"], "Zoom"), 0.0)

    def test_nearly_any_cycle_beats_nothing_wanted(self):
        # Every stat wanted except the riven's own two: only redrawing exactly those two would lose.
        every = roll_library({"weapons": {"Soma": {"positives": {
            s: 1 for s, d in G.stats.items() if d.base.get("rifle") is not None and s not in ("Zoom", "Impact")}}}})
        self.assertGreater(odds(every, "Soma", ["Zoom", "Impact"]), 0.98)

    def test_a_locked_stat_is_kept(self):
        loose = odds(self.CRIT, "Soma", ["Critical Damage", "Impact", "Puncture"], "Zoom")
        kept = odds(self.CRIT, "Soma", ["Critical Damage", "Impact", "Puncture"], "Zoom", locked=["Critical Damage"])
        self.assertTrue(0 < loose < kept < 1, (loose, kept))   # keeping Critical Damage makes a better cycle likelier

    def test_same_riven_same_answer(self):
        args = (self.CRIT, "Soma", ["Critical Damage", "Impact", "Puncture"], "Zoom")
        self.assertEqual(odds(*args), odds(*args))

    def test_only_for_a_lone_card(self):
        from riven_helper.panel_text import card_rows, rows_text
        from tests.helpers import saved_ocr
        an = analyzer()
        (res,) = an.analyze_lines(saved_ocr("ocr_ekhein.json"), 1920)
        self.assertIn("next cycle rates higher", rows_text(card_rows(an, res, alone=True)))
        self.assertNotIn("next cycle rates higher", rows_text(card_rows(an, res)))


if __name__ == "__main__":
    unittest.main()
