"""Settings from config.json (anything missing falls back to these defaults)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # the project folder

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
    return cfg
