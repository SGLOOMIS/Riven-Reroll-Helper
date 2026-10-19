"""Generate a default roll list (rolls/warframe_market.json) from warframe.market riven auctions.

For every riven weapon on warframe.market, this downloads the highest-priced riven listings, takes
the top quarter by price, and counts how often each stat shows up on them (weighted by price):

  * positives: weight = how often the stat appears on top-priced rivens, relative to the most
    common one (1.0). Stats below 0.3 are dropped.
  * negatives: the negatives that show up on top-priced rivens are the ones buyers don't mind.

It also builds "*rifle", "*shotgun", "*pistol" and "*melee" fallbacks for weapons with too few
listings, by averaging the weapons of that class.

    .venv\\Scripts\\python tools\\build_market_rolls.py            (about 8 minutes the first time)
    .venv\\Scripts\\python tools\\build_market_rolls.py --refresh  (ignore the 24 h download cache)

The output is a normal roll file: edit it, or copy entries into your own files. Your own files
are used alongside it, and the best-matching roll wins.
"""

import argparse
import json
import math
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from riven_helper.gamedata import GameData  # noqa: E402

API = "https://api.warframe.market"
CACHE = ROOT / "tools" / ".market_cache"
CLASS_OF = {"rifle": "rifle", "shotgun": "shotgun", "pistol": "pistol", "melee": "melee", "zaw": "melee"}


class Market:
    def __init__(self, platform, delay=1.0):
        self.headers = {"User-Agent": "RivenRerollHelper/1.0 (personal riven rating tool)",
                        "Language": "en", "Platform": platform, "Crossplay": "true", "Accept": "application/json"}
        self.delay = delay
        self.last = 0.0

    def get(self, path, **params):
        url = f"{API}/{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        for attempt in range(8):
            wait = self.delay - (time.time() - self.last)     # stay well under warframe.market's rate limit
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=self.headers), timeout=60) as r:
                    return json.load(r)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504):
                    retry_after = e.headers.get("Retry-After")
                    pause = float(retry_after) if retry_after and retry_after.isdigit() else min(5 * 2 ** attempt, 120)
                    print(f"  HTTP {e.code}, waiting {pause:.0f}s", flush=True)
                    time.sleep(pause)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                time.sleep(min(5 * 2 ** attempt, 120))
        raise RuntimeError(f"giving up on {url}")


