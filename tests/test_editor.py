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
            for stat, weight, required in (("crit damage", "1", True), ("MS", "1", False),
                                           ("Critical Chance", "0.8", False)):
                ed.pos_stat.set(stat)
                ed.pos_weight.set(weight)
                ed.pos_req.set(required)
                ed._set_positive()
            ed.neg_stat.set("Zoom")
            ed._add_negative()
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
        self.assertEqual(roll["positives"], {"Critical Damage": 1.0, "Multishot": 1.0, "Critical Chance": 0.8})
        self.assertEqual((roll["required"], roll["negatives"], roll["dealbreakers"]),
                         (["Critical Damage"], ["Zoom"], ["-Multishot"]))
        self.assertEqual(data["bad"], ["-Damage > 100"])
        self.assertEqual(RollFile(path).check(G), [])
        lib = RollLibrary(G, [str(path)])
        self.assertEqual([r.label for r in lib.rolls_for(G.weapon_by_name("Vectis Prime"))], ["crit"])


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
            C.set_theme("Default")
        cfg = load_config(self.config)
        self.assertEqual((cfg["editor_theme"], cfg["next_step"], cfg["config_rolls"], cfg["upgrade_overlay"]),
                         ("Orokin", False, False, True))
        self.assertEqual(cfg["roll_files"], ["rolls", elsewhere.resolve().as_posix(), "rolls/mine.json"])
        self.assertEqual(cfg["hotkeys"]["snapshot"], "F10")      # everything else kept


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


if __name__ == "__main__":
    unittest.main()
