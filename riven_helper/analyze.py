"""Reading and rating the riven cards in a frame: OCR -> cards -> stat math -> ratings.

Analyzer.analyze_image(img, ocr) returns a CardResult for each card on screen. Along the way:
  * a card that came out doubtful (numbers don't fit, a stat name without its number) is read
    again on its own, enlarged; small dimmed text is where OCR drops things
  * both cards on the cycle screen are the same riven, so they share one weapon and one rank
  * the weapon shown under FITS IN is remembered for frames where it's hidden
"""

from dataclasses import dataclass

from .gamedata import GameData, norm
from .kuva import base_rate, lock_doubles, read_cycle_cost
from .parse import parse_cards
from .riven_math import infer
from .rolls import Rating, RollLibrary, rate

OCR_SCALE = 1.5                                    # enlarge frames this much before OCR (helps at 1080p)
# Settings for re-reading a doubtful card: (enlargement, invert colours). Small dim text is sensitive
# to exact pixels, so a line one setting drops another usually gets.
REREAD_SETTINGS = [(3.0, False), (2.0, False), (2.5, True), (4.0, False)]


@dataclass
class CardResult:
    card: object       # parse.Card
    ev: object         # riven_math.RivenEval, or None if the card couldn't be worked out
    rating: object     # rolls.Rating


