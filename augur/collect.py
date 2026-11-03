"""Collect ARAM Mayhem games through the official Riot API (match-v5).

Starts from one Riot ID, then keeps adding the other players of every game it downloads
("snowball"), so collection spreads across the server.
"""
import collections
import json
import time
import urllib.parse

from . import db, net
from . import gamedata as gamedata_mod

ACCOUNT_REGION = {"americas": "americas", "asia": "asia", "europe": "europe", "sea": "asia"}


class RiotAPI:
    def __init__(self, key, region):
        if not key:
            raise SystemExit("No Riot API key. Put it in config.local.json as \"riot_api_key\" "
                             "or set the RIOT_API_KEY environment variable.")
        self.key = key
        self.region = region
        self.limits = [(20, 1), (100, 120)]  # dev key defaults; replaced by the server's headers
        self.sent = collections.deque()
        self.calls = 0

    def _wait(self):
        while True:
            now = time.time()
            longest = max(w for _, w in self.limits)
            while self.sent and now - self.sent[0] > longest:
                self.sent.popleft()
            pause = 0
            for limit, window in self.limits:
                recent = [t for t in self.sent if now - t < window]
                if len(recent) >= limit - 1:
                    pause = max(pause, window - (now - recent[0]) + 0.05)
            if pause <= 0:
                return
            time.sleep(pause)

    def get(self, host, path, params=None):
        url = f"https://{host}.api.riotgames.com{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        for attempt in range(6):
            self._wait()
            self.sent.append(time.time())
            self.calls += 1
            try:
                status, headers, body = net.request(url, {"X-Riot-Token": self.key}, timeout=20)
                self._read_limits(headers)
                return json.loads(body)
            except net.HTTPError as e:
                if e.status == 429:
                    time.sleep(float(e.headers.get("Retry-After", 10)) + 0.5)
                    continue
                if e.status in (401, 403):
                    raise SystemExit("Riot rejected the API key (it may have expired - dev keys last 24 hours). "
                                     "Get a new one at https://developer.riotgames.com")
                if e.status == 404:
                    return None
                if e.status >= 500:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
            except OSError:
                time.sleep(2 * (attempt + 1))
        return None

    def _read_limits(self, headers):
        spec = headers.get("X-App-Rate-Limit")
        if spec:
            try:
                self.limits = [tuple(int(x) for x in part.split(":")) for part in spec.split(",")]
            except ValueError:
                pass

    def account(self, riot_id):
        name, _, tag = riot_id.partition("#")
        if not tag:
            raise SystemExit('Riot ID must look like "Name#TAG"')
        path = f"/riot/account/v1/accounts/by-riot-id/{urllib.parse.quote(name)}/{urllib.parse.quote(tag)}"
        acc = self.get(ACCOUNT_REGION.get(self.region, self.region), path)
        if not acc:
            raise SystemExit(f"Riot ID {riot_id} not found in region {self.region}")
        return acc["puuid"]

    def match_ids(self, puuid, queue, start_time=None, count=100):
        params = {"queue": queue, "count": count}
        if start_time:
            params["startTime"] = int(start_time)
        return self.get(self.region, f"/lol/match/v5/matches/by-puuid/{puuid}/ids", params) or []

    def match(self, match_id):
        return self.get(self.region, f"/lol/match/v5/matches/{match_id}")

    def timeline(self, match_id):
        return self.get(self.region, f"/lol/match/v5/matches/{match_id}/timeline")


def build_orders(timeline, completed):
    """participantId -> completed item ids in the order they were bought."""
    orders = collections.defaultdict(list)
    if not timeline:
        return orders
    for frame in timeline.get("info", {}).get("frames", []):
        for ev in frame.get("events", []):
            pid = ev.get("participantId")
            if ev.get("type") == "ITEM_PURCHASED":
                orders[pid].append(ev.get("itemId"))
            elif ev.get("type") == "ITEM_UNDO" and ev.get("beforeId"):
                bought = orders[pid]
                for i in range(len(bought) - 1, -1, -1):
                    if bought[i] == ev["beforeId"]:
                        del bought[i]
                        break
    out = {}
    for pid, bought in orders.items():
        seen = []
        for iid in bought:
            if iid in completed and iid not in seen:
                seen.append(iid)
        out[pid] = seen
    return out


