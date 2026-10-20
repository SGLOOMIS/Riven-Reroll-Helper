"""Riven Reroll Helper.

    python -m riven_helper                 run the overlay (run.bat)
    python -m riven_helper --edit [file]   open the roll-file editor (edit.bat)
    python -m riven_helper --check         list every roll that loaded, and any problems
    python -m riven_helper --image a.png   rate a screenshot instead of the live game (--out b.png: draw it)
"""

import argparse
import sys
from pathlib import Path

from .analyze import Analyzer
from .config import load_config
from .layout import best_flags, render_to_image
from .panel_text import card_rows, rows_text, upgrade_rows


def check(analyzer):
    """Print every roll and group that loaded, then any warnings. Returns the exit code."""
    lib = analyzer.library
    print(f"{len(lib.files)} roll file(s):")
    for f in lib.files:
        print("  ", f)
    for key, rolls in sorted(lib.rolls.items()):
        for r in rolls:
            wanted = ", ".join(f"{s}:{w:g}" for s, w in r.positives.items())
            print(f"  {key:<20} {r.label:<24} + {wanted}   - {', '.join(r.negatives) or '(none listed)'}   [{r.source}]")
    for group, members in sorted(lib.groups.items()):
        print(f"  group @{group}: {', '.join(sorted(members))}")
    for w in lib.warnings:
        print("WARNING:", w)
    return 1 if lib.warnings else 0


def rate_screenshot(analyzer, cfg, path, out=None):
    """Read a screenshot like the overlay would and print what it found."""
    from PIL import Image

    from .capture import Ocr
    from .theme import detect as detect_theme
    from .upgrade_screen import detect_weapon
    img = Image.open(path).convert("RGB")
    ocr = Ocr()
    results, lines = analyzer.analyze_image(img, ocr)
    theme = detect_theme(img)
    if theme:
        print(f"UI theme: {theme.primary} / {theme.accent} on {theme.background}")
    if not results:
        print("No riven cards found.")
    for i, (res, best) in enumerate(zip(results, best_flags(results))):
        print(f"--- card {i + 1}{'  << BETTER' if best else ''}  (box {tuple(int(v) for v in res.card.box)})")
        for st in res.card.stats:
            print(f"    read: {st.text!r} -> {st.name} {'NEG' if st.is_negative else 'POS'} {st.magnitude:.4f}")
        for line in rows_text(card_rows(analyzer, res, best)).splitlines():
            print("   ", line)
    upgrade = None if results else detect_weapon(img, lines, ocr, analyzer.gamedata)
    if upgrade:
        print(f"Upgrade screen for {upgrade}:")
        for line in rows_text(upgrade_rows(analyzer, upgrade)).splitlines():
            print("   ", line)
    if out:
        render_to_image(img, analyzer, results, cfg, upgrade, theme).save(out)
        print(f"Annotated image written to {out}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="riven_helper", description="Warframe riven reroll rating overlay")
    p.add_argument("--config", help="config.json to use (default: the one in the project folder)")
    p.add_argument("--rolls", action="append", help="roll file or folder to use instead of config.json's (repeatable)")
    p.add_argument("--image", help="rate a screenshot instead of watching the game")
    p.add_argument("--out", help="with --image: save a copy with the overlay drawn on it")
    p.add_argument("--check", action="store_true", help="list the rolls that loaded and any problems")
    p.add_argument("--edit", nargs="?", const="", metavar="FILE", help="open the roll-file editor")
    args = p.parse_args(argv)
    if sys.stdout is not None:            # None under pythonw (edit.bat), which has no console
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.edit is not None:
        from .editor import main as edit
        edit(args.edit or None)
        return 0
    cfg = load_config(args.config)
    if args.rolls:
        cfg["roll_files"], cfg["_dir"] = args.rolls, str(Path.cwd())
    analyzer = Analyzer(cfg)
    if args.check:
        return check(analyzer)
    if args.image:
        rate_screenshot(analyzer, cfg, args.image, args.out)
        return 0
    from .app import App
    App(cfg, analyzer).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
