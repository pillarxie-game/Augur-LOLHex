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
        if time.time() - cached.get("fetched", 0) < CACHE_HOURS * 3600:
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
            "source": "OP.GG (mcp-api.op.gg)"}
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
        if time.time() - cached.get("fetched", 0) < CACHE_HOURS * 3600:
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
        "fetched": int(time.time()), "source": "OP.GG ARAM (mcp-api.op.gg)",
    }
    path.write_text(json.dumps(out), encoding="utf-8")
    return out