def listings_for(market, slug, max_age_hours, refresh):
    """Price + attributes of open riven listings for one weapon, cached on disk."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{slug}.json"
    if not refresh and path.exists() and time.time() - path.stat().st_mtime < max_age_hours * 3600:
        return json.loads(path.read_text(encoding="utf-8"))
    data = market.get("v1/auctions/search", type="riven", weapon_url_name=slug, sort_by="price_desc")
    out = []
    for a in data.get("payload", {}).get("auctions", []):
        if a.get("closed") or not a.get("visible", True):
            continue
        price = a.get("buyout_price") or a.get("starting_price")
        if not price or price <= 0:
            continue
        out.append({"price": price,
                    "attrs": [[x["url_name"], bool(x["positive"])] for x in a["item"].get("attributes", [])]})
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


def analyse(listings, attr_names, top_fraction=0.25, min_top=5):
    """Return (positive shares, negative shares, top count, median top price) or None."""
    listings = sorted(listings, key=lambda l: l["price"], reverse=True)
    top = listings[:max(min_top, math.ceil(len(listings) * top_fraction))]
    median = statistics.median(l["price"] for l in top)
    # Cap weights so one troll listing at 99,999p can't dominate.
    weights = [min(l["price"], 3 * median) for l in top]

    pos, neg, neg_total = {}, {}, 0.0
    for l, w in zip(top, weights):
        stats = [(attr_names.get(slug), positive) for slug, positive in l["attrs"]]
        if any(name is None for name, _ in stats):
            continue
        for name, positive in stats:
            if positive:
                pos[name] = pos.get(name, 0.0) + w
        negs = [name for name, positive in stats if not positive]
        if negs:
            neg_total += w
            for name in negs:
                neg[name] = neg.get(name, 0.0) + w
    total = sum(weights)
    if not pos or total == 0:
        return None
    pos = {k: v / total for k, v in pos.items()}
    neg = {k: v / neg_total for k, v in neg.items()} if neg_total else {}
    return pos, neg, len(top), median


def make_roll(pos, neg, min_weight=0.3, max_positives=6, min_neg_share=0.08):
    peak = max(pos.values())
    positives = {k: round(v / peak * 20) / 20 for k, v in sorted(pos.items(), key=lambda kv: -kv[1])}
    positives = dict(list({k: w for k, w in positives.items() if w >= min_weight}.items())[:max_positives])
    negatives = {}
    if neg:
        npeak = max(neg.values())
        for k, v in sorted(neg.items(), key=lambda kv: -kv[1]):
            if v >= min_neg_share and k not in positives:
                negatives[k] = round(0.8 + 0.2 * v / npeak, 2)
    return {"positives": positives, "negatives": negatives}


def json_key(name, riven_type, gamedata):
    """The weapon key to write, matching riven_helper/data/dispositions.json naming."""
    if gamedata.weapon_by_name(name) or riven_type == "kitgun":
        return name
    if riven_type != "melee" and gamedata.weapon_by_name(f"{name} (Primary)"):
        return f"{name} (Primary)"
    return name


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--out", default=str(ROOT / "rolls" / "warframe_market.json"))
    p.add_argument("--platform", default="pc", choices=["pc", "ps4", "xbox", "switch", "mobile"])
    p.add_argument("--min-listings", type=int, default=10, help="weapons with fewer listings use the class fallback")
    p.add_argument("--max-age-hours", type=float, default=24)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--limit", type=int, help="only process the first N weapons (testing)")
    args = p.parse_args()

    gamedata = GameData()
    market = Market(args.platform)
    attr_names = {}
    for a in market.get("v2/riven/attributes")["data"]:
        canonical = gamedata.match_stat(a["i18n"]["en"]["name"], cutoff=0.85)
        if canonical:
            attr_names[a["slug"]] = canonical
        else:
            print(f"warning: no matching stat for market attribute {a['slug']!r}")

    weapons = sorted(market.get("v2/riven/weapons")["data"], key=lambda w: w["i18n"]["en"]["name"])
    if args.limit:
        weapons = weapons[:args.limit]

    out, per_class, skipped = {}, {}, []
    for i, w in enumerate(weapons, 1):
        name, slug, rtype = w["i18n"]["en"]["name"], w["slug"], w["rivenType"]
        listings = listings_for(market, slug, args.max_age_hours, args.refresh)
        print(f"[{i}/{len(weapons)}] {name}: {len(listings)} listings", flush=True)
        if len(listings) < args.min_listings:
            skipped.append(name)
            continue
        result = analyse(listings, attr_names)
        if not result:
            skipped.append(name)
            continue
        pos, neg, n_top, median = result
        out[json_key(name, rtype, gamedata)] = make_roll(pos, neg)
        if rtype in CLASS_OF:
            peak = max(pos.values())
            per_class.setdefault(CLASS_OF[rtype], []).append(({k: v / peak for k, v in pos.items()}, neg))

    wildcards = {}
    for cls, entries in sorted(per_class.items()):
        n = len(entries)
        pos_keys = set().union(*(e[0] for e in entries))
        neg_keys = set().union(*(e[1] for e in entries))
        pos = {k: sum(e[0].get(k, 0) for e in entries) / n for k in pos_keys}
        neg = {k: sum(e[1].get(k, 0) for e in entries) / n for k in neg_keys}
        wildcards[f"*{cls}"] = make_roll(pos, neg)

    doc = {
        "name": "warframe.market defaults",
        # Only used for a weapon when none of your own roll files has a roll for it.
        "fallback": True,
        "_generated": f"{date.today().isoformat()} by tools/build_market_rolls.py ({args.platform})",
        "_method": "Top 25% of riven listings by price per weapon. Positive weight = price-weighted share of "
                   "those rivens carrying the stat, relative to the most common stat. Negatives listed are the "
                   "ones that appear on top-priced rivens (score 0.8-1.0 by how often).",
        "weapons": {**wildcards, **dict(sorted(out.items()))},
    }
    Path(args.out).write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(out)} weapons + {len(wildcards)} class fallbacks to {args.out}")
    if skipped:
        print(f"{len(skipped)} weapons had fewer than {args.min_listings} listings and use the class fallback.")


if __name__ == "__main__":
    main()
