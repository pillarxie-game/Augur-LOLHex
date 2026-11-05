"""What a hex missing from OP.GG's list for a champion means.

OP.GG's tiers (3-5) follow popularity, and the hexes it lists for a champion already add up to about
4-5 picks per game, so a missing hex is one players almost never pick on that champion. It is NOT a
hidden top tier (that earlier assumption made rare hexes like Eureka look top tier on Darius).

Missing hexes are "gap" (useless for the champion, decided by the game itself) or "unknown":
1. a hex that needs range on a melee champion, or a mana hex on a champion without mana: gap
2. "Upgrade <item>" when neither the champion nor 2 similar champions build the item: gap
3. everything else: unknown, estimated by the model from similar champions and hexes
"""
import json
import re

try:
    import numpy as np
except ImportError:
    np = None

from . import config

AD_TAGS = {"ad", "attackspeed"}  # crit / on-hit hexes can work through abilities (Jeweled Gauntlet, Twin Fire)
LOW_SAMPLE = 20000  # fallback when no champion has game counts
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
        if {"ap", "ad", "attackspeed"} & set(A[h].get("tags", [])):
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

    def builds_tag(c, tag):
        return sum(tag in items.get(i, {}).get("tags", []) for i in builds[c])

    # "few games" is relative to this patch (early in a patch every champion has few games)
    low_cut = max(500, 0.5 * float(np.median([p for p in plays.values() if p] or [LOW_SAMPLE])))
    out, neighbours = {}, {}
    for i, c in enumerate(champs):
        nb = [k for k in np.argsort(-sim[i]) if plays.get(champs[k], 0) >= low_cut][:NEIGHBOURS] \
            or list(np.argsort(-sim[i])[:NEIGHBOURS])  # learn from well-sampled lookalikes
        neighbours[c] = [champs[k] for k in nb[:5]]
        aps = aps_all[c]
        ranged = gamedata["champions"][c]["flags"].get("ranged")
        mana = gamedata["champions"][c].get("partype") == "Mana"
        row = {}
        for j, h in enumerate(hexes):
            if listed[i, j]:
                continue
            a = A[h]
            tags = set(a.get("tags", []))
            # Only certain cases count as "nobody takes it": a hex that needs range on a melee champion, or a
            # mana hex on a champion without mana. Guesses from damage type, builds or similar champions were
            # tested against arammayhem.com's tagged combos and were no better than chance, so a missing hex
            # is otherwise "unknown" and the model estimates it.
            needs_range = bool(RANGE_RE.search(a.get("desc", "").lower()))
            if (needs_range and not ranged) or ("mana" in tags and not mana):
                row[h] = "gap"
            elif a["name"].startswith("Upgrade "):
                # upgrades an item: only useful if the champion (or 2 similar champions) actually build it
                ups = _upgraded_items(a, items, by_name)
                built = bool(ups & builds[c]) or sum(bool(ups & builds[champs[k]]) for k in nb) >= 2
                row[h] = "unknown" if built else "gap"
            else:
                # Not listed = almost never picked on this champion (the hexes OP.GG lists already add up to
                # about 4-5 picks per game). That alone doesn't say good or bad: the model estimates it.
                row[h] = "unknown"
        out[c] = row
    # hex damage type: from tags/description, else inferred from who OP.GG lists it as weak for
    hex_type = {}
    for h in hexes:
        a, tags = A[h], set(A[h].get("tags", []))
        via = "abilit" in a.get("desc", "").lower()
        if "onhit" in tags and via:
            hex_type[h] = "ap_onhit"  # abilities apply on-hit: great on AP on-hit builds (Ethereal Weapon on AP Kai'Sa)
        elif ("ap" in tags and "ad" not in tags) or inferred_type.get(h) == "ap":
            hex_type[h] = "ap"
        elif (tags & AD_TAGS and "ap" not in tags and not via) or inferred_type.get(h) == "ad":
            hex_type[h] = "ad"
    classify.hex_type = hex_type
    classify.ap_share = aps_all
    return out, neighbours
