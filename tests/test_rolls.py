"""Roll files (loading, groups, priority) and rating a riven against them."""

import tempfile
import unittest
from pathlib import Path

from riven_helper.rolls import RollLibrary, parse_rules, rate

from tests.helpers import FIXTURES, G, ROOT, riven, roll_library

CRIT = ["Critical Damage", "Multishot", "Critical Chance"]


def labels(lib, weapon):
    return sorted(r.label for r in lib.rolls_for(G.weapon_by_name(weapon)))


class TestLoading(unittest.TestCase):
    def test_multiple_files_and_aliases(self):
        lib = roll_library(
            {"weapons": {"Rubico": {"label": "A", "positives": ["CD", "MS", "CC"], "negatives": ["Zoom"]}}},
            {"weapons": {"Rubico Prime": {"label": "B", "positives": {"Damage": 1, "Status Chance": 1}}}})
        self.assertEqual(lib.warnings, [])
        rolls = lib.rolls_for(G.weapon_by_name("Rubico"))
        self.assertEqual(sorted(r.label for r in rolls), ["A", "B"])
        perfect = rate(riven("Rubico", CRIT, "Zoom"), rolls, G)
        self.assertEqual((perfect.score, perfect.roll.label), (100.0, "A"))
        other = rate(riven("Rubico", ["Damage", "Status Chance"]), rolls, G)
        self.assertEqual((other.score, other.roll.label), (100.0, "B"))       # no negative is neutral

    def test_weapon_groups(self):
        lib = roll_library(
            {"groups": {"Crit snipers": ["Rubico", "Vectis", "Lanka"]},
             "weapons": {"@crit snipers": {"label": "group", "positives": ["CD", "MS", "CC"]},
                         "Rubico": {"label": "own", "positives": ["Damage", "Status Chance"]},
                         "*rifle": {"label": "fallback", "positives": ["Zoom", "Impact"]}}},
            {"weapons": {"@Crit Snipers": {"label": "other file", "positives": ["CD", "Damage"]}}})
        self.assertEqual(lib.warnings, [])
        self.assertEqual(labels(lib, "Rubico"), ["group", "other file", "own"])        # own + group rolls
        self.assertEqual(labels(lib, "Rubico Prime"), ["group", "other file", "own"])  # members cover the family
        self.assertEqual(labels(lib, "Vectis Prime"), ["group", "other file"])
        self.assertEqual(labels(lib, "Soma"), ["fallback"])                            # not in the group
        self.assertEqual(lib.groups_of(G.weapon_by_name("Lanka")), ["crit snipers"])
        best = rate(riven("Vectis", CRIT), lib.rolls_for(G.weapon_by_name("Vectis")), G)
        self.assertEqual(best.roll.label, "group")

    def test_market_file_only_when_nothing_else(self):
        market = {"fallback": True, "weapons": {
            name: {"label": f"market {name.lower()}", "positives": ["CD"]}
            for name in ("Rubico", "Soma", "Vectis", "Lanka")} | {
            "*rifle": {"label": "market rifle", "positives": ["CD"]}}}
        mine = {"groups": {"snipers": ["Vectis"]},
                "weapons": {"Rubico": {"label": "my rubico", "positives": ["MS"]},
                            "@snipers": {"label": "my snipers", "positives": ["MS"]}}}
        lib = roll_library(market, mine)
        self.assertEqual(labels(lib, "Rubico"), ["my rubico"])          # my roll beats the market
        self.assertEqual(labels(lib, "Vectis"), ["my snipers"])         # a group roll too
        self.assertEqual(labels(lib, "Soma"), ["market soma"])          # nothing of mine: market
        self.assertEqual(labels(lib, "Boltor"), ["market rifle"])       # nothing at all: market class fallback
        lib = roll_library(market, {"weapons": {"*rifle": {"label": "my rifles", "positives": ["MS"]}}})
        self.assertEqual(labels(lib, "Lanka"), ["my rifles"])           # my class fallback beats market rolls
        real = RollLibrary(G, [str(ROOT / "rolls" / "warframe_market.json")])
        self.assertTrue(all(r.fallback for rolls in real.rolls.values() for r in rolls))

    def test_mistakes_reported(self):
        lib = roll_library({"groups": {"g": ["Rubico", "Bananarang"]},
                            "weapons": {"@g": {"positives": ["CD"]}, "@nope": {"positives": ["CD"]}}})
        self.assertTrue(any('unknown weapon "Bananarang"' in w for w in lib.warnings))
        self.assertTrue(any('no file defines a group "nope"' in w for w in lib.warnings))

        folder = Path(tempfile.mkdtemp())
        (folder / "list.json").write_text("[1, 2]", encoding="utf-8")
        (folder / "broken.json").write_text('{"weapons": {', encoding="utf-8")
        warnings = RollLibrary(G, [str(folder)]).warnings
        self.assertTrue(any("not a roll file" in w for w in warnings))
        self.assertTrue(any("invalid JSON" in w for w in warnings))

    def test_rule_parsing(self):
        warnings = []
        rules = parse_rules(["-Damage > 100%", "+Zoom", "Impact", "-Multishot >= 50"], G, warnings, "test")
        self.assertEqual(warnings, [])
        self.assertEqual([(r.stat, r.sign, r.op, r.value) for r in rules],
                         [("Damage", "-", ">", 100.0), ("Zoom", "+", None, None), ("Impact", None, None, None),
                          ("Multishot", "-", ">=", 50.0)])
        parse_rules(["-Bananas > 3"], G, warnings, "test")
        self.assertTrue(warnings)

    def test_shipped_roll_files_load_cleanly(self):
        for source in (ROOT / "rolls", FIXTURES):
            lib = RollLibrary(G, [str(source)])
            self.assertEqual(lib.warnings, [], source)
            self.assertGreaterEqual(len(lib.files), 1, source)


