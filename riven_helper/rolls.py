"""Your roll lists: loading the roll JSON files, and rating a riven against them.

A roll file (see README) has:
    "weapons":       {weapon name | "@group" | "*rifle": roll or [rolls]}
    "groups":        {group name: [weapon names]}      (optional; usable from any file)
    "bad", "dealbreakers": rules for every roll in the file (optional)
    "fallback": true  for files used only when no other file covers a weapon (the market defaults)

A roll has "positives" (a list, or {stat: weight}), and optionally "label", "negatives" (harmless
negatives), "required", "bad" and "dealbreakers".
"""

import glob
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .gamedata import norm

DEFAULT_RATING = {
    "type_weight": 0.9,              # share of a wanted stat's credit for being the right type (rest: roll quality)
    "bad_stat_score": 0.5,           # score multiplier for each bad stat
    "missing_required_score": 0.25,  # score multiplier for each missing required stat
}

# A rule like "-Damage > 100", "+Zoom" or "Impact": optional sign, stat, optional comparison.
RULE_RE = re.compile(r"^\s*(?P<sign>[+\-−])?\s*(?P<stat>.*?)\s*"
                     r"(?:(?P<op>>=|<=|>|<)\s*(?P<value>\d+(?:\.\d+)?)\s*%?)?\s*$")


@dataclass
class StatRule:
    """A "bad" or "dealbreaker" rule.

    sign: "-" (only as the negative), "+" (only as a positive) or None (either way).
    value: compared with the number on the card: 100 means 100% for percentage stats,
    25 means x1.25 for faction damage, flat stats as shown (+2.7).
    """
    stat: str
    sign: str = None
    op: str = None
    value: float = None
    text: str = ""

    def matches(self, riven_stat, stat_def):
        if riven_stat.name != self.stat:
            return False
        if self.sign and (self.sign == "-") != riven_stat.is_negative:
            return False
        if self.op is None:
            return True
        shown = riven_stat.magnitude if stat_def.unit == "flat" else riven_stat.magnitude * 100
        return {">": shown > self.value, ">=": shown >= self.value,
                "<": shown < self.value, "<=": shown <= self.value}[self.op]


@dataclass
class Roll:
    label: str
    positives: dict           # stat -> weight (1 = ideal)
    negatives: list           # negatives known to be harmless (shown as such; negatives are neutral anyway)
    required: list
    bad: list                 # [StatRule]
    dealbreakers: list        # [StatRule]
    source: str = ""          # file name
    fallback: bool = False    # from a fallback file: only used when no other file covers the weapon


@dataclass
class Rating:
    score: float              # 0 .. 100
    roll: Roll = None
    tags: dict = field(default_factory=dict)      # stat -> good / ok / unwanted / harmless / neutral / bad / dealbreaker
    detail: str = ""                               # why there's no score
    missing: list = field(default_factory=list)    # required stats the riven lacks
    dealbreaker: str = ""                          # the rule that made the riven unusable
    bad: list = field(default_factory=list)        # why each bad stat is bad


def parse_rules(items, gamedata, warnings, where):
    """Rule strings -> [StatRule]; anything unreadable goes to warnings."""
    rules = []
    for item in items or []:
        m = RULE_RE.match(str(item))
        if not m or not m.group("stat"):
            warnings.append(f"{where}: can't read rule '{item}'")
            continue
        stat = gamedata.match_stat(m.group("stat"), cutoff=0.85)
        if stat is None:
            warnings.append(f"{where}: unknown stat in rule '{item}'")
            continue
        sign = {"+": "+", "-": "-", "−": "-"}.get(m.group("sign"))
        value = float(m.group("value")) if m.group("value") else None
        rules.append(StatRule(stat, sign, m.group("op"), value, str(item).strip()))
    return rules


def _stats(names, gamedata, warnings, where):
    """Stat names (any spelling, e.g. "CD") -> canonical names; unknown ones go to warnings."""
    out = []
    for name in names or []:
        stat = gamedata.match_stat(str(name), cutoff=0.85)
        if stat is None:
            warnings.append(f"{where}: unknown stat '{name}'")
        elif stat not in out:
            out.append(stat)
    return out


def _key(weapon_key):
    """How a "weapons" key is matched: loosely, keeping a "*" (class fallback) or "@" (group) prefix."""
    k = weapon_key.strip()
    return k[0] + norm(k[1:]) if k[:1] in "*@" else norm(k)


