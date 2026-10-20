# Riven Reroll Helper

An overlay for Warframe's riven **Cycle** (reroll) screen. It reads the rivens off the screen, works out
how well each stat rolled, compares them with your own list of good rolls for that weapon, and shows a
percentage rating just above each card. On the cycle screen the better card gets a **BETTER** badge.

```
screenshot ──► OCR: weapon + stats ──► each stat as a ratio of its max ──┐
                                                                          ├──► rating panels
your roll JSON files ─────────────────────────────────────────────────────┘
```

**It only looks at the screen.** The overlay works entirely from screenshots. It never attaches to
Warframe, never reads or changes its memory or files, and never sends it input. To find the game it asks
Windows where the window titled "Warframe" is; set `"window_title": null` to skip even that and capture
the primary monitor. The panels are click-through windows on top of the screen, hidden from screen
capture so they never end up in recordings or get read back by the OCR.

## Setup

1. Install Python 3.10+ (python.org) and tick "Add to PATH".
2. Run Warframe in **Borderless Fullscreen** or **Windowed** (nothing can draw over exclusive fullscreen).
3. Double-click `run.bat` for the overlay, or `edit.bat` for the roll editor. The first run creates a
   Python environment in `.venv` and installs `requirements.txt` (a few minutes). Later runs start
   straight away, and it installs again on its own if `requirements.txt` changes. Delete `.venv` to start
   fresh.

OCR is Windows' built-in OCR. If it isn't available, add your language's OCR feature in *Settings > Time &
language > Language & region > your language > Language options*.

| Key | Action |
|-----|--------|
| F8  | hide / show the overlay |
| F9  | reload roll files (saving a roll file also reloads it) |
| F10 | save a snapshot to `debug/`: the screenshot, the OCR text, and the screenshot with the panels drawn on |

## What it shows

- **Above each card:** the rating, which roll it matched, how well each stat rolled, how the negative
  counts (harmless, neutral, bad or dealbreaker), and which weapon's numbers the card uses.
