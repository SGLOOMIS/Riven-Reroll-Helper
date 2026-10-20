"""Roll files (loading, groups, priority) and rating a riven against them."""

import json
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


class TestTargeting(unittest.TestCase):
    def test_cycle_through_a_weapons_rolls(self):
        from riven_helper.analyze import Analyzer
        from tests.helpers import fixture_config
        folder = Path(tempfile.mkdtemp())
        (folder / "r.json").write_text(json.dumps({"weapons": {"Rubico": [
            {"label": "crit", "positives": ["CD", "MS", "CC"]},
            {"label": "status", "positives": ["Damage", "Status Chance"]}]}}), encoding="utf-8")
        an = Analyzer(fixture_config(folder))
        rubico, crit = G.weapon_by_name("Rubico"), riven("Rubico", CRIT)
        self.assertEqual(an.target(rubico), (None, 2))
        self.assertEqual(an.rate(crit).roll.label, "crit")                  # best match
        self.assertEqual(an.cycle_target(rubico).label, "crit")
        self.assertEqual(an.target(rubico), (1, 2))
        self.assertEqual(an.cycle_target(rubico).label, "status")
        status = an.rate(crit)
        self.assertEqual(status.roll.label, "status")                       # rated against the targeted roll
        self.assertLess(status.score, 50)
        self.assertIsNone(an.cycle_target(rubico))                          # back to the best match
        self.assertEqual(an.rate(crit).roll.label, "crit")


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
        # The roll accepts a negative (Zoom), so a harmless one counts like a third wanted stat: 2 of 3 without.
        neutral = rate(riven("Soma", two, "Impact"), rolls, G)
        self.assertEqual((neutral.score, neutral.tags["Impact"]), (66.7, "neutral"))
        harmless = rate(riven("Soma", two, "Zoom"), rolls, G)
        self.assertEqual((harmless.score, harmless.tags["Zoom"]), (100.0, "harmless"))
        conflict = rate(riven("Soma", two, "Critical Chance"), rolls, G)            # a wanted stat, negative
        self.assertEqual((conflict.score, conflict.tags["Critical Chance"]), (33.3, "bad"))
        # A roll that accepts no negatives: having none, or a neutral one, loses nothing.
        strict = roll_library({"weapons": {"Soma": {"positives": ["CD", "MS", "CC"]}}}).rolls_for(G.weapon_by_name("Soma"))
        self.assertEqual(rate(riven("Soma", two, "Impact"), strict, G).score, 100.0)
        self.assertEqual(rate(riven("Soma", two), strict, G).score, 100.0)

    def test_bad_rules(self):
        lib = roll_library({"bad": ["-Impact"],
                            "weapons": {"Soma": {"positives": ["CD", "MS", "CC"], "bad": ["+Zoom"]}}})
        self.assertEqual(lib.warnings, [])
        rolls = lib.rolls_for(G.weapon_by_name("Soma"))
        # ("+Zoom" makes Zoom a harmless negative, so the roll accepts one: a bad negative earns no third share.)
        r = rate(riven("Soma", ["Critical Damage", "Multishot"], "Impact"), rolls, G)
        self.assertEqual((r.score, r.tags["Impact"]), (33.3, "bad"))           # file-wide rule: 2 of 3, x 0.5
        r = rate(riven("Soma", ["Critical Damage", "Zoom"], "Impact"), rolls, G)
        self.assertEqual(r.tags["Zoom"], "bad")                                 # roll rule, positive side
        self.assertAlmostEqual(r.score, 8.3)                                    # 1 of 3, two bad stats: x 0.25

    def test_bad_as_positive_is_a_good_negative(self):
        # "+Zoom" is bad (you don't want it as a positive), so Zoom as the negative is a good place for the
        # riven's curse: harmless, and listed with the roll's accepted negatives. Wherever the rule is written.
        lib = roll_library({"bad": ["+Zoom", "-Impact", "Puncture"],
                            "weapons": {"Soma": {"positives": ["CD", "MS", "CC"], "bad": ["+Weapon Recoil"]}}})
        (roll,) = lib.rolls_for(G.weapon_by_name("Soma"))
        self.assertEqual(roll.negatives, ["Zoom", "Weapon Recoil"])
        tag = lambda neg: rate(riven("Soma", ["Critical Damage", "Multishot"], neg), [roll], G).tags[neg]
        self.assertEqual([tag(n) for n in ("Zoom", "Weapon Recoil", "Impact", "Puncture", "Slash")],
                         ["harmless", "harmless", "bad", "bad", "neutral"])
        self.assertEqual(rate(riven("Soma", ["Critical Damage", "Zoom"], "Impact"), [roll], G).tags["Zoom"], "bad")
        # A stat the roll wants is never a good negative, even with a "+" bad rule somewhere.
        wants = roll_library({"bad": ["+Multishot"], "weapons": {"Soma": {"positives": ["CD", "MS"]}}})
        self.assertEqual(wants.rolls_for(G.weapon_by_name("Soma"))[0].negatives, [])
        self.assertEqual(wants.rolls_for(G.weapon_by_name("Soma"))[0].bad, [])         # nor bad as a positive

    def test_harmless_negative_is_a_bad_positive(self):
        # The same list the other way round: a harmless negative halves the score as a positive. From the
        # roll or the whole file ("negatives"), and a roll can switch the file's off ("ignore_negatives").
        lib = roll_library({"negatives": ["Impact"],
                            "weapons": {"Soma": [{"label": "a", "positives": ["CD", "MS", "CC"], "negatives": ["Zoom"]},
                                                 {"label": "b", "positives": ["CD", "MS", "CC"],
                                                  "ignore_negatives": ["Impact"]}]}})
        a, b = lib.rolls_for(G.weapon_by_name("Soma"))
        self.assertEqual((a.negatives, b.negatives), (["Zoom", "Impact"], []))
        for stat in ("Zoom", "Impact"):
            r = rate(riven("Soma", ["Critical Damage", "Multishot", stat]), [a], G)
            self.assertEqual(r.tags[stat], "bad")
            self.assertAlmostEqual(r.score, 66.7 * 0.5 * 0.75, places=0)  # 2 of 3, no negative: x0.75, then halved
        self.assertEqual(rate(riven("Soma", ["Critical Damage", "Multishot", "Impact"]), [b], G).tags["Impact"],
                         "unwanted")
        self.assertEqual(len([r for r in a.bad if r.stat == "Zoom"]), 1)     # listed twice, counted once

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
