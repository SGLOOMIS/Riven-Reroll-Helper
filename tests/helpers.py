"""Shared bits for the tests. Run them all with:  .venv\\Scripts\\python -m unittest discover tests"""

import json
import tempfile
import unittest
from pathlib import Path

from riven_helper.gamedata import GameData
from riven_helper.riven_math import BONUS_L, MALUS_L, RivenStat, infer
from riven_helper.rolls import RollLibrary

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"      # example rolls, saved OCR output, screenshots
G = GameData()


def shown_value(stat, weapon, rank, n_positives, has_negative, is_negative, W):
    """The value a card would show for a stat with roll W (the riven formula)."""
    b = G.stats[stat].base[weapon.cls]
    L = MALUS_L[n_positives] if is_negative else BONUS_L[(n_positives, has_negative)]
    return b * 10 * (rank + 1) * weapon.disposition * L * W


def riven(weapon, positives, negative=None, W=1.1, rank=8):
    """A worked-out riven with these stats, all rolled at W (the negative at W = 1)."""
    w = G.weapon_by_name(weapon)
    n, has_neg = len(positives), negative is not None
    stats = [RivenStat(p, shown_value(p, w, rank, n, has_neg, False, W), False) for p in positives]
    if negative:
        stats.append(RivenStat(negative, shown_value(negative, w, rank, n, True, True, 1.0), True))
    return infer(stats, G.candidates_for(weapon), G)


def ocr_line(text, x, y, h=20):
    """One fake OCR line: the words of text laid out left to right."""
    out, cx = [], x
    for word in text.split():
        w = len(word) * h * 0.5
        out.append((word, cx, y, w, h))
        cx += w + h * 0.3
    return out


def roll_library(*files):
    """A RollLibrary over these roll-file dicts (written to a temporary folder)."""
    folder = Path(tempfile.mkdtemp())
    for i, data in enumerate(files):
        (folder / f"f{i}.json").write_text(json.dumps(data), encoding="utf-8")
    return RollLibrary(G, [str(folder)])


def fixture_config(roll_files=None):
    """config.json's settings, with the fixture roll files (fixed, not the live market data)."""
    from riven_helper.config import load_config
    cfg = load_config()
    cfg["roll_files"], cfg["_dir"] = [str(roll_files or FIXTURES)], str(roll_files or FIXTURES)
    return cfg


def analyzer(roll_files=None):
    from riven_helper.analyze import Analyzer
    return Analyzer(fixture_config(roll_files))


def saved_ocr(name):
    """OCR output saved from a real F10 snapshot (tests/fixtures/ocr/)."""
    return json.loads((FIXTURES / "ocr" / name).read_text(encoding="utf-8"))


def windows_ocr(test):
    """The Windows OCR engine, or skip the test when it isn't available."""
    try:
        from riven_helper.capture import Ocr
        return Ocr()
    except Exception as e:
        raise unittest.SkipTest(f"Windows OCR unavailable: {e}")
