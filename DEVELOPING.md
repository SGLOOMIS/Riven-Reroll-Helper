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

Players get `Riven Helper.exe` (see *Making a release*). From the source, `Riven Helper.bat` runs `setup.bat` (find or install Python 3.12+, create `.venv`, install
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
- **NEXT** (`flow.py`) follows a fixed reroll strategy, a flowchart, for the roll the riven matched:
  0. *An unwanted spliced stat* (one the roll doesn't want) stays for good, so the riven could never get
     there with it: **Unlock** it (and any lock) and cycle, starting the riven over.
  1. *Shape first.* A locked stat keeps the riven's shape (how many positives, and whether it has a
     negative), so while the shape is wrong the step is **Cycle without a lock**. The shape aimed for holds
     the most wanted stat value (its L multiplier times the best weights it has room for); one within 5%
     of the best is accepted.
  2. *A spliced stat* (when the roll wants one, Blast, and the riven has none spliced): with no trait of
     it (Heat, Cold) rolled over X (`splice_min`, 50%), **Lock** the most useful stat; with one over X,
     **Lock** that trait and wait for its partner; with both, one over X, **Splice A + B** (the spliced
     stat stays locked for free, and keeps the shape).
  3. *Wanted stats.* Otherwise **Lock** the most wanted stat on the riven (the highest weight, Required
     first, the current lock kept between equals); with none, the most useful stat.
  4. **Done** once the riven rates `kuva_target` or more, at any point.

  "The most useful stat": a harmless negative (it keeps the shape, negative included, and leaves every
  positive slot free), then a wanted stat, then a trait of the spliced stat, then the best-rolled other
  stat. Each step says what it's cycling for and the Kuva the whole strategy is expected to take from
  here. With `kuva_target` 0, NEXT goes by simpler rules (`advice.py`: shape, one splice, one lock).
- **BETTER** (cycle screen) goes to the card the strategy is expected to finish for less Kuva (a card
  rated `kuva_target` already: 0); within 5% of each other, neither. With no target (0) it goes to the
  card further towards the ideal roll (`advice.progress`): when a wanted stat only comes from splicing,
  a riven with it spliced, then one that can splice it now, then one with a good ingredient waiting for
  its partner; otherwise the higher rating. With next-step advice off it's simply the higher rating.
- **Next-cycle odds** (one card on screen, once it rates `kuva_target`; `flow.chance_of_better`): the
  chance the next cycle, keeping the locked and spliced stats (and with them the shape), rates higher
  against the same roll, worked out exactly like the Kuva below. The game doesn't publish its odds, so
  it assumes the four shapes are equally likely, stats are drawn evenly from the weapon class's pool, and
  rolls are spread evenly over 90–110%. (`odds.py` simulates the same cycles; the tests check the two
  agree.)
- **Nothing waits on a plan:** in the overlay a planning thread of its own (`App.planner`) works the plans
  out (`flow.warm`) after the panels are up, then draws them again; neither the screen reading nor the
  drawing waits for it, and the panels only use plans already worked out. Then it works out the plans for
  the weapon's other rolls too (`flow.warm_ahead`), so the cycle-roll hotkey (F7), which re-rates the cards
  already read rather than reading the screen again, finds them ready.
- **Expected Kuva** (`flow.py`), worked out exactly, not simulated. Each cycle keeps the shape and the
  locked and spliced stats and draws the rest as above. Stats that play the same part for the roll (all
  the unwanted ones, all the harmless negatives, ...) are counted together, so the chance of every kind of
  outcome is a count of combinations, and the chance an outcome rates the target or more is an exact
  integral over the rolls (a sum of evenly spread values; rules judged by value, like a dealbreaker on
  -Damage ≥ 100%, split it where they change). The strategy then makes a small Markov chain, each state
  what the next cycle keeps; the expected Kuva is solved from it, each cycle costing its base rate (doubled
  with a stat that isn't spliced locked), rising cycle by cycle to 3,500. A stat locked in a later cycle
  (and a trait the splice keeps) is counted by third of its range, each its own state; the stats on screen
  at their own rolls. Checked against playing the strategy out thousands of times (`tests/test_flow.py`).
  When the strategy can't reach the target the line says so. Speed: most outcomes are ruled out by a quick
  upper bound before the exact integral, and a shape that can't reach the target isn't gone through; a
  first plan for a weapon takes 0.6 s at most on the saved rivens, each next riven of it a few hundredths.
- **Kuva costs** (`kuva.py`): the next cycle's cost is read off the CYCLE FOR button. A cycle's cost is its
  base rate, rising 900, 1,000, 1,200, 1,400, 1,700, 2,000, 2,350, 2,750, 3,150 to 3,500, doubled while a
  stat that isn't spliced is locked (locking a spliced stat doesn't change it). OCR loses the digit beside
  the Kuva icon, so the reading is matched to the possible costs by the rest; when that leaves several
  (",000": 2,000, 4,000 or 7,000 with a lock), the number is read again with the icon cut off, and failing
  that the highest is taken. On the cycle screen (no button) it's taken as 3,500.
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
  "bad": ["+Zoom", "-Status Chance"],
  "dealbreakers": ["-Damage > 100"],
  "weapons": {
    "@Crit snipers": { "positives": ["Critical Damage", "Multishot", "Critical Chance"] },
    "Rubico": [
      {
        "label": "Crit sniper",
        "positives": { "Critical Damage": 1, "Multishot": 1, "Critical Chance": 0.8, "Damage": 0.7 },
        "required": ["Critical Damage"],
        "bad": ["+Impact", "+Puncture", "-Damage"],
        "dealbreakers": ["-Multishot"]
      }
    ],
    "*rifle": { "positives": ["CD", "MS", "CC"] }
  }
}
```

- **Weapon keys:** a weapon name (covering its whole riven family: `Rubico` also covers Rubico Prime),
  `@group`, or a class fallback `*rifle`, `*shotgun`, `*pistol`, `*melee`, `*archgun`, or `*`.
- A key holds **one roll or a list**; the best-scoring roll is shown, unless the cycle-roll hotkey (F7)
  targets one. `label` names it (also matched against the upgrade screen's config tab).
- **ignore_bad** / **ignore_dealbreakers** *(optional)*: rules from the file or `config.json` that this
  roll doesn't follow (written as the inherited rule's text; how it's spelled doesn't matter). The editor
  shows inherited rules greyed on each roll: removing one there adds it here, and editing one replaces it
  for that roll.
- **positives:** a list, or `{stat: weight}` (1 = ideal, 0.5 = nice to have). The editor shows these as
  tiers: Required (weight 1, and in `required`), Wanted (0.75; any weight from 0.75 shows as Wanted) and
  Acceptable (0.5). **required:** stats the riven must have. **bad** (the editor's *Unwanted stats*) / **dealbreakers:** rules, on a roll, at the top of
  a file (every roll in it), or in `config.json` (every file).
- Stat names match loosely (`Critical Damage`, `crit damage`, `CD`).

**Harmless negatives are bad positives.** A plain `"+Stat"` bad rule (bad as a positive, any value) also
makes the stat a harmless negative: having it as the negative spends the riven's curse on something you
don't want. Older files may list harmless negatives in `negatives` (on a roll or at the top of the file)
and `ignore_negatives`; those mean the same, load the same, and the editor turns them into `"+Stat"`
rules. An inherited `"+Stat"` doesn't apply to a roll that wants that stat as a positive.

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
rating = (Σ weight × (0.9 + 0.1 × quality)  +  negative)  ÷  (sum of the N highest weights  +  slot)
         × 0.5  for each bad stat
         × 0.5  for each required stat that's missing
         = 0    if a dealbreaker matches                 N = number of positives on the riven

slot     = the average of those N weights, when the roll accepts negatives (lists harmless ones); else 0
negative = slot when the riven's negative is harmless; else 0
```

