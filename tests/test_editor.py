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


if __name__ == "__main__":
    unittest.main()
