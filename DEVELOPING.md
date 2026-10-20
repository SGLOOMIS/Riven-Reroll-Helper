# Riven Reroll Helper: technical notes

How it works, the roll file format, and how to work on it. The player guide is [README.md](README.md).

```
screenshot ──► OCR: weapon + stats ──► each stat as a ratio of its max ──┐
                                                                          ├──► rating panels
your roll JSON files ─────────────────────────────────────────────────────┘
```

**Screen only.** Everything works from screenshots (`mss`) and Windows' built-in OCR (`winrt`). To
find the game it asks Windows where the window titled "Warframe" is; `"window_title": null` skips even
that and captures the primary monitor. Hotkeys are read with `GetAsyncKeyState`. The panels are
click-through layered windows, hidden from screen capture so they never end up in recordings or get read
back by the OCR.

## Running it

`Riven Helper.bat` runs `setup.bat` (find or install Python 3.10+, create `.venv`, install
`requirements.txt` when it changes), then starts `pythonw -m riven_helper`: the roll editor, with the
overlay running inside its event loop. Other ways to run it:

```bash
.venv\Scripts\python -m riven_helper --overlay
```

only the overlay, printing everything it does to the console (`--edit [file]`: only the editor;
`--check`: list every roll that loaded and any problems; `--config` / `--rolls`: other settings or roll
files).

## What the panels show, in detail

- **Card panels:** the rating, which roll it matched, each stat's roll quality, how the negative counts
  (harmless, neutral, bad, dealbreaker), and the next step (`advice.py`).
- **NEXT** follows how [trait locking and splicing](https://wiki.warframe.com/w/Riven_Mods#Splicing) work:
  1. *Shape first.* A locked stat keeps the riven's shape (how many positives, and whether it has a
     negative), so while the shape is wrong the step is **Cycle without a lock**. The shape aimed for holds
     the most wanted stat value (its L multiplier times the best weights it has room for); one within 5%
     of the best is kept.
  2. *Splice once.* When two stats on the riven splice (`data/splices.json`) into a stat of the ideal
     roll, the step is **Splice A + B**, unless that would keep less than 80% of the spliced stat's
     maximum. Into another wanted stat only when it's wanted at least as much as the stats used up. A
     spliced stat keeps the better of the two rolls, stays locked and fixes the shape; the advice never
     suggests a second splice.
  3. *One lock.* Otherwise **Lock** the stat that matters most: the highest weight, then the better roll.
     A splice ingredient counts as the stat it splices into, and comes first among equals.
  4. *Values last.* Once the stats are right it's **Done**; a low roll is only mentioned.
- **BETTER** (cycle screen) goes to the card further towards the ideal roll (`advice.progress`): when a
  wanted stat only comes from splicing, a riven with it spliced, then one that can splice it now, then
  one with a good ingredient waiting for its partner; otherwise the higher rating. With next-step advice
  off it's simply the higher rating.
- **Next-cycle odds** (one card on screen, `odds.py`): a few thousand simulated cycles keeping the locked
  and spliced stats (and with them the shape), each rated against the same rolls. The game doesn't
  publish its odds, so it assumes the four shapes are equally likely, stats are drawn evenly from the
  weapon class's pool, and rolls are spread evenly over 90–110%.
- **IDEAL ROLL** (riven screens) and **IDEAL RIVEN** (upgrade screen): the roll's best stats at their
  maximum, assuming 3 positives + 1 negative. On the upgrade screen, the roll whose `label` matches the
  selected config tab (found by the bar under it) is shown.
- **Colours** (`theme.py`): the screen header's text colour for headings and outline, its accent for the
  better card, and the LOCK TRAIT / CONFIRM button fill for the background; Vitruvian (the game's
  default) until a header has been seen.

Panels only show while the screen is at rest. While the cards move or a dialog dims the screen, they fade
out; a reading is shown once it can be trusted (two readings agree). Between readings the cards are
followed by image matching, so OCR runs about once per reroll.

