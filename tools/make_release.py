"""Build what players download: dist/Riven-Helper-<date>.zip, holding a "Riven Helper" folder with
Riven Helper.exe in it. No Python or setup needed: unzip and double-click.

The exe and its _internal/ folder (Python, the libraries and the program, packed by PyInstaller) sit
beside the files players can see and change: config.json (the defaults, never your own settings),
rolls/ (the market default rolls; their own roll files go here too) and README.md. Not the tests,
tools, snapshots or anyone's own roll files.

    .venv\\Scripts\\python -m pip install -r requirements-build.txt      (once)
    .venv\\Scripts\\python tools\\make_release.py
"""

import json
import os
import shutil
import sys
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from riven_helper.config import DEFAULTS  # noqa: E402

NAME = "Riven Helper"
# PyInstaller's working files: outside the project, since a synced folder (OneDrive) locks the files
# PyInstaller is writing.
BUILD = Path(os.environ.get("LOCALAPPDATA", ROOT)) / "RivenHelperBuild"


def icon(path):
    """A riven-like purple diamond, as the exe's icon."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(128, 8), (240, 128), (128, 248), (16, 128)], fill=(124, 70, 200, 255), outline=(232, 214, 255, 255),
              width=10)
    d.polygon([(128, 60), (190, 128), (128, 196), (66, 128)], fill=(205, 180, 250, 255))
    img.save(path, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def build_exe():
    """Riven Helper.exe and _internal/, in build/dist/Riven Helper/."""
    import PyInstaller.__main__
    BUILD.mkdir(exist_ok=True)
    icon(BUILD / "icon.ico")
    PyInstaller.__main__.run([
        str(ROOT / "tools" / "exe_entry.py"),
        "--name", NAME,
        "--windowed",                     # no console window
        "--icon", str(BUILD / "icon.ico"),
        "--add-data", f"{ROOT / 'riven_helper' / 'data'};riven_helper/data",
        "--distpath", str(BUILD / "dist"), "--workpath", str(BUILD / "work"), "--specpath", str(BUILD),
        "--noconfirm", "--clean", "--log-level", "WARN",
    ])
    return BUILD / "dist" / NAME


def main():
    folder = build_exe()
    (folder / "rolls").mkdir(exist_ok=True)
    shutil.copy(ROOT / "rolls" / "warframe_market.json", folder / "rolls")
    (folder / "config.json").write_text(json.dumps(DEFAULTS, indent=2) + "\n", encoding="utf-8")
    shutil.copy(ROOT / "README.md", folder)

    out = ROOT / "dist" / f"Riven-Helper-{date.today():%Y%m%d}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                z.write(path, f"{NAME}/{path.relative_to(folder).as_posix()}")
    print(f"Wrote {out} ({out.stat().st_size / 1e6:.0f} MB); unzipped: {folder}")


if __name__ == "__main__":
    main()
