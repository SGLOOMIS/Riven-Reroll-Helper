"""The riven formula, rank/roll inference, and which weapons share a riven."""

import unittest

from riven_helper.riven_math import RivenStat, infer, max_value

from tests.helpers import G, shown_value


class TestFormula(unittest.TestCase):
    def test_wiki_reference_value(self):
        # Rifle crit damage, rank 8, disposition 1, 2 positives no negative, W = 1: 0.013333 * 90 * 0.99
        soma = G.weapon_by_name("Soma")
        v = shown_value("Critical Damage", soma, 8, 2, False, False, 1.0) / soma.disposition
        self.assertAlmostEqual(v, 0.013333 * 90 * 0.99, places=6)

    def test_max_value(self):
        # Tenet Plinx, R8, 3 positives + 1 negative: 0.01 * 90 * 0.75 * 0.9375 * 1.1
        cd = max_value(G.stats["Critical Damage"], G.weapon_by_name("Tenet Plinx"), 8)
        self.assertAlmostEqual(cd, 0.6961, places=3)


class TestInfer(unittest.TestCase):
    def test_rank_and_quality(self):
        rubico = G.weapon_by_name("Rubico")
        stats = [RivenStat(name, round(shown_value(name, rubico, 8, 3, True, neg, W), 3), neg)
                 for name, W, neg in (("Critical Damage", 1.05, False), ("Multishot", 0.9, False),
                                      ("Critical Chance", 1.1, False), ("Zoom", 1.0, True))]
        ev = infer(stats, G.candidates_for("Rubico"), G)
        self.assertEqual(ev.rank, 8)
        self.assertTrue(ev.consistent)
        q = {s.name: s for s in ev.stats}
        self.assertAlmostEqual(q["Critical Damage"].quality, 0.75, places=2)   # 1.05: 3/4 up the 0.9 - 1.1 range
        self.assertAlmostEqual(q["Multishot"].roll, 0.9, places=2)
        self.assertAlmostEqual(q["Critical Chance"].quality, 1.0, places=2)

    def test_unranked(self):
        nikana = G.weapon_by_name("Nikana")
        stats = [RivenStat(name, shown_value(name, nikana, 0, 2, False, False, 1.0), False)
                 for name in ("Critical Damage", "Damage")]
        self.assertEqual(infer(stats, G.candidates_for("Nikana"), G).rank, 0)

    def test_variant_disposition_when_base_doesnt_fit(self):
        prime = G.weapon_by_name("Rubico Prime")
        stats = [RivenStat(name, shown_value(name, prime, 8, 2, False, False, 1.0), False)
                 for name in ("Critical Damage", "Multishot")]
        self.assertEqual(infer(stats, G.candidates_for("Rubico"), G, ranks=[8]).weapon.name, "Rubico Prime")


class TestFamilies(unittest.TestCase):
    def test_separate_riven_families(self):
        names = lambda title: [w.name for w in G.candidates_for(title)]
        self.assertNotIn("Dex Nikana", names("Nikana"))
        self.assertEqual(names("Dex Nikana"), ["Dex Nikana"])
        self.assertNotIn("Mutalist Cernos", names("Cernos"))
        self.assertIn("Kuva Kohm", names("Kohm"))
        self.assertEqual(names("Kuva Bramma"), ["Kuva Bramma"])
        self.assertEqual(G.find_family_in_text("Dex Nikana Crita-satis"), "dex nikana")

    def test_fits_in_weapon_first(self):
        self.assertEqual(G.candidates_for("Plinx")[0].name, "Plinx")
        self.assertEqual(G.candidates_for("Plinx", shown_weapon="tenet plinx")[0].name, "Tenet Plinx")


if __name__ == "__main__":
    unittest.main()
