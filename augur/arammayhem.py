"""Which hexes are really in ARAM: Mayhem right now, from arammayhem.com's hex list.

Riot's game files keep some removed or disabled hexes (Sneakerhead), so the game files alone can't say
what is offered. arammayhem.com's hex list marks deleted hexes and leaves out ones no longer in the game.

Used politely and only on your computer: one page, read at most once a day, credited on the page, never
copied into the repository or the published site. Its pick rates and tiers are used only when its data
is for the live patch (Augur uses the latest patch's data only).
"""
import html
import json
import re
import time

from . import config, net

URL = "https://arammayhem.com/augments/"
CACHE_HOURS = 24


def _parse(page):
    patch = None
    plain = re.sub(r"<[^>]+>", " ", page)
    m = re.search(r"Tier List\s*(?:\(|—|-)\s*Patch\s*(\d{2})\.(\d{1,2})", plain) \
        or re.search(r"Meta Patch\D{0,80}?(\d{2})\.(\d{1,2})", plain)
    if m:
        patch = f"{m.group(1)}.{m.group(2)}"
    rows = {}
    for chunk in page.split("augment-rank-row")[1:]:
        text = re.sub(r"<[^>]+>", "|", chunk[:4000])
        text = html.unescape(re.sub(r"(\s*\|\s*)+", "|", text))
        name = re.search(r'font-semibold text-foreground[^>]*>([^<]+)<', chunk)
        if not name:
            continue
        name = html.unescape(name.group(1)).strip()
        pick = re.search(r"\|(\d{1,3}\.\d{1,2})%", text)
        tier = re.search(r"\|(S\+|S-|S|A\+|A-|A|B\+|B-|B|C\+|C-|C|D)\|", text)
        rarity = re.search(r"\|(Prismatic|Gold|Silver)\|", text)
        rows[name.lower()] = {
            "name": name,
            "deleted": ">Deleted<" in chunk[:3000],
            "pick_rate": float(pick.group(1)) / 100 if pick else None,
            "tier": tier.group(1) if tier else None,
            "rarity": rarity.group(1).lower() if rarity else None,
        }
    return {"patch": patch, "hexes": rows}


def hex_list(refresh=False):
    """{'patch': '26.21', 'hexes': {lower name: {deleted, pick_rate, tier, rarity}}, 'fetched': unix time}"""
    folder = config.ROOT / "data" / "arammayhem"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "hexes.json"
    if path.exists() and not refresh:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - cached.get("fetched", 0) < CACHE_HOURS * 3600:
            return cached
    try:
        page = net.get_text(URL, timeout=30)
    except Exception:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    data = _parse(page)
    data.update(fetched=int(time.time()), source="arammayhem.com")
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def same_patch(site_patch, game_version):
    """arammayhem writes 26.21 for the game version 16.21.x: compare the minor numbers within the year."""
    try:
        return site_patch.split(".")[1] == game_version.split(".")[1]
    except (AttributeError, IndexError):
        return False


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower().replace("\u2019", "'"))


def deleted(gamedata, site):
    """Hex ids arammayhem.com marks as Deleted. (Its list is incomplete, so a hex missing from it is NOT
    treated as removed: OP.GG still has current-patch picks for most of those.)"""
    marked = {_norm(r["name"]) for r in site.get("hexes", {}).values() if r.get("deleted")}
    return {h for h, a in gamedata["augments"].items() if _norm(a["name"]) in marked}
