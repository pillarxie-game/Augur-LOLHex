"""ARAM hex stats from OP.GG's official public data server (https://mcp-api.op.gg/mcp).

Your copy of Augur asks OP.GG directly, one champion at a time, and keeps the answer for 12 hours
in data/opgg/. Nothing from OP.GG is stored in the repository or the published website.

OP.GG returns, per champion: tier (3 to 5; it leaves out its tiers 1-2), a performance score and
a popularity score for each hex it lists.
"""
import json
import re
import time
import urllib.request

from . import config

URL = "https://mcp-api.op.gg/mcp"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
           "User-Agent": "Augur/1.0 (free ARAM Mayhem helper)"}
CACHE_HOURS = 12


def _game_version():
    """Current game version (from the downloaded game data); OP.GG data from an older version is refetched."""
    try:
        return json.loads((config.ROOT / "data" / "gamedata.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        return None


def _fresh(cached):
    return (time.time() - cached.get("fetched", 0) < CACHE_HOURS * 3600
            and cached.get("game_version") == _game_version())


def _rpc(method, params=None, sid=None, rid=1):
    h = dict(HEADERS)
    if sid:
        h["Mcp-Session-Id"] = sid
    body = {"jsonrpc": "2.0", "method": method}
    if rid is not None:
        body["id"] = rid
    if params is not None:
        body["params"] = params
    with urllib.request.urlopen(urllib.request.Request(URL, json.dumps(body).encode(), h), timeout=30) as r:
        raw = r.read().decode("utf-8")
        sid = r.headers.get("mcp-session-id") or sid
    if not raw.strip():
        return None, sid
    events = re.findall(r"^data: (.*)$", raw, re.M)
    return json.loads(events[-1] if events else raw), sid


def call_tool(name, arguments, attempts=3):
    for i in range(attempts):
        try:
            return _call_tool(name, arguments)
        except (OSError, TimeoutError) as e:  # network hiccup: try again
            if i == attempts - 1:
                raise RuntimeError(f"OP.GG did not answer ({e})") from None
            time.sleep(2 * (i + 1))


def _call_tool(name, arguments):
    _, sid = _rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                 "clientInfo": {"name": "augur", "version": "1.0"}})
    _rpc("notifications/initialized", sid=sid, rid=None)
    res, _ = _rpc("tools/call", {"name": name, "arguments": arguments}, sid=sid, rid=2)
    if not res or "error" in res:
        raise RuntimeError(f"OP.GG: {res.get('error') if res else 'no answer'}")
    return "".join(c.get("text", "") for c in res["result"].get("content", []))


def parse_augments(text):
    """The answer looks like ...Augment(1349,3,80.89,0.2),Augment(...)... -> {id: [tier, performance, popular]}"""
    out = {}
    for hid, tier, perf, pop in re.findall(r"Augment\((\d+),(\d+),(-?[\d.]+),(-?[\d.]+)\)", text):
        out[hid] = [int(tier), float(perf), float(pop)]
    return out


def aram_augments(champ_id, refresh=False):
    """{'champion': id, 'augments': {hex id: [tier, performance, popular]}, 'fetched': unix time}."""
    folder = config.ROOT / "data" / "opgg"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{int(champ_id)}.json"
    if path.exists() and not refresh:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if _fresh(cached):
            return cached
    try:
        text = call_tool("lol_list_aram_augments", {
            "champion_id": int(champ_id),
            "desired_output_fields": ["data.augments[].{id,tier,performance,popular}"],
        })
    except Exception:
        if path.exists():  # OP.GG unreachable: an older copy beats nothing
            return {**json.loads(path.read_text(encoding="utf-8")), "stale": True}
        raise
    data = {"champion": int(champ_id), "augments": parse_augments(text), "fetched": int(time.time()),
            "game_version": _game_version(), "source": "OP.GG (mcp-api.op.gg)"}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


# ---------- builds (items) ----------