- **NEXT on each card panel:** the next step towards the roll, following how locking and splicing
  work (see [Trait Locking and Splicing](https://wiki.warframe.com/w/Riven_Mods#Splicing)):
  1. *Shape first.* A locked stat keeps the riven's shape (how many positives, and whether it has a
     negative), so while the shape is wrong the step is **Cycle without a lock**. The shape aimed for is
     the one that holds the most wanted stat value; one within 5% of it is kept.
  2. *Splice once.* When two stats on the riven splice into a stat the roll wants at least as much as
     the ones used up, the step is **Splice A + B**. A spliced stat keeps the better of the two rolls,
     stays locked and fixes the shape. Splicers are rare, so the advice never suggests a second one.
  3. *One lock.* Otherwise **Lock** the wanted stat that matters most (highest weight, then better
     roll) and cycle for the rest. A spliced stat doesn't count as the lock.
  4. *Values last.* Once the stats are right it's **Done**, and a low roll on an unspliced stat is only
     mentioned.

  Locked and spliced stats are recognised by the lock icon in front of them on the card. The splice
  combinations are in `riven_helper/data/splices.json`.
- **Far left, IDEAL ROLL:** the best roll for the weapon being rerolled, with the highest value each stat
  can reach on it (assuming 3 positives + 1 negative) and the negatives that roll accepts.
- **Weapon upgrade screen, IDEAL RIVEN:** a compact panel below the arcane slot with the weapon's best
  stats and their maximum values on a maxed riven. It shows the roll whose `label` matches the selected
  config tab ("CONFIG A", or the name you gave it, like "Main"; case doesn't matter), so a roll labelled
  "Main" is shown while that config is open. Without a matching roll it shows the weapon's first roll. The weapon's name is read from the screen's header,
  which works with every Warframe UI theme, light or dark.

The panels take on your UI theme's colours, read from the screen's header ("INVENTORY/MODS",
"UPGRADES/…"): its text colour for the headings and outline, its accent for the better card, and its
background for the panel. Stat names keep the riven's lavender, and every colour is adjusted where
needed to stay readable on light themes. Until a header has been seen, the default orange theme is
used.

Panels only show while the screen is at rest: the riven screen with its card, or the cycle screen with
the new or the old riven selected. While the cards move, or a dialog dims the screen, the card panels fade
out, then fade back in once everything settles. A reading is shown once it can be trusted (two readings
agree). Between readings the cards are followed by image matching, so OCR runs only once per reroll.

## Roll files

Every `.json` file in `rolls/` is loaded, and they're all used together. Use `roll_files` in
`config.json` to load files from elsewhere (files, folders or globs).

The easiest way to write them is the **editor** (`edit.bat`). It has tabs for the rolls, weapon groups and
file-wide rules, autocompletes weapon and stat names, and checks the file with the same loader the overlay
uses when you save.

By hand, a file looks like this (`tests/fixtures/` has two more examples):

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

- **Weapon keys:** a weapon name (it covers the whole riven family, so `Rubico` also covers Rubico Prime),
  `@group` for a group from any roll file, or a class fallback: `*rifle`, `*shotgun`, `*pistol`,
  `*melee`, `*archgun`, or `*` for everything.
- A key can hold **one roll or a list**. The riven is scored against each and the best score is shown.
- **positives:** the stats you want, as a list or as `{stat: weight}` (1 = ideal, 0.5 = nice to have).
- **negatives** *(optional)*: negatives you know are harmless (shown as such and listed on IDEAL ROLL).
- **required** *(optional)*: stats the riven must have.
- **bad** / **dealbreakers** *(optional)*: rules, on a roll, at the top of a file (for every roll in it)
  or in `config.json` (for every file).
- Stat names match loosely: `Critical Damage`, `crit damage` and `CD` all work. `run.bat --check` lists
  every roll that loaded and anything it couldn't read.

Rules are strings. The number is what the card shows: 100 means 100%, 25 means ×1.25 (or ×0.75 as a
negative) for faction damage, and flat stats compare as shown.

| Rule | Matches |
|------|---------|
| `"-Multishot"` | Multishot as the negative |
| `"+Zoom"` | Zoom as a positive |
| `"Impact"` | Impact either way |
| `"-Damage > 100"` | negative Damage over 100% (`>`, `>=`, `<`, `<=`) |

### Market defaults

`rolls/warframe_market.json` covers every riven weapon on warframe.market. It's built from the top 25%
of riven listings by price: how often each stat appears (most common = 1.0), and the negatives buyers
accept. It's a **fallback** file (`"fallback": true`), so for each weapon the first of these with any
rolls is used:

1. your rolls for the weapon or a group it's in
2. your class fallbacks (`*rifle`, `*`)
3. the market roll for the weapon
4. the market class fallback

Put your own rolls in separate files, since refreshing the market file overwrites it:

```bash
.venv\Scripts\python tools\build_market_rolls.py
```

### The rating

```
rating = Σ weight × (0.9 + 0.1 × quality)  ÷  (sum of the N highest weights in the roll)
         × 0.5  for each bad stat
         × 0.25 for each required stat that's missing
         = 0    if a dealbreaker matches                 N = number of positives on the riven
```

90% is for having the right stat types and 10% for how well they rolled. **Quality** is the stat's value
divided by the highest value it could have. Negatives are neutral unless the roll wants that stat as a
positive, or a `bad` rule matches it. The three numbers are `type_weight`, `bad_stat_score` and
`missing_required_score` in `config.json`.

## Riven math

From the [Warframe Wiki](https://wiki.warframe.com/w/Riven_Mods):

```
value = b × 10 × (rank + 1) × disposition × L × W        W from 0.9 to 1.1
```

- `b` is the stat's base value for the weapon class (`riven_helper/data/stats.json`).
- `L` depends on the layout: 2 positives 0.99, 2 + negative 1.2375 (negative 0.495), 3 positives 0.75,
  3 + negative 0.9375 (negative 0.75).
- Dispositions (`riven_helper/data/dispositions.json`) come from the official game export. After a
  disposition change, rebuild them:

```bash
.venv\Scripts\python tools\build_dispositions.py
```

**Variants.** A riven is named after its family's base weapon but fits every variant (Plinx, Tenet
Plinx). The card's numbers are for the weapon in its **FITS IN** panel, so that weapon's disposition is
used. If FITS IN can't be read, the base weapon is tried first, then the variants.

**Rank** isn't shown on screen, so each rank is tried, from 8 down, until every stat lands inside the
0.9–1.1 range. If none fits, the panel says so. That usually means an OCR misread or an out-of-date
disposition.

## config.json

| Key | Meaning |
|-----|---------|
| `roll_files` | Roll files, folders or globs (default `["rolls"]`) |
| `rating` | `type_weight` 0.9, `bad_stat_score` 0.5, `missing_required_score` 0.25 |
| `bad` / `dealbreakers` | Rules for every roll in every file, e.g. `["-Damage > 100"]` |
| `window_title` | The game window to watch; `null` captures the primary monitor |
| `font_size` | Panel text size at 1080p (it scales with the game window) |
| `hotkeys` | `toggle`, `reload`, `snapshot` (F1–F12, Insert, Home, End, Pause, ScrollLock) |

## The code

`riven_helper/`, in the order data flows through it:

| File | What it does |
|------|--------------|
| `capture.py` | Finds the game window, takes screenshots, runs Windows OCR |
| `parse.py` | OCR lines → riven cards (title, stats, FITS IN) |
| `upgrade_screen.py` | Recognises the upgrade screen and reads its weapon header |
| `gamedata.py` | Stats, weapons, dispositions and riven families |
| `riven_math.py` | The riven formula: rank, roll and quality of each stat |
| `rolls.py` | Loads roll files and rates a riven against them |
| `advice.py` | The NEXT step: cycle, lock, splice or done |
| `analyze.py` | Screenshot → rated cards, re-reading doubtful ones |
| `session.py` | Live loop: when to read, card tracking, waiting for the screen to settle |
| `tracker.py` | Follows cards between reads by image matching |
| `panel_text.py` | What each panel says |
| `theme.py` | Reads the UI theme off the screen; the panel colours for it |
| `style.py` | Draws panels in the game's style |
| `layout.py` | Where each panel goes |
| `overlay_state.py` | Which panels are showing, and their fades |
| `winpanel.py` | Click-through, capture-hidden windows that show the panels |
| `app.py` | Ties it together: worker thread, hotkeys, snapshots |
| `editor.py`, `editor_model.py` | The roll editor (window, and the file model behind it) |
| `config.py`, `__main__.py` | Settings, and the command line |

## Testing

- **Nothing shows up, or only sometimes:** check the console window. It says which OCR language is in
  use (English is best, since the game's text is English) and whether the game is being watched or
  paused because it isn't the active window. Then press F10 on the cycle screen and look at
  `debug/*.annotated.png` and `*.ocr.json` to see what was read.
- **Rate a screenshot** without the game:

```bash
run.bat --image debug\20261019-120000.png --out result.png
```

- **Replay a recording** through the same live logic, to check how panels behave during transitions:

```bash
.venv\Scripts\python tools\replay_video.py recording.mp4 --out replay.mp4
```

- **Unit tests** (`tests/`, one file per topic; `tests/make_sample.py` draws synthetic screens for them):

```bash
.venv\Scripts\python -m unittest discover tests
```
