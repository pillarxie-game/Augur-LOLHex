/* Augur grading engine. Runs in the browser and in Node (tests).
 *
 * Every grade is a sum of parts, each in win-rate points (+1.0 = about one percent more wins).
 * Each part comes with a reason. Small samples are pulled toward a prior:
 *     estimate = (games * data + K * prior) / (games + K)
 * so a hex with 10 lucky games barely moves, and rules ("AP hex on an AD champion") only
 * matter until there is enough data to measure the real effect.
 */
(function (root) {
  "use strict";

  const K = { champ: 200, hexAll: 100, champHex: 150, ctx: 300, pair: 120, round: 300,
              item: 100, slot: 150, personal: 20, bench: 200, champOpgg: 2000 };
  const GRADES = [[4.5, "S+"], [3, "S"], [1.5, "A"], [0, "B"], [-1.5, "C"], [-Infinity, "D"]];
  const TIERS = [[2.5, "S+"], [1.5, "S"], [0.5, "A"], [-0.5, "B"], [-1.5, "C"], [-Infinity, "D"]];
  const ON_HIT_CASTERS = new Set(["Kayle", "Teemo", "KogMaw", "Varus", "Kennen", "Kaisa", "Gwen", "Nilah"]);
  const STACK_TAGS = ["ap", "ad", "attackspeed", "onhit", "crit", "tank", "heal", "shield", "haste", "ms"];

  const I18N = typeof module !== "undefined" && module.exports ? require("./i18n.js") : root.AugurI18n;

  const n = (c) => (c ? c[0] : 0);
  const wr = (c) => (c && c[0] > 0 ? c[1] / c[0] : null);
  const smooth = (c, prior, k) => ((c ? c[1] : 0) + k * prior) / (n(c) + k);
  const shrink = (games, data, prior, k) => (games * data + k * prior) / (games + k);
  const pct = (x) => (x == null ? "-" : (100 * x).toFixed(1) + "%");
  const signed = (x) => (x >= 0 ? "+" : "") + x.toFixed(1) + "%";
  const games = (x) => Math.round(x).toLocaleString("en-US");

  // Tier value (2 = T1-T2, 1 = T3, 0 = T4, -1 = T5) -> label
  function tierLabel(v) { return v >= 1.5 ? "T1-T2" : v >= 0.5 ? "T3" : v >= -0.5 ? "T4" : "T5"; }

  function letter(total, table) {
    for (const [min, g] of table || GRADES) if (total >= min) return g;
    return "D";
  }

  class Grader {
    constructor(game, stats, opts) {
      opts = opts || {};
      this.game = game;
      this.s = stats || {};
      this.me = opts.personal || null;
      this.opgg = opts.opgg || {}; // champion id -> {augments: {hex id: [tier, performance, popular]}}
      this.opggBuild = opts.opggBuild || {};
      this.opggAll = (opts.opggAll && opts.opggAll.hexes) || {};
      this.opggChampions = (opts.opggAll && opts.opggAll.champions) || null;
      this.opggChamps = (opts.opggAll && opts.opggAll.champ_stats) || {};
      this.model = (opts.model && opts.model.useful && opts.model.pred) || {}; // champion -> hex -> estimated tier value
      this.modelFull = (opts.model && opts.model.useful && opts.model.full) || {};
      this.scores = (opts.model && opts.model.scores) || {}; // champion -> hex -> Augur score 0-100 (computed each version)
      this.styleScores = (opts.model && opts.model.style_scores) || {}; // hybrid champions: champion -> "ap"/"ad" -> hex -> score
      this.style = null; // "ap" / "ad" for hybrid champions, set per grading call
      this.lowSample = new Set(((opts.model && opts.model.low_sample) || []).map(String));
      this.gaps = {}; // champion -> Set of hexes OP.GG leaves out because almost nobody takes them there
      for (const [c, list] of Object.entries((opts.opggAll && opts.opggAll.gaps) || {})) this.gaps[c] = new Set(list.map(String));
      this.unavailable = {}; // champion -> Set of hexes this champion is never offered (e.g. Draw Your Sword for melee)
      for (const [c, list] of Object.entries((opts.opggAll && opts.opggAll.unavailable) || {})) this.unavailable[c] = new Set(list.map(String));
      this.unknown = {}; // champion -> Set of hexes with too little evidence (the model estimates them)
      for (const [c, list] of Object.entries((opts.opggAll && opts.opggAll.unknown) || {})) this.unknown[c] = new Set(list.map(String)); // every pair, for ordering within a tier // champion id -> OP.GG ARAM win rate, games, tier // hex id -> {score, listed, best[]} across all champions // champion id -> OP.GG ARAM build (core, boots, item slots)
      this.lang = I18N.T[opts.lang] ? opts.lang : "en";
      this.g = wr(this.s.global) || 0.5;
      this.features = (this.s.meta && this.s.meta.features) || {};
      // Hand-written rules ("AP hex on an AD champion", "enemy has 3 tanks") are off by default:
      // grades use only real data (OP.GG and collected games). Tests can switch them on.
      this.rules = !!opts.rules;
    }

    t(key, vars) {
      let s = I18N.pick(this.lang, key) || key;
      for (const [k, v] of Object.entries(vars || {})) s = s.split("{" + k + "}").join(v);
      return s;
    }

    name(kind, id) {
      const o = (this.game[kind] || {})[String(id)];
      if (!o) return String(id);
      return (o.names && o.names[this.lang]) || (this.lang === "zh" && o.name_zh) || o.name;
    }

    champ(id) { return this.game.champions[String(id)] || null; }

    /* What kind of champion is this? Real damage data wins over Data Dragon's guesses. */
    profile(cid) {
      const c = this.champ(cid) || { tags: [], flags: {}, ap: 0.5, tankiness: 0.5, partype: "Mana", key: "" };
      const p = (this.s.profile || {})[String(cid)];
      const pn = p && p.ap != null ? p.n : 0;
      const ap = shrink(pn, pn ? p.ap : 0, c.ap, 30);
      const tank = Math.max(c.flags.tank ? 0.8 : c.tankiness, pn ? Math.min(1, (p.taken - 0.6) / 0.9) * pn / (pn + 30) : 0);
      const fighter = c.tags.includes("Fighter");
      return {
        ap, tank: tank >= 0.6, support: c.flags.support || (pn >= 30 && p.help > 2),
        auto: c.flags.marksman || (fighter && ap < 0.45) || ON_HIT_CASTERS.has(c.key),
        mage: c.tags[0] === "Mage", front: !!c.flags.front, mana: c.partype === "Mana",
      };
    }

    champWR(cid) { return smooth((this.s.champ || {})[String(cid)], this.g, K.champ); }

    /* How strong a champion is, for ranking champions. Never uses your personal record.
       OP.GG's ARAM win rate (tens of thousands of games) is the base; Augur's collected games
       only move it once there are thousands of them, so a few of your own games can't reorder champions. */
    champRating(cid) {
      const own = (this.s.champ || {})[String(cid)], oc = this.opggChamps[String(cid)];
      if (oc && oc.win_rate && oc.play) {
        const w = smooth(own, oc.win_rate, K.champOpgg);
        return { wr: w, games: oc.play + n(own), src: n(own) >= 500 ? "mixed" : "opgg", op: oc, own };
      }
      return { wr: smooth(own, this.g, K.bench), games: n(own), src: n(own) ? "own" : "none", own };
    }

    hexAllDelta(h) { return (smooth((this.s.hex_all || {})[String(h)], this.g, K.hexAll) - this.g) * 100; }

    hexTier(h) { return letter(this.hexAllDelta(h), TIERS); }

    fitRules(cid, aug) {
      if (!this.rules) return [];
      const p = this.profile(cid), tags = new Set(aug.tags || []), out = [];
      const cname = this.name("champions", cid);
      const apOnly = tags.has("ap") && !tags.has("ad") && !tags.has("adaptive");
      const adOnly = tags.has("ad") && !tags.has("ap") && !tags.has("adaptive");
      if (apOnly && p.ap < 0.35) out.push({ v: -3, text: this.t("apOnAd") });
      else if (apOnly && p.ap > 0.65) out.push({ v: 1, text: this.t("fitsAp") });
      if (adOnly && p.ap > 0.65) out.push({ v: -3, text: this.t("adOnAp") });
      else if (adOnly && p.ap < 0.35) out.push({ v: 0.8, text: this.t("fitsAd") });
      if (tags.has("attackspeed") || tags.has("onhit") || tags.has("crit")) {
        if (p.auto) out.push({ v: 1, text: this.t("fitsAuto") });
        else if (p.ap > 0.6 || p.mage) out.push({ v: -2, text: this.t("noAuto", { c: cname }) });
      }
      if (tags.has("mana") && !p.mana) out.push({ v: -3, text: this.t("noMana") });
      if (tags.has("tank") && p.tank) out.push({ v: 1, text: this.t("fitsTank") });
      if (tags.has("support") && p.support) out.push({ v: 1.2, text: this.t("fitsSupport") });
      else if (tags.has("support") && !tags.has("ap") && !tags.has("ad") && !p.support)
        out.push({ v: -1, text: this.t("notSupport", { c: cname }) });
      return out;
    }

    activeFeatures(allies, enemies) {
      const out = {};
      for (const [name, f] of Object.entries(this.features)) {
        const champs = f.side === "enemy" ? enemies : allies;
        if (champs.length < (f.side === "enemy" ? 3 : 2)) continue; // team not known yet
        const hits = champs.filter((c) => { const ch = this.champ(c); return ch && ch.flags[f.flag]; });
        const k = hits.length;
        if (f.op === ">=" ? k >= f.n : k <= f.n) out[name] = hits;
      }
      return out;
    }

    contextParts(cid, h, aug, allies, enemies) {
      const tags = new Set(aug.tags || []), p = this.profile(cid), out = [];
      const feats = this.activeFeatures(allies, enemies);
      const names = (ids) => ids.map((c) => this.name("champions", c)).join(", ");
      const enemyTanks = enemies.filter((c) => (this.champ(c) || { flags: {} }).flags.tank);
      for (const [f, hits] of Object.entries(feats)) {
        let prior = 0;
        if (f === "etank" && tags.has("antitank")) prior = Math.min(2.4, 0.8 * (hits.length - 1) + 0.8);
        if (f === "eap" && tags.has("mr")) prior = 1.2;
        if (f === "ead" && tags.has("armor")) prior = 1.2;
        if (f === "anofront" && tags.has("tank")) prior = p.front ? 1.2 : 0.5;
        const cellHF = ((this.s.ctx || {})[String(h)] || {})[f];
        const games_ = n(cellHF);
        let lift = 0;
        if (games_ > 0) {
          const base = wr((this.s.ctx_base || {})[f]) || this.g;
          const hw = wr((this.s.hex_all || {})[String(h)]) || this.g;
          lift = ((wr(cellHF) - base) - (hw - this.g)) * 100;
        }
        if (!this.rules) prior = 0;
        if (!this.rules && games_ < 50) continue; // not measured yet: no real data, so nothing to say
        const v = shrink(games_, lift, prior, K.ctx);
        if (Math.abs(v) < 0.2 && !prior) continue;
        let text = this.t(f, { k: hits.length, names: names(hits) });
        if (games_ >= 50) text += " · " + this.t("dataNote", { d: signed(lift), n: games(games_) });
        out.push({ v, text });
      }
      if (this.rules && tags.has("antitank") && enemyTanks.length === 0 && enemies.length >= 3)
        out.push({ v: -0.5, text: this.t("fewTanks") });
      return out;
    }

    synergyParts(h, aug, owned) {
      const out = [];
      const hw = smooth((this.s.hex_all || {})[String(h)], this.g, K.hexAll);
      for (const o of owned) {
        if (String(o) === String(h)) continue;
        const oa = this.game.augments[String(o)];
        if (!oa) continue;
        const shared = STACK_TAGS.filter((t) => (aug.tags || []).includes(t) && (oa.tags || []).includes(t));
        const prior = this.rules ? Math.min(1.2, 0.4 * shared.length) : 0;
        const [a, b] = [Number(h), Number(o)].sort((x, y) => x - y);
        const cell = (this.s.pair_all || {})[a + "_" + b];
        let lift = 0;
        if (n(cell) > 0) {
          const ow = smooth((this.s.hex_all || {})[String(o)], this.g, K.hexAll);
          lift = ((wr(cell) - ow) - (hw - this.g)) * 100;
        }
        if (!this.rules && n(cell) < 30) continue;
        const v = shrink(n(cell), lift, prior, K.pair);
        if (Math.abs(v) < 0.2) continue;
        const text = n(cell) >= 30 || !shared.length
          ? this.t("synergy", { h: this.name("augments", o), d: signed(lift) }) + ` (${games(n(cell))})`
          : this.t("stacks", { h: this.name("augments", o), t: shared.join(", ") });
        out.push({ v, text });
      }
      return out;
    }

    /* OP.GG across all champions: tier-based strength (used when there is nothing for this champion). */
    opggAllPart(h) {
      const a = this.opggAll[String(h)];
      if (!a || a.strength == null) return null;
      return { v: Math.max(-1.5, Math.min(1.5, a.strength)) * 0.5, src: "opgg",
               text: this.t("opggAllR2", { k: a.top_champs || 0, n: this.opggChampions || "-" }) };
    }

    opggTier(h) {
      const a = this.opggAll[String(h)];
      if (!a || a.strength == null) return null;
      return letter(a.strength, [[1.4, "S+"], [0.9, "S"], [0.4, "A"], [-0.2, "B"], [-0.5, "C"], [-Infinity, "D"]]);
    }

    /* OP.GG for this champion. OP.GG lists only its tiers 3-5; a hex it tracks but leaves out for this
       champion is in that champion's top tiers (1-2). The tier counts most; performance is a small adjustment. */
    /* Build styles this champion has its own scores for (e.g. Kai'Sa: ["ap", "ad"]). */
    stylesFor(cid) { return Object.keys(this.styleScores[String(cid)] || {}); }

    /* Pick AP or AD from the items you own (for hybrid champions), else null (mixed). */
    styleFromItems(cid, items) {
      if (!this.stylesFor(cid).length || !items || !items.length) return null;
      let ap = 0, ad = 0;
      for (const i of items) {
        const t = new Set((this.game.items[String(i)] || {}).tags || []);
        if (t.has("SpellDamage")) ap++; else if (t.has("Damage") || t.has("CriticalStrike") || t.has("AttackSpeed")) ad++;
      }
      return ap > ad ? "ap" : ad > ap ? "ad" : null;
    }

    opggPart(cid, h) {
      const styled = this.style && (this.styleScores[String(cid)] || {})[this.style];
      const sc = (styled || this.scores[String(cid)] || {})[String(h)];
      const o = this.opgg[String(cid)];
      if (sc != null && o && o.augments) {
        const base = this.opggPartRaw(cid, h, o);
        const pts = this.pointsForPct(cid, sc / 100);
        let text = this.t("scoreR", { s: sc, c: this.name("champions", cid) });
        if (styled) text += " · " + this.t(this.style === "ap" ? "styleAP" : "styleAD");
        if (base && base.text) text += " · " + base.text.split(" · ")[0];
        if (this.lowSample.has(String(cid))) text += " · " + this.t("lowSample");
        return { v: pts, src: base && base.src === "model" ? "model" : "opgg", text, score: sc };
      }
      if (!o || !o.augments) return this.opggAllPart(h);
      return this.opggPartRaw(cid, h, o);
    }

    opggPartRaw(cid, h, o) {
      if (!o._stats) {
        const perf = Object.values(o.augments).filter((x) => x[2] >= 0.01).map((x) => x[1]).sort((a, b) => a - b);
        const med = perf[Math.floor(perf.length / 2)] || 0;
        const sd = Math.sqrt(perf.reduce((t, x) => t + (x - med) ** 2, 0) / Math.max(1, perf.length)) || 1;
        o._stats = { med, sd };
      }
      const e = o.augments[String(h)];
      const cname = this.name("champions", cid);
      const full = this.modelFull[String(cid)] || {};
      const tierV = this.tierValue(cid, h);
      const isGap = !e && this.gaps[String(cid)] && this.gaps[String(cid)].has(String(h));
      const toPoints = (v) => this.pointsFor(cid, v); // position among this champion's own hexes -> grade points
      if (tierV == null) {
        const est = (this.model[String(cid)] || {})[String(h)];
        if (est != null) // OP.GG has nothing for this pair: the model's estimate from similar champions, trusted less
          return { v: 0.8 * toPoints(est), src: "model", text: this.t("opggModelR", { c: cname, t: ((this.scores[String(cid)] || {})[String(h)] ?? "-") + "/100" }) };
        return { v: 0, text: this.t("opggNone") };
      }
      // Inside one tier, order by how the hex does for similar champions (the model), anchored to OP.GG's real tier
      const m = full[String(h)];
      const v = m != null ? 0.5 * tierV + 0.5 * Math.max(tierV - 0.75, Math.min(tierV + 0.75, m)) : tierV;
      let text = e ? this.t("opggR", { c: cname, t: e[0], p: e[1].toFixed(1), m: (o._stats || { med: 0 }).med.toFixed(1) })
                   : isGap ? this.t("opggGap", { c: cname }) : this.t("opggTop", { c: cname });
      const rk = this.tierRank(cid, h, tierV);
      if (rk) text += " · " + this.t("rankNote", { r: rk[0], n: rk[1] });
      return { v: toPoints(v), src: "opgg", text };
    }

    /* The OP.GG-based value (tier, ordered within the tier by similar champions) for one pair, before grading. */
    /* OP.GG tier value for one pair: 1 = T3, 0 = T4, -1 = T5 or useless for the champion, null = not listed */
    tierValue(cid, h) {
      const o = this.opgg[String(cid)], e = o && o.augments && o.augments[String(h)];
      if (e) return { 3: 1, 4: 0, 5: -1 }[e[0]] ?? null;
      if (this.gaps[String(cid)] && this.gaps[String(cid)].has(String(h))) return -1;
      return null; // not listed: one of the most picked or almost never picked -> the model's estimate
    }

    opggValue(cid, h) {
      const tierV = this.tierValue(cid, h);
      const m = (this.modelFull[String(cid)] || {})[String(h)];
      if (tierV == null) { const est = (this.model[String(cid)] || {})[String(h)]; return est != null ? est : null; }
      return m != null ? 0.5 * tierV + 0.5 * Math.max(tierV - 0.75, Math.min(tierV + 0.75, m)) : tierV;
    }

    /* Grade points from a value's position among this champion's own hexes:
       top 5% S+, next 15% S, next 20% A, next 25% B, next 20% C, bottom 15% D. */
    pointsForPct(cid, pctl) {
      const knots = [[0, -3], [0.15, -1.5], [0.35, 0], [0.6, 1.5], [0.8, 3], [0.95, 4.5], [1, 5.5]];
      for (let i = 1; i < knots.length; i++) {
        const [x0, y0] = knots[i - 1], [x1, y1] = knots[i];
        if (pctl <= x1) return y0 + (y1 - y0) * (pctl - x0) / (x1 - x0);
      }
      return 5.5;
    }

    pointsFor(cid, v) {
      this._dist = this._dist || {};
      if (!this._dist[cid]) {
        this._dist[cid] = Object.values(this.game.augments).filter((a) => !a.disabled && this.offered(cid, a.id))
          .map((a) => this.opggValue(cid, a.id)).filter((x) => x != null).sort((a, b) => a - b);
      }
      const d = this._dist[cid];
      if (!d.length) return 0;
      let below = 0;
      while (below < d.length && d[below] < v) below++;
      let same = 0;
      while (below + same < d.length && d[below + same] === v) same++;
      const pctl = (below + same / 2) / d.length; // 0 = worst, 1 = best
      const knots = [[0, -3], [0.15, -1.5], [0.35, 0], [0.6, 1.5], [0.8, 3], [0.95, 4.5], [1, 5.5]];
      for (let i = 1; i < knots.length; i++) {
        const [x0, y0] = knots[i - 1], [x1, y1] = knots[i];
        if (pctl <= x1) return y0 + (y1 - y0) * (pctl - x0) / (x1 - x0);
      }
      return 5.5;
    }

    /* Rank of a hex among this champion's hexes in the same OP.GG tier, by the model (similar champions). */
    tierRank(cid, h, tierV) {
      const full = this.modelFull[String(cid)], o = this.opgg[String(cid)];
      if (!full || !o) return null;
      this._rank = this._rank || {};
      const key = cid + ":" + tierV;
      if (!this._rank[key]) {
        const same = Object.keys(full).filter((x) => this.tierValue(cid, x) === tierV).sort((a, b) => full[b] - full[a]);
        this._rank[key] = Object.fromEntries(same.map((x, i) => [x, i + 1]));
        this._rank[key]._n = same.length;
      }
      const r = this._rank[key][String(h)];
      return r ? [r, this._rank[key]._n] : null;
    }

    offered(cid, h) { return !(this.unavailable[String(cid)] && this.unavailable[String(cid)].has(String(h))); }

    gradeHex(ctx, h) {
      const cid = String(ctx.champ), aug = this.game.augments[String(h)];
      this.style = ctx.style || this.styleFromItems(cid, ctx.items);
      if (!aug) return null;
      const owned = ctx.owned || [], allies = ctx.allies || [], enemies = ctx.enemies || [];
      const parts = [];
      const cname = this.name("champions", cid);
      const cW = this.champWR(cid);
      const cell = ((this.s.hex || {})[cid] || {})[String(h)];
      const ng = n(cell), a = ng / (ng + K.champHex);
      const allCell = (this.s.hex_all || {})[String(h)];
      const hd = this.hexAllDelta(h);
      if (ng > 0) {
        const d = (wr(cell) - cW) * 100;
        parts.push({ v: a * d, text: this.t("champData", { c: cname, wr: pct(wr(cell)), n: games(ng), d: signed(d) }) });
      }
      if (n(allCell) > 0) parts.push({ v: (1 - a) * hd, text: this.t("overallR", { d: signed(hd), n: games(n(allCell)) }) });
      else parts.push({ v: 0, text: this.t("noData") });
      const op = this.opggPart(cid, h);
      if (op) parts.push({ v: (1 - a) * op.v, text: op.text, src: op.src || "opgg", score: op.score });
      for (const f of this.fitRules(cid, aug)) parts.push({ v: (1 - a) * (op && op.v ? 0.5 : 1) * f.v, text: f.text });
      parts.push(...this.contextParts(cid, h, aug, allies, enemies));
      parts.push(...this.synergyParts(h, aug, owned));
      const round = ctx.round || owned.length + 1;
      const rc = ((this.s.round_all || {})[String(h)] || {})[String(round)];
      if (n(rc) > 0 && n(allCell) > 0) {
        const d = (wr(rc) - wr(allCell)) * 100, v = shrink(n(rc), d, 0, K.round);
        if (Math.abs(v) >= 0.3) parts.push({ v, text: this.t("roundR", { r: round, d: signed(d), n: games(n(rc)) }) });
      }
      if (this.me && this.me.hex) {
        const mc = this.me.hex[String(h)];
        if (n(mc) > 0) {
          const avg = wr(this.me.global) || this.g, d = (wr(mc) - avg) * 100;
          const v = Math.max(-3, Math.min(3, shrink(n(mc), d, 0, K.personal)));
          if (Math.abs(v) >= 0.2)
            parts.push({ v, text: this.t("personal", { w: mc[1], l: mc[0] - mc[1], wr: pct(wr(mc)), avg: pct(avg) }) });
        }
      }
      if (aug.disabled) parts.push({ v: -10, text: this.t("disabled") });
      const total = parts.reduce((s, p) => s + p.v, 0);
      parts.sort((x, y) => Math.abs(y.v) - Math.abs(x.v));
      return {
        id: aug.id, name: this.name("augments", h), rarity: aug.rarity, icon: aug.icon,
        total, score: (parts.find((p) => p.score != null) || {}).score ?? Math.max(0, Math.min(100, 50 + 5 * total)), grade: letter(total),
        games: ng, confidence: ng >= 300 ? "high" : ng >= 50 ? "medium" : "low",
        parts: parts.filter((p) => Math.abs(p.v) >= 0.05 || p.v === 0),
      };
    }

    /* Grade the 3 offered cards, and say whether rerolling one is worth it. */
    gradeOffers(ctx) {
      const offers = (ctx.offers || []).map((h) => this.gradeHex(ctx, h)).filter(Boolean);
      const result = { offers, reroll: null };
      if (!offers.length) return result;
      const rarity = offers[0].rarity;
      const skip = new Set([...(ctx.owned || []), ...(ctx.offers || [])].map(String));
      const pool = Object.values(this.game.augments)
        .filter((a) => a.rarity === rarity && !a.disabled && !skip.has(String(a.id)) && this.offered(ctx.champ, a.id))
        .map((a) => this.gradeHex(ctx, a.id).total);
      if (!pool.length) return result;
      const totals = offers.map((o) => o.total), best = Math.max(...totals);
      let bestGain = -Infinity, pick = null;
      offers.forEach((o, i) => {
        const others = totals.filter((_, j) => j !== i), keep = others.length ? Math.max(...others) : -Infinity;
        const gain = pool.reduce((s, x) => s + Math.max(keep, x), 0) / pool.length - best;
        if (gain > bestGain) { bestGain = gain; pick = o; }
      });
      const beat = pool.filter((x) => x > best).length / pool.length;
      result.reroll = bestGain >= 0.4
        ? { card: pick.id, gain: bestGain, text: this.t("reroll", { h: pick.name, d: signed(bestGain), p: Math.round(beat * 100) + "%" }) }
        : { card: null, gain: bestGain, text: this.t("noReroll", { p: Math.round(pool.filter((x) => x < best - 0.05).length / pool.length * 100) + "%" }) };
      return result;
    }

    /* OP.GG ARAM: how this item does for this champion (core build, boots, or as item #4-6). */
    opggItemPart(cid, iid) {
      const b = this.opggBuild[String(cid)];
      if (!b || !b.play) return null;
      const base = b.win_rate;
      let best = null;
      const consider = (rec, slot) => {
        if (!rec || !rec.ids.map(String).includes(String(iid)) || !rec.play) return;
        if (!best || rec.play > best.rec.play) best = { rec, slot };
      };
      consider(b.core, "core");
      consider(b.boots, "boots");
      for (const [slot, recs] of Object.entries(b.slots || {})) for (const r of recs) consider(r, slot);
      if (!best) return null;
      const wr_ = best.rec.win / best.rec.play;
      let v;
      if (best.slot === "core" || best.slot === "boots") {
        // OP.GG's most-built items: a steady bonus, plus half the edge over the champion's average
        v = 0.8 + 0.5 * shrink(best.rec.play, (wr_ - base) * 100, 0, 500);
      } else {
        // Later items win more just because winning players buy more items, so compare with the other options for that slot
        const recs = b.slots[best.slot], tot = recs.reduce((t, r) => t + r.play, 0);
        const slotWr = recs.reduce((t, r) => t + r.win, 0) / (tot || 1);
        v = 0.3 + shrink(best.rec.play, (wr_ - slotWr) * 100, 0, 500);
      }
      const text = best.slot === "core" || best.slot === "boots"
        ? this.t("opggCoreR", { wr: pct(wr_), n: games(best.rec.play) })
        : this.t("opggItemR", { wr: pct(wr_), s: best.slot, n: games(best.rec.play) });
      return { v: Math.max(-2.5, Math.min(2.5, v)), text, src: "opgg" };
    }

    /* Grade possible next items. ctx.items = completed items you own. */
    gradeItems(ctx, limit) {
      const cid = String(ctx.champ), owned = new Set((ctx.items || []).map(String));
      const items = this.game.items, p = this.profile(cid), cname = this.name("champions", cid);
      const ownsBoots = [...owned].some((i) => items[i] && items[i].boots);
      const slot = Math.min(5, [...owned].filter((i) => items[i] && items[i].completed).length);
      const champTable = (this.s.item || {})[cid] || {};
      const champGames = n((this.s.champ || {})[cid]) || 1;
      let candidates = Object.keys(champTable).filter((i) => items[i] && items[i].completed);
      if (candidates.length < 10)
        candidates = candidates.concat(Object.keys(this.s.item_all || {})
          .filter((i) => items[i] && items[i].completed && !candidates.includes(i))
          .sort((x, y) => this.s.item_all[y][0] - this.s.item_all[x][0]).slice(0, 40));
      const ob = this.opggBuild[cid];
      if (ob) { // OP.GG's build items are always candidates
        const extra = [...((ob.core || {}).ids || []), ...((ob.boots || {}).ids || []),
                       ...Object.values(ob.slots || {}).flat().flatMap((r) => r.ids)].map(String);
        for (const i of extra) if (items[i] && items[i].completed && !candidates.includes(i)) candidates.push(i);
      }
      if (!candidates.length) candidates = Object.keys(items).filter((i) => items[i].completed && items[i].gold >= 2500);
      const feats = this.activeFeatures(ctx.allies || [], ctx.enemies || []);
      const names = (ids) => ids.map((c) => this.name("champions", c)).join(", ");
      const cW = this.champWR(cid);
      const out = [];
      for (const i of candidates) {
        if (owned.has(i) || (ownsBoots && items[i].boots)) continue;
        const it = items[i], tags = new Set(it.tags), parts = [];
        const cell = champTable[i], ng = n(cell), a = ng / (ng + K.item);
        const all = (this.s.item_all || {})[i];
        const dAll = (smooth(all, this.g, K.item) - this.g) * 100;
        if (ng > 0) {
          const d = (wr(cell) - cW) * 100;
          parts.push({ v: a * d, text: this.t("itemData", { c: cname, wr: pct(wr(cell)), n: games(ng), d: signed(d) }) });
          const sc = cell[2] && cell[2][slot];
          if (n(sc) > 0) {
            const sd = (wr(sc) - wr(cell)) * 100, v = shrink(n(sc), sd, 0, K.slot);
            if (Math.abs(v) >= 0.3) parts.push({ v, text: this.t("slotR", { s: slot + 1, d: signed(sd), n: games(n(sc)) }) });
          }
        }
        if (n(all) > 0) parts.push({ v: (1 - a) * dAll, text: this.t("itemAll", { d: signed(dAll), n: games(n(all)) }) });
        const op = this.opggItemPart(cid, i);
        if (op) parts.push({ v: (1 - a) * op.v, text: op.text, src: op.src || "opgg", score: op.score });
        const fitW = (1 - a) * (op ? 0.5 : 1);
        if (this.rules) {
        if (tags.has("SpellDamage") && !tags.has("Damage") && p.ap < 0.35) parts.push({ v: -3 * fitW, text: this.t("apItemAd") });
        if ((tags.has("Damage") || tags.has("CriticalStrike")) && !tags.has("SpellDamage") && p.ap > 0.65)
          parts.push({ v: -3 * fitW, text: this.t("adItemAp") });
        if (tags.has("AntiHeal") && feats.eheal) parts.push({ v: 1.5, text: this.t("antiheal", { names: names(feats.eheal) }) });
        if (tags.has("SpellBlock") && feats.eap) parts.push({ v: p.front ? 1.0 : 0.6, text: this.t("mrItem") });
        if (tags.has("Armor") && feats.ead) parts.push({ v: p.front ? 1.0 : 0.6, text: this.t("armorItem") });
        if ((tags.has("AntiTank") || tags.has("ArmorPenetration") || tags.has("MagicPenetration")) && feats.etank)
          parts.push({ v: 1.0, text: this.t("shredItem", { k: feats.etank.length, names: names(feats.etank) }) });
        }
        const total = parts.reduce((s, x) => s + x.v, 0);
        parts.sort((x, y) => Math.abs(y.v) - Math.abs(x.v));
        out.push({ id: it.id, name: this.name("items", i), icon: it.icon, total, grade: letter(total),
                   games: ng, popularity: ng / champGames, parts });
      }
      out.sort((x, y) => y.total - x.total || y.games - x.games);
      return out.slice(0, limit || 8);
    }

    /* ARAM champion select: grade your champion and the bench for your team. */
    gradeBench(ctx) {
      const team = ctx.team || [];
      const front = team.filter((c) => (this.champ(c) || { flags: {} }).flags.front).length;
      const apCount = team.filter((c) => (this.champ(c) || { flags: {} }).flags.apdmg).length;
      return [ctx.me, ...(ctx.bench || [])].filter(Boolean).map((cid) => {
        const c = this.champ(cid) || { flags: {} }, cell = (this.s.champ || {})[String(cid)], parts = [];
        const rt = this.champRating(cid);
        if (rt.src === "opgg" || rt.src === "mixed")
          parts.push({ v: (rt.wr - 0.5) * 100, src: "opgg",
                       text: this.t("opggChampWr", { wr: pct(rt.op.win_rate), n: games(rt.op.play), t: rt.op.tier })
                         + (rt.src === "mixed" ? " · " + this.t("champWr", { wr: pct(wr(rt.own)), n: games(n(rt.own)) }) : "") });
        else if (rt.src === "own")
          parts.push({ v: (rt.wr - this.g) * 100, text: this.t("champWr", { wr: pct(wr(cell)), n: games(n(cell)) }) });
        else parts.push({ v: 0, text: this.t("champNoData") });
        if (this.rules && team.length >= 3 && front === 0 && c.flags.front) parts.push({ v: 1.0, text: this.t("needFront") });
        if (this.rules && team.length >= 3 && apCount >= 3 && !c.flags.apdmg) parts.push({ v: 0.7, text: this.t("needAd") });
        if (this.rules && team.length >= 3 && apCount === 0 && c.flags.apdmg) parts.push({ v: 0.7, text: this.t("needAp") });
        const total = parts.reduce((s, x) => s + x.v, 0);
        return { id: Number(cid), name: this.name("champions", cid), icon: c.icon, mine: String(cid) === String(ctx.me),
                 total, grade: letter(total), games: n(cell), parts };
      }).sort((x, y) => y.total - x.total);
    }
  }

  const api = { Grader, letter, wr, smooth, GRADES, TIERS, K, tierLabel };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.AugurGrade = api;
})(typeof window !== "undefined" ? window : this);
