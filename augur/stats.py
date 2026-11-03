"""Turn collected games into win-rate tables (stats.json), used by the website and the grader.

Every table cell is [games, wins]. Games from older patches count less (patch_decay per patch),
so grades follow the current balance instead of lagging behind it.
"""
import collections
import itertools
import json
import time

from . import db

# Team situations whose effect on each hex is measured from data.
# side: whose champions are counted; flag: champion flag from gamedata; test: count >= n (or == n).
FEATURES = {
    "etank":    {"side": "enemy", "flag": "tank",   "op": ">=", "n": 2},
    "eap":      {"side": "enemy", "flag": "apdmg",  "op": ">=", "n": 3},
    "ead":      {"side": "enemy", "flag": "apdmg",  "op": "<=", "n": 1},
    "eheal":    {"side": "enemy", "flag": "healer", "op": ">=", "n": 2},
    "anofront": {"side": "ally",  "flag": "front",  "op": "<=", "n": 0},
}


def active_features(flags_of, allies, enemies):
    out = []
    for name, f in FEATURES.items():
        champs = enemies if f["side"] == "enemy" else allies
        n = sum(1 for c in champs if flags_of(c).get(f["flag"]))
        if (n >= f["n"]) if f["op"] == ">=" else (n <= f["n"]):
            out.append(name)
    return out


def cell():
    return [0.0, 0.0]


def add(c, w, win):
    c[0] += w
    c[1] += w * win


def patch_weights(con, cfg):
    patches = [p for p, _ in db.info(con) if p not in ("remake", "unknown")]
    return {p: cfg["patch_decay"] ** i for i, p in enumerate(patches[: cfg["patches_kept"]])}


