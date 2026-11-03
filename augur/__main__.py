"""Augur command line.  Run `python -m augur --help`."""
import argparse
import json
import shutil
import sys
from pathlib import Path

from . import config, db, gamedata, stats

WEB = Path(__file__).resolve().parent / "web"


def need_gamedata(cfg):
    g = gamedata.load(cfg)
    if not g:
        print("No game data yet - downloading it first.")
        g = gamedata.update(cfg)
    return g


def use_demo(cfg):
    real = cfg["data_path"] / "gamedata.json"
    cfg["data_path"] = config.ROOT / "data-demo"
    if real.exists():
        shutil.copy2(real, cfg["data_path"] / "gamedata.json")
    cfg["site_path"] = config.ROOT / "site-demo"
    if not (cfg["data_path"] / "augur.db").exists():
        raise SystemExit("No demo games. Run: python tools/make_demo_db.py")


def build(cfg, g, demo=False):
    s = stats.build(cfg, g, demo=demo)
    site = cfg["site_path"]
    (site / "data").mkdir(parents=True, exist_ok=True)
    for f in WEB.iterdir():
        if f.is_file():
            shutil.copy2(f, site / f.name)
    (site / ".nojekyll").touch()
    with open(site / "data" / "gamedata.json", "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, separators=(",", ":"))
    stats.save(cfg, s, site / "data" / "stats.json")
    print(f"Website built in {site}")
    return s


def tierlist(cfg, g, champ=None, top=20):
    s = stats.build(cfg, g, log=lambda *a: None)
    glob = s["global"]
    gw = glob[1] / glob[0] if glob[0] else 0.5
    if champ:
        c = next((c for c in g["champions"].values() if champ.lower() in (c["key"].lower(), c["name"].lower(), c["name_zh"])), None)
        if not c:
            raise SystemExit(f"Unknown champion {champ}")
        table, title = s["hex"].get(str(c["id"]), {}), c["name"]
        cell = s["champ"].get(str(c["id"]), [0, 0])
        base = (cell[1] + 200 * gw) / (cell[0] + 200)
    else:
        table, title, base = s["hex_all"], "all champions", gw
    rows = []
    for h, (n, w) in table.items():
        a = g["augments"].get(h)
        if a and n:
            rows.append(((w + 100 * base) / (n + 100) - base, a, n, w / n))
    rows.sort(key=lambda r: -r[0])
    print(f"Top hexes for {title} ({s['meta']['total_games']} games)")
    for d, a, n, wr in rows[:top]:
        print(f"  {d * 100:+5.1f}  {wr * 100:5.1f}%  {int(n):>6} games  [{a['rarity']:<9}] {a['name']}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m augur", description="Augur: ARAM Mayhem hex stats and grades")
    p.add_argument("--demo", action="store_true", help="use the fake test games in data-demo/")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("update", help="download the hex list, champions and items (run after each patch)")
    c = sub.add_parser("collect", help="collect games through the Riot API")
    c.add_argument("--riot-id", help='start from this player, e.g. "Name#TAG"')
    c.add_argument("--games", type=int, default=1000)
    c.add_argument("--days", type=int, default=30, help="only games from the last N days")
    c.add_argument("--no-timeline", action="store_true", help="skip item order (twice as fast)")
    cc = sub.add_parser("collect-client", help="collect games through your League client (any server, incl. 国服)")
    cc.add_argument("--games", type=int, default=500)
    b = sub.add_parser("build", help="compute stats and build the website into docs/")
    sv = sub.add_parser("serve", help="run the local match helper in your browser")
    sv.add_argument("--port", type=int)
    sv.add_argument("--no-browser", action="store_true")
    sub.add_parser("info", help="how many games are collected, per patch")
    e = sub.add_parser("export", help="write all games to a shareable .jsonl.gz file (no player ids)")
    e.add_argument("file", nargs="?", default="dataset.jsonl.gz")
    i = sub.add_parser("import", help="add games from export files (duplicates are skipped)")
    i.add_argument("files", nargs="+")
    r = sub.add_parser("read", help="read the 3 offered hexes from screenshots (or the screen now)")
    r.add_argument("files", nargs="*", help="image files; none = take a screenshot now")
    o = sub.add_parser("opgg", help="show OP.GG's ARAM hex stats for a champion")
    o.add_argument("champ")
    o.add_argument("--top", type=int, default=15)
    t = sub.add_parser("tierlist", help="print the best hexes, overall or for one champion")
    t.add_argument("--champ")
    t.add_argument("--top", type=int, default=20)
    args = p.parse_args(argv)

    cfg = config.load()
    if args.demo:
        use_demo(cfg)
    if args.cmd == "update":
        g = gamedata.update(cfg)
        from . import screen
        if screen.available():
            screen.load_icons(cfg, g)  # for reading cards from the screen
    elif args.cmd == "collect":
        from . import collect
        collect.run(cfg, need_gamedata(cfg), args.riot_id, args.games, args.days, not args.no_timeline)
    elif args.cmd == "collect-client":
        from . import lcu
        lcu.collect_games(cfg, need_gamedata(cfg), args.games)
    elif args.cmd == "build":
        build(cfg, need_gamedata(cfg), demo=args.demo)
    elif args.cmd == "serve":
        from . import server
        g = need_gamedata(cfg)
        if args.demo or not (cfg["site_path"] / "index.html").exists():
            build(cfg, g, demo=args.demo)
        else:  # keep the site's code current even when stats are not rebuilt
            for f in WEB.iterdir():
                if f.is_file():
                    shutil.copy2(f, cfg["site_path"] / f.name)
        server.serve(cfg, g, args.port, not args.no_browser)
    elif args.cmd == "info":
        con = db.connect(cfg)
        rows = db.info(con)
        total = sum(n for p, n in rows if p != "remake")
        print(f"{total} games collected")
        for patch, n in rows:
            print(f"  patch {patch}: {n}")
    elif args.cmd == "export":
        print(f"Exported {db.export(db.connect(cfg), args.file)} games to {args.file}")
    elif args.cmd == "import":
        con = db.connect(cfg)
        for f in args.files:
            print(f"{f}: added {db.import_file(con, f)} games")
    elif args.cmd == "read":
        from . import screen
        g = need_gamedata(cfg)
        for f in args.files or [None]:
            res = screen.read_cards(f if f else screen.grab(), cfg, g)
            print(f"{f or 'screen'}  ({res['found']}/3 recognised{'' if res['ocr'] else ', icons only: OCR not installed'})")
            for c in res["cards"]:
                if c["id"]:
                    print(f"   {c['name']:<28} confidence {c['confidence']:.2f} (by {c['how']})")
                else:
                    print(f"   ?  {c['text'] or ''!r} {c['how'] or 'not recognised'}")
    elif args.cmd == "opgg":
        from . import opgg
        g = need_gamedata(cfg)
        c = next((c for c in g["champions"].values() if args.champ.lower() in
                  (c["key"].lower(), c["name"].lower(), *[n.lower() for n in c.get("names", {}).values()])), None)
        if not c:
            raise SystemExit(f"Unknown champion {args.champ}")
        d = opgg.aram_augments(c["id"])
        rows = sorted(((v[1], v[0], v[2], g["augments"].get(h, {}).get("name", f"(not in Mayhem pool: {h})"))
                       for h, v in d["augments"].items() if v[2] >= 0.01), reverse=True)
        print(f"OP.GG ARAM hex stats for {c['name']}: {len(d['augments'])} hexes listed, {len(rows)} with 1%+ popularity (OP.GG leaves out its top 2 tiers)")
        for perf, tier, pop, name in rows[:args.top]:
            print(f"  performance {perf:6.1f}  tier {tier}  popular {pop:.2f}  {name}")
    elif args.cmd == "tierlist":
        tierlist(cfg, need_gamedata(cfg), args.champ, args.top)


if __name__ == "__main__":
    sys.exit(main())
