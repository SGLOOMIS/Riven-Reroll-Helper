"""The roll-file editor, driven the way a user would (window hidden)."""

import json
import tempfile
import unittest
from pathlib import Path

from riven_helper.rolls import RollLibrary

from tests.helpers import G


class TestEditor(unittest.TestCase):
    def test_build_group_rolls_and_save(self):
        from riven_helper.editor import Editor
        from riven_helper.editor_model import RollFile
        ed = Editor()
        ed.root.withdraw()
        try:
            ed.group_name.insert(0, "Crit snipers")
            ed._add_group()
            for weapon in ("Rubico", "Vectis"):
                ed.member_pick.set(weapon)
                ed._add_member()
            ed._group_rolls()                                   # opens "@Crit snipers" on the Rolls tab
            self.assertEqual(ed.entry, "@Crit snipers")
            ed.label.insert(0, "crit")
            ed._set_label()
            for stat, tier in (("crit damage", "Required"), ("MS", "Wanted"), ("Critical Chance", "Acceptable")):
                ed.pos_stat.set(stat)
                ed.pos_tier.set(tier)
                ed._set_positive()
            for stat in ("Zoom", "Impact"):                    # "+Zoom", any value: a harmless negative too
                ed.roll_bad.sign.set("as a positive (+)")
                ed.roll_bad.stat.set(stat)
                ed.roll_bad._add()
            ed.roll_deal.sign.set("as the negative (-)")
            ed.roll_deal.stat.set("Multishot")
            ed.roll_deal._add()
            ed.file_bad.sign.set("as the negative (-)")
            ed.file_bad.stat.set("Damage")
            ed.file_bad.op.set(">")
            ed.file_bad.value.insert(0, "100")
            ed.file_bad._add()
            path = Path(tempfile.mkdtemp()) / "mine.json"
            ed.doc.save(path)
            self.assertFalse(ed.doc.dirty)
        finally:
            ed.root.destroy()
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["groups"], {"Crit snipers": ["Rubico", "Vectis"]})
        roll = data["weapons"]["@Crit snipers"]
        self.assertEqual(roll["label"], "crit")
        self.assertEqual(roll["positives"], {"Critical Damage": 1.0, "Multishot": 0.75, "Critical Chance": 0.5})
        self.assertEqual((roll["required"], roll["bad"], roll["dealbreakers"]),
                         (["Critical Damage"], ["+Zoom", "+Impact"], ["-Multishot"]))
        self.assertNotIn("negatives", roll)
        self.assertEqual(data["bad"], ["-Damage > 100"])
        self.assertEqual(RollFile(path).check(G), [])
        lib = RollLibrary(G, [str(path)])
        self.assertEqual([r.label for r in lib.rolls_for(G.weapon_by_name("Vectis Prime"))], ["crit"])


class TestInheritedRules(unittest.TestCase):
    """A roll shows the unwanted stats and dealbreakers it inherits; changing one there is an exception for that
    roll."""

    def test_exceptions_for_one_roll(self):
        from riven_helper.editor import C, Editor
        path = Path(tempfile.mkdtemp()) / "wishlist.json"
        path.write_text(json.dumps({
            "negatives": ["Slash"], "bad": ["+Zoom"], "dealbreakers": ["-Damage >= 100"],
            "weapons": {"Torid": [{"label": "crit", "positives": {"Critical Chance": 0.75, "Blast": 1.0,
                                                                   "Damage": 0.5, "Critical Damage": 1.0},
                                   "required": ["Blast"]},
                                  {"label": "other", "positives": ["Multishot"]}]}}), encoding="utf-8")
        ed = Editor(str(path))
        ed.root.withdraw()
        try:
            ed.entry_box.selection_set(0)
            ed._pick_entry()
            ed.roll_box.selection_set(0)
            ed._pick_roll()
            # Sorted by weight: required first among equals.
            self.assertEqual(list(ed.pos.get_children()), ["Blast", "Critical Damage", "Critical Chance", "Damage"])
            # The file's rules show on the roll, as inherited. Its harmless negatives ("negatives") are the
            # same as "+Stat" rules, so they're in the one list.
            self.assertEqual(ed.doc.bad, ["+Zoom", "+Slash"])
            self.assertEqual([ed.roll_bad.box.get(i) for i in range(ed.roll_bad.box.size())],
                             ["+Zoom      (from all rolls in this file)", "+Slash      (from all rolls in this file)"])
            ed.roll_bad.box.selection_set(0)
            ed.roll_bad._remove()                            # off for this roll
            self.assertIn("off for this roll", ed.roll_bad.box.get(0))
            ed.roll_deal.box.selection_set(0)
            ed.roll_deal._pick()                             # the builder now holds "-Damage >= 100"
            ed.roll_deal.value.delete(0, "end")
            ed.roll_deal.value.insert(0, "150")
            ed.roll_deal._add()                              # replaced for this roll
            ed.save()
        finally:
            ed.root.destroy()
            C.set_theme("Vitruvian")
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual((saved["bad"], saved.get("negatives")), (["+Zoom", "+Slash"], None))
        crit, other = saved["weapons"]["Torid"]
        self.assertEqual((crit["ignore_bad"], crit["ignore_dealbreakers"], crit["dealbreakers"]),
                         (["+Zoom"], ["-Damage >= 100"], ["-Damage >= 150"]))
        self.assertNotIn("ignore_bad", other)                # the other roll still follows the file
        lib = RollLibrary(G, [str(path)])
        self.assertEqual(lib.warnings, [])
        crit_roll, other_roll = lib.rolls_for(G.weapon_by_name("Torid"))
        self.assertEqual(([r.text for r in crit_roll.bad], [r.text for r in crit_roll.dealbreakers]),
                         (["+Slash"], ["-Damage >= 150"]))
        self.assertEqual(([r.text for r in other_roll.bad], [r.text for r in other_roll.dealbreakers]),
                         (["+Zoom", "+Slash"], ["-Damage >= 100"]))
        self.assertEqual((crit_roll.negatives, other_roll.negatives), (["Slash"], ["Zoom", "Slash"]))