def parse_match(m, timeline, completed, source="riot-api"):
    """Turn a match-v5 record into (match_row, player_rows), or None for remakes."""
    info = m["info"]
    duration = info.get("gameDuration", 0)
    if duration > 100000:  # very old records used milliseconds
        duration //= 1000
    parts = info.get("participants", [])
    if duration < 300 or len(parts) != 10 or any(p.get("gameEndedInEarlySurrender") for p in parts):
        return None
    orders = build_orders(timeline, completed)
    players = []
    for p in parts:
        augs = [p.get(f"playerAugment{i}", 0) for i in range(1, 7)]
        name, tag = p.get("riotIdGameName") or p.get("summonerName") or "", p.get("riotIdTagline") or ""
        players.append({
            "match_id": m["metadata"]["matchId"],
            "puuid": p.get("puuid"),
            "riot_id": f"{name}#{tag}" if tag else name,
            "champ": p["championId"],
            "team": p["teamId"],
            "win": int(bool(p["win"])),
            "augs": ",".join(str(a) for a in augs if a),
            "items": ",".join(str(p.get(f"item{i}", 0)) for i in range(6) if p.get(f"item{i}")),
            "build": ",".join(str(i) for i in orders.get(p.get("participantId"), [])),
            "dmg_phys": p.get("physicalDamageDealtToChampions", 0),
            "dmg_magic": p.get("magicDamageDealtToChampions", 0),
            "dmg_true": p.get("trueDamageDealtToChampions", 0),
            "taken": p.get("totalDamageTaken", 0),
            "heal_ally": p.get("totalHealsOnTeammates", 0),
            "shield_ally": p.get("totalDamageShieldedOnTeammates", 0),
            "cc": p.get("timeCCingOthers", 0),
        })
    match = {
        "match_id": m["metadata"]["matchId"],
        "patch": db.patch_of(info.get("gameVersion")),
        "game_start": info.get("gameStartTimestamp") or info.get("gameCreation"),
        "duration": duration,
        "queue": info.get("queueId"),
        "source": source,
    }
    return match, players


def run(cfg, gamedata, riot_id=None, games=1000, days=30, timeline=True, log=print):
    api = RiotAPI(cfg["riot_api_key"], cfg["riot_region"])
    con = db.connect(cfg)
    completed = gamedata_mod.completed_ids(gamedata)
    if riot_id:
        con.execute("INSERT OR IGNORE INTO crawl VALUES (?, NULL)", (api.account(riot_id),))
        con.commit()
    start_time = time.time() - days * 86400
    added = skipped = 0
    started = time.time()
    while added < games:
        row = con.execute("SELECT puuid FROM crawl WHERE done_at IS NULL ORDER BY RANDOM() LIMIT 1").fetchone()
        if not row:
            # Queue empty: revisit players last checked more than 2 days ago.
            n = con.execute("UPDATE crawl SET done_at=NULL WHERE done_at < ?", (time.time() - 2 * 86400,)).rowcount
            if not n:
                log("No more players to visit. Start again with --riot-id of another Mayhem player.")
                break
            continue
        puuid = row[0]
        ids = []
        for q in cfg["queues"]:
            ids += api.match_ids(puuid, q, start_time)
        for mid in ids:
            if added >= games:
                break
            if db.has_match(con, mid):
                continue
            m = api.match(mid)
            if not m:
                continue
            parsed = parse_match(m, api.timeline(mid) if timeline else None, completed)
            if not parsed:
                skipped += 1
                db.save_game(con, {"match_id": mid, "patch": "remake", "source": "skip"}, [])
                continue
            match, players = parsed
            db.save_game(con, match, players)
            con.executemany("INSERT OR IGNORE INTO crawl VALUES (?, NULL)",
                            [(p["puuid"],) for p in players if p["puuid"]])
            added += 1
            if added % 10 == 0:
                con.commit()
                rate = added / max(1, time.time() - started) * 3600
                log(f"  {added}/{games} games  (patch {match['patch']}, ~{rate:.0f} games/hour, {api.calls} API calls)")
        con.execute("UPDATE crawl SET done_at=? WHERE puuid=?", (int(time.time()), puuid))
        con.commit()
    con.commit()
    log(f"Done: added {added} games ({skipped} remakes skipped).")
    return added
