"""The weapon upgrade screen's IDEAL RIVEN panel, and end-to-end reads through Windows OCR."""

import tempfile
import unittest
from pathlib import Path

from riven_helper.layout import plan_upgrade_screen
from riven_helper.upgrade_screen import weapon_from_header, weapon_from_text

from tests.helpers import FIXTURES, G, analyzer, fixture_config, saved_ocr, windows_ocr


class TestUpgradeScreen(unittest.TestCase):
    def test_header_misread_in_saved_ocr(self):
        # Real snapshot: the header read as "QIJPGRADES/SPECTRA VANDAL [30]".
        self.assertEqual(weapon_from_text(saved_ocr("ocr_upgrade_qij_header.json"), G), "spectra vandal")

    def test_header_dropped_by_ocr(self):
        # OCR dropped "UPGRADES/SPECTRA" (only "VANDAL [30]"): the header is read again, on its own.
        import cv2

        from riven_helper.session import Session
        session = Session(analyzer(), windows_ocr(self))
        events, _ = session.step(cv2.imread(str(FIXTURES / "img" / "upgrade_header_dropped.jpg")), now=0.0)
        self.assertIn(("upgrade", "spectra vandal"), events)

    def test_gun_panel_and_no_flicker(self):
        # A compact IDEAL RIVEN panel in the empty area below the arcane slot; it goes when the screen does.
        import cv2
        import numpy as np

        from riven_helper.session import Session
        an = analyzer()
        session = Session(an, windows_ocr(self))
        frame = cv2.imread(str(FIXTURES / "img" / "upgrade_spectra_vandal.jpg"))
        events, _ = session.step(frame, now=0.0)
        self.assertIn(("upgrade", "spectra vandal"), events)
        img, (x, y) = plan_upgrade_screen(an, "spectra vandal", 1919, 1079, fixture_config())
        self.assertTrue(1572 <= x and x + img.width <= 1872 and 470 <= y and y + img.height <= 610)
        events, _ = session.step(frame, now=1.5)                   # same screen: no change, no flicker
        self.assertFalse([e for e in events if e[0] == "upgrade"])
        events, _ = session.step(np.zeros_like(frame), now=3.0)    # left the screen: one miss is tolerated...
        self.assertFalse([e for e in events if e[0] == "upgrade"])
        events, _ = session.step(np.zeros_like(frame), now=4.5)    # ...two clear it
        self.assertIn(("upgrade", None), events)

    def test_other_ui_theme_at_1440p(self):
        # From a 2560x1440 system with a pale gold UI theme instead of orange: OCR read only
        # "PRIME [30]" of "UPGRADES/EPITAPH PRIME [30]", and the header reader must find the gold text.
        import cv2

        from riven_helper.session import Session
        an = analyzer()
        session = Session(an, windows_ocr(self))
        frame = cv2.imread(str(FIXTURES / "img" / "upgrade_gold_theme_epitaph_prime.jpg"))
        events, _ = session.step(frame, now=0.0)
        self.assertIn(("upgrade", "epitaph prime"), events)
        img, (x, y) = plan_upgrade_screen(an, "epitaph prime", 2560, 1440, fixture_config())
        self.assertTrue(2100 <= x and x + img.width <= 2500 and 630 <= y and y + img.height <= 810)

    def test_condensed_header_any_resolution(self):
        # Gold-theme melee screen "UPGRADES/SKIAJATI [30]": OCR reads only "[30]", and the condensed
        # header font is only readable widened. It must read the same at 1080p, 1440p and 4K.
        from PIL import Image
        ocr = windows_ocr(self)
        src = Image.open(FIXTURES / "img" / "upgrade_gold_theme_skiajati.jpg").convert("RGB")
        for size in ((1920, 1080), (2560, 1440), (3840, 2160)):
            self.assertEqual(weapon_from_header(src.resize(size, Image.LANCZOS), ocr, G), "skiajati", size)

    def test_every_ui_theme(self):
        # Warframe's 20 UI themes: light and dark, one or two text colours. Each one's screen header
        # ("CUSTOMIZE UI THEME/THEME", the same style as the upgrade screen's) must come out readable.
        import difflib

        from riven_helper.upgrade_screen import _capitals, _glyphs, _respaced, _texts, header_mask
        from tests.theme_headers import theme_frames
        ocr = windows_ocr(self)
        for name, frame in theme_frames():
            mask = header_mask(frame)
            image = _respaced(mask, _glyphs(mask), widen=True)
            best = max(difflib.SequenceMatcher(None, _capitals(" ".join(_texts(ocr.read(image, scale)))).replace(" ", ""),
                                               "CUSTOMIZEUITHEME/THEME").ratio() for scale in (1.0, 1.5))
            self.assertGreater(best, 0.85, name)

    def test_melee_screens(self):
        # The melee header OCRs as "[30]" or "PRIME [30]" only; the header reader still gets the weapon,
        # and the panel goes below the arcane slot at the top right (melee has a different layout).
        from PIL import Image
        ocr, an = windows_ocr(self), analyzer()
        for fixture, weapon in (("upgrade_melee_praedos.jpg", "praedos"), ("upgrade_melee_fang_prime.jpg", "fang prime")):
            img = Image.open(FIXTURES / "img" / fixture).convert("RGB")
            self.assertEqual(weapon_from_header(img, ocr, G), weapon, fixture)
            panel, (x, y) = plan_upgrade_screen(an, weapon, img.width, img.height, fixture_config())
            self.assertTrue(1570 <= x and x + panel.width <= 1875, fixture)
            self.assertTrue(320 <= y and y + panel.height <= 615, fixture)


class TestWindowsOcr(unittest.TestCase):
    """Riven screens end to end through Windows OCR."""

    def test_dimmed_card_reread(self):
        # The unselected card's "+1.3" is lost at normal scale; the enlarged second read recovers it.
        from PIL import Image
        img = Image.open(FIXTURES / "img" / "cycle_dimmed_left.png").convert("RGB")
        results, _ = analyzer().analyze_image(img, windows_ocr(self))
        dimmed, selected = sorted(results, key=lambda r: r.card.box[0])
        self.assertEqual([s.name for s in dimmed.ev.stats], ["Range", "Initial Combo", "Damage to Grineer"])
        self.assertEqual((dimmed.ev.rank, selected.ev.rank), (8, 8))
        self.assertTrue(dimmed.ev.consistent and selected.ev.consistent)

    def test_generated_samples(self):
        from PIL import Image

        import tests.make_sample as make_sample
        ocr, an = windows_ocr(self), analyzer()
        folder = Path(tempfile.mkdtemp())
        for kind, expect in (("rubico", (99, 9)), ("nikana", (99, 10))):
            make_sample.main(folder / f"{kind}.png", kind)
            img = Image.open(folder / f"{kind}.png").convert("RGB")
            res = an.analyze_lines(ocr.read(img, 1.5), img.width)
            self.assertEqual([round(r.rating.score) for r in res], list(expect), kind)
            self.assertTrue(all(r.ev.consistent for r in res), kind)


if __name__ == "__main__":
    unittest.main()
