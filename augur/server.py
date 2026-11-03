"""Local helper: serves the website plus a small API that reads your running game and client.

Only listens on 127.0.0.1, so nothing is exposed to the network.
"""
import json
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import io

from . import config, lcu, net, opgg, screen, stats

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
    screen_lock = threading.Lock()  # one OCR at a time
    jobs = {"collect": {"running": False, "log": []}, "build": {"running": False, "log": []},
            "opgg_all": {"running": False, "log": []}}

    def run_job(name, fn):
        job = jobs[name]
        if job["running"]:
            return False
        job.update(running=True, log=[], error=None)

        def log(*a):
            job["log"] = (job["log"] + [" ".join(str(x) for x in a)])[-50:]

        def work():
            try:
                fn(log)
            except BaseException as e:  # SystemExit from the collectors carries a readable message
                job["error"] = str(e)
            finally:
                job["running"] = False
        threading.Thread(target=work, daemon=True).start()
        return True

    def rebuild(log):
        from . import __main__ as cli
        g = gamedata.load(cfg) or gamedata
        cli.build(cfg, g)
        log("Stats rebuilt.")

    def opgg_all(log):
        opgg.fetch_all(gamedata, log=log)

    cfg["_start_job"] = lambda name: run_job(name, {"opgg_all": opgg_all}[name])

    def collect(log):
        lcu.collect_games(cfg, gamedata, games=500, log=log)
        rebuild(log)

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
                return self.send_json({"ok": True, "desktop": bool(cfg.get("_desktop")), "settings": settings_view()})
            if path == "/api/settings":
                return self.send_json(settings_view())
            if path == "/api/job":
                return self.send_json(jobs)
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
            if path == "/api/screen":
                return self.read_screen(None)
            if path.startswith("/api/opgg") and not cfg.get("use_opgg", True):
                return self.send_json({"error": "OP.GG is turned off in settings"})
            if path == "/api/opgg_summary":
                f = config.ROOT / "data" / "opgg" / "summary.json"
                return self.send_json(json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"error": "not downloaded yet"})
            if path == "/api/opgg_build":
                from urllib.parse import parse_qs, urlparse
                champ = (parse_qs(urlparse(self.path).query).get("champ") or [""])[0]
                c = gamedata["champions"].get(champ)
                if not c:
                    return self.send_json({"error": "unknown champion"}, 400)
                try:
                    return self.send_json(opgg.champion_build(c["key"], c["id"]))
                except Exception as e:
                    return self.send_json({"error": f"OP.GG unavailable: {e}"})
            if path == "/api/opgg":
                from urllib.parse import parse_qs, urlparse
                champ = (parse_qs(urlparse(self.path).query).get("champ") or [""])[0]
                if not champ.isdigit():
                    return self.send_json({"error": "champ id needed"}, 400)
                try:
                    return self.send_json(opgg.aram_augments(int(champ)))
                except Exception as e:
                    return self.send_json({"error": f"OP.GG unavailable: {e}"})
            if path == "/api/history":
                rows = []
                if history_file.exists():
                    with open(history_file, encoding="utf-8") as f:
                        rows = [json.loads(l) for l in f if l.strip()]
                return self.send_json(rows)
            return super().do_GET()

        def read_screen(self, data):
            if not screen.available():
                return self.send_json({"error": "Screen reading needs: pip install -r requirements-screen.txt"})
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(data)) if data else screen.grab()
                with screen_lock:
                    return self.send_json(screen.read_cards(img, cfg, gamedata))
            except Exception as e:
                return self.send_json({"error": f"Could not read the screen: {e}"})

        def read_body(self, limit=100_000):
            size = int(self.headers.get("Content-Length", 0))
            if size > limit:
                raise ValueError("too large")
            return json.loads(self.rfile.read(size) or b"{}")

        def do_POST(self):
            if self.path == "/api/settings":
                try:
                    saved = config.save(self.read_body())
                except ValueError as e:
                    return self.send_json({"error": str(e)}, 400)
                cfg.update(saved)
                if cfg.get("_on_settings"):
                    cfg["_on_settings"](saved)
                return self.send_json(settings_view())
            if self.path in ("/api/collect", "/api/build", "/api/opgg_all"):
                name = self.path.rsplit("/", 1)[-1]
                started = run_job(name, {"collect": collect, "build": rebuild, "opgg_all": opgg_all}[name])
                return self.send_json({"started": started, "jobs": jobs})
            if self.path == "/api/screen":
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 20_000_000:
                    return self.send_json({"error": "image missing or too large"}, 413)
                return self.read_screen(self.rfile.read(size))
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

    def settings_view():
        out = {k: cfg.get(k) for k in config.EDITABLE}
        out["data_folder"] = str(config.ROOT)
        out["ocr_available"] = screen.available() and screen.ocr_engine() is not None
        return out

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