def parse_value(text):
    """Parse OP.GG's compact answer format, e.g. Data(Summary(1,0.5),[Item([1,2],["a"],3)]) -> nested lists."""
    pos = 0

    def skip():
        nonlocal pos
        while pos < len(text) and text[pos] in " \n\t":
            pos += 1

    def value():
        nonlocal pos
        skip()
        c = text[pos]
        if c == "[":
            pos += 1
            return seq("]")
        if c == '"':
            pos += 1
            out = []
            while text[pos] != '"':
                if text[pos] == "\\":
                    pos += 1
                out.append(text[pos])
                pos += 1
            pos += 1
            return "".join(out)
        m = re.match(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", text[pos:])
        if m:
            pos += m.end()
            return float(m.group()) if any(ch in m.group() for ch in ".eE") else int(m.group())
        m = re.match(r"[A-Za-z_]\w*", text[pos:])
        name = m.group()
        pos += m.end()
        if name in ("null", "None"):
            return None
        if name in ("true", "True", "false", "False"):
            return name.lower() == "true"
        skip()
        if pos < len(text) and text[pos] == "(":
            pos += 1
            return seq(")")
        return name

    def seq(end):
        nonlocal pos
        items = []
        skip()
        while text[pos] != end:
            items.append(value())
            skip()
            if text[pos] == ",":
                pos += 1
            skip()
        pos += 1
        return items

    return value()


def _items(v):
    ids, _names, play, win, pick = v
    return {"ids": ids, "play": play, "win": win, "pick": pick}


def _build_text(champ_key):
    return call_tool("lol_get_champion_analysis", {
        "game_mode": "aram", "position": "mid", "champion": champ_key.upper(),
        "desired_output_fields": [
            "data.summary.average_stats.{play,win_rate,pick_rate,tier,rank}",
            "data.core_items.{ids[],ids_names[],play,win,pick_rate}",
            "data.boots.{ids[],ids_names[],play,win,pick_rate}",
            "data.fourth_items[].{ids[],ids_names[],play,win,pick_rate}",
            "data.fifth_items[].{ids[],ids_names[],play,win,pick_rate}",
            "data.sixth_items[].{ids[],ids_names[],play,win,pick_rate}",
        ],
    })


def champion_build(champ_key, champ_id, refresh=False):
    """OP.GG ARAM build for one champion: win rate, tier, core items, boots and 4th-6th item options."""
    folder = config.ROOT / "data" / "opgg"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"build_{int(champ_id)}.json"
    if path.exists() and not refresh:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if _fresh(cached):
            return cached
    try:
        text = _build_text(champ_key)
    except Exception:
        if path.exists():  # OP.GG unreachable: an older copy beats nothing
            return {**json.loads(path.read_text(encoding="utf-8")), "stale": True}
        raise
    body = text[text.index("LolGetChampionAnalysis("):]
    data = parse_value(body)[0]  # [Summary, core, boots, fourth[], fifth[], sixth[]?, message?]

    def is_item(v):
        return isinstance(v, list) and len(v) == 5 and isinstance(v[0], list) and isinstance(v[2], int)

    play, win_rate, pick_rate, tier, rank = data[0][0]
    lists = [v for v in data[3:] if isinstance(v, list) and v and all(is_item(x) for x in v)]
    out = {
        "champion": int(champ_id), "play": play, "win_rate": win_rate, "pick_rate": pick_rate,
        "tier": tier, "rank": rank,
        "core": _items(data[1]) if is_item(data[1]) else None,
        "boots": _items(data[2]) if is_item(data[2]) else None,
        "slots": {str(4 + i): [_items(x) for x in lst] for i, lst in enumerate(lists[:3])},
        "fetched": int(time.time()), "game_version": _game_version(), "source": "OP.GG ARAM (mcp-api.op.gg)",
    }
    path.write_text(json.dumps(out), encoding="utf-8")
    return out


# ---------- all champions ----------

def fetch_all(gamedata, log=print, pause=0.4):
    """ARAM hex stats for every champion (cached ones are reused), then the all-champion summary."""
    champs = sorted(gamedata["champions"].values(), key=lambda c: c["name"])
    ok = failed = 0
    for i, c in enumerate(champs, 1):
        try:
            d = aram_augments(c["id"])
            b = champion_build(c["key"], c["id"])  # ARAM win rate, tier and build
            ok += 1
            if time.time() - min(d["fetched"], b["fetched"]) < 5:
                time.sleep(pause)  # fresh download: be gentle with OP.GG
        except Exception as e:
            failed += 1
            log(f"  {c['name']}: {e}")
        if i % 20 == 0 or i == len(champs):
            log(f"  {i}/{len(champs)} champions")
    summary = summarize(gamedata)
    log(f"OP.GG data for {ok} champions ({failed} failed); {len(summary['hexes'])} hexes summarized.")
    try:
        from . import model
        model.train(gamedata, log=log)  # fills hexes OP.GG has no tier for, from similar champions
    except Exception as e:
        log(f"Model skipped: {e}")
    return summary


def summarize(gamedata):
    """Per hex across all champions: popularity-weighted performance, how many champions list it, best champions."""
    folder = config.ROOT / "data" / "opgg"
    per_hex = {}
    champs = 0
    plays = {}
    for c in gamedata["champions"].values():
        bp = folder / f"build_{c['id']}.json"
        if bp.exists():
            plays[c["id"]] = json.loads(bp.read_text(encoding="utf-8")).get("play") or 0
    total_play = sum(plays.values()) or 1
    for c in gamedata["champions"].values():
        path = folder / f"{c['id']}.json"
        if not path.exists():
            continue
        champs += 1
        d = json.loads(path.read_text(encoding="utf-8"))
        rows = [v for v in d["augments"].values() if v[2] >= 0.01]
        perf = sorted(v[1] for v in rows)
        med = perf[len(perf) // 2] if perf else 0
        for hid, (tier, p, pop) in d["augments"].items():
            if hid not in gamedata["augments"]:
                continue
            e = per_hex.setdefault(hid, {"w": 0.0, "rel": 0.0, "listed": 0, "tiers": [0, 0, 0], "champs": [], "picks": 0.0})
            e["listed"] += 1
            e["picks"] += pop * plays.get(c["id"], 0)  # "popular" is the share of the champion's games with this hex
            if 3 <= tier <= 5:
                e["tiers"][tier - 3] += 1
            if pop >= 0.01 and med:
                e["w"] += pop
                e["rel"] += pop * (p - med)
                e["champs"].append([c["id"], round(p - med, 1), pop])
    # OP.GG lists only tiers 3-5 per champion. A hex it tracks but leaves out for a champion is in that
    # champion's top tiers (1-2): checked against independent rankings for Yasuo and Lux (18 of 18 each).
    tier_value = {"top": 2.0, 3: 0.8, 4: 0.0, 5: -0.8}
    hexes = {}
    for hid, e in per_hex.items():
        t3, t4, t5 = e["tiers"]
        # Ability hexes ("Upgrades one of your champion's abilities...") only exist for some champions, and
        # hexes OP.GG lists for under 5 champions are too rare: for those, a missing entry means "no data".
        desc = gamedata["augments"][hid].get("desc", "").lower()
        e["infer_top"] = e["listed"] >= 5 and "upgrades one of your champion" not in desc
        top = max(0, champs - e["listed"]) if e["infer_top"] else 0
        champs_counted = top + e["listed"]
        e["strength"] = round((top * tier_value["top"] + t3 * tier_value[3] + t4 * tier_value[4]
                               + t5 * tier_value[5]) / champs_counted, 2) if champs_counted else None
        e["top"] = top
        e["champs"].sort(key=lambda x: -x[1])
        hexes[hid] = {
            "score": round(e["rel"] / e["w"], 2) if e["w"] else None,  # vs each champion's median, weighted by popularity
            "strength": e["strength"], "top_champs": e["top"], "infer_top": e["infer_top"],  # tier-based: champions with it in OP.GG T1-T2
            "listed": e["listed"], "tiers": e["tiers"],
            "pick_rate": round(e["picks"] / total_play, 4) if plays else None,  # share of all players picking it
            "best": e["champs"][:8], "worst": e["champs"][-5:][::-1] if len(e["champs"]) > 8 else [],
        }
    champ_stats = {}
    for c in gamedata["champions"].values():
        path = folder / f"build_{c['id']}.json"
        if path.exists():
            b = json.loads(path.read_text(encoding="utf-8"))
            champ_stats[str(c["id"])] = {k: b.get(k) for k in ("win_rate", "play", "pick_rate", "tier", "rank")}
    out = {"champions": champs, "champ_stats": champ_stats, "hexes": hexes, "built": int(time.time()),
           "game_version": _game_version(),
           "source": "OP.GG ARAM (mcp-api.op.gg)"}
    (folder / "summary.json").write_text(json.dumps(out), encoding="utf-8")
    return out
