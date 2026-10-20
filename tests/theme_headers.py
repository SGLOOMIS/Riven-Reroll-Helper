"""The 20 Warframe UI themes' screen headers ("CUSTOMIZE UI THEME/THEME"), for testing the header reader.

Each fixture is the top strip of a screenshot; the file name keeps the full screenshot's size so the
strip can be put back where it was on a frame of that size.
"""

import re
from pathlib import Path

from PIL import Image

FOLDER = Path(__file__).resolve().parent / "fixtures" / "themes"


def theme_frames():
    """(name, full-size frame with the header strip in place) for each theme."""
    for path in sorted(FOLDER.glob("theme_*.png")):
        w, h = map(int, re.search(r"_(\d+)x(\d+)\.png$", path.name).groups())
        frame = Image.new("RGB", (w, h))
        frame.paste(Image.open(path).convert("RGB"), (0, 0))
        yield path.stem, frame
