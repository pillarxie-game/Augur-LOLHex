"""Talk to the League client running on this PC (works on every server, including 国服).

Used for: collecting games from match history, and reading champion select (bench grades).
"""
import base64
import collections
import time
from pathlib import Path

from . import collect, db, net
from . import gamedata as gamedata_mod


class Client:
    def __init__(self, cfg):
        lock = next((Path(p) for p in cfg["lockfile_paths"] if Path(p).exists()), None)
        if not lock:
            raise RuntimeError("League client not found. Start the client, or add its lockfile path "
                               "to \"lockfile_paths\" in config.local.json.")
        _, _, port, password, proto = lock.read_text().split(":")
        self.base = f"{proto}://127.0.0.1:{port}"
        token = base64.b64encode(f"riot:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}

    def get(self, path):
        try:
            return net.get_json(self.base + path, self.headers, timeout=10, retries=2, insecure=True)
        except net.HTTPError as e:
            if e.status == 404:
                return None
            raise


def to_match_v5(g):
    """The client's match history uses an older format. Convert it to match-v5 shape."""
    ids = {pi["participantId"]: pi.get("player", {}) for pi in g.get("participantIdentities", [])}
    parts = []
    for p in g.get("participants", []):
        s = p.get("stats", {})
        who = ids.get(p["participantId"], {})
        row = {k: v for k, v in s.items()}
        row.update({
            "participantId": p["participantId"],
            "championId": p["championId"],
            "teamId": p["teamId"],
            "win": s.get("win", False),
            "puuid": who.get("puuid"),
            "riotIdGameName": who.get("gameName") or who.get("summonerName"),
            "riotIdTagline": who.get("tagLine", ""),
        })
        parts.append(row)
    return {
        "metadata": {"matchId": f"{g.get('platformId', 'LCU')}_{g['gameId']}"},
        "info": {
            "gameDuration": g.get("gameDuration", 0),
            "gameVersion": g.get("gameVersion", ""),
            "gameCreation": g.get("gameCreation"),
            "queueId": g.get("queueId"),
            "participants": parts,
        },
    }


def collect_games(cfg, gamedata, games=500, log=print):
    cl = Client(cfg)
    me = cl.get("/lol-summoner/v1/current-summoner")
    if not me:
        raise SystemExit("Log in to the League client first.")
    con = db.connect(cfg)
    completed = gamedata_mod.completed_ids(gamedata)
    queues = set(cfg["queues"])
    todo = collections.deque([me["puuid"]])
    seen = {me["puuid"]}
    added = 0
    while todo and added < games:
        puuid = todo.popleft()
        hist = cl.get(f"/lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=49") or {}
        for g in hist.get("games", {}).get("games", []):
            if added >= games:
                break
            if g.get("queueId") not in queues:
                continue
            full = cl.get(f"/lol-match-history/v1/games/{g['gameId']}")
            if not full:
                continue
            m = to_match_v5(full)
            if db.has_match(con, m["metadata"]["matchId"]):
                continue
            tl = cl.get(f"/lol-match-history/v1/game-timelines/{g['gameId']}")
            parsed = collect.parse_match(m, tl and {"info": tl}, completed, source="client")
            time.sleep(0.2)
            if not parsed:
                continue
            match, players = parsed
            db.save_game(con, match, players)
            added += 1
            for p in players:
                if p["puuid"] and p["puuid"] not in seen:
                    seen.add(p["puuid"])
                    todo.append(p["puuid"])
            if added % 10 == 0:
                con.commit()
                log(f"  {added}/{games} games")
    con.commit()
    log(f"Done: added {added} games from the League client.")
    return added


def champ_select(cfg):
    """Return {'me': champId, 'team': [champIds], 'bench': [champIds]} or None outside champ select."""
    cl = Client(cfg)
    s = cl.get("/lol-champ-select/v1/session")
    if not s:
        return None
    cell = s.get("localPlayerCellId")
    me = next((p for p in s.get("myTeam", []) if p.get("cellId") == cell), {})
    return {
        "me": me.get("championId") or None,
        "team": [p["championId"] for p in s.get("myTeam", []) if p.get("championId") and p.get("cellId") != cell],
        "bench": [b["championId"] for b in s.get("benchChampions", []) if b.get("championId")],
        "enemies": [p["championId"] for p in s.get("theirTeam", []) if p.get("championId")],
    }