## Roll files

Every `.json` in `rolls/` is loaded (plus anything `roll_files` in `config.json` lists). Git ignores all
of them except `warframe_market.json`, so players' own rolls stay local.

```json
{
  "groups": { "Crit snipers": ["Rubico", "Vectis", "Lanka"] },
  "bad": ["-Status Chance"],
  "dealbreakers": ["-Damage > 100"],
  "weapons": {
    "@Crit snipers": { "positives": ["Critical Damage", "Multishot", "Critical Chance"] },
    "Rubico": [
      {
        "label": "Crit sniper",
        "positives": { "Critical Damage": 1, "Multishot": 1, "Critical Chance": 0.8, "Damage": 0.7 },
        "required": ["Critical Damage"],
        "negatives": ["Zoom", "Impact", "Puncture"],
        "bad": ["+Zoom"],
        "dealbreakers": ["-Multishot"]
      }
    ],
    "*rifle": { "positives": ["CD", "MS", "CC"] }
  }
}
```

- **Weapon keys:** a weapon name (covering its whole riven family: `Rubico` also covers Rubico Prime),
  `@group`, or a class fallback `*rifle`, `*shotgun`, `*pistol`, `*melee`, `*archgun`, or `*`.
- A key holds **one roll or a list**; the best-scoring roll is shown. `label` names it (also matched
  against the upgrade screen's config tab).
- **positives:** a list, or `{stat: weight}` (1 = ideal, 0.5 = nice to have). **negatives:** ones known
  to be harmless. **required:** stats the riven must have. **bad** / **dealbreakers:** rules, on a roll,
  at the top of a file (every roll in it), or in `config.json` (every file).
- Stat names match loosely (`Critical Damage`, `crit damage`, `CD`).

Rules are strings: `"-Multishot"` (as the negative), `"+Zoom"` (as a positive), `"Impact"` (either way),
`"-Damage > 100"` (`>`, `>=`, `<`, `<=`). The number is what the card shows: 100 means 100%, 25 means
×1.25 (×0.75 as a negative) for faction damage; flat stats compare as shown.

**Market defaults.** `rolls/warframe_market.json` is built from the top 25% of warframe.market riven
listings by price: how often each stat appears (most common = 1.0), and the negatives buyers accept. It's
a fallback file (`"fallback": true`), so for each weapon the first of these with any rolls is used: your
rolls for the weapon or its groups, your class fallbacks, the market roll, the market class fallback.
Refresh it (downloads are cached in `tools/.market_cache`):

```bash
.venv\Scripts\python tools\build_market_rolls.py
```

## The rating

```
rating = Σ weight × (0.9 + 0.1 × quality)  ÷  (sum of the N highest weights in the roll)
         × 0.5  for each bad stat
         × 0.25 for each required stat that's missing
         = 0    if a dealbreaker matches                 N = number of positives on the riven
```

90% for the right stat types, 10% for how well they rolled. **Quality** is the stat's value divided by
the highest it could have. Negatives are neutral unless the roll wants that stat as a positive or a
`bad` rule matches it. The three numbers are `type_weight`, `bad_stat_score` and `missing_required_score`
in `config.json`.

## Riven math

From the [Warframe Wiki](https://wiki.warframe.com/w/Riven_Mods):

```
value = b × 10 × (rank + 1) × disposition × L × W        W from 0.9 to 1.1
```

- `b`: the stat's base value for the weapon class (`riven_helper/data/stats.json`).
- `L`: 2 positives 0.99, 2 + negative 1.2375 (negative 0.495), 3 positives 0.75, 3 + negative 0.9375
  (negative 0.75).
- Dispositions (`riven_helper/data/dispositions.json`) come from the official game export. After a
  disposition change: `.venv\Scripts\python tools\build_dispositions.py`.
- **Variants:** a riven is named after its family's base weapon but fits every variant; the card's
  numbers are for the weapon under **FITS IN**, so that weapon's disposition is used.
- **Rank** isn't shown, so each rank is tried from 8 down until every stat fits 0.9–1.1. If none fits,
  the panel says so (usually an OCR misread or an out-of-date disposition).

## config.json

| Key | Meaning |
|-----|---------|
| `roll_files` | Roll files, folders or globs (default `["rolls"]`) |
| `rating` | `type_weight` 0.9, `bad_stat_score` 0.5, `missing_required_score` 0.25 |
| `bad` / `dealbreakers` | Rules for every roll in every file, e.g. `["-Damage > 100"]` |
| `window_title` | The game window to watch; `null` captures the primary monitor |
| `font_size` | Panel text size at 1080p (it scales with the game window) |
| `hotkeys` | `toggle`, `reload`, `snapshot` (F1–F12, Insert, Home, End, Pause, ScrollLock) |
| `next_step` | NEXT advice, and BETTER by progress towards the ideal roll (false: BETTER by rating) |
| `upgrade_overlay` | IDEAL RIVEN on weapon upgrade screens |
| `config_rolls` | On the upgrade screen, the roll labelled like the selected config tab |
| `editor_theme` | The roll editor's colours: a UI theme's name (`riven_helper/data/themes.json`) |

The editor's Settings tab writes these; a running overlay notices the file change and applies them.

## The code

`riven_helper/`, in the order data flows through it:

| File | What it does |
|------|--------------|
| `capture.py` | Finds the game window, takes screenshots, runs Windows OCR |
| `parse.py` | OCR lines → riven cards (title, stats, lock icons, FITS IN) |
| `upgrade_screen.py` | Recognises the upgrade screen; reads its weapon header and config tab |
| `gamedata.py` | Stats, weapons, dispositions and riven families |
| `riven_math.py` | The riven formula: rank, roll and quality of each stat |
| `rolls.py` | Loads roll files and rates a riven against them |
| `advice.py` | The NEXT step, and progress towards the ideal roll (BETTER) |
| `odds.py` | The chance that the next cycle rates higher |
| `analyze.py` | Screenshot → rated cards, re-reading doubtful ones |
| `session.py` | Live loop: when to read, card tracking, waiting for the screen to settle |
| `tracker.py` | Follows cards between reads by image matching |
| `panel_text.py` | What each panel says |
| `theme.py` | Reads the UI theme off the screen; the panel colours for it |
| `style.py` | Draws panels in the game's style |
| `layout.py` | Where each panel goes |
| `overlay_state.py` | Which panels are showing, and their fades |
| `winpanel.py` | Click-through, capture-hidden windows that show the panels |
| `app.py` | The overlay: worker thread, hotkeys, snapshots, settings reload |
| `editor.py`, `editor_model.py` | The roll editor (window, and the file model behind it) |
| `config.py`, `__main__.py` | Settings, and the command line |

## Testing

```bash
.venv\Scripts\python -m unittest discover tests
```

One file per topic in `tests/`, using OCR saved from real snapshots and screenshots in
`tests/fixtures/` (`tests/make_sample.py` draws synthetic screens). Also useful:

- **Rate a screenshot** without the game (and draw the panels on it):
  `.venv\Scripts\python -m riven_helper --image debug\20261019-120000.png --out result.png`
- **Replay a recording** through the same live logic, to check panels during transitions:
  `.venv\Scripts\python tools\replay_video.py recording.mp4 --out replay.mp4`

## Making a release

```bash
.venv\Scripts\python tools\make_release.py
```

builds `dist/Riven-Helper-<date>.zip` with only what players need (the program, `Riven Helper.bat`,
`setup.bat`, the market defaults, a fresh `config.json`, the README): no tests, tools, snapshots or
personal roll files. Upload it as a GitHub release; the README's download link points there.