class Analyzer:
    def __init__(self, cfg):
        self.cfg = cfg
        self.gamedata = GameData()
        self._fits_in_memory = {}                  # riven family -> weapon last shown under FITS IN
        self.targets = {}                          # weapon name -> index of the roll it's rated against
        self.cycle_base = None                     # the next cycle's base rate (CYCLE FOR, without the lock)
        self._cost_sure = True
        self._load_rolls()

    def _load_rolls(self):
        cfg = self.cfg
        self.library = RollLibrary(self.gamedata, cfg["roll_files"], cfg["_dir"], cfg["rating"],
                                   bad=cfg["bad"], dealbreakers=cfg["dealbreakers"])

    def apply_settings(self, cfg):
        """New settings (config.json was saved): take them over in place, so everyone holding this
        Analyzer's cfg sees them, and load the roll files they list. Updated, never emptied first, so the
        other thread never finds a setting missing."""
        self.cfg.update(cfg)
        self._load_rolls()

    def analyze_image(self, img, ocr):
        """OCR a frame (PIL image) and rate its riven cards. Returns (results, OCR lines)."""
        lines = ocr.read(img, OCR_SCALE)
        results = self.analyze_lines(lines, img.width)
        reread = False
        for i, res in enumerate(results):
            if self._doubtful(res):
                better = self._reread(img, ocr, res)
                if better is not None:
                    results[i], reread = better, True
        if reread:
            self._share_weapon_and_rank(results)
        if results and not self._cost_sure:            # e.g. ",000": read the number again without the icon
            self._read_cost(lines, results, img, ocr)
        return results, lines

    def _read_cost(self, lines, results, image=None, ocr=None):
        """The next cycle's base rate, from the CYCLE FOR button (kuva.py)."""
        locked = lock_doubles(results[0].ev)
        cost, self._cost_sure = read_cycle_cost(lines, locked, image, ocr)
        self.cycle_base = base_rate(cost, locked)

    def analyze_lines(self, lines, image_width):
        """Rate the cards in already OCR'd lines (used directly by tests on saved OCR output)."""
        results = [self._evaluate(card) for card in parse_cards(lines, image_width, self.gamedata)]
        if results:
            self._read_cost(lines, results)
        self._share_weapon_and_rank(results)
        return results

    def rolls_for(self, weapon):
        """The rolls a riven for this weapon is rated against: the targeted one (cycle_target), or all
        of them, the best match counting."""
        rolls = self.library.rolls_for(weapon)
        i = self.targets.get(weapon.name)
        return [rolls[i]] if i is not None and i < len(rolls) else rolls

    def target(self, weapon):
        """(the targeted roll's number, from 1, or None for the best match; how many rolls there are)."""
        n = len(self.library.rolls_for(weapon))
        i = self.targets.get(weapon.name)
        return (i + 1 if i is not None and i < n else None), n

    def cycle_target(self, weapon):
        """Target the weapon's next roll: best match -> roll 1 -> roll 2 ... -> best match.
        Returns the targeted roll, or None for the best match."""
        rolls = self.library.rolls_for(weapon)
        i = self.target(weapon)[0]                 # the next roll's index is the current one's number
        i = 0 if i is None else i
        if i >= len(rolls) or len(rolls) < 2:
            self.targets.pop(weapon.name, None)
            return None
        self.targets[weapon.name] = i
        return rolls[i]

    def rate(self, ev):
        return rate(ev, self.rolls_for(ev.weapon), self.gamedata, self.cfg["rating"])

    def _evaluate(self, card):
        title = card.title_name
        if not title and card.shown_weapon:
            shown = self.gamedata.weapon_by_base_name(card.shown_weapon)
            title = shown.family if shown else None
        if not title:
            return CardResult(card, None, Rating(0.0, detail="weapon not recognised"))
        # FITS IN can be hidden (a dialog, the cycle animation): use the weapon it last showed.
        if card.shown_weapon:
            self._fits_in_memory[norm(title)] = card.shown_weapon
        else:
            card.shown_weapon = self._fits_in_memory.get(norm(title))
        candidates = self.gamedata.candidates_for(title, card.shown_weapon)
        ev = infer(card.stats, candidates, self.gamedata) if candidates else None
        if ev is None:
            return CardResult(card, None, Rating(0.0, detail="stats don't fit this weapon"))
        return CardResult(card, ev, self.rate(ev))

    @staticmethod
    def _doubtful(res):
        return res.ev is None or not res.ev.consistent or bool(res.card.orphans) or bool(res.ev.notes)

    @staticmethod
    def confidence(res):
        """How trustworthy a reading is (compare with >): fits, more stats read, nothing dropped,
        no warnings, and larger text (the selected card)."""
        ev = res.ev
        return (ev is not None and ev.consistent, len(res.card.stats), not res.card.orphans,
                ev is not None and not ev.notes, res.card.text_h)

    def _reread(self, img, ocr, res):
        """Read one card's area again at a few settings; return a better result, or None."""
        from .layout import card_rect
        x, y, w, h = card_rect(res.card.geometry, img.width, img.height)
        left, top = max(0, int(x - w * 0.1)), max(0, int(y))
        crop = img.crop((left, top, min(img.width, int(x + w * 1.1)),
                         min(img.height, int(y + h + res.card.text_h * 2))))
        best = res
        for scale, invert in REREAD_SETTINGS:
            lines = [[(t, wx + left, wy + top, ww, wh) for t, wx, wy, ww, wh in line]
                     for line in ocr.read(crop, scale, invert)]
            cards = parse_cards(lines, img.width, self.gamedata)
            if not cards:
                continue
            card = max(cards, key=lambda c: len(c.stats))
            # Keep what the full frame knew: the title, FITS IN, the screen, and where the card is.
            card.title_name = card.title_name or res.card.title_name
            card.shown_weapon = card.shown_weapon or res.card.shown_weapon
            card.riven_screen = res.card.riven_screen
            card.box, card.text_h = res.card.box, res.card.text_h
            again = self._evaluate(card)
            if self.confidence(again) > self.confidence(best):
                best = again
            if not self._doubtful(best):
                break
        return best if best is not res else None

    def _share_weapon_and_rank(self, results):
        """Both cards on the cycle screen are the same riven: re-check the less reliable reading with
        the weapon and rank of the most reliable one."""
        fitting = [r for r in results if r.ev and r.ev.consistent]
        if len(results) < 2 or not fitting:
            return
        ref = max(fitting, key=self.confidence)
        for i, res in enumerate(results):
            if res is ref or res.ev is None or (res.ev.rank, res.ev.weapon) == (ref.ev.rank, ref.ev.weapon):
                continue
            candidates = [ref.ev.weapon] + [w for w in self.gamedata.candidates_for(ref.ev.weapon.family)
                                            if w is not ref.ev.weapon]
            ev = infer(res.card.stats, candidates, self.gamedata, ranks=[ref.ev.rank])
            if ev is not None and ev.consistent:
                results[i] = CardResult(res.card, ev, self.rate(ev))
            else:
                res.ev.notes.append(f"doesn't fit {ref.ev.weapon.name} R{ref.ev.rank} like the other card: "
                                    "a stat line may be misread")
