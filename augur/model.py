"""A small model that fills in OP.GG hex tiers where OP.GG has no entry for a champion.

Training data: OP.GG's real tier for each (champion, hex) pair:
    T1-T2 (a tracked hex OP.GG leaves out for the champion) = 2, T3 = 1, T4 = 0, T5 = -1.
Pairs with no information (ability hexes a champion can't get, hexes OP.GG rarely tracks) are what
the model predicts. It learns from similar champions and similar hexes:

    value(c, h) = mean + champion bias + hex bias + champion factors · hex factors
                  + champion traits (class, AP/AD, range) x hex traits (tags, rarity)

It is checked on held-out real tiers before use; if it does not beat a simple baseline
(mean + biases), its predictions are not published.
"""
import json
import time

try:
    import numpy as np
except ImportError:
    np = None

from . import config

TIER_VALUE = {3: 1.0, 4: 0.0, 5: -1.0}
TOP_VALUE = 2.0
CHAMP_TAGS = ["Fighter", "Tank", "Mage", "Assassin", "Marksman", "Support"]


def _features(gamedata, champs, hexes):
    hex_tags = sorted({t for h in hexes for t in gamedata["augments"][h].get("tags", [])})
    C = np.array([[1.0 if t in gamedata["champions"][c]["tags"] else 0.0 for t in CHAMP_TAGS]
                  + [gamedata["champions"][c]["ap"], 1.0 if gamedata["champions"][c]["flags"]["ranged"] else 0.0]
                  for c in champs])
    H = np.array([[1.0 if t in gamedata["augments"][h].get("tags", []) else 0.0 for t in hex_tags]
                  + [1.0 if gamedata["augments"][h]["rarity"] == r else 0.0 for r in ("silver", "gold", "prismatic")]
                  for h in hexes])
    return C, H


def _own_hex_stats():
    """Hex win rates from your collected games (current patch), if any: champion -> hex -> [games, wins]."""
    cfg = config.load()
    path = cfg["site_path"] / "data" / "stats.json"
    try:
        s = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    if s.get("meta", {}).get("demo"):
        return {}, {}
    return s.get("hex", {}), s.get("champ", {})


def build_matrix(gamedata):
    """Observed values Y and weights W (0 = unknown), plus the champion and hex order.

    Inputs, all real data:
      * OP.GG tier per champion: T1-T2 = 2, T3 = 1, T4 = 0, T5 = -1 (gaps.py decides what a missing hex means)
      * OP.GG pick rate: inside a tier, hexes players pick more often for that champion rank a bit higher
      * Your collected games: real hex win rate vs the champion's average, weighted by games; with enough
        games this outweighs OP.GG
    """
    folder = config.ROOT / "data" / "opgg"
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    gaps = {c: set(v) for c, v in summary.get("gaps", {}).items()}
    unknown = {c: set(v) for c, v in summary.get("unknown", {}).items()}
    build_fit = {c: set(v) for c, v in summary.get("build_fit", {}).items()}
    own_hex, own_champ = _own_hex_stats()
    champs = [c for c in gamedata["champions"] if (folder / f"{c}.json").exists()]
    hexes = [h for h, a in gamedata["augments"].items() if not a.get("disabled") and h in summary["hexes"]]
    Y = np.zeros((len(champs), len(hexes)))
    W = np.zeros_like(Y)
    for i, c in enumerate(champs):
        aug = json.loads((folder / f"{c}.json").read_text(encoding="utf-8"))["augments"]
        logs = [np.log(e[2] + 0.003) for e in aug.values()]
        mu, sd = (float(np.mean(logs)), float(np.std(logs)) or 1.0) if logs else (0.0, 1.0)
        for j, h in enumerate(hexes):
            e = aug.get(h)
            if e and e[0] in TIER_VALUE:
                pick = max(-1.0, min(1.0, (np.log(e[2] + 0.003) - mu) / sd))
                Y[i, j] = TIER_VALUE[e[0]] + 0.4 * pick  # picked more often -> a little higher in its tier
                W[i, j] = 1.0 if e[2] >= 0.01 else 0.5  # rarely picked: OP.GG's tier is less certain
            elif not e and h in build_fit.get(c, ()):
                Y[i, j], W[i, j] = TOP_VALUE, 1.0  # the champion's OP.GG build fits this hex
            elif not e and h in unknown.get(c, ()):
                pass  # not enough evidence: the model estimates it
            elif not e and h in gaps.get(c, ()):
                Y[i, j], W[i, j] = -1.0, 0.6  # missing because almost nobody takes it on this champion
            elif not e and summary["hexes"][h].get("infer_top"):
                Y[i, j], W[i, j] = TOP_VALUE, 0.8
            # your games: real win rate of this hex on this champion
            g = (own_hex.get(c) or {}).get(h)
            cg = own_champ.get(c)
            if g and g[0] >= 20 and cg and cg[0]:
                base = cg[1] / cg[0]
                wr = (g[1] + 150 * base) / (g[0] + 150)  # small samples pulled to the champion's average
                yo = max(-1.5, min(2.5, 0.5 + (wr - base) * 100 / 4))  # +6 points of win rate ~ top tier
                wo = 2.0 * g[0] / (g[0] + 150)
                Y[i, j] = (W[i, j] * Y[i, j] + wo * yo) / (W[i, j] + wo)
                W[i, j] += wo
    return Y, W, champs, hexes


