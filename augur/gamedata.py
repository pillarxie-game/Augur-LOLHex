"""Download static game data: the Mayhem hex pool, champions and items.

Sources (all public, re-downloaded each patch):
  * League client game data mirrored by CommunityDragon: hex pool, ids, names (EN + 中文), rarity, icons
  * League of Legends Wiki (CC BY-SA): hex descriptions
  * Riot Data Dragon: champions and items
"""
import json
import re
import time

from . import net

CDRAGON = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global"
DDRAGON = "https://ddragon.leagueoflegends.com"
WIKI = "https://wiki.leagueoflegends.com/en-us/Module:MayhemAugmentData/data?action=raw"
MODE = "KIWI"  # Riot's internal name for ARAM Mayhem

RARITY = {"kSilver": "silver", "kGold": "gold", "kPrismatic": "prismatic"}

# Champions whose kit heals a lot (for "enemy has healers" advice).
HEALERS = {
    "Aatrox", "Alistar", "Bard", "Briar", "DrMundo", "Fiddlesticks", "Illaoi", "Ivern", "Janna",
    "Kayn", "Milio", "Nami", "Nidalee", "Olaf", "Rakan", "Renata", "Seraphine", "Senna", "Sona",
    "Soraka", "Swain", "Sylas", "Taric", "Vladimir", "Warwick", "Yuumi", "Zac", "Zeri", "Maokai",
    "Volibear", "Darius", "Gwen", "Irelia", "Trundle", "Yorick",
}

# Words in a hex description -> tag. Tags drive "fits your champion" advice before there is data.
TAG_PATTERNS = {
    "ap": r"ability power",
    "ad": r"(?<!ability )attack damage",
    "attackspeed": r"attack speed",
    "onhit": r"on-hit|basic attacks?",
    "crit": r"critical strike",
    "tank": r"(gain|grants?|increase|bonus)[^.]{0,40}(maximum health|bonus health|\bhealth\b|armor|magic resist|tenacity|damage reduction)|reduce[sd]? (the )?damage (you )?take",
    "antitank": r"(target'?s?|enemy'?s?|their|its) (\w+ )?(maximum|max|missing|bonus|current) health|penetration|lethality|true damage|greater size|larger than|more (maximum |bonus )?health than|reduc\w* (their|the target'?s?) (armor|magic resist)",
    "heal": r"\bheal|omnivamp|life steal|lifesteal",
    "shield": r"\bshield",
    "support": r"\ball(y|ies)\b|heal and shield power",
    "haste": r"ability haste|reduc\w* (your )?(\w+ )?cooldowns?",
    "ult": r"ultimate",
    "ms": r"movement speed",
    "adaptive": r"adaptive force",
    "mana": r"\bmana\b",
    "armor": r"(gain|grants?|bonus)[^.]{0,30}armor",
    "mr": r"(gain|grants?|bonus)[^.]{0,30}magic resist",
}


def clean_wiki(text):
    """Turn wiki markup like {{as|10 ability power|ap}} into plain text."""
    def template(m):
        parts = [p for p in m.group(1).split("|") if "=" not in p or p.startswith("{")]
        name = parts[0].strip().lower()
        args = parts[1:]
        if not args:
            return ""
        return args[-1] if name in ("tip", "tt", "ft") else args[0]

    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"\{\{([^{}]*)\}\}", template, text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def parse_wiki_module(lua):
    out = {}
    for m in re.finditer(r'\["((?:[^"\\]|\\.)*)"\]\s*=\s*\{(.*?)\n\t\},', lua, re.S):
        fields = {
            k: v.replace('\\"', '"').replace("\\\\", "\\")
            for k, v in re.findall(r'\["(\w+)"\]\s*=\s*"((?:[^"\\]|\\.)*)"', m.group(2))
        }
        out[norm(m.group(1))] = {"desc": clean_wiki(fields.get("description", "")), "tier": fields.get("tier", "")}
    return out