def roll_paths(sources, base_dir=".", warnings=None):
    """The roll files that config.json's roll_files lists: files, every .json in a folder, or globs
    (relative to base_dir). Sources that don't exist are reported in warnings."""
    paths = []
    for src in sources:
        p = Path(src) if Path(src).is_absolute() else Path(base_dir) / src
        if p.is_dir():
            paths += sorted(p.glob("*.json"))
        elif any(c in str(p) for c in "*?["):
            paths += [Path(x) for x in sorted(glob.glob(str(p)))]
        elif p.exists():
            paths.append(p)
        elif warnings is not None:
            warnings.append(f"roll source not found: {src}")
    return paths


class RollLibrary:
    """Every roll from every roll file, ready to look up by weapon."""

    def __init__(self, gamedata, sources, base_dir=".", rating=None, bad=None, dealbreakers=None):
        self.gamedata = gamedata
        self.sources = sources                 # files, folders or globs
        self.base_dir = Path(base_dir)
        self.rating = {**DEFAULT_RATING, **(rating or {})}
        self.global_bad, self.global_dealbreakers = bad or [], dealbreakers or []
        self.rolls = {}                        # weapon key -> [Roll]
        self.groups = {}                       # group name -> {member weapon or family names}
        self.files = {}                        # path -> modification time (to notice edits)
        self.warnings = []
        self.reload()

    def _paths(self):
        return roll_paths(self.sources, self.base_dir, self.warnings)

    def changed(self):
        """True when a roll file was added, removed or edited since the last load."""
        return {str(p): p.stat().st_mtime for p in self._paths()} != self.files

    def reload(self):
        self.warnings = []
        self.rolls, self.groups, self.files = {}, {}, {}
        self._tier_cache = {}                  # weapon name -> its tiers (see _tiers), until the next reload
        for path in self._paths():
            self.files[str(path)] = path.stat().st_mtime
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as e:
                self.warnings.append(f"{path.name}: invalid JSON at line {e.lineno} col {e.colno}: {e.msg}")
                continue
            if not isinstance(data, dict) or not isinstance(data.get("weapons"), dict):
                self.warnings.append(f'{path.name}: not a roll file (needs a "weapons" object), skipped')
                continue
            self._load_file(path.name, data)
        for key in self.rolls:
            if key.startswith("@") and key[1:] not in self.groups:
                self.warnings.append(f'rolls for "@{key[1:]}" but no file defines a group "{key[1:]}"')
        return self.warnings

    def _load_file(self, name, data):
        w, gd = self.warnings, self.gamedata
        for group, members in (data.get("groups") or {}).items():
            if not isinstance(members, list):
                w.append(f'{name}: group "{group}" should be a list of weapon names')
                continue
            for m in members:
                if not (gd.family_members(str(m)) or gd.weapon_by_name(str(m))):
                    w.append(f'{name}: group "{group}": unknown weapon "{m}"')
            self.groups.setdefault(norm(group), set()).update(norm(str(m)) for m in members)
        file_bad = parse_rules(self.global_bad, gd, w, "config.json bad") + \
            parse_rules(data.get("bad"), gd, w, f"{name} bad")
        file_deal = parse_rules(self.global_dealbreakers, gd, w, "config.json dealbreakers") + \
            parse_rules(data.get("dealbreakers"), gd, w, f"{name} dealbreakers")

        for weapon_key, entries in data["weapons"].items():
            for i, entry in enumerate([entries] if isinstance(entries, dict) else entries):
                where = f"{name} > {weapon_key}[{i}]"
                pos = entry.get("positives") or {}
                weights = pos if isinstance(pos, dict) else {s: 1.0 for s in pos}
                positives = {}
                for raw, weight in weights.items():
                    stat = gd.match_stat(str(raw), cutoff=0.85)
                    if stat is None:
                        w.append(f"{where}: unknown stat '{raw}'")
                    else:
                        positives[stat] = float(weight)
                if not positives:
                    w.append(f"{where}: no valid positives, skipped")
                    continue
                roll = Roll(label=entry.get("label", ""), positives=positives,
                            negatives=_stats(entry.get("negatives"), gd, w, where),
                            required=_stats(entry.get("required"), gd, w, where),
                            bad=file_bad + parse_rules(entry.get("bad"), gd, w, where),
                            dealbreakers=file_deal + parse_rules(entry.get("dealbreakers"), gd, w, where),
                            source=name, fallback=bool(data.get("fallback", False)))
                self.rolls.setdefault(_key(weapon_key), []).append(roll)

    def groups_of(self, weapon):
        """The groups a weapon is in (a member can name the weapon or its whole riven family)."""
        names = {norm(weapon.name), norm(weapon.base_name), norm(weapon.family)}
        return sorted(g for g, members in self.groups.items() if members & names)

    def rolls_for(self, weapon):
        """The rolls a riven for this weapon is rated against (see _tiers for the order)."""
        return next((tier for tier in self._tiers(weapon) if tier), [])

    def roll_named(self, weapon, label):
        """The first roll for this weapon labelled label (ignoring case and spacing), searching every
        tier in priority order, or None."""
        wanted = norm(label or "")
        return next((r for tier in self._tiers(weapon) for r in tier if wanted and norm(r.label) == wanted), None)

    def _tiers(self, weapon):
        if weapon.name not in self._tier_cache:
            self._tier_cache[weapon.name] = self._find_tiers(weapon)
        return self._tier_cache[weapon.name]

    def _find_tiers(self, weapon):
        """Every roll that applies to this weapon, as four tiers in priority order; a riven is rated
        against the first tier that has any:

        1. your rolls for the weapon or its riven family (any variant), and for groups it's in
        2. your class fallbacks ("*rifle", "*")
        3. fallback files' rolls for the weapon (the market defaults)
        4. fallback files' class fallbacks
        """
        names = {norm(weapon.name), norm(weapon.base_name), norm(weapon.family)}
        specific = []
        for key, rolls in self.rolls.items():
            if key[:1] == "@":
                continue
            variant = None if key[:1] == "*" else self.gamedata.weapon_by_name(key)
            same_family = variant is not None and norm(variant.family) == norm(weapon.family) \
                and variant.cls == weapon.cls          # "Rubico Prime" rolls also apply to a Rubico riven
            if key in names or same_family:
                specific += [r for r in rolls if r not in specific]
        for group in self.groups_of(weapon):
            specific += [r for r in self.rolls.get("@" + group, []) if r not in specific]
        fallbacks = self.rolls.get("*" + weapon.cls, []) + self.rolls.get("*", [])
        return [[r for r in specific if not r.fallback], [r for r in fallbacks if not r.fallback],
                [r for r in specific if r.fallback], [r for r in fallbacks if r.fallback]]


