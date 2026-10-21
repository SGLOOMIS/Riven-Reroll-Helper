"""Reading riven cards from OCR text: made-up lines, and OCR saved from real game screens."""

import unittest

from riven_helper.parse import RIVEN_SCREEN_RE, parse_cards, parse_stat

from tests.helpers import G, analyzer, ocr_line, saved_ocr


class TestStatLines(unittest.TestCase):
    def test_stat_lines(self):
        s = parse_stat("+135.2% Critical Damage", G)
        self.assertEqual((s.name, round(s.magnitude, 3), s.is_negative), ("Critical Damage", 1.352, False))
        s = parse_stat("x1.32 Damage to Grineer", G)
        self.assertEqual((s.name, round(s.magnitude, 2), s.is_negative), ("Damage to Grineer", 0.32, False))
        self.assertTrue(parse_stat("x0.75 Damage to Corpus", G).is_negative)
        self.assertFalse(parse_stat("-60.1% Weapon Recoil", G).is_negative)      # minus recoil is a bonus
        self.assertAlmostEqual(parse_stat("+2.7 Punch Through", G).magnitude, 2.7)
        self.assertAlmostEqual(parse_stat("+12.5o/o Heat", G).magnitude, 0.125)
        self.assertEqual(parse_stat("+90.1% X Toxin", G).name, "Toxin")          # element icon read as a letter
        self.assertIsNone(parse_stat("RIVEN MOD", G))
        self.assertIsNone(parse_stat("+12 Banana Power", G))

    def test_two_cards_on_one_ocr_line(self):
        # Windows OCR often merges text from both cards into one line.
        lines = []
        for i, (a, b) in enumerate([("Rubico Critatox", "Rubico Visitis"),
                                    ("+112.2% Critical Damage", "+180.4% Damage"),
                                    ("+80.2% Multishot", "x1.58 Damage to Grineer"),
                                    ("-42.7% Zoom", "-56.4% Impact")]):
            y = 100 + i * 40 + (0 if i == 0 else 60)
            lines.append(ocr_line(a, 500, y) + ocr_line(b, 1100, y))
        cards = parse_cards(lines, 1920, G)
        self.assertEqual(len(cards), 2)
        self.assertEqual([s.name for s in cards[0].stats], ["Critical Damage", "Multishot", "Zoom"])
        self.assertEqual(cards[1].stats[1].name, "Damage to Grineer")
        self.assertEqual((cards[0].title_name, cards[1].title_name), ("rubico", "rubico"))

    def test_wrapped_stat_name(self):
        lines = [ocr_line("Nikana Crita-satilis", 500, 100),
                 ocr_line("+7.7% Critical Damage", 500, 200),
                 ocr_line("+9.7% Critical Chance on", 500, 240),
                 ocr_line("Slide Attack", 500, 262),
                 ocr_line("+12.4% Melee Damage", 500, 300)]
        card = parse_cards(lines, 1920, G)[0]
        self.assertEqual([s.name for s in card.stats], ["Critical Damage", "Critical Chance on Slide Attack", "Damage"])


