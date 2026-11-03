"""Save your Riot API key (typed hidden) and starting Riot ID into config.local.json, then test them.

    python tools/set_key.py
"""
import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from augur import collect  # noqa: E402

path = ROOT / "config.local.json"
cfg = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

key = getpass.getpass("Paste your Riot API key (RGAPI-...), hidden, then Enter: ").strip()
if not key.startswith("RGAPI-"):
    sys.exit("That doesn't look like a Riot key (it should start with RGAPI-). Nothing saved.")
riot_id = input("Riot ID to start from (Name#TAG): ").strip()
region = cfg.get("riot_region", "asia")

try:
    puuid = collect.RiotAPI(key, region).account(riot_id)
except SystemExit as e:
    sys.exit(f"Check failed: {e}\nNothing saved.")

cfg.update({"riot_api_key": key, "riot_region": region, "seed_riot_id": riot_id})
path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"OK: key works and {riot_id} was found. Saved to config.local.json (never committed).")
print("You can close this tab and go back to the chat.")
