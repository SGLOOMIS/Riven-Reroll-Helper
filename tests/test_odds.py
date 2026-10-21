"""The chance that the next cycle rates higher (odds.py)."""

import unittest

from riven_helper.advice import next_step
from riven_helper.analyze import CardResult
from riven_helper.odds import chance_of_better
from riven_helper.rolls import rate

from tests.helpers import FIXTURES, G, analyzer, riven, roll_library


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

    def test_only_for_a_lone_card_at_the_target(self):
        # The next cycle's odds show on the lone card once it rates the Kuva target; before that the Kuva
        # line says more. This 50% riven: not at 90%, at 40%.
        from riven_helper.panel_text import card_rows, rows_text
        from tests.helpers import saved_ocr
        an = analyzer()
        (res,) = an.analyze_lines(saved_ocr("ocr_ekhein.json"), 1920)
        self.assertNotIn("next cycle rates higher", rows_text(card_rows(an, res, alone=True)))
        self.assertIn("expected Kuva to 90%+: about", rows_text(card_rows(an, res, alone=True)))
        an.cfg = dict(an.cfg, kuva_target=40)
        self.assertIn("next cycle rates higher", rows_text(card_rows(an, res, alone=True)))
        self.assertNotIn("next cycle rates higher", rows_text(card_rows(an, res)))

    def test_exact_odds_match_the_simulation(self):
        # The panel's odds are worked out exactly (flow.chance_of_better); the simulation here agrees.
        from riven_helper import flow
        from tests.helpers import saved_ocr
        an = analyzer()
        for name in ("ocr_ekhein.json", "ocr_amprex_locked.json", "ocr_ekhein_locked.json"):
            (res,) = an.analyze_lines(saved_ocr(name), 1920)
            exact = flow.chance_of_better(res, an)
            simulated = chance_of_better(res, an, samples=20000)
            self.assertAlmostEqual(exact, simulated, delta=0.012, msg=name)


class TestKuva(unittest.TestCase):
    def test_cost_read_off_the_cycle_button(self):
        from riven_helper.kuva import read_cycle_cost
        from riven_helper.capture import Ocr
        from PIL import Image
        from tests.helpers import saved_ocr
        # OCR swallows the first digit into the Kuva icon ("a,500", "goo"); the rest still tells them apart.
        # The number can also come out as a line of its own (cedo). 2,000 checked on the amprex screenshot.
        for name, cost in (("ocr_ekhein.json", 3500), ("ocr_coda_bubonico.json", 3150), ("ocr_velox_prime.json", 900),
                           ("ocr_amprex_locked.json", 2000), ("ocr_cedo_split_multiplier.json", 1000),
                           ("ocr_cycle_selected_left.json", None)):
            self.assertEqual(read_cycle_cost(saved_ocr(name))[0], cost, name)
        # With a stat locked the button shows double: ",000" is then 2,000, 4,000 or 7,000, so it's read again
        # without the Kuva icon (without the screenshot: the highest). The amprex's is 2,000 (base rate
        # 1,000: it was cycled once).
        self.assertEqual(read_cycle_cost(saved_ocr("ocr_amprex_locked.json"), locked=True), (7000, False))
        try:
            ocr = Ocr()
        except Exception as e:                                   # no Windows OCR here
            self.skipTest(f"Windows OCR not available: {e}")
        image = Image.open(FIXTURES / "img" / "riven_locked_amprex.jpg")
        self.assertEqual(read_cycle_cost(saved_ocr("ocr_amprex_locked.json"), True, image, ocr), (2000, True))

    def test_expected_kuva(self):
        from riven_helper.kuva import expected_kuva
        self.assertAlmostEqual(expected_kuva(0.01, 3500), 350000)          # at the cap: 100 cycles x 3,500
        self.assertAlmostEqual(expected_kuva(0.01), 350000)                # cost unknown: the cap
        self.assertAlmostEqual(expected_kuva(0.01, 3500, locked=True), 700000)    # a locked stat: double
        self.assertAlmostEqual(expected_kuva(1.0, 900), 900)               # the very next cycle
        # Half the time the first cycle (900), else the second (1,000) too, ... : 900 + 1000/2 + 1200/4 + ...
        self.assertAlmostEqual(expected_kuva(0.5, 900), 2127.93, places=2)
        self.assertLess(expected_kuva(0.01, 900), expected_kuva(0.01, 3500))   # the cheap cycles first
        self.assertIsNone(expected_kuva(0.0, 3500))

    def test_shown_on_the_panel(self):
        from riven_helper.kuva import kuva_amount
        from riven_helper.panel_text import kuva_text
        self.assertEqual([kuva_amount(k) for k in (2128, 10500, 951000, 5250000)], ["2,100", "10k", "950k", "5.2M"])
        an = analyzer()
        an.library = TestOdds.CRIT
        ev = riven("Soma", ["Critical Damage", "Multishot", "Critical Chance"], "Zoom")
        perfect = CardResult(None, ev, rate(ev, TestOdds.CRIT.rolls_for(G.weapon_by_name("Soma")), G))
        self.assertEqual(kuva_text(perfect, an), ("already rated 90%+", None))
        an.cfg = dict(an.cfg, kuva_target=0)
        self.assertIsNone(kuva_text(perfect, an))                          # switched off


if __name__ == "__main__":
    unittest.main()
