"""Build the zip players download: dist/Riven-Helper-<date>.zip.

Only what's needed to run it goes in: the program, its launchers, the market default rolls, a fresh
config.json (the defaults, never your own settings) and the docs. Not the tests, tools, snapshots,
the Python environment or anyone's own roll files.

    .venv\\Scripts\\python tools\\make_release.py
"""

import json
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from riven_helper.config import DEFAULTS  # noqa: E402

FOLDER = "Riven Helper"                  # the folder players get when they unzip it
FILES = ["Riven Helper.bat", "setup.bat", "requirements.txt", "README.md", "DEVELOPING.md",
         "rolls/warframe_market.json"]


def contents():
    """(path in the zip, file on disk) for everything that ships, except config.json."""
    yield from ((name, ROOT / name) for name in FILES)
    for path in sorted((ROOT / "riven_helper").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in (".py", ".json"):
            yield path.relative_to(ROOT).as_posix(), path


def main():
    out = ROOT / "dist" / f"Riven-Helper-{date.today():%Y%m%d}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name, path in contents():
            z.write(path, f"{FOLDER}/{name}")
        z.writestr(f"{FOLDER}/config.json", json.dumps(DEFAULTS, indent=2) + "\n")
    count = len(zipfile.ZipFile(out).namelist())
    print(f"Wrote {out} ({count} files, {out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