def fit(Y, W, C, H, k=6, reg=0.05, steps=1500, lr=0.03, seed=0, biases_only=False):
    rng = np.random.default_rng(seed)
    n, m = Y.shape
    mu = (W * Y).sum() / max(W.sum(), 1)
    P = {"bc": np.zeros(n), "bh": np.zeros(m), "U": rng.normal(0, 0.1, (n, k)), "V": rng.normal(0, 0.1, (m, k)),
         "B": np.zeros((C.shape[1], H.shape[1]))}
    adam = {key: [np.zeros_like(v), np.zeros_like(v)] for key, v in P.items()}

    def predict(P):
        out = mu + P["bc"][:, None] + P["bh"][None, :]
        if not biases_only:
            out = out + P["U"] @ P["V"].T + C @ P["B"] @ H.T
        return out

    for t in range(1, steps + 1):
        E = W * (predict(P) - Y)  # weighted error on observed cells only
        g = {"bc": E.sum(1), "bh": E.sum(0)}
        if not biases_only:
            g["U"] = E @ P["V"] + reg * P["U"] * W.sum(1, keepdims=True).clip(1)
            g["V"] = E.T @ P["U"] + reg * P["V"] * W.sum(0, keepdims=True).T.clip(1)
            g["B"] = C.T @ E @ H + reg * 10 * P["B"]
        for key, grad in g.items():
            grad = grad / max(W.sum(), 1) * n  # scale-free step size
            m1, m2 = adam[key]
            m1[:] = 0.9 * m1 + 0.1 * grad
            m2[:] = 0.999 * m2 + 0.001 * grad ** 2
            P[key] -= lr * (m1 / (1 - 0.9 ** t)) / (np.sqrt(m2 / (1 - 0.999 ** t)) + 1e-8)
    return predict(P)


def scores(Y, W, pred, champs, hexes, low_sample=20000, overrides=None, unavailable=None):
    """Augur score 0-100 for every (champion, hex): its position among that champion's own hexes.
    96 = better than about 96% of the champion's hexes. Based on OP.GG's real tier, ordered inside the
    tier by similar champions (the model); pairs without OP.GG data use the model's estimate.
    Champions with few OP.GG games lean more on similar champions."""
    folder = config.ROOT / "data" / "opgg"
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    rarely = {(c, h) for c, hs in summary.get("gaps", {}).items() for h in hs}
    for c in champs:  # listed, but popularity rounds to 0: nobody picks it
        aug = json.loads((folder / f"{c}.json").read_text(encoding="utf-8"))["augments"]
        rarely |= {(c, h) for h, e in aug.items() if e[2] < 0.005}
    if unavailable is None:
        unavailable = {c: set(v) for c, v in summary.get("unavailable", {}).items()}
    out, low = {}, []
    for i, c in enumerate(champs):
        skip = unavailable.get(c, set())  # hexes this champion is never offered: no score at all
        try:
            play = json.loads((folder / f"build_{c}.json").read_text(encoding="utf-8")).get("play") or 0
        except (OSError, ValueError):
            play = 0
        few = play < low_sample
        if few:
            low.append(c)
        a, spread = (0.3, 1.0) if few else (0.5, 0.75)
        vals = []
        ov = (overrides or {}).get(c, {})
        for j in range(len(hexes)):
            if j in ov:  # build-style decision (see style_scores): replaces OP.GG's mixed-style numbers
                vals.append(ov[j])
                continue
            if W[i, j] > 0:
                t = Y[i, j]
                v = a * t + (1 - a) * float(np.clip(pred[i, j], t - spread, t + spread))
                if (c, hexes[j]) in rarely:  # (almost) nobody picks it on this champion: rank it at the bottom
                    v = min(v, -1.0) - 0.5
                vals.append(v)
            else:
                vals.append(float(pred[i, j]) - 0.25)  # estimate only: a little below an equal real tier
        keep = [j for j in range(len(hexes)) if hexes[j] not in skip]
        v = np.array([vals[j] for j in keep])
        order = v.argsort()
        ranks = np.empty(len(v))
        ranks[order] = np.arange(len(v))
        # ties share the average position
        for val in np.unique(v):
            idx = v == val
            ranks[idx] = ranks[idx].mean()
        # up to 90 by position among the champion's hexes; 91-100 only for a hex clearly ahead of its
        # other top hexes (more than half a standard deviation above the champion's 95th percentile)
        q95, sd = float(np.percentile(v, 95)), float(v.std()) or 1.0
        row = {}
        for k, j in enumerate(keep):
            sc = 90 * (ranks[k] + 0.5) / len(v)
            extra = (v[k] - q95) / sd - 0.5
            if extra > 0:
                sc += min(10, 10 * extra)
            row[hexes[j]] = int(round(sc))
        out[c] = row
    return out, low


