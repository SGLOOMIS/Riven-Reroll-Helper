"""What the overlay shows: panel text, panel placement, the game-style look, card tracking and fades."""

import json
import tempfile
import unittest
from pathlib import Path

from riven_helper.layout import BUTTON_ZONE, card_rect, place_card_panels, plan_riven_screen
from riven_helper.panel_text import ideal_rows, rows_text

from tests.helpers import FIXTURES, analyzer, fixture_config, saved_ocr

W, H = 1920, 1080


def hits(a, b):
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


class TestPanelText(unittest.TestCase):
    def test_ideal_roll_panel(self):
        folder = Path(tempfile.mkdtemp())
        (folder / "plinx.json").write_text(json.dumps({"weapons": {"Plinx": {
            "positives": {"CD": 1, "CC": 1, "MS": 1, "Damage": 0.5}, "negatives": ["Zoom", "Recoil"]}}}))
        an = analyzer(folder)
        rows = ideal_rows(an, an.analyze_lines(saved_ocr("ocr_plinx_tenet.json"), W))
        text = rows_text(rows)
        self.assertEqual(rows[0], ("title", "IDEAL ROLL"))
        self.assertIn("Tenet Plinx  R8", text)            # the FITS IN variant and the card's rank
        self.assertIn("up to +69.6%", text)               # max Critical Damage (see test_math)
        self.assertIn("~ Damage", text)                   # a lower-weighted stat shown as an alternative
        self.assertIn("- Zoom, Weapon Recoil", text)


class TestPlacement(unittest.TestCase):
    def test_panel_just_above_card(self):
        box = (841, 724, 243, 125, 19)                     # Plinx card: stats + MR footer, line height
        cx, top, cw, _ = card_rect(box, W, H)
        self.assertAlmostEqual(top, 446, delta=15)         # the card art's top is ~460 at 1080p
        ((px, py),) = place_card_panels([(box, (300, 180))], W, H)
        self.assertLess(py + 180, top)                     # above the card...
        self.assertLess(top - (py + 180), 20)              # ...with a small gap
        self.assertAlmostEqual(px + 150, cx + cw / 2, delta=2)

    def test_two_cards_never_overlap(self):
        ideal = (38, 183, 420, 210)
        for spread in (300, 420, 540, 700):               # distance between the two cards' centres
            boxes = [(960 - spread / 2 - 121, 724, 242, 125), (960 + spread / 2 - 121, 724, 242, 125)]
            sizes = [(400, 170), (400, 170)]
            spots = place_card_panels(list(zip(boxes, sizes)), W, H, [ideal])
            rects = [(x, y, w, h) for (x, y), (w, h) in zip(spots, sizes)]
            self.assertFalse(hits(*rects), spread)
            for r in rects:
                self.assertFalse(any(hits(r, card_rect(b, W, H)) for b in boxes), (spread, r))
                self.assertFalse(hits(r, ideal), spread)
                self.assertLessEqual(r[1] + r[3], H * BUTTON_ZONE)

    def test_cycle_screen_panels_above_their_cards(self):
        # From the Spinnerex snapshot: dimmed card left, selected card centre, IDEAL ROLL at far left.
        dimmed, selected = (501, 752, 202, 63, 14), (831, 676, 262, 173, 18)
        ideal = (38, 183, 303, 274)
        sizes = [(225, 175), (290, 175)]
        spots = place_card_panels([(dimmed, sizes[0]), (selected, sizes[1])], W, H, [ideal])
        for (px, py), (pw, ph), box in zip(spots, sizes, (dimmed, selected)):
            cx, top, cw, _ = card_rect(box, W, H)
            self.assertLess(py + ph, top)                  # above its own card
            self.assertTrue(cx < px + pw / 2 < cx + cw)    # and over it
        rects = [(x, y, w, h) for (x, y), (w, h) in zip(spots, sizes)]
        self.assertFalse(hits(*rects))
        self.assertGreaterEqual(spots[0][0], ideal[0] + ideal[2])   # clear of IDEAL ROLL


