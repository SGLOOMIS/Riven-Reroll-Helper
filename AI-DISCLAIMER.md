# AI usage disclaimer

## How this program was made

Riven Reroll Helper was built with the help of generative AI. Most of its code, tests and
documentation were written by Anthropic's Claude (through Claude Code), working from the project
author's instructions.

The author decided what the program should do and how it should behave: the features, the rating and
next-step rules, the look of the overlay, and the safety constraints. The author also tested it in the
game, and supplied the screenshots, recordings and bug reports it was corrected against. The AI wrote
and changed the code to match, and checked its work with an automated test suite, saved game
screenshots and screen recordings.

That means:

- **It can contain mistakes.** It has been tested, but no one has reviewed every line by hand the
  way a professional code audit would. Bugs, misread stats and wrong advice are possible.
- **Treat its advice as a suggestion.** Ratings, next-step advice and next-cycle odds are estimates.
  Some rest on assumptions, because the game doesn't publish its odds (DEVELOPING.md on the project
  page lists them). Check before you spend Kuva or a Riven Splicer on its say-so.
- **The game data comes from the community.** Riven formulas and dispositions come from the
  [Warframe Wiki](https://wiki.warframe.com/w/Riven_Mods) and the WFCD game data export, and the
  default rolls from warframe.market. They can be out of date after a game update.

## What the program itself does with AI

**Nothing.** The program contains no AI model and makes no AI requests while it runs. It doesn't send
your screen, your rolls or anything else to an AI service, or anywhere else: it works offline. It
reads the screen with Windows' built-in text recognition (OCR), on your own computer.

## Not affiliated

This is an unofficial fan-made tool. It isn't made, endorsed or supported by Digital Extremes or
Anthropic. Warframe is a trademark of Digital Extremes Ltd.

It only reads the screen: it never reads or changes the game's memory or files, and never sends the
game input. Even so, you use third-party tools at your own risk.

## No warranty

The program is provided as is, without warranty of any kind. The author isn't responsible for any
loss of in-game resources, account issues or other damage from using it.