def style_scores(Y, W, pred, champs, hexes):
    """For champions OP.GG shows building both AP and AD (Kai'Sa), scores for each build style.
    OP.GG's numbers mix both styles, so within a style: hexes of that damage type (and, for AP, hexes that
    make abilities apply on-hit) count as top tier; hexes of the other type count as almost never taken."""
    summary = json.loads((config.ROOT / "data" / "opgg" / "summary.json").read_text(encoding="utf-8"))
    types, styles = summary.get("hex_type", {}), summary.get("styles", {})
    out = {}
    for c, kinds in styles.items():
        if c not in champs:
            continue
        i = champs.index(c)
        out[c] = {}
        onhit = "onhit" in kinds
        for style in [k for k in kinds if k in ("ap", "ad")]:
            ov = {}
            for j, h in enumerate(hexes):
                t = types.get(h)
                if style == "ap" and t == "ap_onhit" and onhit:
                    ov[j] = TOP_VALUE + 0.9  # AP on-hit build: abilities applying on-hit is a standout
                elif t == style or (style == "ap" and t == "ap_onhit"):
                    ov[j] = TOP_VALUE + 0.3 * float(np.tanh(pred[i, j]))  # top tier for this style, ordered by the model
                elif (style == "ap" and t == "ad") or (style == "ad" and t in ("ap", "ap_onhit")):
                    ov[j] = -1.5  # wrong damage type for this style
            row, _ = scores(Y[i:i + 1], W[i:i + 1], pred[i:i + 1], [c], hexes, overrides={c: ov})
            out[c][style] = row[c]
    return out


def _score(pred, Y, mask):
    err = (pred - Y)[mask]
    rmse = float(np.sqrt((err ** 2).mean()))
    to_class = lambda v: np.digitize(v, [-0.5, 0.5, 1.5])  # T5, T4, T3, T1-T2
    acc = float((to_class(pred[mask]) == to_class(Y[mask])).mean())
    return rmse, acc


def train(gamedata, log=print, folds=5):
    if np is None:
        log("Model skipped: numpy not installed.")
        return None
    Y, W, champs, hexes = build_matrix(gamedata)
    C, H = _features(gamedata, champs, hexes)
    obs = np.argwhere(W > 0)
    rng = np.random.default_rng(1)
    fold = rng.integers(0, folds, len(obs))
    res = {"model": [], "baseline": []}
    for f in range(folds):
        test = obs[fold == f]
        Wtr = W.copy()
        Wtr[test[:, 0], test[:, 1]] = 0
        mask = np.zeros_like(W, dtype=bool)
        mask[test[:, 0], test[:, 1]] = True
        res["model"].append(_score(fit(Y, Wtr, C, H), Y, mask))
        res["baseline"].append(_score(fit(Y, Wtr, C, H, biases_only=True), Y, mask))
    m = np.mean(res["model"], axis=0)
    b = np.mean(res["baseline"], axis=0)
    metrics = {"rmse": round(float(m[0]), 3), "tier_accuracy": round(float(m[1]), 3),
               "baseline_rmse": round(float(b[0]), 3), "baseline_tier_accuracy": round(float(b[1]), 3),
               "observed_pairs": int(len(obs)), "predicted_pairs": int((W == 0).sum())}
    useful = m[0] < b[0] and m[1] >= b[1]
    log(f"Model check on held-out OP.GG tiers: tier accuracy {m[1]:.1%} (baseline {b[1]:.1%}), "
        f"error {m[0]:.2f} (baseline {b[0]:.2f}) -> {'used' if useful else 'NOT used'}")
    pred = fit(Y, W, C, H)
    out = {"metrics": metrics, "useful": bool(useful), "built": int(time.time()), "pred": {}, "full": {},
           "scores": {}, "low_sample": [], "game_version": gamedata.get("version")}
    if useful:
        for i, c in enumerate(champs):
            row = {hexes[j]: round(float(pred[i, j]), 2) for j in range(len(hexes)) if W[i, j] == 0}
            if row:
                out["pred"][c] = row
            # every pair: used to order hexes inside one OP.GG tier (which of a champion's ~116 T1-T2 hexes
            # are also top for similar champions); checked against independent rankings for Yasuo and Lux
            out["full"][c] = {hexes[j]: round(float(pred[i, j]), 2) for j in range(len(hexes))}
        out["scores"], out["low_sample"] = scores(Y, W, pred, champs, hexes)
        out["style_scores"] = style_scores(Y, W, pred, champs, hexes)
    (config.ROOT / "data" / "opgg" / "model.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return out