class TestRealScreens(unittest.TestCase):
    """OCR output captured from the real game (F10 snapshots), so no OCR engine is needed."""

    def analyze(self, fixture):
        return analyzer().analyze_lines(saved_ocr(fixture), 1920)

    def test_kitgun_primary_or_secondary(self):
        # A kitgun chamber is a Primary or a Secondary, both shown as "Gaze" with different dispositions and
        # stat pools. This one fits Gaze (Secondary): no "may have been misread" warning for that.
        (res,) = self.analyze("ocr_gaze_kitgun.json")
        self.assertEqual((res.ev.weapon.name, res.ev.weapon.cls, res.ev.rank), ("Gaze (Secondary)", "pistol", 8))
        self.assertTrue(res.ev.consistent)
        self.assertEqual(res.ev.notes, [])
        self.assertEqual([s.name for s in res.ev.stats], ["Slash", "Ammo Maximum", "Reload Speed", "Puncture"])

    def test_fits_in_variant_disposition(self):
        # A "Plinx" riven whose FITS IN panel shows Tenet Plinx: the numbers use Tenet Plinx's disposition.
        (res,) = self.analyze("ocr_plinx_tenet.json")
        self.assertEqual((res.card.title_name, res.card.shown_weapon), ("plinx", "tenet plinx"))
        self.assertEqual((res.ev.weapon.name, res.ev.rank), ("Tenet Plinx", 8))
        self.assertTrue(res.ev.consistent)
        # The locked trait's lock icon is OCR'd as "O"; the stat must still be read.
        self.assertEqual([s.name for s in res.ev.stats], ["Critical Damage", "Weak Point Damage", "Fire Rate"])
        self.assertEqual(res.ev.negative.name, "Fire Rate")

    def test_locked_trait_glued_to_sign(self):
        # Lock icon OCR'd as "0" with no space ("0+111.1% Critical" / "Damage"), and the card's
        # box must reach down to its MR footer.
        (res,) = self.analyze("ocr_ekhein_locked.json")
        self.assertEqual([s.name for s in res.ev.stats],
                         ["Status Duration", "Initial Combo", "Critical Damage", "Combo Duration"])
        self.assertEqual((res.ev.weapon.name, res.ev.rank), ("Ekhein", 8))
        x, y, w, h = res.card.box
        self.assertGreaterEqual(y + h, 845)                # the "MR 12" footer is at y ~834-849

    def test_element_icon_and_percent_misread(self):
        # "+41.90/0 *Cold": % read as 0/0 and the snowflake as "*"; FITS IN shows Coda Bubonico,
        # whose rivens use Bubonico's shotgun values.
        (res,) = self.analyze("ocr_coda_bubonico.json")
        self.assertEqual([(s.name, round(s.magnitude, 3)) for s in res.ev.stats],
                         [("Cold", 0.419), ("Critical Damage", 0.371), ("Multishot", 0.495)])
        self.assertEqual((res.ev.weapon.name, res.ev.rank, res.ev.weapon.cls), ("Coda Bubonico", 8, "shotgun"))
        self.assertTrue(res.ev.consistent)
        self.assertEqual(res.ev.notes, [])

    def test_dropped_x_and_clipped_fits_in(self):
        # "x0.71 Damage to Infested" OCR'd as "0.71 ..." and FITS IN "Velox Prime" as "elox Prime".
        (res,) = self.analyze("ocr_velox_prime.json")
        self.assertEqual(res.card.shown_weapon, "velox prime")
        self.assertEqual((res.ev.negative.name, round(res.ev.negative.magnitude, 2)), ("Damage to Infested", 0.29))
        self.assertEqual((res.ev.weapon.name, res.ev.rank), ("Velox Prime", 8))
        self.assertTrue(res.ev.consistent)

    def test_split_multiplier_at_1440p(self):
        # From a 2560x1440 system: "x1.32 Damage to Grineer" OCR'd as two words, "xl" ".32".
        (res,) = analyzer().analyze_lines(saved_ocr("ocr_cedo_split_multiplier.json"), 2560)
        self.assertEqual([(s.name, round(s.magnitude, 3)) for s in res.ev.stats],
                         [("Ammo Maximum", 0.555), ("Damage to Grineer", 0.32), ("Projectile Speed", 0.249)])
        self.assertEqual((res.ev.weapon.name, res.ev.rank), ("Cedo Prime", 8))
        self.assertTrue(res.ev.consistent)

    def test_locked_traits_list_is_not_a_card(self):
        # A spliced Blast and a locked Critical Chance: the riven screen lists both above LOCK TRAIT
        # ("O +119.6% *Blast", "O +173.5% Critical Chance"), which must not become a second card. On the card,
        # OCR split "+115.4% Cold" as "+1 15.4%".
        (res,) = self.analyze("ocr_torid_locked_list.json")
        self.assertEqual([(s.name, round(s.magnitude, 3)) for s in res.ev.stats],
                         [("Critical Chance", 1.735), ("Blast", 1.197), ("Cold", 1.154), ("Weapon Recoil", 0.927)])
        self.assertEqual((res.ev.weapon.name, res.ev.rank), ("Torid", 8))
        self.assertTrue(res.ev.consistent)
        self.assertAlmostEqual(parse_stat("-81 .7% Projectile Speed", G).magnitude, 0.817)

    def test_cycle_screen_same_riven_both_states(self):
        # Carousel: the selected card is large, the other small and dimmed. The same two rivens
        # must read the same whichever one is selected (wrapped "Damage" claimed, "9.3s" kept).
        left, right = self.analyze("ocr_cycle_selected_left.json")
        self.assertEqual([s.name for s in left.ev.stats], ["Range", "Initial Combo", "Damage to Grineer"])
        self.assertEqual([s.name for s in right.ev.stats], ["Combo Duration", "Finisher Damage", "Damage to Grineer"])
        self.assertEqual(right.card.orphans, [])
        self.assertEqual((left.ev.rank, right.ev.rank), (8, 8))
        self.assertGreater(left.card.text_h, right.card.text_h)          # left is the selected card here
        _, big = self.analyze("ocr_cycle_selected_right.json")
        self.assertAlmostEqual(big.ev.stats[0].magnitude, 9.3)            # "+9.36" misread of "+9.3s"
        self.assertEqual(big.ev.rank, 8)

    def test_riven_screen_detected_only_there(self):
        # The riven screen has labels like FITS IN / CYCLE FOR; a riven in the inventory grid doesn't.
        (res,) = self.analyze("ocr_plinx_tenet.json")
        self.assertTrue(res.card.riven_screen)
        grid = [line for line in saved_ocr("ocr_plinx_tenet.json")
                if not RIVEN_SCREEN_RE.search(" ".join(w[0] for w in line))]
        (card,) = parse_cards(grid, 1920, G)
        self.assertFalse(card.riven_screen)

    def test_melee_flat_stats(self):
        (res,) = self.analyze("ocr_ekhein.json")
        self.assertEqual((res.ev.weapon.name, res.ev.rank), ("Ekhein", 8))
        self.assertTrue(res.ev.consistent)
        self.assertEqual(res.ev.negative.name, "Combo Duration")


if __name__ == "__main__":
    unittest.main()
