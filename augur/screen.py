"""Read the 3 offered hex cards from a screenshot.

Each card is found from its position (the cards sit at the same place relative to screen height
at any resolution). The name under the icon is read with OCR (English or 中文) and matched to
the hex list in all 16 languages (extra Korean and Japanese OCR models download on first use).
The card's rarity color and icon are a second check, and the fallback when a name can't be read.
When unsure, a card is never filled in: its 3 likeliest hexes are returned as "alternatives".

Needs: pip install -r requirements-screen.txt   (Pillow, numpy, rapidocr_onnxruntime)
"""
import concurrent.futures
import difflib
import re
import time
import unicodedata
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

# Extra OCR models for scripts the default model (Chinese + Latin) can't read. Downloaded on first use.
HF = "https://huggingface.co/SWHL/RapidOCR/resolve/main/PP-OCRv1/"
DICTS = "https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/release/2.7/ppocr/utils/dict/"
EXTRA_OCR = {
    "ko": ("korean_mobile_v2.0_rec_infer.onnx", "korean_dict.txt"),
    "ja": ("japan_rec_crnn.onnx", "japan_dict.txt"),
}

_ocr = {}
_icons = None


def available():
    return np is not None


def ocr_engine(lang="default"):
    """RapidOCR engine for 'default' (中文 + Latin scripts), 'ko' or 'ja'. None if unavailable."""
    if lang not in _ocr:
        try:
            from rapidocr_onnxruntime import RapidOCR
            if lang == "default":
                _ocr[lang] = RapidOCR()
            else:
                folder = config.ROOT / "data" / "ocr"
                folder.mkdir(parents=True, exist_ok=True)
                model, keys = EXTRA_OCR[lang]
                for name, url in ((model, HF + model), (keys, DICTS + keys)):
                    if not (folder / name).exists():
                        req = urllib.request.Request(url, headers={"User-Agent": "Augur/1.0"})
                        (folder / name).write_bytes(urllib.request.urlopen(req, timeout=60).read())
                _ocr[lang] = RapidOCR(rec_model_path=str(folder / model), rec_keys_path=str(folder / keys),
                                      rec_img_shape=[3, 32, 320])
        except Exception:
            _ocr[lang] = None
    return _ocr[lang]


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
        shape = Image.fromarray(((la[..., 1] > 0.5) * 255).astype("uint8")).resize((S, S), Image.BILINEAR)
        ids.append(a["id"])
        vecs.append(np.concatenate([_norm_vec(glyph), _norm_vec(shape)]))
    _icons = (ids, np.array(vecs))
    return _icons


def detect_rarity(rgb, W, H):
    """All 3 cards share a rarity. Gold frames are warm, prismatic frames lavender, silver neutral."""
    warm = []
    for k in (-1, 0, 1):
        cx = W / 2 + k * CARD_DX * H
        px = [rgb.getpixel((int(cx + dx), int(0.125 * H))) for dx in range(-20, 21, 5)]
        warm.append(sum(p[0] - p[2] for p in px) / len(px))
    m = sorted(warm)[1]  # median: the highlighted card can be tinted
    if m > 12:
        return "gold"
    if m < -8:
        return "prismatic"
    if -5 <= m <= 8:
        return "silver"
    return None


def icon_scores(gray, cx, H, icons):
    ids, T = icons
    crops = []
    for size in ICON_SIZES:
        s = size * H
        for dx in (-0.02, -0.01, 0, 0.01, 0.02):
            for dy in (-0.02, -0.01, 0, 0.01, 0.02):
                x, y = cx + dx * H, ICON_Y * H + dy * H
                c = np.asarray(gray.crop((int(x - s / 2), int(y - s / 2), int(x + s / 2), int(y + s / 2)))
                               .resize((S, S), Image.BILINEAR), dtype=float)
                bg = np.percentile(c, 30)  # the card's dark background
                crops.append(np.concatenate([_norm_vec(c), _norm_vec(c > bg + 40)]))
    # average of brightness match and shape match (each vector half is normalized, so max is 2)
    best = (np.array(crops) @ T.T).max(0) / 2
    return {ids[i]: float(best[i]) for i in range(len(ids))}


