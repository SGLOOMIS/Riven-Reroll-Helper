# Riven Reroll Helper

An overlay for Warframe's riven **Cycle** (reroll) screen. It reads the riven off the screen, rates it
against the rolls you want for that weapon, and tells you what to do next: cycle, lock a stat,
splice, or stop. On the cycle screen it marks the better of the two rivens.

**It only looks at the screen.** It works from screenshots alone: it never attaches to Warframe,
never reads or changes its memory or files, and never sends it input.

**Made with AI.** Most of the code was written by an AI assistant (Anthropic's Claude) under the
author's direction. The program itself uses no AI and works offline. It's an unofficial fan tool, not
affiliated with Digital Extremes. See [AI-DISCLAIMER.md](AI-DISCLAIMER.md).

## Install

1. [Download](../../releases) the latest release and unzip it anywhere (for example your Documents).
2. Run Warframe in **Borderless Fullscreen** or **Windowed** (nothing can draw over exclusive
   fullscreen).
3. Double-click **`Riven Helper.exe`** in the unzipped folder. Nothing else to install.

The program isn't digitally signed yet, so Windows may say *"Windows protected your PC"* the first
time: click **More info**, then **Run anyway**.

## Use

`Riven Helper.exe` opens the **roll editor**, and the overlay runs for as long as it's open: minimise
it while you play, close it when you're done. The editor's top bar shows what the overlay is doing.

| Key | Action |
|-----|--------|
| F7  | switch the roll the riven on screen is rated against: best match, then each of the weapon's rolls |
| F8  | hide / show the overlay |
| F9  | reload your roll files (saving one in the editor does this too) |
| F10 | save a snapshot to `debug/` (handy for reporting a misread) |

What you'll see:

- **Above the riven:** its rating for your roll, how well each stat rolled (0% is the lowest roll that
  stat can have, 100% the highest), how its negative counts,
  and **NEXT**, the next step towards the riven you want. It follows one strategy: unlock a spliced
  stat your roll doesn't want, to start the riven over; get the shape right without a lock; when your roll wants a spliced stat (Blast), lock the most useful stat (a
  harmless negative first) until Heat or Cold rolls well, then lock that and wait for its partner,
  and splice; then lock your most wanted stat and cycle until the riven rates 90%.
- **Every riven:** the Kuva you can expect to spend following that strategy until the riven rates
  90% or more: an average, worked out exactly from the game's rules (any one riven can take far
  more or far less). The 90% is the Kuva target in the editor's Settings tab.
- **One riven on screen, once it rates the Kuva target:** the chance that the next cycle rates higher
  still, worked out the same way.
- **Cycle screen:** **BETTER** on the riven to keep: the one expected to reach the Kuva target for less
  Kuva (both cards show their amount), which can be the lower-rated one.
- **On the left, IDEAL ROLL:** the best stats for this weapon and the highest values they can reach.
- **A weapon's upgrade screen, IDEAL RIVEN:** the riven to look for. If one of your rolls is named
  like the selected config tab (for example "Main"), that one is shown.

The panels take on your Warframe UI theme's colours.

## Your rolls

Out of the box every weapon uses defaults built from what sells on warframe.market. To rate rivens
for your own builds, use the editor:

- **Rolls:** add a weapon (or a group, or `*rifle` for every rifle), then the stats you want, each as
  **Required** (the riven must have it), **Wanted** or **Acceptable** (nice to have). You can also
  list **unwanted stats** (each one on the riven halves its rating) and dealbreakers like
  "-Damage > 100" that make a riven worthless. A stat unwanted **as a positive** makes a good
  negative: having it there raises the rating, since a negative makes the other stats 25% stronger.
- **Several rolls for one weapon:** the riven is rated against the one it matches best. Press **F7** to
  target a particular one instead; the IDEAL ROLL panel says which is targeted.
- **Groups:** name a set of weapons once ("Crit snipers") and write rolls for the whole group.
- **File rules:** unwanted stats and dealbreakers for every roll in the file. Each roll shows them greyed;
  remove or change one there to make an exception for just that roll.
- **Save** puts the file in `rolls/` and checks it. Your rolls always win over the market defaults.

## Settings

The editor's **Settings** tab:

- **Theme:** colour the editor like one of Warframe's 20 UI themes.
- **Overlay:** turn off the next-step advice, the upgrade screen panel, or its config-specific rolls,
  and set the **Kuva target**: the rating the Kuva estimate and NEXT aim for (90% by default; 0 hides
  the Kuva line), and the **splice threshold**: how well Heat or Cold (any trait of a spliced stat
  you want) must roll before NEXT locks it and waits for its partner (50%: halfway up its range).
- **Roll lists:** add roll files or folders from anywhere on your computer, such as a friend's list.

Changes apply straight away. Everything is saved in `config.json`.

## Problems?

- **Nothing shows up:** check the editor's top bar. "paused: Warframe isn't the active window" means
  click into the game; the overlay only watches while Warframe is in front.
- **"no English OCR installed":** the overlay reads the screen with Windows' own text recognition. Add
  English in *Settings > Time & language > Language & region*.
- **A stat or weapon is misread:** press F10 on that screen and share the files from `debug/` when you
  report it.
- **Saved a roll file by mistake:** the version before your last save is next to it in `rolls/`, as
  `<name>.json.bak`. Rename it back to `.json` to restore it.
- **Windows or your antivirus blocks it:** see *Install* above. Unsigned programs packed this way are
  sometimes flagged by mistake; the full source code is on the project page.

Technical details (the riven math, the roll file format, the code, testing) are in
[DEVELOPING.md](DEVELOPING.md).
