"""SQLite storage for collected games. One row per game, one row per player."""
import gzip
import json
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id   TEXT PRIMARY KEY,
    patch      TEXT NOT NULL,      -- "16.21"
    game_start INTEGER,            -- ms since epoch
    duration   INTEGER,            -- seconds
    queue      INTEGER,
    source     TEXT                -- riot-api / client
);
CREATE TABLE IF NOT EXISTS players (
    match_id TEXT NOT NULL,
    puuid    TEXT,
    riot_id  TEXT,                 -- "Name#TAG"
    champ    INTEGER NOT NULL,
    team     INTEGER NOT NULL,     -- 100 / 200
    win      INTEGER NOT NULL,
    augs     TEXT NOT NULL,        -- hex ids in pick order, "1205,1324,..."
    items    TEXT NOT NULL,        -- final items
    build    TEXT NOT NULL,        -- completed items in purchase order ("" without a timeline)
    dmg_phys INTEGER, dmg_magic INTEGER, dmg_true INTEGER,
    taken    INTEGER, heal_ally INTEGER, shield_ally INTEGER, cc INTEGER,
    PRIMARY KEY (match_id, champ, team)
);
CREATE TABLE IF NOT EXISTS crawl (
    puuid   TEXT PRIMARY KEY,
    done_at INTEGER                -- NULL = waiting in the queue
);
CREATE INDEX IF NOT EXISTS players_riot ON players(riot_id);
"""

PLAYER_COLS = ["match_id", "puuid", "riot_id", "champ", "team", "win", "augs", "items", "build",
               "dmg_phys", "dmg_magic", "dmg_true", "taken", "heal_ally", "shield_ally", "cc"]
MATCH_COLS = ["match_id", "patch", "game_start", "duration", "queue", "source"]


def connect(cfg):
    con = sqlite3.connect(cfg["data_path"] / "augur.db")
    con.executescript(SCHEMA)
    return con


def has_match(con, match_id):
    return con.execute("SELECT 1 FROM matches WHERE match_id=?", (match_id,)).fetchone() is not None


def save_game(con, match, players):
    """match: dict with MATCH_COLS. players: list of dicts with PLAYER_COLS."""
    con.execute(f"INSERT OR IGNORE INTO matches VALUES ({','.join('?' * len(MATCH_COLS))})",
                [match.get(c) for c in MATCH_COLS])
    con.executemany(f"INSERT OR IGNORE INTO players VALUES ({','.join('?' * len(PLAYER_COLS))})",
                    [[p.get(c) for c in PLAYER_COLS] for p in players])


def patch_of(game_version):
    parts = (game_version or "").split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else "unknown"


def patch_key(patch):
    try:
        return tuple(int(x) for x in patch.split("."))
    except ValueError:
        return (0,)


def info(con):
    rows = con.execute("SELECT patch, COUNT(*) FROM matches GROUP BY patch").fetchall()
    return sorted(rows, key=lambda r: patch_key(r[0]), reverse=True)


def export(con, path):
    """Write every game as one JSON line (gzip). Personal ids are dropped, so the file is safe to share."""
    n = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for row in con.execute(f"SELECT {','.join(MATCH_COLS)} FROM matches"):
            m = dict(zip(MATCH_COLS, row))
            ps = con.execute(f"SELECT {','.join(PLAYER_COLS)} FROM players WHERE match_id=?", (m["match_id"],))
            m["players"] = [{**dict(zip(PLAYER_COLS, p)), "puuid": None, "riot_id": None} for p in ps]
            f.write(json.dumps(m, separators=(",", ":")) + "\n")
            n += 1
    return n


def import_file(con, path):
    added = 0
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            m = json.loads(line)
            if has_match(con, m["match_id"]):
                continue
            save_game(con, m, m.pop("players"))
            added += 1
    con.commit()
    return added