class TestTiers(unittest.TestCase):
    def test_tiers_from_weights(self):
        from riven_helper.editor_model import RollFile, set_tier, tier_of
        roll = {"positives": {"Blast": 1.0, "Critical Damage": 1.0, "Critical Chance": 0.75, "Damage": 0.5,
                              "Multishot": 0.85}, "required": ["Blast", "Critical Damage"]}
        self.assertEqual([tier_of(roll, s) for s in roll["positives"]],
                         ["Required", "Required", "Wanted", "Acceptable", "Wanted"])   # 0.85: any weight works
        set_tier(roll, "Damage", "Required")
        set_tier(roll, "Blast", "Acceptable")
        self.assertEqual((roll["positives"]["Damage"], roll["positives"]["Blast"]), (1.0, 0.5))
        self.assertEqual(roll["required"], ["Critical Damage", "Damage"])
        # Opening and saving a file never rounds the weights of stats you didn't change.
        path = Path(tempfile.mkdtemp()) / "market.json"
        path.write_text(json.dumps({"weapons": {"Soma": {"positives": {"CD": 1, "MS": 0.85}}}}), encoding="utf-8")
        doc = RollFile(path)
        doc.save()
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["weapons"]["Soma"]["positives"],
                         {"CD": 1.0, "MS": 0.85})


class TestSettings(unittest.TestCase):
    """The editor's Settings tab, writing a copy of config.json (never the real one)."""

    def setUp(self):
        import shutil

        from tests.helpers import ROOT
        self.folder = Path(tempfile.mkdtemp())
        self.config = self.folder / "config.json"
        shutil.copy(ROOT / "config.json", self.config)
        (self.folder / "rolls").mkdir()

    def test_save_settings(self):
        from riven_helper.config import load_config
        from riven_helper.editor import C, Editor
        elsewhere = Path(tempfile.mkdtemp()) / "friend.json"
        elsewhere.write_text(json.dumps({"weapons": {"Soma": {"positives": ["CD"]}}}), encoding="utf-8")
        ed = Editor(config_path=self.config)
        ed.root.withdraw()
        try:
            ed.theme_pick.set("Orokin")
            ed._apply_theme("Orokin")
            self.assertEqual(C.bg, "#d8dedc")                    # recoloured right away (a light theme)
            ed.options["next_step"].set(False)
            ed.options["config_rolls"].set(False)
            ed._add_source(elsewhere)                            # "Add files..." for a file outside the folder
            ed._add_source(self.folder / "rolls" / "mine.json")
            ed._save_settings()
            self.assertIn("friend.json", " ".join(ed.files))     # now in the File list too
        finally:
            ed.root.destroy()
            C.set_theme("Vitruvian")
        cfg = load_config(self.config)
        self.assertEqual((cfg["editor_theme"], cfg["next_step"], cfg["config_rolls"], cfg["upgrade_overlay"]),
                         ("Orokin", False, False, True))
        self.assertEqual(cfg["roll_files"], ["rolls", elsewhere.resolve().as_posix(), "rolls/mine.json"])
        self.assertEqual(cfg["hotkeys"]["snapshot"], "F10")      # everything else kept


