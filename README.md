# Riven Reroll Helper

An overlay for Warframe's riven **Cycle** (reroll) screen. It reads the riven off the screen, rates it
against the rolls you want for that weapon, and tells you what to do next: cycle, lock a stat,
splice, or stop. On the cycle screen it marks the better of the two rivens.

**It only looks at the screen.** It works from screenshots alone: it never attaches to Warframe,
never reads or changes its memory or files, and never sends it input.

## Install

1. [Download](../../releases) the latest release and unzip it anywhere (for example your Documents).
2. Run Warframe in **Borderless Fullscreen** or **Windowed** (nothing can draw over exclusive
   fullscreen).
3. Double-click **`Riven Helper.bat`**.

The first start takes a few minutes: it sets up what it needs and, if Python isn't installed yet,
offers to install it for you. After that it starts straight away.

## Use

`Riven Helper.bat` opens the **roll editor**, and the overlay runs for as long as it's open: minimise
it while you play, close it when you're done. The editor's top bar shows what the overlay is doing.

| Key | Action |
|-----|--------|
| F8  | hide / show the overlay |
| F9  | reload your roll files (saving one in the editor does this too) |
| F10 | save a snapshot to `debug/` (handy for reporting a misread) |

What you'll see:

- **Above the riven:** its rating for your roll, how well each stat rolled, how its negative counts,
  and **NEXT**, the next step towards the riven you want. It knows how locking and splicing work:
  it gets the shape right first, locks the stat that matters most, and suggests a splice only when
  it's worth one of your rare Riven Splicers.
- **One riven on screen:** the chance that the next cycle rates higher.
- **Cycle screen:** **BETTER** on the riven to keep, which can be the lower-rated one if it's closer
  to the ideal roll (for example one ready to splice).
- **On the left, IDEAL ROLL:** the best stats for this weapon and the highest values they can reach.
- **A weapon's upgrade screen, IDEAL RIVEN:** the riven to look for. If one of your rolls is named
  like the selected config tab (for example "Main"), that one is shown.

The panels take on your Warframe UI theme's colours.

## Your rolls

Out of the box every weapon uses defaults built from what sells on warframe.market. To rate rivens
for your own builds, use the editor:

- **Rolls:** add a weapon (or a group, or `*rifle` for every rifle), then the stats you want. A
  weight of 1 means ideal and 0.5 nice to have. You can also list harmless negatives, stats a riven
  must have, bad stats, and dealbreakers like "-Damage > 100" that make a riven worthless.
- **Groups:** name a set of weapons once ("Crit snipers") and write rolls for the whole group.
- **File rules:** bad stats and dealbreakers for every roll in the file.
- **Save** puts the file in `rolls/` and checks it. Your rolls always win over the market defaults.

## Settings

The editor's **Settings** tab:

- **Theme:** colour the editor like one of Warframe's 20 UI themes.
- **Overlay:** turn off the next-step advice, the upgrade screen panel, or its config-specific rolls.
- **Roll lists:** add roll files or folders from anywhere on your computer, such as a friend's list.

Changes apply straight away. Everything is saved in `config.json`.

## Problems?

- **Nothing shows up:** check the editor's top bar. "paused: Warframe isn't the active window" means
  click into the game; the overlay only watches while Warframe is in front.
- **"no English OCR installed":** the overlay reads the screen with Windows' own text recognition. Add
  English in *Settings > Time & language > Language & region*.
- **A stat or weapon is misread:** press F10 on that screen and share the files from `debug/` when you
  report it.
- **Setup failed:** check your internet connection and start `Riven Helper.bat` again. To start over
  completely, delete the `.venv` folder.

Technical details (the riven math, the roll file format, the code, testing) are in
[DEVELOPING.md](DEVELOPING.md).
