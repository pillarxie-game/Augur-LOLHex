"""Generate FAKE games with known effects, to test that Augur's math finds them.

    python tools/make_demo_db.py --games 20000

Writes to data-demo/ (never mixed with real data). Hidden truths it plants:
  * Giant Slayer is strong when the enemy has 2+ tanks, useless otherwise
  * AP-only hexes hurt AD champions, AD-only hexes hurt AP champions
  * Two specific hexes are much stronger together (printed at the end)
  * Some champions are simply stronger than others
"""
import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from augur import config, db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=20000)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rnd = random.Random(args.seed)

    cfg = config.load()
    game = json.load(open(cfg["data_path"] / "gamedata.json", encoding="utf-8"))
    cfg["data_path"] = config.ROOT / "data-demo"
    cfg["data_path"].mkdir(exist_ok=True)
    dbfile = cfg["data_path"] / "augur.db"
    if dbfile.exists():
        dbfile.unlink()
    con = db.connect(cfg)

    champs = list(game["champions"].values())
    hexes = [a for a in game["augments"].values() if not a["disabled"]]
    by_rarity = {r: [a for a in hexes if a["rarity"] == r] for r in ("silver", "gold", "prismatic")}
    items = [i for i in game["items"].values() if i["completed"] and not i["boots"] and i["gold"] >= 2200]
    boots = [i for i in game["items"].values() if i["boots"] and i["completed"]]
    champ_power = {c["id"]: rnd.gauss(0, 0.15) for c in champs}
    hex_power = {a["id"]: rnd.gauss(0, 0.08) for a in hexes}
    item_power = {i["id"]: rnd.gauss(0, 0.05) for i in items}
    giant = next(a["id"] for a in hexes if a["name"] == "Giant Slayer")
    combo = tuple(sorted([rnd.choice(by_rarity["silver"])["id"], rnd.choice(by_rarity["gold"])["id"]]))

    def hex_value(c, a, enemies):
        v = hex_power[a["id"]]
        t = set(a["tags"])
        if "ap" in t and "ad" not in t and c["ap"] < 0.35:
            v -= 0.3
        if "ad" in t and "ap" not in t and c["ap"] > 0.65:
            v -= 0.3
        if a["id"] == giant:
            v += 0.45 if sum(e["flags"]["tank"] for e in enemies) >= 2 else -0.1
        return v

    patches = ["16.21", "16.20", "16.19"]
    for g in range(args.games):
        picked = rnd.sample(champs, 10)
        teams = {100: picked[:5], 200: picked[5:]}
        score = {}
        rows = []
        for team, members in teams.items():
            enemies = teams[300 - team]
            s = 0
            for c in members:
                owned = []
                for rarity in rnd.choice([["silver", "gold", "gold", "prismatic"], ["gold", "prismatic", "gold", "silver"],
                                          ["prismatic", "gold", "silver", "gold"]]):
                    offer = rnd.sample([a for a in by_rarity[rarity] if a["id"] not in owned], 3)
                    # players pick a little better than random
                    # and chase a known combo when half of it is owned
                    choice = max(offer, key=lambda a: hex_value(c, a, enemies) + rnd.gauss(0, 0.25)
                                 + (1 if a["id"] in combo and set(combo) & set(owned) else 0))
                    owned.append(choice["id"])
                v = champ_power[c["id"]] + sum(hex_value(c, game["augments"][str(h)], enemies) for h in owned)
                if combo[0] in owned and combo[1] in owned:
                    v += 0.5
                fit = [i for i in items if ("SpellDamage" in i["tags"]) == (c["ap"] > 0.5)] or items
                build = [rnd.choice(boots)["id"]] + [i["id"] for i in rnd.sample(fit, 4)]
                rnd.shuffle(build)
                v += sum(item_power.get(i, 0) for i in build)
                s += v
                prof_ap = c["ap"]
                rows.append({
                    "match_id": f"DEMO_{g}", "puuid": f"p{rnd.randrange(5000)}",
                    "riot_id": "DemoPlayer#DEMO" if rnd.random() < 0.002 else None,
                    "champ": c["id"], "team": team, "augs": ",".join(map(str, owned)),
                    "items": ",".join(map(str, build)), "build": ",".join(map(str, build)),
                    "dmg_phys": int(30000 * (1 - prof_ap)), "dmg_magic": int(30000 * prof_ap), "dmg_true": 1000,
                    "taken": int(20000 + 30000 * c["tankiness"]), "heal_ally": 2000 if c["flags"]["support"] else 0,
                    "shield_ally": 0, "cc": 20,
                })
            score[team] = s
        p100 = 1 / (1 + math.exp(-(score[100] - score[200])))
        win100 = rnd.random() < p100
        for r in rows:
            r["win"] = int(win100 == (r["team"] == 100))
        patch = patches[min(2, int(rnd.expovariate(1.2)))]
        db.save_game(con, {"match_id": f"DEMO_{g}", "patch": patch, "game_start": 0, "duration": 1100,
                           "queue": 2400, "source": "demo"}, rows)
        if g % 2000 == 0:
            con.commit()
    con.commit()
    names = [game["augments"][str(h)]["name"] for h in combo]
    print(f"Wrote {args.games} fake games to {dbfile}")
    print(f"Hidden combo: {names[0]} + {names[1]}  (ids {combo[0]}, {combo[1]})")
    json.dump({"combo": combo, "giant": giant}, open(cfg["data_path"] / "truth.json", "w"))


if __name__ == "__main__":
    main()
