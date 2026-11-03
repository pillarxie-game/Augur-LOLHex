"""Tests for parsing Riot match records, the client's format, and dataset export/import.

    python -m unittest discover tests
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from augur import collect, config, db, gamedata, lcu, opgg, stats  # noqa: E402

GAME = json.load(open(ROOT / "data" / "gamedata.json", encoding="utf-8"))
COMPLETED = gamedata.completed_ids(GAME)
CHAMPS = [c["id"] for c in GAME["champions"].values()][:10]
HEXES = [a["id"] for a in GAME["augments"].values()][:6]
IE = next(int(i) for i, it in GAME["items"].items() if it["name"] == "Infinity Edge")


def fake_match(mid="KR_1", version="16.21.723.4567", duration=1200):
    parts = []
    for i, c in enumerate(CHAMPS):
        p = {"participantId": i + 1, "championId": c, "teamId": 100 if i < 5 else 200, "win": i < 5,
             "puuid": f"puuid{i}", "riotIdGameName": f"P{i}", "riotIdTagline": "KR1",
             "item0": IE, "item1": 1001, "physicalDamageDealtToChampions": 20000,
             "magicDamageDealtToChampions": 5000, "totalDamageTaken": 30000}
        for k, h in enumerate(HEXES[:4]):
            p[f"playerAugment{k + 1}"] = h
        parts.append(p)
    return {"metadata": {"matchId": mid},
            "info": {"gameDuration": duration, "gameVersion": version, "gameStartTimestamp": 1, "queueId": 2400,
                     "participants": parts}}


def fake_timeline():
    ev = [{"type": "ITEM_PURCHASED", "participantId": 1, "itemId": 1001},
          {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": IE},
          {"type": "ITEM_UNDO", "participantId": 1, "beforeId": IE, "afterId": 0},
          {"type": "ITEM_PURCHASED", "participantId": 1, "itemId": IE}]
    return {"info": {"frames": [{"events": ev}]}}


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config.load()
        self.cfg["data_path"] = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_match(self):
        match, players = collect.parse_match(fake_match(), fake_timeline(), COMPLETED)
        self.assertEqual(match["patch"], "16.21")
        self.assertEqual(len(players), 10)
        p = players[0]
        self.assertEqual(p["augs"], ",".join(map(str, HEXES[:4])))
        self.assertEqual(p["build"], str(IE))  # boots-less: only the completed item, undo handled
        self.assertEqual(p["riot_id"], "P0#KR1")
        self.assertEqual(p["win"], 1)

    def test_remake_skipped(self):
        self.assertIsNone(collect.parse_match(fake_match(duration=200), None, COMPLETED))

    def test_client_format(self):
        g = {"gameId": 5, "platformId": "HN1", "gameVersion": "16.21.1", "gameDuration": 1100, "queueId": 2400,
             "participants": [{"participantId": i + 1, "championId": c, "teamId": 100 if i < 5 else 200,
                               "stats": {"win": i < 5, "item0": IE, "playerAugment1": HEXES[0]}} for i, c in enumerate(CHAMPS)],
             "participantIdentities": [{"participantId": i + 1, "player": {"puuid": f"x{i}", "gameName": "名字", "tagLine": "123"}}
                                       for i in range(10)]}
        match, players = collect.parse_match(lcu.to_match_v5(g), None, COMPLETED, source="client")
        self.assertEqual(match["match_id"], "HN1_5")
        self.assertEqual(players[3]["augs"], str(HEXES[0]))
        self.assertEqual(players[0]["riot_id"], "名字#123")

    def test_stats_and_export_roundtrip(self):
        con = db.connect(self.cfg)
        for i in range(3):
            m, ps = collect.parse_match(fake_match(f"KR_{i}"), fake_timeline(), COMPLETED)
            db.save_game(con, m, ps)
        con.commit()
        s = stats.build(self.cfg, GAME, log=lambda *a: None)
        self.assertEqual(s["meta"]["total_games"], 3)
        self.assertEqual(s["hex_all"][str(HEXES[0])], [30.0, 15.0])
        self.assertEqual(s["item"][str(CHAMPS[0])][str(IE)][0], 3.0)
        out = Path(self.tmp.name) / "d.jsonl.gz"
        self.assertEqual(db.export(con, out), 3)
        cfg2 = dict(self.cfg, data_path=Path(self.tmp.name) / "b")
        cfg2["data_path"].mkdir()
        con2 = db.connect(cfg2)
        self.assertEqual(db.import_file(con2, out), 3)
        self.assertEqual(db.import_file(con2, out), 0)  # duplicates skipped
        self.assertIsNone(con2.execute("SELECT puuid FROM players LIMIT 1").fetchone()[0])  # ids stripped

    def test_opgg_parse(self):
        text = 'class Augment: id,tier,performance,popular\nX(Data([Augment(1349,3,80.89,0.2),Augment(1028,5,85,0.19)]))'
        self.assertEqual(opgg.parse_augments(text), {"1349": [3, 80.89, 0.2], "1028": [5, 85.0, 0.19]})

    def test_patch_weights(self):
        con = db.connect(self.cfg)
        for i, v in enumerate(["16.19.1", "16.20.1", "16.21.1", "16.18.1"]):
            m, ps = collect.parse_match(fake_match(f"KR_{i}", v), None, COMPLETED)
            db.save_game(con, m, ps)
        con.commit()
        self.assertEqual(stats.patch_weights(con, self.cfg), {"16.21": 1.0, "16.20": 0.5, "16.19": 0.25})


if __name__ == "__main__":
    unittest.main()