def rate(ev, rolls, gamedata, rating=None):
    """The best rating of an evaluated riven against a list of rolls.

    Each positive earns its weight: 90% (type_weight) for being a wanted stat, plus 10% times how
    well it rolled (its value as a fraction of the maximum, 0.82 .. 1). That's divided by the best
    this roll allows for this many positives, so the right stats score about 98% at the worst rolls
    and 100% at the best; unwanted stats earn nothing.
    Negatives are neutral unless the roll wants that stat as a positive, or it matches a "bad" rule;
    each bad stat (and each missing required stat) multiplies the score down. A dealbreaker makes it 0.
    """
    if ev is None:
        return Rating(0.0, detail="could not read riven")
    if not rolls:
        return Rating(0.0, detail=f"no rolls listed for {ev.weapon.family}")
    settings = {**DEFAULT_RATING, **(rating or {})}
    type_w = settings["type_weight"]

    best = None
    for roll in rolls:
        tags, bad = {}, []
        top = sorted((w for w in roll.positives.values() if w > 0), reverse=True)[:len(ev.positives)]
        earned = 0.0
        for st in ev.positives:
            w = roll.positives.get(st.name, 0.0)
            earned += w * (type_w + (1 - type_w) * st.quality)
            tags[st.name] = "good" if w >= 1 else "ok" if w > 0 else "unwanted"
        score = min(earned / (sum(top) or 1.0), 1.0)

        neg = ev.negative
        if neg is not None:
            if roll.positives.get(neg.name, 0) > 0:
                tags[neg.name] = "bad"
                bad.append(f"-{neg.name}: the roll wants it positive")
            else:
                tags[neg.name] = "harmless" if neg.name in roll.negatives else "neutral"
        for st in ev.stats:
            rule = next((r for r in roll.bad if r.matches(st, gamedata.stats[st.name])), None)
            if rule and tags.get(st.name) != "bad":
                tags[st.name] = "bad"
                bad.append(f"{'-' if st.is_negative else '+'}{st.name}: listed as bad ({rule.text})")
        score *= settings["bad_stat_score"] ** len(bad)

        have = {st.name for st in ev.positives}
        missing = [req for req in roll.required if req not in have]
        score *= settings["missing_required_score"] ** len(missing)

        breaker = ""
        for st in ev.stats:
            rule = next((r for r in roll.dealbreakers if r.matches(st, gamedata.stats[st.name])), None)
            if rule:
                tags[st.name], breaker, score = "dealbreaker", rule.text, 0.0
                break

        result = Rating(round(score * 100, 1), roll, tags, missing=missing, dealbreaker=breaker, bad=bad)
        if best is None or result.score > best.score or (result.score == best.score and best.dealbreaker
                                                         and not breaker):
            best = result
    return best
