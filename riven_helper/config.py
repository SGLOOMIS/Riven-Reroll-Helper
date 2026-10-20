"""Settings from config.json (anything missing falls back to these defaults)."""

import json
import sys
from pathlib import Path

# Where config.json, rolls/ and debug/ live: the project folder, or the folder holding Riven Helper.exe
# when packaged (the program's own files are then inside it, in _internal/).
ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent

DEFAULTS = {
    # Roll files, folders or globs, relative to the project folder.
    "roll_files": ["rolls"],
    # Scoring: share of a wanted stat's credit for being the right type (the rest is roll quality),
    # and the score multipliers for each bad stat and each missing required stat.
    "rating": {"type_weight": 0.9, "bad_stat_score": 0.5, "missing_required_score": 0.25},
    # Rules for every roll in every file, e.g. ["-Damage > 100"].
    "bad": [],
    "dealbreakers": [],
    # The game window to watch. null: capture the primary monitor instead (no window lookup at all).
    "window_title": "Warframe",
    # Panel text size at 1080p; it scales with the game window.
    "font_size": 11,
    "hotkeys": {"toggle": "F8", "reload": "F9", "snapshot": "F10"},
    # Overlay features (the roll editor's Settings tab changes these).
    "next_step": True,          # NEXT on card panels, and BETTER for the card closest to the ideal roll
                                # (off: no NEXT, and BETTER simply for the higher rating)
    "upgrade_overlay": True,    # IDEAL RIVEN on weapon upgrade screens
    "config_rolls": True,       # there, the roll labelled like the selected config tab ("Main", "CONFIG A")
    "editor_theme": "Vitruvian",  # the roll editor's colours: a Warframe UI theme's name
}


def load_config(path=None):
    """The settings, with config.json's values over the defaults. Unknown keys are ignored."""
    path = Path(path or ROOT / "config.json")
    cfg = json.loads(json.dumps(DEFAULTS))
    user = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    for key, value in user.items():
        if key not in cfg:
            continue
        if isinstance(cfg[key], dict) and isinstance(value, dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    cfg["_dir"] = str(path.parent)                     # roll_files are relative to this
    cfg["_path"] = str(path)
    return cfg


def save_settings(changes, path=None):
    """Write these settings into config.json, keeping everything else in it as it is."""
    path = Path(path or ROOT / "config.json")
    user = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    user.update(changes)
    path.write_text(json.dumps(user, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
