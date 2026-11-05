"""Why is a hex missing from OP.GG's list for a champion: top tier, or almost nobody takes it?

OP.GG lists only its tiers 3-5 per champion, so a missing hex is often in the champion's top tiers.
But OP.GG also leaves out hexes with (almost) no games on that champion. This tells them apart using
OP.GG's own data:

1. "Upgrade <item>" hexes: top tier only if the champion, or 2 of its most similar champions, build that
   item in OP.GG's ARAM builds. (Lux doesn't build Sundered Sky, so Upgrade Sundered Sky is a gap.)
2. Damage type: an AD / attack-speed hex missing for a champion whose OP.GG build is mostly AP items
   (or an AP hex for a mostly-AD build), or a mana hex for a champion without mana, is a gap.
3. Otherwise, the most similar champions vote: if they leave it out too, it is top for this kind of
   champion; if they list it as weak and rarely picked, it is a gap.

Checked against independent rankings: all 14 recommended Yasuo hexes and 14 of 14 Lux hexes stay top.
"""
import json
import re

try:
    import numpy as np
except ImportError:
    np = None

from . import config

AD_TAGS = {"ad", "attackspeed"}  # crit / on-hit hexes can work through abilities (Jeweled Gauntlet, Twin Fire)
LOW_SAMPLE = 20000  # champions with fewer OP.GG ARAM games: a missing hex alone doesn't mean top tier
RANGE_RE = re.compile(r"at least \D{0,3}\d{3,4} units|\d{3,4} units away|farther than \d+% of your (total )?attack range")
VAL = {3: 1, 4: 0, 5: -1}
NEIGHBOURS = 12


def _build_items(folder, cid, alias):
    try:
        b = json.loads((folder / f"build_{cid}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    ids = set(map(str, (b.get("core") or {}).get("ids", []))) | set(map(str, (b.get("boots") or {}).get("ids", [])))
    for recs in (b.get("slots") or {}).values():
        for r in recs:
            ids |= set(map(str, r["ids"]))
    return {alias.get(i, i) for i in ids}


def _upgraded_items(aug, items, by_name):
    """Items an "Upgrade X" hex upgrades: the ones its description names, else names starting with X."""
    desc = aug.get("desc", "").lower()
    named = {k for k, i in items.items() if i.get("completed") and i["name"].lower() in desc}
    if named:
        return named
    x = aug["name"][8:].lower()
    return {k for n, k in by_name.items() if n == x or n.startswith(x)}


def classify(gamedata, summary):
    """Returns {champion id: {hex id: "top" | "gap"}} for hexes OP.GG leaves out, plus champion neighbours."""
    if np is None:
        return {}, {}
    folder = config.ROOT / "data" / "opgg"
    A, items = gamedata["augments"], gamedata["items"]
    alias = gamedata.get("item_alias", {})
    champs = [c for c in gamedata["champions"] if (folder / f"{c}.json").exists()]
    hexes = [h for h, a in A.items() if not a.get("disabled") and h in summary["hexes"] and summary["hexes"][h].get("infer_top")]
    op = {c: json.loads((folder / f"{c}.json").read_text(encoding="utf-8"))["augments"] for c in champs}
    builds = {c: _build_items(folder, c, alias) for c in champs}
    by_name = {i["name"].lower(): k for k, i in items.items()}

    # champion similarity from OP.GG: same hexes left out, and similar tiers where both are listed
    M = np.full((len(champs), len(hexes)), np.nan)
    for i, c in enumerate(champs):
        for j, h in enumerate(hexes):
            e = op[c].get(h)
            if e and e[0] in VAL:
                M[i, j] = VAL[e[0]]
    listed = ~np.isnan(M)
    sim = np.zeros((len(champs), len(champs)))
    for i in range(len(champs)):
        same = (listed[i][None, :] == listed).mean(1)
        for k in range(len(champs)):
            both = listed[i] & listed[k]
            agree = 1 - np.abs(M[i, both] - M[k, both]).mean() / 2 if both.sum() > 10 else 0.5
            sim[i, k] = 0.6 * same[k] + 0.4 * agree
        sim[i, i] = -1

    # damage type from each champion's OP.GG build
    def ap_share(c):
        ap = ad = 0
        for iid in builds[c]:
            tags = set(items.get(iid, {}).get("tags", []))
            ap += "SpellDamage" in tags
            ad += bool(tags & {"Damage", "CriticalStrike", "AttackSpeed"}) and "SpellDamage" not in tags
        return ap / (ap + ad) if ap + ad else 0.5

    # Hexes with no description or tags (e.g. Lich Brain): OP.GG lists them (as weak) for the champions they
    # don't suit, so mostly-AD champions listing it means it is an AP hex, and the reverse.
    aps_all = {c: ap_share(c) for c in champs}
    inferred_type = {}
    for j, h in enumerate(hexes):
        if A[h].get("desc") or A[h].get("tags"):
            continue
        who = [aps_all[champs[i]] for i in range(len(champs)) if listed[i, j]]
        if len(who) >= 5:
            m = sum(who) / len(who)
            inferred_type[h] = "ap" if m < 0.4 else "ad" if m > 0.6 else None

    plays = {}
    for c in champs:
        try:
            plays[c] = json.loads((folder / f"build_{c}.json").read_text(encoding="utf-8")).get("play") or 0
        except (OSError, ValueError):
            plays[c] = 0

    out, neighbours = {}, {}
    for i, c in enumerate(champs):
        nb = [k for k in np.argsort(-sim[i]) if plays.get(champs[k], 0) >= LOW_SAMPLE][:NEIGHBOURS] \
            or list(np.argsort(-sim[i])[:NEIGHBOURS])  # learn from well-sampled lookalikes
        neighbours[c] = [champs[k] for k in nb[:5]]
        aps = aps_all[c]
        low = plays.get(c, 0) < LOW_SAMPLE
        ranged = gamedata["champions"][c]["flags"].get("ranged")
        mana = gamedata["champions"][c].get("partype") == "Mana"
        row = {}
        for j, h in enumerate(hexes):
            if listed[i, j]:
                continue
            a = A[h]
            tags = set(a.get("tags", []))
            if a["name"].startswith("Upgrade "):
                ups = _upgraded_items(a, items, by_name)
                built = bool(ups & builds[c]) or sum(bool(ups & builds[champs[k]]) for k in nb) >= 2
                row[h] = "top" if built else "gap"
                continue
            via_abilities = "abilit" in a.get("desc", "").lower()
            ad_only = (bool(tags & AD_TAGS) and "ap" not in tags and "adaptive" not in tags and not via_abilities) \
                or inferred_type.get(h) == "ad"
            ap_only = ("ap" in tags and "ad" not in tags and "adaptive" not in tags) or inferred_type.get(h) == "ap"
            needs_range = bool(RANGE_RE.search(a.get("desc", "").lower()))
            if (ad_only and aps > 0.7) or (ap_only and aps < 0.3) or ("mana" in tags and not mana) \
                    or (needs_range and not ranged):
                row[h] = "gap"
                continue
            top = gap = 0.0
            for k in nb:
                e = op[champs[k]].get(h)
                w = max(sim[i, k], 0)
                if not e:
                    top += w
                elif e[0] == 5 and e[2] < 0.01:
                    gap += w
                elif e[0] >= 4:
                    gap += 0.5 * w
            # few games on this champion: a missing hex is weaker evidence, so similar champions must clearly agree
            row[h] = "top" if top >= gap * (1.5 if low else 1.0) else "gap"
        out[c] = row
    return out, neighbours
