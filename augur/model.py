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


def build_matrix(gamedata):
    """Observed values Y, weights W (0 = unknown), plus the champion and hex order."""
    folder = config.ROOT / "data" / "opgg"
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    champs = [c for c in gamedata["champions"] if (folder / f"{c}.json").exists()]
    hexes = [h for h, a in gamedata["augments"].items() if not a.get("disabled") and h in summary["hexes"]]
    Y = np.zeros((len(champs), len(hexes)))
    W = np.zeros_like(Y)
    for i, c in enumerate(champs):
        aug = json.loads((folder / f"{c}.json").read_text(encoding="utf-8"))["augments"]
        for j, h in enumerate(hexes):
            e = aug.get(h)
            if e and e[0] in TIER_VALUE:
                Y[i, j] = TIER_VALUE[e[0]]
                W[i, j] = 1.0 if e[2] >= 0.01 else 0.5  # rarely picked: OP.GG's tier is less certain
            elif not e and summary["hexes"][h].get("infer_top"):
                Y[i, j], W[i, j] = TOP_VALUE, 0.8
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
    out = {"metrics": metrics, "useful": bool(useful), "built": int(time.time()), "pred": {}, "full": {}}
    if useful:
        for i, c in enumerate(champs):
            row = {hexes[j]: round(float(pred[i, j]), 2) for j in range(len(hexes)) if W[i, j] == 0}
            if row:
                out["pred"][c] = row
            # every pair: used to order hexes inside one OP.GG tier (which of a champion's ~116 T1-T2 hexes
            # are also top for similar champions); checked against independent rankings for Yasuo and Lux
            out["full"][c] = {hexes[j]: round(float(pred[i, j]), 2) for j in range(len(hexes))}
    (config.ROOT / "data" / "opgg" / "model.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return out
