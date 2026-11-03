"""Read the 3 offered hex cards from a screenshot.

Each card is found from its position (the cards sit at the same place relative to screen height
at any resolution). The name under the icon is read with OCR (English or 中文) and matched to
the hex list; the icon is compared with the official hex icons as a second check, and as the
only check when OCR isn't installed.

Needs: pip install -r requirements-screen.txt   (Pillow, numpy, rapidocr_onnxruntime)
"""
import concurrent.futures
import difflib
import re
import time
import urllib.request

from . import config

try:
    import numpy as np
    from PIL import Image
except ImportError:  # the rest of Augur works without these
    np = Image = None

# Card layout, in units of screen height, measured from real Mayhem screenshots.
CARD_DX = 0.487      # horizontal distance between card centers
ICON_Y = 0.278       # icon center
NAME_BAND = (0.42, 0.53)
NAME_HALF_WIDTH = 0.21
ICON_SIZES = (0.15, 0.17, 0.19, 0.21, 0.23)
S = 40               # icons are compared at 40x40 pixels

_ocr = None
_icons = None


def available():
    return np is not None


def ocr_engine():
    global _ocr
    if _ocr is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr = RapidOCR()
        except Exception:
            _ocr = False
    return _ocr or None


def _norm_vec(a):
    v = np.asarray(a, dtype=float).ravel()
    v -= v.mean()
    return v / (np.linalg.norm(v) + 1e-9)


def load_icons(cfg, gamedata, log=print):
    """Official hex icons as normalized 40x40 vectors (downloaded once into data/icons)."""
    global _icons
    if _icons is not None:
        return _icons
    folder = config.ROOT / "data" / "icons"  # shared by real and demo data
    folder.mkdir(parents=True, exist_ok=True)

    def fetch(a):
        p = folder / f"{a['id']}.png"
        for _ in range(2):
            if p.exists() or not a.get("icon"):
                return
            try:
                req = urllib.request.Request(a["icon"], headers={"User-Agent": "Augur/1.0"})
                p.write_bytes(urllib.request.urlopen(req, timeout=10).read())
            except Exception:
                time.sleep(1)

    missing = [a for a in gamedata["augments"].values() if not (folder / f"{a['id']}.png").exists()]
    if missing:
        log(f"Downloading {len(missing)} hex icons...")
        with concurrent.futures.ThreadPoolExecutor(8) as ex:
            list(ex.map(fetch, missing))
    ids, vecs = [], []
    for a in gamedata["augments"].values():
        p = folder / f"{a['id']}.png"
        if not p.exists():
            continue
        la = np.asarray(Image.open(p).convert("LA"), dtype=float) / 255
        glyph = Image.fromarray((la[..., 0] * la[..., 1] * 255).astype("uint8")).resize((S, S), Image.BILINEAR)
        ids.append(a["id"])
        vecs.append(_norm_vec(glyph))
    _icons = (ids, np.array(vecs))
    return _icons


def icon_scores(gray, cx, H, icons):
    ids, T = icons
    crops = []
    for size in ICON_SIZES:
        s = size * H
        for dx in (-0.02, -0.01, 0, 0.01, 0.02):
            for dy in (-0.02, -0.01, 0, 0.01, 0.02):
                x, y = cx + dx * H, ICON_Y * H + dy * H
                c = gray.crop((int(x - s / 2), int(y - s / 2), int(x + s / 2), int(y + s / 2)))
                crops.append(_norm_vec(c.resize((S, S), Image.BILINEAR)))
    best = (np.array(crops) @ T.T).max(0)
    return {ids[i]: float(best[i]) for i in range(len(ids))}


def name_key(s):
    return re.sub(r"[\W_]+", "", s.lower())


def read_name(rgb, cx, H):
    """OCR the name band of one card. Returns the text of its top line (the hex name)."""
    eng = ocr_engine()
    if not eng:
        return None
    box = (int(cx - NAME_HALF_WIDTH * H), int(NAME_BAND[0] * H), int(cx + NAME_HALF_WIDTH * H), int(NAME_BAND[1] * H))
    res, _ = eng(np.asarray(rgb.crop(box)))
    if not res:
        return ""
    lines = sorted(((min(p[1] for p in r[0]), min(p[0] for p in r[0]), r[1]) for r in res if r[2] > 0.5))
    if not lines:
        return ""
    top = lines[0][0]
    row_h = 0.03 * H
    return " ".join(t for y, x, t in sorted(lines, key=lambda l: l[1]) if y - top < row_h)


def match_name(text, gamedata):
    """Best hex for an OCR'd name, comparing with English and Chinese names."""
    key = name_key(text)
    if not key:
        return None, 0.0
    best, score = None, 0.0
    for a in gamedata["augments"].values():
        for n in (a["name"], a.get("name_zh") or ""):
            k = name_key(n)
            if not k:
                continue
            r = difflib.SequenceMatcher(None, key, k).ratio()
            if r > score:
                best, score = a, r
    return best, score


def read_cards(image, cfg, gamedata):
    """image: PIL image or path. Returns {'cards': [...3 dicts...], 'found': n, 'ocr': bool}."""
    if not available():
        raise RuntimeError("Screen reading needs Pillow and numpy: pip install -r requirements-screen.txt")
    if not hasattr(image, "size"):
        image = Image.open(image)
    rgb = image.convert("RGB")
    gray = rgb.convert("L")
    W, H = rgb.size
    icons = load_icons(cfg, gamedata)
    by_id = {a["id"]: a for a in gamedata["augments"].values()}
    use_ocr = ocr_engine() is not None
    cards = []
    for k in (-1, 0, 1):
        cx = W / 2 + k * CARD_DX * H
        isc = icon_scores(gray, cx, H, icons)
        text = read_name(rgb, cx, H) if use_ocr else None
        card = {"text": text, "id": None, "name": None, "confidence": 0.0, "how": None}
        if text and len(name_key(text)) < 2:
            text = ""  # stray marks, not a name
        if text:
            hit, ratio = match_name(text, gamedata)
            if hit and ratio >= 0.75:
                icon = isc.get(hit["id"], 0.0)
                card.update(id=hit["id"], name=hit["name"], confidence=round(0.8 * ratio + 0.2 * icon, 2), how="name")
            elif text.strip():
                card["how"] = "not in hex list"  # e.g. a hex Riot removed from Mayhem
        if card["id"] is None and not (text and text.strip()):
            # No readable name: fall back to the icon alone, only when it is clearly the best.
            ranked = sorted(isc.items(), key=lambda kv: -kv[1])
            (hid, s1), (_, s2) = ranked[0], ranked[1]
            if s1 >= 0.85 and s1 - s2 >= 0.03:
                card.update(id=hid, name=by_id[hid]["name"], confidence=round(s1, 2), how="icon")
        cards.append(card)
    return {"cards": cards, "found": sum(1 for c in cards if c["id"]), "ocr": use_ocr, "size": [W, H]}


def grab():
    """Screenshot of the main screen (Windows and macOS)."""
    from PIL import ImageGrab
    return ImageGrab.grab()