def build(cfg, gamedata, demo=False, log=print):
    con = db.connect(cfg)
    weights = patch_weights(con, cfg)
    champs = gamedata["champions"]
    no_flags = {}
    alias = gamedata.get("item_alias", {})

    def flags_of(cid):
        return champs.get(str(cid), {}).get("flags", no_flags)

    glob = cell()
    champ = collections.defaultdict(cell)
    hex_all = collections.defaultdict(cell)
    hexc = collections.defaultdict(lambda: collections.defaultdict(cell))
    round_all = collections.defaultdict(lambda: collections.defaultdict(cell))
    pair_all = collections.defaultdict(cell)
    pairc = collections.defaultdict(lambda: collections.defaultdict(cell))
    ctx = collections.defaultdict(lambda: collections.defaultdict(cell))
    ctx_base = collections.defaultdict(cell)
    item_all = collections.defaultdict(lambda: [0.0, 0.0, [cell() for _ in range(6)]])
    itemc = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0, 0.0, [cell() for _ in range(6)]]))
    prof = collections.defaultdict(lambda: [0] * 7)
    pr_n = collections.Counter()
    games_per_patch = collections.Counter()

    def add_item(t, w, win, slot):
        t[0] += w
        t[1] += w * win
        if slot < 6:
            add(t[2][slot], w, win)

    placeholders = ",".join("?" * len(weights)) or "''"
    q = f"""SELECT m.match_id, m.patch, p.champ, p.team, p.win, p.augs, p.build,
                   p.dmg_phys, p.dmg_magic, p.dmg_true, p.taken, p.heal_ally, p.shield_ally, p.cc
            FROM matches m JOIN players p ON p.match_id = m.match_id
            WHERE m.patch IN ({placeholders}) ORDER BY m.match_id"""
    for mid, rows in itertools.groupby(con.execute(q, list(weights)), key=lambda r: r[0]):
        rows = list(rows)
        if len(rows) != 10:
            continue
        w = weights[rows[0][1]]
        games_per_patch[rows[0][1]] += 1
        teams = collections.defaultdict(list)
        for r in rows:
            teams[r[3]].append(r[2])
        for (_, _, c, team, win, augs, build_s, *nums) in rows:
            cs = str(c)
            allies = [x for x in teams[team] if x != c]
            enemies = [x for t, xs in teams.items() if t != team for x in xs]
            feats = active_features(flags_of, allies, enemies)
            add(glob, w, win)
            add(champ[cs], w, win)
            for f in feats:
                add(ctx_base[f], w, win)
            hs = [h for h in augs.split(",") if h] if augs else []
            for r_i, h in enumerate(hs):
                add(hex_all[h], w, win)
                add(hexc[cs][h], w, win)
                add(round_all[h][str(r_i + 1)], w, win)
                for f in feats:
                    add(ctx[h][f], w, win)
            for a, b in itertools.combinations(sorted(set(hs), key=int), 2):
                k = f"{a}_{b}"
                add(pair_all[k], w, win)
                add(pairc[cs][k], w, win)
            for slot, iid in enumerate(alias.get(i, i) for i in (build_s or "").split(",") if i):
                add_item(item_all[iid], w, win, slot)
                add_item(itemc[cs][iid], w, win, slot)
            pr = prof[cs]
            for i, v in enumerate(nums):
                pr[i] += v or 0
            pr_n[cs] += 1

    def r2(c):
        return [round(c[0], 2), round(c[1], 2)]

    def item_out(t):
        return [round(t[0], 2), round(t[1], 2), [r2(s) for s in t[2]]]

    # Champion profiles from real damage numbers (fall back to Data Dragon when a champion has no games).
    tot = [0.0] * 7
    n_all = sum(pr_n.values()) or 1
    for cs, pr in prof.items():
        for i in range(7):
            tot[i] += pr[i]
    avg_taken = tot[3] / n_all or 1
    avg_help = (tot[4] + tot[5]) / n_all or 1
    profile = {}
    for cs, pr in prof.items():
        n = pr_n[cs]
        dmg = pr[0] + pr[1] + pr[2]
        profile[cs] = {
            "n": n,
            "ap": round(pr[1] / dmg, 2) if dmg else None,
            "taken": round(pr[3] / n / avg_taken, 2),
            "help": round((pr[4] + pr[5]) / n / avg_help, 2),
        }

    out = {
        "meta": {
            "generated": time.strftime("%Y-%m-%d %H:%M"),
            "game_version": gamedata["version"],
            "patches": weights,
            "games": dict(games_per_patch),
            "total_games": sum(games_per_patch.values()),
            "demo": demo,
            "features": FEATURES,
        },
        "global": r2(glob),
        "champ": {k: r2(v) for k, v in champ.items()},
        "hex_all": {k: r2(v) for k, v in hex_all.items()},
        "hex": {c: {h: r2(v) for h, v in t.items()} for c, t in hexc.items()},
        "round_all": {h: {r: r2(v) for r, v in t.items()} for h, t in round_all.items()},
        "pair_all": {k: r2(v) for k, v in pair_all.items() if v[0] >= 3},
        "pair": {c: {k: r2(v) for k, v in t.items() if v[0] >= 2} for c, t in pairc.items()},
        "ctx_base": {k: r2(v) for k, v in ctx_base.items()},
        "ctx": {h: {f: r2(v) for f, v in t.items()} for h, t in ctx.items()},
        "item_all": {k: item_out(v) for k, v in item_all.items()},
        "item": {c: {i: item_out(v) for i, v in t.items() if v[0] >= 2} for c, t in itemc.items()},
        "profile": profile,
    }
    log(f"Stats from {out['meta']['total_games']} games: "
        + ", ".join(f"patch {p} x{w:g} ({games_per_patch[p]} games)" for p, w in weights.items()))
    return out


def personal(cfg, riot_ids):
    """Your own record per hex (all patches, unweighted). Stays on your PC - never published."""
    if not riot_ids:
        return None
    con = db.connect(cfg)
    q = f"SELECT win, augs FROM players WHERE riot_id IN ({','.join('?' * len(riot_ids))})"
    glob, hexes = cell(), collections.defaultdict(cell)
    for win, augs in con.execute(q, riot_ids):
        add(glob, 1, win)
        for h in (augs or "").split(","):
            if h:
                add(hexes[h], 1, win)
    return {"global": glob, "hex": dict(hexes)}


def save(cfg, stats, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(stats, f, separators=(",", ":"))
