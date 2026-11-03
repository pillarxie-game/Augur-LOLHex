"""Screen reading test. Put Mayhem selection screenshots in tests/screens/ named after the
3 hexes, e.g. "Nightstalking+Dawnbringer's Resolve+Apex Inventor.jpg" (use "?" for a hex that
isn't in the current pool). Screenshots are not committed (they are Riot's game images).

    .venv/bin/python -m unittest tests.test_screen
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from augur import config, gamedata, screen  # noqa: E402

SHOTS = sorted((ROOT / "tests" / "screens").glob("*.*")) if (ROOT / "tests" / "screens").exists() else []


@unittest.skipUnless(screen.available() and screen.ocr_engine() and SHOTS, "needs OCR and tests/screens/*")
class ScreenReading(unittest.TestCase):
    def test_screenshots(self):
        cfg = config.load()
        g = gamedata.load(cfg)
        for shot in SHOTS:
            want = shot.stem.split("_", 1)[-1].split("+")
            got = [c["name"] or "?" for c in screen.read_cards(shot, cfg, g)["cards"]]
            with self.subTest(shot=shot.name):
                self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
