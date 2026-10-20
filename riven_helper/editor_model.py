"""The data behind the roll-file editor: load, edit, save and check a roll JSON file.

Kept free of any UI so it can be tested on its own. A roll file is held in
an easy-to-edit form:

    entries:  {weapon key: [roll, ...]}   keys are weapon names, "@group" or "*rifle"-style fallbacks
    roll:     {"label", "positives": {stat: weight}, "required": [stats],
               "bad": [rule text], "dealbreakers": [rule text],
               "ignore_bad" / "ignore_dealbreakers": the file's ones it switches off}
    groups:   {group name: [weapon names]}
    bad / dealbreakers: rules for every roll in the file

Harmless negatives and stats bad as a positive are the same thing, so the editor keeps them in one
list: a plain "+Stat" bad rule (bad as a positive, any value) is also a harmless negative. A file's
"negatives" lists are turned into those rules on loading ("ignore_negatives" into "ignore_bad").

Anything else in the file is kept as it was.
"""

import json
import tempfile
from pathlib import Path

from .config import write_atomic
from .gamedata import norm
from .rolls import RULE_RE, RollLibrary

CLASSES = ["rifle", "shotgun", "pistol", "melee", "archgun"]
ROLL_KEYS = ("label", "positives", "negatives", "required", "bad", "dealbreakers", "ignore_negatives",
             "ignore_bad", "ignore_dealbreakers")       # "negatives" only keeps what can't become a rule
FILE_KEYS = ("name", "weapons", "groups", "negatives", "bad", "dealbreakers")
# How much each wanted stat matters. Stored as the stat's weight, and Required also in "required".
TIERS = {"Required": 1.0, "Wanted": 0.75, "Acceptable": 0.5}
SIGNS = {"as the negative (-)": "-", "as a positive (+)": "+", "either way": ""}
OPERATORS = ["(any value)", ">", ">=", "<", "<="]


def new_roll(label=""):
    return {"label": label, "positives": {}, "negatives": [], "required": [], "bad": [], "dealbreakers": [],
            "ignore_bad": [], "ignore_dealbreakers": []}


def tier_of(roll, stat):
    """A wanted stat's tier, from its weight and the required list (any weight works, not only the
    tiers' own: 0.75 and up is Wanted, below that Acceptable)."""
    if stat in roll["required"]:
        return "Required"
    return "Wanted" if float(roll["positives"][stat]) >= TIERS["Wanted"] else "Acceptable"


def set_tier(roll, stat, tier):
    """Want a stat at this tier: its weight, and whether the riven must have it."""
    roll["positives"][stat] = TIERS[tier]
    if tier == "Required" and stat not in roll["required"]:
        roll["required"].append(stat)
    elif tier != "Required" and stat in roll["required"]:
        roll["required"].remove(stat)


def rule_text(sign, stat, op=None, value=None):
    """Build a rule string: rule_text("-", "Damage", ">", 100) -> "-Damage > 100"."""
    text = f"{sign or ''}{stat}"
    if op and op in OPERATORS[1:] and value not in (None, ""):
        text += f" {op} {float(value):g}"
    return text


def rule_parts(text):
    """(sign "+" / "-" / "", stat, operator or None, value or None) of a rule's text."""
    m = RULE_RE.match(text)
    if not m:
        return "", text.strip(), None, None
    sign = {"−": "-"}.get(m.group("sign") or "", m.group("sign") or "")
    return sign, m.group("stat"), m.group("op"), m.group("value")


def same_rule(a, b):
    """Do two rule texts mean the same ("-Damage >= 100" and "-damage>=100")?"""
    pa, pb = rule_parts(a), rule_parts(b)
    number = lambda v: float(v) if v else None
    return (pa[0], pa[1].lower(), pa[2], number(pa[3])) == (pb[0], pb[1].lower(), pb[2], number(pb[3]))


def is_bad_as_positive(text):
    """Is this rule a plain "+Stat" (bad as a positive, any value), which is a harmless negative?"""
    sign, _, op, _ = rule_parts(text)
    return sign == "+" and op is None


def negatives_to_rules(negatives, rules, keep=()):
    """Turn harmless negatives into "+Stat" rules (the same thing, in one list), added to rules in place.
    Returns the ones that stay negatives: stats in keep (wanted as positives, where a "+" rule would mean
    something else; the overlay ignores those negatives anyway)."""
    kept, left = {k.lower() for k in keep}, []
    for stat in negatives:
        if stat.lower() in kept:
            left.append(stat)
        elif not any(same_rule(f"+{stat}", r) for r in rules):
            rules.append(f"+{stat}")
    return left


def describe_rule(text, dealbreaker=False):
    """Plain-English reading of an unwanted-stat rule (or a dealbreaker), for the editor's list."""
    m = RULE_RE.match(text)
    if not m:
        return text
    sign = {"−": "-"}.get(m.group("sign") or "", m.group("sign") or "")
    amount = f" {m.group('op')} {m.group('value')}" if m.group("op") else ""
    if dealbreaker:
        where = {"-": "it's the negative", "+": "it's a positive"}.get(sign, "it's on the riven")
        return f"rated 0 if {where}" + (f", {amount.strip()}" if amount else "")
    if is_bad_as_positive(text):
        return "unwanted as a positive, a good negative"
    where = {"-": "as the negative", "+": "as a positive"}.get(sign, "anywhere")
    return f"unwanted {where}" + (f" when{amount}" if amount else "")


