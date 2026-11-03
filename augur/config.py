"""Settings. Defaults live here; put your own values in config.local.json (not committed)."""
import json
import os
import shutil
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)  # running from the packaged app (Augur.exe)
# Program files: read-only inside the packaged app.
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _home():
    if os.environ.get("AUGUR_HOME"):
        return Path(os.environ["AUGUR_HOME"])
    if not FROZEN:
        return BUNDLE  # running from source: keep everything in the project folder
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / "Augur"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Augur"
    return Path.home() / ".augur"


# Your data and settings: games, stats, caches, config.local.json.
ROOT = _home()
ROOT.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    # Riot API (https://developer.riotgames.com). Can also come from the RIOT_API_KEY env var.
    "riot_api_key": "",
    # Regional routing for match-v5: americas, asia, europe or sea.
    "riot_region": "asia",
    # ARAM Mayhem queue ids (from the client's queues.json).
    "queues": [2400],
    # Only games from the newest N patches count. Each older patch counts for patch_decay times less.
    "patches_kept": 3,
    "patch_decay": 0.5,
    # Your Riot IDs ("Name#TAG"). Your own games in the database give the "your record" part of grades.
    "my_riot_ids": [],
    # League client lockfile locations, tried in order (for champion select bench grades).
    "lockfile_paths": [
        "C:/Riot Games/League of Legends/lockfile",
        "D:/Riot Games/League of Legends/lockfile",
        "/Applications/League of Legends.app/Contents/LoL/lockfile",
    ],
    "server_port": 8765,
    # Desktop app
    "ui_lang": "",              # "" = follow the system language
    "auto_read": True,          # watch the screen for hex cards
    "read_interval": 3,         # seconds between screen checks
    "overlay": True,            # small always-on-top window with the grades
    "overlay_position": "top-right",  # top-right, top-left, bottom-right, bottom-left
    "overlay_opacity": 0.92,
    "use_opgg": True,           # add OP.GG's ARAM hex stats to grades
    "ocr_extra": ["ko", "ja"],  # extra OCR scripts for Korean / Japanese clients
    "data_dir": "data",
    "site_dir": "docs",
}


def load():
    cfg = dict(DEFAULTS)
    for name in ("config.json", "config.local.json"):
        path = ROOT / name
        if path.exists():
            with open(path, encoding="utf-8") as f:
                cfg.update(json.load(f))
    if os.environ.get("RIOT_API_KEY"):
        cfg["riot_api_key"] = os.environ["RIOT_API_KEY"]
    cfg["data_path"] = ROOT / cfg["data_dir"]
    cfg["site_path"] = ROOT / cfg["site_dir"]
    cfg["data_path"].mkdir(parents=True, exist_ok=True)
    # Files shipped inside the app, so the first run works offline and reads cards right away.
    if BUNDLE != ROOT:
        seed = BUNDLE / "data"
        if not (cfg["data_path"] / "gamedata.json").exists() and (seed / "gamedata.json").exists():
            shutil.copy2(seed / "gamedata.json", cfg["data_path"] / "gamedata.json")
        for folder in ("icons", "ocr"):
            src, dst = seed / folder, ROOT / "data" / folder
            if src.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
                for f in src.iterdir():
                    if not (dst / f.name).exists():
                        shutil.copy2(f, dst / f.name)
    return cfg


# Settings the desktop app may change (written to config.local.json).
EDITABLE = {
    "ui_lang": str, "auto_read": bool, "read_interval": (int, float), "overlay": bool,
    "overlay_position": str, "overlay_opacity": (int, float), "use_opgg": bool,
    "my_riot_ids": list, "lockfile_paths": list, "ocr_extra": list, "riot_region": str,
}


def save(changes):
    """Validate and merge changes into config.local.json. Returns the saved values."""
    path = ROOT / "config.local.json"
    current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for k, v in changes.items():
        if k not in EDITABLE or not isinstance(v, EDITABLE[k]) or isinstance(v, bool) != (EDITABLE[k] is bool):
            raise ValueError(f"bad setting {k!r}")
        if isinstance(v, list) and not all(isinstance(x, str) for x in v):
            raise ValueError(f"bad setting {k!r}")
        current[k] = v
    if "read_interval" in current:
        current["read_interval"] = max(1, min(30, current["read_interval"]))
    if "overlay_opacity" in current:
        current["overlay_opacity"] = max(0.3, min(1.0, current["overlay_opacity"]))
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return current
