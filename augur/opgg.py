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
    text = call_tool("lol_list_aram_augments", {
        "champion_id": int(champ_id),
        "desired_output_fields": ["data.augments[].{id,tier,performance,popular}"],
    })
    data = {"champion": int(champ_id), "augments": parse_augments(text), "fetched": int(time.time()),
            "source": "OP.GG (mcp-api.op.gg)"}
    path.write_text(json.dumps(data), encoding="utf-8")
    return data