class TestPanelStyle(unittest.TestCase):
    def test_panels_render_in_game_colours(self):
        from riven_helper.theme import palette
        NAVY, ORANGE = palette().fill, palette().label
        an = analyzer()
        results = an.analyze_lines(saved_ocr("ocr_cycle_selected_left.json"), W)
        cards, ideal = plan_riven_screen(an, results, W, H, fixture_config())
        self.assertEqual(len(cards), 2)
        self.assertIsNotNone(ideal)
        img, _ = cards[0]
        self.assertEqual(img.mode, "RGBA")
        px = img.getpixel((img.width // 2, img.height - 6))
        self.assertTrue(px[3] < 255 and abs(px[0] - NAVY[0]) < 25)                        # translucent navy
        border = [img.getpixel((i, 1)) for i in range(img.width)]
        self.assertTrue(any(p[3] > 100 and abs(p[0] - ORANGE[0]) < 10 for p in border))   # orange outline
        self.assertEqual(img.getpixel((0, 0))[3], 0)                                      # cut corner is clear


class TestTheme(unittest.TestCase):
    """Panels are drawn in the player's UI theme, read off the screen header."""

    def theme(self, number):
        """The Theme read off theme screenshot number (1-20)."""
        from riven_helper.theme import detect
        from tests.theme_headers import theme_frames
        return next(detect(frame) for name, frame in theme_frames() if name.startswith(f"theme_{number:02d}_"))

    def test_detected_from_header(self):
        def near(a, b):
            return max(abs(x - y) for x, y in zip(a, b)) <= 30
        orange = self.theme(1)                              # orange "CUSTOMIZE UI THEME/", red-orange "THEME"
        self.assertTrue(near(orange.primary, (249, 133, 8)) and near(orange.accent, (248, 54, 5)), orange)
        self.assertLess(max(orange.background), 60)          # on a dark bar
        light = self.theme(17)                              # dark green text, gold accent, on light grey
        self.assertLess(max(light.primary), 80)
        self.assertGreater(min(light.background), 180)
        from PIL import Image

        from riven_helper.theme import detect
        self.assertIsNone(detect(Image.new("RGB", (1920, 1080), (40, 40, 40))))   # no header: nothing
        # The cycle animation's bright crystal right behind the header (no bar): not the theme's background.
        frame = Image.new("RGB", (1920, 1080))
        frame.paste(Image.open(FIXTURES / "img" / "header_over_art_1920x1080.png").convert("RGB"), (0, 0))
        over_art = detect(frame)
        self.assertLess(max(over_art.background), 60)
        self.assertTrue(near(over_art.primary, (253, 132, 2)))

    def test_background_is_the_buttons_fill(self):
        # The panels' background is the LOCK TRAIT / CONFIRM button's fill, read around its label.
        from PIL import Image

        from riven_helper.theme import button_colour, detect
        img = Image.open(FIXTURES / "img" / "riven_locked_amprex.jpg").convert("RGB")
        lines = saved_ocr("ocr_amprex_locked.json")
        fill = button_colour(img, lines)
        self.assertTrue(max(abs(a - b) for a, b in zip(fill, (17, 25, 35))) <= 6, fill)
        self.assertEqual(detect(img, lines).background, fill)
        self.assertIsNone(button_colour(img, []))                    # no button on screen
        self.assertEqual(detect(img, [], button=(1, 2, 3)).background, (1, 2, 3))   # one seen before

    def test_palette_stays_readable(self):
        from riven_helper.theme import luminance, detect, palette
        from tests.theme_headers import theme_frames
        for name, frame in theme_frames():
            p = palette(detect(frame))
            for colour in (p.label, p.text, p.stat, p.good, p.bad):
                self.assertGreaterEqual(abs(luminance(colour) - luminance(p.fill)), 0.3, (name, colour, p.fill))

    def test_overlay_redraws_in_new_theme(self):
        from riven_helper.overlay_state import OverlayState
        an = analyzer()
        state = OverlayState(an, fixture_config())
        state.on_results((W, H), an.analyze_lines(saved_ocr("ocr_cycle_selected_left.json"), W))
        for _ in range(8):
            before = {key: (img, x, y, a) for key, img, x, y, a in state.tick()}
        state.on_theme(self.theme(17))                       # light theme picked
        after = {key: (img, x, y, a) for key, img, x, y, a in state.tick()}
        card = ("card", 0)
        self.assertEqual(before[card][1:], after[card][1:])  # same place, same fade
        fill = after[card][0].getpixel((after[card][0].width // 2, after[card][0].height - 6))
        self.assertGreater(min(fill[:3]), 150)              # now light, like the theme


class TestTracker(unittest.TestCase):
    """Cards are followed between reads by template matching on screenshots."""

    def test_follows_cycle_screen_swap(self):
        # The two real cycle-screen states: Para-locticon selected (centre), then Tempicta selected.
        from PIL import Image

        from riven_helper.tracker import CardTracker, to_gray_small
        results = analyzer().analyze_lines(saved_ocr("ocr_cycle_selected_left.json"), W)
        frame_a = Image.open(FIXTURES / "img" / "cycle_full_a.jpg").convert("RGB")
        frame_b = Image.open(FIXTURES / "img" / "cycle_full_b.jpg").convert("RGB")
        tracker = CardTracker()
        tracker.set_cards(frame_a, [r.card.geometry for r in results])
        self.assertTrue(all(t.score > 0.95 and t.lost == 0 for t in tracker.update(to_gray_small(frame_a))))
        para, tempicta = tracker.update(to_gray_small(frame_b))
        self.assertEqual((para.lost, tempicta.lost), (0, 0))
        self.assertLess(para.x, 600)                                  # slid to the left...
        self.assertAlmostEqual(para.scale, 0.8, delta=0.04)           # ...and shrank (dimmed)
        self.assertAlmostEqual(tempicta.scale, 1.25, delta=0.05)      # the other grew into the centre
        self.assertAlmostEqual(tempicta.x + tempicta.size[0] * tempicta.scale / 2, 960, delta=40)

    def test_rerolled_card_stops_matching(self):
        from PIL import Image

        import tests.make_sample as make_sample
        from riven_helper.tracker import CardTracker, to_gray_small
        folder = Path(tempfile.mkdtemp())
        make_sample.main(folder / "a.png", "rubico")
        make_sample.main(folder / "b.png", "nikana")                 # different rivens in the same places
        a = Image.open(folder / "a.png").convert("RGB")
        b = Image.open(folder / "b.png").convert("RGB")
        tracker = CardTracker()
        tracker.set_cards(a, [(560, 416, 242, 137, 30), (1100, 417, 242, 102, 30)])
        self.assertTrue(all(t.lost == 0 for t in tracker.update(to_gray_small(a))))
        self.assertTrue(all(t.lost >= 1 for t in tracker.update(to_gray_small(b))))


class TestOverlayState(unittest.TestCase):
    """Card panels only show while the screen is at rest in a reroll state."""

    def setUp(self):
        from riven_helper.overlay_state import OverlayState
        an = analyzer()
        self.results = an.analyze_lines(saved_ocr("ocr_cycle_selected_left.json"), W)
        self.state = OverlayState(an, fixture_config())
        self.state.on_results((W, H), self.results)

    def tracks(self, dx=0.0, k=1.0):
        return [(r.card.box[0] + dx, r.card.box[1], k, None) for r in self.results]

    def shown(self, ticks=8):
        items = []
        for _ in range(ticks):
            items = self.state.tick()
        return {key: (x, y, alpha) for key, _img, x, y, alpha in items}

    def test_hidden_while_moving_shown_when_settled(self):
        self.state.on_track(self.tracks())
        before = self.shown()
        self.assertEqual(before[("card", 0)][2], 255)
        self.state.on_track(self.tracks(dx=-120, k=0.8))          # the cards slide
        self.assertNotIn(("card", 0), self.shown())
        geometries = [(r.card.box[0] - 120, r.card.box[1], r.card.box[2] * 0.8, r.card.box[3] * 0.8,
                       r.card.text_h * 0.8) for r in self.results]
        self.state.on_relayout(geometries)                         # came to rest: shown at the new spot
        after = self.shown()
        self.assertEqual(after[("card", 0)][2], 255)
        self.assertLess(after[("card", 0)][0], before[("card", 0)][0] - 60)

    def test_hold_and_dialog(self):
        self.state.on_track([None for _ in self.results])         # dimmed by a dialog
        items = self.shown()
        self.assertFalse(any(key[0] == "card" for key in items))
        self.assertNotIn(("ideal",), items)                        # IDEAL ROLL hides too
        self.state.on_hold()                                       # a new reading is being confirmed
        self.assertEqual(self.state.cards, [])


if __name__ == "__main__":
    unittest.main()
