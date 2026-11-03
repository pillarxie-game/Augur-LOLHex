"""Settings. Defaults live here; put your own values in config.local.json (not committed)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
    return cfg