# OCR often reads Cyrillic/Greek letters as the Latin letters they look like. Fold both sides to one form.
LOOKALIKE = str.maketrans({
    "а": "a", "в": "b", "е": "e", "ё": "e", "к": "k", "м": "m", "н": "h", "о": "o", "р": "p", "с": "c",
    "т": "t", "у": "y", "х": "x", "ч": "4", "п": "n", "и": "u", "й": "u", "з": "3", "б": "6", "г": "r",
    "ш": "w", "щ": "w", "ь": "b", "ы": "bi", "л": "n", "д": "a", "я": "a", "ж": "x", "ц": "u", "э": "3",
    "ю": "io", "ф": "o", "ı": "i", "ß": "ss", "ł": "l", "đ": "d", "ø": "o",
})


def name_key(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).translate(LOOKALIKE)
    return re.sub(r"[\W_]+", "", s)


def read_rows(rgb, cx, H, lang="default"):
    """OCR the name band of one card. Returns its text rows, top first (the name, then the tag line)."""
    eng = ocr_engine(lang)
    if not eng:
        return None
    box = (int(cx - NAME_HALF_WIDTH * H), int(NAME_BAND[0] * H), int(cx + NAME_HALF_WIDTH * H), int(NAME_BAND[1] * H))
    res, _ = eng(np.asarray(rgb.crop(box)))
    words = sorted(((min(p[1] for p in r[0]), min(p[0] for p in r[0]), r[1]) for r in (res or []) if r[2] > 0.5))
    rows, row_h = [], 0.03 * H
    for y, x, t in words:
        if rows and y - rows[-1][0] < row_h:
            rows[-1][1].append((x, t))
        else:
            rows.append([y, [(x, t)]])
    return [" ".join(t for _, t in sorted(ws)) for _, ws in rows]


def text_similarity(texts, gamedata):
    """hex id -> best similarity (0..1) between any OCR row and any of the hex's names, in any language."""
    keys = [k for k in (name_key(t) for t in texts) if len(k) >= 2]
    sims = {}
    for a in gamedata["augments"].values():
        best = 0.0
        for n in {a["name"], *(a.get("names") or {}).values()}:
            k = name_key(n)
            for t in keys if k else []:
                best = max(best, difflib.SequenceMatcher(None, t, k).ratio())
        sims[a["id"]] = best
    return sims


def match_name(text, gamedata):
    sims = text_similarity([text], gamedata)
    hid = max(sims, key=sims.get)
    by_id = {a["id"]: a for a in gamedata["augments"].values()}
    return (by_id[hid], sims[hid]) if sims[hid] > 0 else (None, 0.0)