class RollFile:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.extra = {}                   # top-level keys the editor doesn't edit (kept on save)
        self.name = ""
        self.entries = {}
        self.groups = {}
        self.bad = []
        self.dealbreakers = []
        self.dirty = False
        if self.path and self.path.exists():
            self.load(self.path)

    # -- load / save ---------------------------------------------------------------
    def load(self, path):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("not a roll file: the top level must be an object")
        self.extra = {k: v for k, v in data.items()
                      if k not in FILE_KEYS}
        self.name = data.get("name", "")
        self.groups = {g: list(m) for g, m in (data.get("groups") or {}).items()}
        self.bad = list(data.get("bad") or [])
        negatives_to_rules(data.get("negatives") or [], self.bad)
        self.dealbreakers = list(data.get("dealbreakers") or [])
        self.entries = {}
        for key, rolls in (data.get("weapons") or {}).items():
            rolls = [rolls] if isinstance(rolls, dict) else list(rolls)
            self.entries[key] = [self._roll_in(r) for r in rolls]
        self.dirty = False

    @staticmethod
    def _roll_in(r):
        pos = r.get("positives") or {}
        roll = {"label": r.get("label", ""),
                "positives": dict(pos) if isinstance(pos, dict) else {s: 1.0 for s in pos},
                "negatives": list(r.get("negatives") or []),
                "required": list(r.get("required") or []),
                "bad": list(r.get("bad") or []),
                "dealbreakers": list(r.get("dealbreakers") or []),
                "ignore_bad": list(r.get("ignore_bad") or []),
                "ignore_dealbreakers": list(r.get("ignore_dealbreakers") or []),
                "_extra": {k: v for k, v in r.items() if k not in ROLL_KEYS}}
        roll["negatives"] = negatives_to_rules(roll["negatives"], roll["bad"], keep=roll["positives"])
        negatives_to_rules(r.get("ignore_negatives") or [], roll["ignore_bad"])
        return roll

    @staticmethod
    def _roll_out(r):
        out = {}
        if r.get("label"):
            out["label"] = r["label"]
        pos = r.get("positives") or {}
        # A plain list when every weight is 1, like you'd write by hand.
        out["positives"] = list(pos) if all(float(w) == 1.0 for w in pos.values()) else \
            {s: float(w) for s, w in pos.items()}
        for key in ("required", "negatives", "bad", "dealbreakers", "ignore_bad", "ignore_dealbreakers"):
            if r.get(key):
                out[key] = list(r[key])
        out.update(r.get("_extra") or {})
        return out

    def to_json(self):
        data = {}
        if self.name:
            data["name"] = self.name
        data.update(self.extra)
        if self.groups:
            data["groups"] = {g: list(m) for g, m in self.groups.items()}
        if self.bad:
            data["bad"] = list(self.bad)
        if self.dealbreakers:
            data["dealbreakers"] = list(self.dealbreakers)
        data["weapons"] = {k: [self._roll_out(r) for r in rolls] if len(rolls) != 1 else self._roll_out(rolls[0])
                           for k, rolls in self.entries.items()}
        return data

    def save(self, path=None):
        if path:
            self.path = Path(path)
        if not self.path:
            raise ValueError("no file name")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Never half-written, and the previous version kept as <name>.json.bak (one undo for a bad save).
        write_atomic(self.path, json.dumps(self.to_json(), indent=2, ensure_ascii=False) + "\n", backup=True)
        self.dirty = False

    # -- checking ------------------------------------------------------------------
    def check(self, gamedata, other_files=()):
        """Problems the overlay would report for this file (unknown stats, bad rules, missing groups...).

        other_files: the other roll files that will be loaded with it, so groups defined there count.
        """
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / (self.path.name if self.path else "new.json")
            target.write_text(json.dumps(self.to_json()), encoding="utf-8")
            lib = RollLibrary(gamedata, [str(target)] + [str(f) for f in other_files
                                                         if not self.path or Path(f) != self.path])
            mine = target.name
            return [w for w in lib.warnings if w.startswith(mine) or "no file defines a group" in w]

    # -- editing helpers (mark the file as changed) ---------------------------------------
    def touch(self):
        self.dirty = True

    def add_entry(self, key):
        key = key.strip()
        if not key:
            raise ValueError("enter a weapon, @group or *class")
        if any(norm(k) == norm(key) and k[:1] == key[:1] for k in self.entries):
            raise ValueError(f'"{key}" is already in this file')
        self.entries[key] = [new_roll()]
        self.touch()
        return key

    def rename_entry(self, old, new):
        new = new.strip()
        if not new or new == old:
            return old
        self.entries = {(new if k == old else k): v for k, v in self.entries.items()}
        self.touch()
        return new

    def remove_entry(self, key):
        self.entries.pop(key, None)
        self.touch()

    def add_group(self, name):
        name = name.strip()
        if not name:
            raise ValueError("enter a group name")
        if any(norm(g) == norm(name) for g in self.groups):
            raise ValueError(f'group "{name}" already exists')
        self.groups[name] = []
        self.touch()
        return name

    def rename_group(self, old, new):
        new = new.strip()
        if not new or new == old:
            return old
        self.groups = {(new if g == old else g): m for g, m in self.groups.items()}
        # Keep rolls written for the group pointing at it.
        for key in list(self.entries):
            if key.startswith("@") and norm(key[1:]) == norm(old):
                self.entries = {("@" + new if k == key else k): v for k, v in self.entries.items()}
        self.touch()
        return new

    def remove_group(self, name):
        self.groups.pop(name, None)
        self.touch()


def weapon_choices(gamedata):
    """Names offered when adding a weapon: every riven family and weapon variant."""
    names = {w.family for w in gamedata.weapons.values()} | {w.base_name for w in gamedata.weapons.values()}
    return sorted(names, key=str.lower)


def stat_choices(gamedata):
    return sorted(gamedata.stats, key=str.lower)

