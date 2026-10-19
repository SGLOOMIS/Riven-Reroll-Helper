"""Game data: riven stats (data/stats.json) and weapons with their dispositions (data/dispositions.json).

Also the fuzzy name matching used everywhere: OCR'd or typed stat names ("Status Duraf n", "CD")
map to canonical stat names, and weapon names are found in riven titles and screen headers.
"""

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def norm(text):
    """Lowercase, letters and digits only, single spaces: "Rubico Prime!" -> "rubico prime"."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


@dataclass
class StatDef:
    name: str
    unit: str            # "percent" (+95.2%), "flat" (+2.7 Punch Through) or "multiplier" (x1.32 faction damage)
    base: dict           # weapon class -> base value b in the riven formula
    good_sign: int = 1   # -1 when a minus sign on the card is the good direction (Weapon Recoil)
    aliases: tuple = ()


@dataclass
class Weapon:
    name: str            # e.g. "Rubico Prime", or "Catchmoon (Primary)" for a kitgun chamber in one slot
    disposition: float
    cls: str             # rifle | shotgun | pistol | archgun | melee: which base values apply
    type: str            # e.g. "Bow", "Sniper", "Kitgun"
    family: str          # the riven it uses, named after the family's base weapon ("Rubico")
    card: bool = True    # it's the family's base weapon: what a card shows when FITS IN can't be read

    @property
    def base_name(self):
        """The name without a slot: "Catchmoon (Primary)" -> "Catchmoon"."""
        return re.sub(r"\s*\(.*\)$", "", self.name)

    @property
    def is_bow(self):
        return self.type == "Bow"


class GameData:
    def __init__(self):
        stats = json.loads((DATA_DIR / "stats.json").read_text(encoding="utf-8"))["stats"]
        self.stats = {name: StatDef(name, s["unit"], s["base"], s.get("good_sign", 1), tuple(s.get("aliases", ())))
                      for name, s in stats.items()}
        self._stat_spellings = {norm(n): s.name for s in self.stats.values() for n in (s.name, *s.aliases)}

        weapons = json.loads((DATA_DIR / "dispositions.json").read_text(encoding="utf-8"))["weapons"]
        self.weapons = {name: Weapon(name, w["disposition"], w["class"], w.get("type", ""), w.get("family", name),
                                     w.get("card", True)) for name, w in weapons.items()}
        self.families = {}
        for w in self.weapons.values():
            self.families.setdefault(norm(w.family), []).append(w)
        # Longest first, so "Twin Grakatas" is found before "Grakata" and "Dex Nikana" before "Nikana".
        self.family_names = sorted({norm(w.family) for w in self.weapons.values()}, key=len, reverse=True)
        self.weapon_names = sorted({norm(w.base_name) for w in self.weapons.values()}, key=len, reverse=True)

    # -- stats -------------------------------------------------------------------------
    def match_stat(self, text, cutoff=0.78):
        """The canonical stat name for OCR'd or typed text, or None."""
        key = norm(text)
        if not key:
            return None
        if key in self._stat_spellings:
            return self._stat_spellings[key]
        close = difflib.get_close_matches(key, self._stat_spellings, n=1, cutoff=cutoff)
        return self._stat_spellings[close[0]] if close else None

    # -- weapons -----------------------------------------------------------------------
    @staticmethod
    def _find(text, names):
        padded = f" {norm(text)} "
        return next((n for n in names if len(n) >= 3 and f" {n} " in padded), None)

    def find_family_in_text(self, text):
        """The riven family named in a card title: "Plinx Enitis" -> "plinx"."""
        return self._find(text, self.family_names)

    def find_weapon_in_text(self, text):
        """Any weapon name, variants included: "Tenet Plinx" -> "tenet plinx"."""
        return self._find(text, self.weapon_names)

    def weapon_by_name(self, name):
        """The weapon with this exact name (e.g. "Rubico Prime"), or None."""
        key = norm(name)
        return next((w for w in self.weapons.values() if norm(w.name) == key), None)

    def weapon_by_base_name(self, name):
        """The weapon with this name, ignoring a kitgun slot ("catchmoon" -> Catchmoon (Primary)), or None."""
        key = norm(name)
        return next((w for w in self.weapons.values() if norm(w.base_name) == key), None)

    def family_members(self, family):
        return self.families.get(norm(family), [])

    def candidates_for(self, title_name, shown_weapon=None):
        """Weapons whose disposition a card titled `title_name` might use, most likely first.

        A riven is named after its family (Plinx) but fits every variant (Tenet Plinx), and the
        card shows the numbers of the weapon in the FITS IN panel. So: the FITS IN weapon, then
        the family's base weapon, then its other variants.
        """
        family = self.family_members(title_name)
        if not family:
            w = self.weapon_by_base_name(title_name)
            family = self.family_members(w.family) if w else []
        shown = norm(shown_weapon) if shown_weapon else None
        return sorted(family, key=lambda w: (norm(w.base_name) != shown, not w.card, w.name))
