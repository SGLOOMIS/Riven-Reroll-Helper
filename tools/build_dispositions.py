"""Rebuild riven_helper/data/dispositions.json.

Disposition multipliers come from the official game data export (via the
WFCD warframe-items package, which is also what the Warframe Wiki's
"Riven Mods/Weapon Dispos" page is built from). Kitgun chambers have
separate primary/secondary dispositions that the export doesn't carry, so
those are taken from the wiki (KITGUN_CHAMBERS below).

Riven families (which weapons share a riven, and the riven's name) come from
warframe.market's riven weapon list. A riven is named after its family's base
weapon and its card shows that weapon's numbers, but it also fits the
family's variants: a Rubico riven works on Rubico Prime, while Dex Nikana and
Kuva Bramma have rivens of their own.

Run after a Prime Access / disposition update:
    python tools/build_dispositions.py
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

CDN = "https://cdn.jsdelivr.net/npm/@wfcd/items@latest/data/json/{}.json"
MARKET_RIVENS = "https://api.warframe.market/v2/riven/weapons"
OUT = Path(__file__).resolve().parent.parent / "riven_helper" / "data" / "dispositions.json"

# From https://wiki.warframe.com/w/Riven_Mods/Weapon_Dispos
KITGUN_CHAMBERS = {
    "Catchmoon": {"primary": 1.1, "secondary": 0.75},
    "Gaze": {"primary": 1.1, "secondary": 1.05},
    "Rattleguts": {"primary": 1.0, "secondary": 1.0},
    "Tombfinger": {"primary": 1.0, "secondary": 0.9},
    "Sporelacer": {"primary": 1.15, "secondary": 0.6},
    "Vermisplicer": {"primary": 0.9, "secondary": 1.15},
}

# Weapons with a separate riven per mode (from warframe.market, which matches the game export).
DUAL_MODE = {
    "Vinquibus": {"Primary": (0.6, "rifle"), "Melee": (0.5, "melee")},
}

# Companion weapons use the riven class of the weapon they behave like.
COMPANION_CLASS = {
    "Sweeper": "shotgun", "Sweeper Prime": "shotgun",
    "Burst Laser": "pistol", "Burst Laser Prime": "pistol", "Prisma Burst Laser": "pistol",
    "Deconstructor": "melee", "Deconstructor Prime": "melee",
    "Akaten": "melee", "Batoten": "melee", "Lacerten": "melee",
}

# Variant words. Used to find which riven family a weapon belongs to when it
# isn't a riven name itself (e.g. "Kuva Kohm" -> "Kohm").
PREFIXES = ["Prisma ", "Mk1-", "MK1-", "Kuva ", "Tenet ", "Coda ", "Dex ", "Vaykor ", "Synoid ",
            "Rakta ", "Sancti ", "Secura ", "Telos ", "Carmine ", "Ceti ", "Mutalist ", "Proboscis "]
SUFFIXES = [" Prime", " Vandal", " Wraith"]


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def strip_variants(name):
    """All names reachable by removing variant words, fewest removals first."""
    seen, frontier = [name], [name]
    while frontier:
        nxt = []
        for n in frontier:
            for p in PREFIXES:
                if n.startswith(p):
                    nxt.append(n[len(p):])
            for sfx in SUFFIXES:
                if n.endswith(sfx):
                    nxt.append(n[: -len(sfx)])
        frontier = [n for n in nxt if n not in seen]
        seen += frontier
    return seen


def family_of(name, riven_names, weapon_names):
    """The riven name for this weapon. riven_names: norm(name) -> market spelling."""
    base = name.split(" (")[0]                      # "Catchmoon (Primary)" -> "Catchmoon"
    for candidate in strip_variants(base):
        if norm(candidate) in riven_names:
            return riven_names[norm(candidate)]
    # Not on warframe.market (arch-guns, arch-melee, companions): strip variant
    # words only if that lands on a real weapon.
    for candidate in strip_variants(base)[1:]:
        if norm(candidate) in weapon_names:
            return candidate
    return base


def fetch_riven_names():
    req = urllib.request.Request(MARKET_RIVENS, headers={"User-Agent": "RivenRerollHelper/1.0", "Language": "en"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)["data"]
    return {norm(w["i18n"]["en"]["name"].split(" (")[0]): w["i18n"]["en"]["name"].split(" (")[0] for w in data}


def fetch(category):
    with urllib.request.urlopen(CDN.format(category), timeout=60) as r:
        return json.load(r)


def main():
    weapons = {}

    def add(name, dispo, cls, wtype):
        weapons[name] = {
            "disposition": round(float(dispo), 3),
            "class": cls,
            "type": wtype,
        }

    for item in fetch("Primary"):
        if item.get("omegaAttenuation") and item.get("type") != "Pistol":
            cls = "shotgun" if item.get("type") == "Shotgun" else "rifle"
            add(item["name"], item["omegaAttenuation"], cls, item.get("type"))
    for item in fetch("Secondary"):
        if item.get("omegaAttenuation"):
            add(item["name"], item["omegaAttenuation"], "pistol", item.get("type"))
    for item in fetch("Melee"):
        if not item.get("omegaAttenuation"):
            continue
        if item.get("type") == "Zaw Component":
            # Only strikes ("Tip"/"Tips" parts) carry the riven; skip PvP duplicates and other parts.
            if not re.search(r"/Tips?/", item["uniqueName"]) or "PvP" in item["uniqueName"]:
                continue
            add(item["name"], item["omegaAttenuation"], "melee", "Zaw")
        else:
            add(item["name"], item["omegaAttenuation"], "melee", "Melee")
    for item in fetch("Arch-Gun"):
        if item.get("omegaAttenuation"):
            add(item["name"], item["omegaAttenuation"], "archgun", "Arch-Gun")
    for item in fetch("Arch-Melee"):
        if item.get("omegaAttenuation"):
            add(item["name"], item["omegaAttenuation"], "melee", "Arch-Melee")
    for item in fetch("SentinelWeapons"):
        if item.get("omegaAttenuation"):
            add(item["name"], item["omegaAttenuation"], COMPANION_CLASS.get(item["name"], "rifle"), "Companion")

    for chamber, d in KITGUN_CHAMBERS.items():
        weapons[f"{chamber} (Primary)"] = {"disposition": d["primary"], "class": "rifle",
                                           "type": "Kitgun", "family": chamber}
        weapons[f"{chamber} (Secondary)"] = {"disposition": d["secondary"], "class": "pistol",
                                             "type": "Kitgun", "family": chamber}
        weapons.pop(chamber, None)

    for name, modes in DUAL_MODE.items():
        weapons.pop(name, None)
        for mode, (d, cls) in modes.items():
            weapons[f"{name} ({mode})"] = {"disposition": d, "class": cls, "type": mode, "family": name}

    riven_names = fetch_riven_names()
    weapon_names = {norm(n.split(" (")[0]) for n in weapons}
    for name, w in weapons.items():
        w["family"] = family_of(name, riven_names, weapon_names)
        # The riven card shows the base weapon's numbers; variants are scaled from it.
        w["card"] = norm(name.split(" (")[0]) == norm(w["family"])

    # A riven family shares one riven type, so variants take the base weapon's class
    # (the export calls Coda Bubonico a rifle although Bubonico rivens use shotgun values).
    by_family = {}
    for name, w in weapons.items():
        by_family.setdefault(w["family"], []).append(w)
    for members in by_family.values():
        cards = [w for w in members if w["card"]]
        if len(cards) == 1:
            for w in members:
                w["class"] = cards[0]["class"]

    out = {
        "_source": "Official game export via WFCD warframe-items; kitgun chambers from wiki.warframe.com/w/Riven_Mods/Weapon_Dispos; "
                   "riven families from warframe.market",
        "_fields": "family = the riven this weapon uses (named after the base weapon); card = the riven card shows this "
                   "weapon's numbers (the family's base weapon; both slots for kitguns)",
        "weapons": dict(sorted(weapons.items())),
    }
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(weapons)} weapons to {OUT}")


if __name__ == "__main__":
    sys.exit(main())