def norm(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def infer_tags(desc):
    d = desc.lower()
    return sorted(t for t, p in TAG_PATTERNS.items() if re.search(p, d))


def icon_url(path):
    if not path:
        return ""
    path = path.replace("/lol-game-data/assets/", "").lower()
    return f"{CDRAGON}/default/{path}"


def fetch_augments(log=print):
    lists = net.get_json(f"{CDRAGON}/default/v1/augment-lists.json")
    pool = next((l["augmentList"] for l in lists if l.get("modeName") == MODE), None)
    if not pool:
        raise RuntimeError(f"No {MODE} hex list found in augment-lists.json")
    pool_names = {p.rsplit("/", 1)[-1].lower() for p in pool}
    en = net.get_json(f"{CDRAGON}/default/v1/cherry-augments.json")
    zh = {a["id"]: a for a in net.get_json(f"{CDRAGON}/zh_cn/v1/cherry-augments.json")}
    try:
        wiki = parse_wiki_module(net.get_text(WIKI))
    except Exception as e:  # descriptions are nice to have, not required
        log(f"  wiki descriptions unavailable ({e}); continuing without them")
        wiki = {}
    out = {}
    for a in en:
        if a["augmentNameId"].lower() not in pool_names or not a["nameTRA"].strip():
            continue
        w = wiki.get(norm(a["nameTRA"]), {})
        desc = w.get("desc", "")
        out[str(a["id"])] = {
            "id": a["id"],
            "api": a["augmentNameId"],
            "name": a["nameTRA"],
            "name_zh": zh.get(a["id"], {}).get("nameTRA", a["nameTRA"]),
            "rarity": RARITY.get(a["rarity"], a["rarity"]),
            "icon": icon_url(a.get("augmentSmallIconPath")),
            "desc": desc,
            "disabled": "currently disabled" in desc.lower(),
            "tags": infer_tags(desc),
        }
    log(f"  {len(out)} Mayhem hexes ({sum(1 for a in out.values() if a['desc'])} with descriptions)")
    return out


def champion_flags(c):
    info, tags = c["info"], c["tags"]
    return {
        "tank": "Tank" in tags,
        "front": tags[0] in ("Tank", "Fighter") or "Tank" in tags,
        "apdmg": info["magic"] > info["attack"],
        "healer": c["id"] in HEALERS,
        "support": "Support" in tags,
        "marksman": "Marksman" in tags,
        "ranged": c["stats"]["attackrange"] >= 325,
    }


def fetch_champions(version, log=print):
    en = net.get_json(f"{DDRAGON}/cdn/{version}/data/en_US/champion.json")["data"]
    zh = net.get_json(f"{DDRAGON}/cdn/{version}/data/zh_CN/champion.json")["data"]
    out = {}
    for key, c in en.items():
        info = c["info"]
        out[c["key"]] = {
            "id": int(c["key"]),
            "key": key,
            "name": c["name"],
            "name_zh": zh.get(key, {}).get("name", c["name"]),
            "title_zh": zh.get(key, {}).get("title", ""),
            "tags": c["tags"],
            "partype": c["partype"],
            "ap": round(info["magic"] / max(1, info["attack"] + info["magic"]), 2),
            "tankiness": info["defense"] / 10,
            "flags": champion_flags(c),
            "icon": f"{DDRAGON}/cdn/{version}/img/champion/{c['image']['full']}",
        }
    log(f"  {len(out)} champions")
    return out


def item_tags(item):
    tags = set(item.get("tags", []))
    d = item.get("description", "").lower()
    if "grievous wounds" in d:
        tags.add("AntiHeal")
    if re.search(r"max(imum)? health (as )?(physical |magic )?damage|% (of )?(the target'?s? )?max", d):
        tags.add("AntiTank")
    return sorted(tags)


def fetch_items(version, log=print):
    en = net.get_json(f"{DDRAGON}/cdn/{version}/data/en_US/item.json")["data"]
    zh = net.get_json(f"{DDRAGON}/cdn/{version}/data/zh_CN/item.json")["data"]
    out = {}
    for iid, it in en.items():
        if not it.get("maps", {}).get("12") or not it["gold"].get("purchasable"):
            continue
        tags = item_tags(it)
        if {"Consumable", "Trinket"} & set(tags) or it["gold"]["total"] <= 0:
            continue
        into = [i for i in it.get("into", []) if i in en and en[i].get("maps", {}).get("12")]
        boots = "Boots" in tags
        completed = not into and (it.get("depth", 1) >= 2 or it["gold"]["total"] >= 2000 or boots)
        out[iid] = {
            "id": int(iid),
            "name": it["name"],
            "name_zh": zh.get(iid, {}).get("name", it["name"]),
            "gold": it["gold"]["total"],
            "tags": tags,
            "completed": completed,
            "boots": boots,
            "icon": f"{DDRAGON}/cdn/{version}/img/item/{iid}.png",
        }
    # Data Dragon lists some items twice under different ids (mode variants). Keep one per name.
    alias, keep = {}, {}
    for iid in sorted(out, key=int):
        name = out[iid]["name"]
        if name in keep:
            alias[iid] = keep[name]
        else:
            keep[name] = iid
    for iid in alias:
        del out[iid]
    log(f"  {len(out)} items ({sum(1 for i in out.values() if i['completed'])} completed, {len(alias)} duplicates merged)")
    return out, alias


def update(cfg, log=print):
    log("Downloading game data...")
    version = net.get_json(f"{DDRAGON}/api/versions.json")[0]
    log(f"  game version {version}")
    data = {
        "version": version,
        "updated": time.strftime("%Y-%m-%d"),
        "augments": fetch_augments(log),
        "champions": fetch_champions(version, log),
    }
    data["items"], data["item_alias"] = fetch_items(version, log)
    path = cfg["data_path"] / "gamedata.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    log(f"Saved {path}")
    return data


def load(cfg):
    path = cfg["data_path"] / "gamedata.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def completed_ids(gamedata):
    """All ids (including duplicate copies) of completed items, as ints."""
    done = {i for i, it in gamedata["items"].items() if it["completed"]}
    done |= {a for a, c in gamedata.get("item_alias", {}).items() if c in done}
    return {int(i) for i in done}
