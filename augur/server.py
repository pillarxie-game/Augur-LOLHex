"""Local helper: serves the website plus a small API that reads your running game and client.

Only listens on 127.0.0.1, so nothing is exposed to the network.
"""
import json
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from . import lcu, net, stats

LIVE = "https://127.0.0.1:2999/liveclientdata/allgamedata"


def live_game(gamedata):
    """Read the game in progress from Riot's Live Client Data API (port 2999)."""
    try:
        d = net.get_json(LIVE, timeout=3, retries=1, insecure=True)
    except Exception:
        return {"error": "no game"}
    by_key = {c["key"].lower(): c["id"] for c in gamedata["champions"].values()}
    by_name = {c["name"].lower(): c["id"] for c in gamedata["champions"].values()}

    def champ_id(p):
        raw = (p.get("rawChampionName") or "").rsplit("_", 1)[-1].lower()
        return by_key.get(raw) or by_name.get((p.get("championName") or "").lower())

    act = d.get("activePlayer", {})
    me_ids = {act.get("riotId"), act.get("summonerName")} - {None, ""}
    players = d.get("allPlayers", [])
    me = next((p for p in players if p.get("riotId") in me_ids or p.get("summonerName") in me_ids), None)
    if not me:
        return {"error": "could not find you in the game"}
    team = me.get("team")
    alias = gamedata.get("item_alias", {})
    completed = {i for i, it in gamedata["items"].items() if it["completed"]}
    return {
        "champ": champ_id(me),
        "allies": [champ_id(p) for p in players if p.get("team") == team and p is not me],
        "enemies": [champ_id(p) for p in players if p.get("team") != team],
        "items": [int(alias.get(str(it["itemID"]), it["itemID"])) for it in me.get("items", [])
                  if alias.get(str(it.get("itemID")), str(it.get("itemID"))) in completed],
        "time": d.get("gameData", {}).get("gameTime"),
    }


def make_handler(cfg, gamedata):
    site = str(cfg["site_path"])
    history_file = cfg["data_path"] / "history.jsonl"
    lock = threading.Lock()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=site, **kw)

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/ping":
                return self.send_json({"ok": True})
            if path == "/api/me":
                return self.send_json(stats.personal(cfg, cfg["my_riot_ids"]))
            if path == "/api/live":
                return self.send_json(live_game(gamedata))
            if path == "/api/champselect":
                try:
                    cs = lcu.champ_select(cfg)
                except Exception as e:
                    return self.send_json({"error": str(e)})
                return self.send_json(cs or {"error": "Not in champion select"})
            if path == "/api/history":
                rows = []
                if history_file.exists():
                    with open(history_file, encoding="utf-8") as f:
                        rows = [json.loads(l) for l in f if l.strip()]
                return self.send_json(rows)
            return super().do_GET()

        def do_POST(self):
            if self.path != "/api/history":
                return self.send_json({"error": "not found"}, 404)
            size = int(self.headers.get("Content-Length", 0))
            if size > 100_000:
                return self.send_json({"error": "too large"}, 413)
            try:
                entry = json.loads(self.rfile.read(size))
            except ValueError:
                return self.send_json({"error": "bad json"}, 400)
            entry["saved"] = int(time.time())
            with lock, open(history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return self.send_json({"ok": True})

    return Handler


def serve(cfg, gamedata, port=None, open_browser=True, log=print):
    port = port or cfg["server_port"]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(cfg, gamedata))
    url = f"http://127.0.0.1:{port}/#/grade"
    log(f"Augur is running at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("Stopped.")