90% for the right stat types, 10% for how well they rolled. **Quality** is where the stat's roll sits
in the range it can roll at this weapon, rank and shape: 0 at the lowest (W = 0.9), 1 at the highest
(W = 1.1), so the right stats rate 90% at the worst rolls and 100% at the best. The panels show it as a
percentage. A **harmless negative** counts like one more wanted stat: a negative makes
every other stat 25% stronger, so on a roll that accepts negatives the best riven has one, and a riven
without one, or with a neutral one, rates about 75% at most. Negatives are neutral unless the roll wants
that stat as a positive or a `bad` rule matches it. The multipliers are `type_weight`, `bad_stat_score`
and `missing_required_score` in `config.json`.

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
- **Kitguns:** a chamber is a Primary or a Secondary (`Gaze (Primary)` / `Gaze (Secondary)`), each with
  its own disposition and stat pool, but FITS IN shows only "Gaze". Both modes are tried and the closer
  fit wins; fitting the second isn't reported as a misread.
- **Rank** isn't shown, so each rank is tried from 8 down until every stat fits 0.9–1.1. If none fits,
  the panel says so (usually an OCR misread or an out-of-date disposition).

## config.json

| Key | Meaning |
|-----|---------|
| `roll_files` | Roll files, folders or globs (default `["rolls"]`) |
| `rating` | `type_weight` 0.9, `bad_stat_score` 0.5, `missing_required_score` 0.5 |
| `bad` / `dealbreakers` | Rules for every roll in every file, e.g. `["-Damage > 100"]` |
| `window_title` | The game window to watch; `null` captures the primary monitor |
| `font_size` | Panel text size at 1080p (it scales with the game window) |
| `hotkeys` | `toggle`, `reload`, `snapshot`, `cycle_roll` (F1–F12, Insert, Home, End, Pause, ScrollLock) |
| `next_step` | NEXT advice, and BETTER by the least Kuva to the target (false: BETTER by rating) |
| `upgrade_overlay` | IDEAL RIVEN on weapon upgrade screens |
| `config_rolls` | On the upgrade screen, the roll labelled like the selected config tab |
| `editor_theme` | The roll editor's colours: a UI theme's name (`riven_helper/data/themes.json`) |
| `kuva_target` | The rating the reroll strategy and its expected-Kuva line aim for (90; 0 hides the line, and NEXT uses simpler rules) |
| `splice_min` | X: how far up its range (%) a trait of a wanted spliced stat must roll to be locked and spliced (50) |

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
| `advice.py` | The NEXT step, and progress towards the ideal roll (BETTER without a Kuva target) |
| `odds.py` | Simulated cycles (a check on flow.py's exact odds), and the stats that can't be negative |
| `flow.py` | The reroll strategy (NEXT), and the Kuva it's expected to take, worked out exactly |
| `kuva.py` | The cycle's Kuva cost, read from the screen |
| `analyze.py` | Screenshot → rated cards, re-reading doubtful ones |
| `session.py` | Live loop: when to read, card tracking, waiting for the screen to settle |
| `tracker.py` | Follows cards between reads by image matching |
| `panel_text.py` | What each panel says |
| `theme.py` | Reads the UI theme off the screen; the panel colours for it |
| `style.py` | Draws panels in the game's style |
| `layout.py` | Where each panel goes |
| `overlay_state.py` | Which panels are showing, and their fades |
| `winpanel.py` | Click-through, capture-hidden windows that show the panels |
| `app.py` | The overlay: worker thread, hotkeys, snapshots, settings reload, the targeted roll |
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
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python tools\make_release.py
```

packs the program with PyInstaller (`tools/exe_entry.py` is the entry point) and builds
`dist/Riven-Helper-<date>.zip`: a `Riven Helper` folder with `Riven Helper.exe` and `_internal/`
(Python, the libraries and the program), beside what players can see and change: a fresh `config.json`,
`rolls/` with the market defaults, and the README. No tests, tools, snapshots or personal roll files.
When packaged, `config.ROOT` is the exe's folder, so `config.json`, `rolls/` and `debug/` live there.
Upload the zip as a GitHub release; the README's download link points there.

It's a folder build, not a single-file exe, because single-file builds unpack themselves on every start
and are flagged by antivirus far more often. To sign it, sign `Riven Helper.exe` with `signtool`
(and a timestamp server) before zipping.