class TestReloading(unittest.TestCase):
    """The overlay reloads roll files on its worker thread while the window thread looks rolls up."""

    def test_lookups_during_a_reload_see_old_or_new_rolls(self):
        import threading
        lib = RollLibrary(G, [str(ROOT / "rolls" / "warframe_market.json")])
        weapon, empty, stuck = G.weapon_by_name("Rubico"), 0, 0
        for _ in range(5):
            t = threading.Thread(target=lib.reload)
            t.start()
            while t.is_alive():
                empty += not lib.rolls_for(weapon)     # a panel drawn meanwhile
            t.join()
            stuck += not lib.rolls_for(weapon)         # and no empty answer kept afterwards
        self.assertEqual((empty, stuck), (0, 0))

    def test_half_saved_file_is_read_again(self):
        folder = Path(tempfile.mkdtemp())
        f = folder / "mine.json"
        f.write_text('{"weapons": {"Soma": {"positives": ["CD"', encoding="utf-8")    # caught mid-save
        lib = RollLibrary(G, [str(folder), str(folder / "missing")])
        self.assertTrue(lib.changed())                 # so the overlay looks again
        f.write_text('{"weapons": {"Soma": {"positives": ["CD"]}}}', encoding="utf-8")
        lib.reload()
        self.assertEqual(list(lib.rolls), ["soma"])
        for _ in range(5):
            lib.changed()
        self.assertEqual(len(lib.warnings), 1)         # "missing" reported once, not once per check


class TestRating(unittest.TestCase):
    def test_type_is_90_percent_quality_10(self):
        rolls = roll_library({"weapons": {"Soma": {"positives": ["CD", "MS", "CC"]}}}).rolls_for(G.weapon_by_name("Soma"))
        # quality = value / max = W / 1.1, so the right stats at the worst rolls get 90 + 10 * 0.9/1.1
        self.assertAlmostEqual(rate(riven("Soma", CRIT, W=0.9), rolls, G).score, 98.2)
        self.assertAlmostEqual(rate(riven("Soma", CRIT, W=1.0), rolls, G).score, 99.1)
        self.assertAlmostEqual(rate(riven("Soma", CRIT, W=1.1), rolls, G).score, 100.0)
        # One of three stats unwanted: 2/3 of the credit.
        two = rate(riven("Soma", ["Critical Damage", "Multishot", "Zoom"]), rolls, G)
        self.assertAlmostEqual(two.score, 66.7, places=1)
        self.assertEqual(two.tags["Zoom"], "unwanted")

    def test_negatives_neutral_unless_they_conflict(self):
        rolls = roll_library({"weapons": {"*rifle": {"positives": ["CD", "MS", "CC"], "negatives": ["Zoom"]}}}) \
            .rolls_for(G.weapon_by_name("Soma"))
        two = ["Critical Damage", "Multishot"]
        neutral = rate(riven("Soma", two, "Impact"), rolls, G)
        self.assertEqual((neutral.score, neutral.tags["Impact"]), (100.0, "neutral"))
        harmless = rate(riven("Soma", two, "Zoom"), rolls, G)
        self.assertEqual((harmless.score, harmless.tags["Zoom"]), (100.0, "harmless"))
        conflict = rate(riven("Soma", two, "Critical Chance"), rolls, G)            # a wanted stat, negative
        self.assertEqual((conflict.score, conflict.tags["Critical Chance"]), (50.0, "bad"))

    def test_bad_rules(self):
        lib = roll_library({"bad": ["-Impact"],
                            "weapons": {"Soma": {"positives": ["CD", "MS", "CC"], "bad": ["+Zoom"]}}})
        self.assertEqual(lib.warnings, [])
        rolls = lib.rolls_for(G.weapon_by_name("Soma"))
        r = rate(riven("Soma", ["Critical Damage", "Multishot"], "Impact"), rolls, G)
        self.assertEqual((r.score, r.tags["Impact"]), (50.0, "bad"))           # file-wide rule
        r = rate(riven("Soma", ["Critical Damage", "Zoom"], "Impact"), rolls, G)
        self.assertEqual(r.tags["Zoom"], "bad")                                 # roll rule, positive side
        self.assertAlmostEqual(r.score, 50.0 * 0.5 * 0.5)                       # 1 of 2 wanted, 2 bad stats

    def test_dealbreakers(self):
        lib = roll_library({"dealbreakers": ["-Damage > 100"],
                            "weapons": {"Soma": [{"label": "crit", "positives": ["CD", "MS"]},
                                                 {"label": "any", "positives": ["Status Chance"],
                                                  "dealbreakers": ["-Multishot"]}]}})
        self.assertEqual(lib.warnings, [])
        rolls = lib.rolls_for(G.weapon_by_name("Soma"))
        three = ["Critical Damage", "Multishot", "Status Duration"]
        ev = riven("Soma", three, "Damage")                                     # -Damage ~ -142%
        self.assertGreater(ev.negative.magnitude, 1.0)
        r = rate(ev, rolls, G)
        self.assertEqual((r.score, r.dealbreaker, r.tags["Damage"]), (0.0, "-Damage > 100", "dealbreaker"))
        self.assertEqual(rate(riven("Soma", three, "Damage", rank=3), rolls, G).score, 100.0)   # ~ -63%: fine


if __name__ == "__main__":
    unittest.main()