class TestSafeFiles(unittest.TestCase):
    """Saves are never left half-written; a damaged config.json doesn't stop the program."""

    def test_damaged_config_uses_defaults(self):
        from riven_helper.config import DEFAULTS, load_config, save_settings
        folder = Path(tempfile.mkdtemp())
        config = folder / "config.json"
        config.write_text('{"roll_files": ["rolls"], "font_size": 11,', encoding="utf-8")   # cut short
        cfg = load_config(config)
        self.assertIn("can't be read", cfg["_problem"])
        self.assertEqual(cfg["font_size"], DEFAULTS["font_size"])
        save_settings({"next_step": False}, config)                  # the editor saving its Settings tab
        self.assertTrue((folder / "config.json.damaged").exists())   # the damaged file is kept
        self.assertEqual(load_config(config)["next_step"], False)
        self.assertNotIn("_problem", load_config(config))

    def test_roll_file_save_keeps_a_backup(self):
        from riven_helper.editor_model import RollFile
        folder = Path(tempfile.mkdtemp())
        path = folder / "mine.json"
        doc = RollFile()
        doc.entries = {"Soma": [{"label": "first", "positives": {"Critical Damage": 1.0}}]}
        doc.save(path)
        doc.entries = {}
        doc.save(path)                                               # say, an accidental empty save
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["weapons"], {})
        backup = json.loads((folder / "mine.json.bak").read_text(encoding="utf-8"))
        self.assertIn("Soma", backup["weapons"])                     # the previous version is still there
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["mine.json", "mine.json.bak"])   # no temp file


class TestOverlaySwitches(unittest.TestCase):
    def test_switches(self):
        from riven_helper.layout import best_flags, plan_upgrade_screen
        from riven_helper.panel_text import card_rows, rows_text
        from tests.helpers import analyzer, roll_library, saved_ocr
        an = analyzer()
        results = an.analyze_lines(saved_ocr("ocr_ekhein.json"), 1920)
        self.assertIn("NEXT:", rows_text(card_rows(an, results[0])))
        an.cfg["next_step"] = False                              # advice off: no NEXT, BETTER by rating
        self.assertNotIn("NEXT:", rows_text(card_rows(an, results[0])))
        self.assertEqual(best_flags(results, an), [False])
        an.cfg["config_rolls"] = False                           # config rolls off: the named roll is ignored
        an.library = roll_library({"weapons": {"Praedos": [{"label": "first", "positives": ["CD"]},
                                                           {"label": "Main", "positives": ["Range"]}]}})
        image, _ = plan_upgrade_screen(an, "praedos", 1920, 1080, an.cfg, config="Main")
        an.cfg["config_rolls"] = True
        image_main, _ = plan_upgrade_screen(an, "praedos", 1920, 1080, an.cfg, config="Main")
        self.assertNotEqual(image.tobytes(), image_main.tobytes())

    def test_settings_applied_in_place(self):
        from riven_helper.config import load_config
        from tests.helpers import analyzer
        an = analyzer()
        held = an.cfg                                            # the overlay and session hold this same dict
        new = load_config()
        new["upgrade_overlay"] = False
        an.apply_settings(new)
        self.assertIs(an.cfg, held)
        self.assertFalse(held["upgrade_overlay"])


class TestOneProgram(unittest.TestCase):
    """Riven Helper.bat: the editor with the overlay running inside it."""

    def test_overlay_reports_to_the_editor(self):
        import tkinter as tk

        from riven_helper.app import App
        from tests.helpers import analyzer
        root = tk.Tk()
        root.withdraw()
        try:
            said = []
            app = App(analyzer().cfg, analyzer(), root=root, report=said.append)
            self.assertIs(app.root, root)                         # the editor's window, not a hidden one
            app._handle("status", None, "paused: Warframe isn't the active window")
            self.assertIn("paused: Warframe isn't the active window", said)
        finally:
            root.destroy()

    def test_only_one_copy_runs(self):
        from riven_helper.__main__ import _first_copy
        _first_copy()                                             # this test run holds the flag now...
        self.assertFalse(_first_copy())                           # ...so a second copy would stop


if __name__ == "__main__":
    unittest.main()