def read_cards(image, cfg, gamedata, use_ocr=None):
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
    if use_ocr is None:
        use_ocr = ocr_engine() is not None
    rarity = detect_rarity(rgb, W, H)
    scores = [icon_scores(gray, W / 2 + k * CARD_DX * H, H, icons) for k in (-1, 0, 1)]
    # Cheap check first: no card-like icons means no selection screen, so skip the slow OCR.
    if sum(1 for isc in scores if max(isc.values()) >= 0.6) < 2:
        empty = {"text": None, "id": None, "name": None, "confidence": 0.0, "how": None, "alternatives": [], "is_card": False}
        return {"cards": [dict(empty) for _ in range(3)], "found": 0, "on_screen": False,
                "ocr": use_ocr, "rarity": None, "size": [W, H]}
    sig = _signature(gray, W, H)
    if _last.get("sig") is not None and _last["sig"].shape == sig.shape and _last.get("use_ocr") == use_ocr \
            and np.abs(_last["sig"] - sig).max() < 40:  # no area changed visibly (a new name or icon would)
        return _last["result"]  # same cards as last time
    cards = []
    for k, isc in zip((-1, 0, 1), scores):
        cx = W / 2 + k * CARD_DX * H
        pool = [h for h in isc if not rarity or by_id[h]["rarity"] == rarity]
        lo, hi = np.percentile([isc[h] for h in pool], 50), max(isc[h] for h in pool)
        icon_rel = {h: max(0.0, (isc[h] - lo) / (hi - lo + 1e-9)) for h in pool}
        rows, sims = [], {}
        if use_ocr:
            for lang in ["default", *[l for l in cfg.get("ocr_extra", EXTRA_OCR) if l in EXTRA_OCR]]:
                got = read_rows(rgb, cx, H, lang) or []
                rows += got
                sims = text_similarity(rows, gamedata)
                if max(sims.values(), default=0) >= 0.8:
                    break  # name read clearly; no need for other scripts
        text = rows[0] if rows else ("" if use_ocr else None)
        card = {"text": text, "id": None, "name": None, "confidence": 0.0, "how": None, "alternatives": []}
        # A clearly read name wins whatever the frame color says; rarity only narrows icon matching.
        ranked_text = sorted(sims or pool, key=lambda h: -sims.get(h, 0))
        best_t = sims.get(ranked_text[0], 0) if ranked_text else 0
        # 1) the name alone is clear
        if best_t >= 0.75:
            h = ranked_text[0]
            card.update(id=h, confidence=round(0.8 * best_t + 0.2 * isc[h], 2), how="name")
        else:
            # 2) a partly read name plus the icon agree
            combo = sorted(pool, key=lambda h: -(0.5 * sims.get(h, 0) + 0.5 * icon_rel[h]))
            c1 = 0.5 * sims.get(combo[0], 0) + 0.5 * icon_rel[combo[0]]
            c2 = 0.5 * sims.get(combo[1], 0) + 0.5 * icon_rel[combo[1]] if len(combo) > 1 else 0
            if best_t >= 0.4 and sims.get(combo[0], 0) >= 0.4 and c1 - c2 >= 0.08:
                card.update(id=combo[0], confidence=round(c1, 2), how="name+icon")
            else:
                # 3) icon alone, only when clearly the best; otherwise offer the top candidates
                ranked = sorted(pool, key=lambda h: -isc[h])
                s1, s2 = isc[ranked[0]], isc[ranked[1]]
                same_icon = by_id[ranked[0]]["icon"].rsplit("/", 1)[-1] == by_id[ranked[1]]["icon"].rsplit("/", 1)[-1]
                looks_like_card = s1 >= 0.6  # non-card screens score about 0.2
                if s1 >= 0.88 and s1 - s2 >= 0.02 and not same_icon and best_t < 0.4:
                    card.update(id=ranked[0], confidence=round(0.9 * s1, 2), how="icon")
                elif looks_like_card:
                    # Not sure: never fill it in automatically, offer the likeliest hexes to pick from.
                    picks = sorted(pool, key=lambda h: -(0.5 * sims.get(h, 0) + 0.5 * icon_rel[h]))[:3]
                    card["alternatives"] = picks
                    card["how"] = "unsure"
                card["is_card"] = looks_like_card
        card.setdefault("is_card", True)
        if card["id"]:
            card["name"] = by_id[card["id"]]["name"]
        cards.append(card)
    on_screen = sum(1 for c in cards if c["id"] or c["is_card"]) >= 2
    result = {"cards": cards, "found": sum(1 for c in cards if c["id"]), "on_screen": on_screen,
              "ocr": use_ocr, "rarity": rarity if on_screen else None, "size": [W, H]}
    _last.update(sig=sig, result=result, use_ocr=use_ocr)
    return result


_last = {}


def _signature(gray, W, H):
    """Thumbnail of the three cards' icon and name area, to spot an unchanged screen (e.g. between checks)."""
    box = (int(W / 2 - 1.2 * H * CARD_DX), int(0.15 * H), int(W / 2 + 1.2 * H * CARD_DX), int(0.55 * H))
    return np.asarray(gray.crop(box).resize((360, 120), Image.BILINEAR), dtype=float)


def grab():
    """Screenshot of the main screen (Windows and macOS)."""
    from PIL import ImageGrab
    return ImageGrab.grab()
