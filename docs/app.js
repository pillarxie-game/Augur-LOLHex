/* Augur website: tier lists, champion and hex pages, and the match helper. */
(function () {
  "use strict";
  const { Grader, wr, smooth, K } = window.AugurGrade;

  const I18N = window.AugurI18n;
  const store = {
    get(k, d) { try { const v = localStorage.getItem("augur." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem("augur." + k, JSON.stringify(v)); } catch (e) { /* private mode */ } },
  };

  const S = { lang: store.get("lang", I18N.best(navigator.language)), game: null, stats: null,
              personal: null, local: false, grader: null, opgg: {}, opggBuild: {}, opggAll: null, model: null, match: store.get("match", { champ: null, allies: [], enemies: [], owned: [], offers: [], items: [] }) };
  if (!I18N.T[S.lang]) S.lang = "en";
  const T = (k) => I18N.pick(S.lang, k) ?? k;

  /* ---------- tiny DOM helpers ---------- */
  function el(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "html") e.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : String(kid));
    return e;
  }
  const img = (src, alt) => el("img", { src, alt: alt || "", loading: "lazy", width: 32, height: 32, onerror: (e) => { e.target.style.visibility = "hidden"; } });
  const pct = (x) => (x == null ? "-" : (100 * x).toFixed(1) + "%");
  const signed = (x) => el("span", { class: x >= 0 ? "pos" : "neg" }, (x >= 0 ? "+" : "") + x.toFixed(1));
  const num = (x) => Math.round(x).toLocaleString();
  const gradeBadge = (g, big) => el("span", { class: "grade g-" + g.replace("+", "plus") + (big ? " big" : "") }, g);
  const nameOf = (kind, id) => {
    const o = S.game[kind][String(id)];
    return o ? (o.names && o.names[S.lang]) || (S.lang === "zh" && o.name_zh) || o.name : String(id);
  };
  const n = (c) => (c ? c[0] : 0);

  /* ---------- table with sortable columns ---------- */
  function table(cols, rows, sortKey, desc) {
    let key = sortKey, down = desc !== false;
    const wrap = el("div", { class: "table-wrap" });
    function draw() {
      const sorted = rows.slice().sort((a, b) => {
        const x = a[key], y = b[key];
        return (typeof x === "string" ? x.localeCompare(y) : x - y) * (down ? -1 : 1);
      });
      const head = el("tr", {}, cols.map((c) => el("th", {
        class: c.num ? "num" : "", scope: "col",
        onclick: () => { if (!c.key) return; if (key === c.key) down = !down; else { key = c.key; down = true; } draw(); },
      }, c.label + (c.key === key ? (down ? " ▾" : " ▴") : ""))));
      const body = sorted.map((r) => el("tr", {}, cols.map((c) => el("td", { class: (c.num ? "num " : "") + (c.cls || "") }, c.render(r)))));
      wrap.replaceChildren(el("table", {}, el("thead", {}, head), el("tbody", {}, body)));
    }
    draw();
    return wrap;
  }

  /* ---------- pickers (datalist search in EN and 中文) ---------- */
  let pickerId = 0;
  function picker(kind, placeholder, onPick, filter) {
    const id = "dl" + pickerId++;
    const entries = Object.values(S.game[kind]).filter(filter || (() => true));
    const byLabel = new Map();
    const list = el("datalist", { id }, entries.map((o) => {
      const local = nameOf(kind, o.id);
      const label = local !== o.name ? `${local} · ${o.name}` : o.name;
      byLabel.set(label.toLowerCase(), o.id);
      for (const n of [o.name, o.name_zh, ...Object.values(o.names || {}), ...(o.aka || [])]) if (n) byLabel.set(n.toLowerCase(), o.id);
      return el("option", { value: label });
    }));
    const input = el("input", { list: id, placeholder, autocomplete: "off" });
    input.addEventListener("change", () => {
      const hit = byLabel.get(input.value.trim().toLowerCase());
      if (hit != null) { onPick(hit); input.value = ""; }
    });
    return el("span", {}, input, list);
  }
  function chip(kind, id, onRemove) {
    const o = S.game[kind][String(id)];
    return el("span", { class: "chip" }, o && o.icon ? img(o.icon) : null, nameOf(kind, id),
      onRemove ? el("button", { type: "button", "aria-label": "remove", onclick: onRemove }, "×") : null);
  }

  /* ---------- data ---------- */
  async function load() {
    const get = (u) => fetch(u, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    [S.game, S.stats] = await Promise.all([get("data/gamedata.json"), get("data/stats.json")]);
    if (!S.game) { document.getElementById("app").textContent = "data/gamedata.json is missing. Run: python -m augur update && python -m augur build"; return false; }
    S.stats = S.stats || { meta: { total_games: 0, patches: {} } };
    const ping = await get("api/ping");
    S.local = !!(ping && ping.ok);
    S.settings = (ping && ping.settings) || {};
    S.desktop = !!(ping && ping.desktop);
    if (S.settings.ui_lang && I18N.T[S.settings.ui_lang] && !store.get("lang", null)) S.lang = S.settings.ui_lang;
    if (S.local) S.personal = await get("api/me");
    if (S.local && S.settings.use_opgg !== false) {
      const sum = await get("api/opgg_summary");
      if (sum && sum.hexes) S.opggAll = sum;
      const mdl = await get("api/opgg_model");
      if (mdl && mdl.pred) S.model = mdl;
    } else if (!S.local) {
      // A test or offline copy can ship OP.GG data and icons as files next to the page.
      const bundle = await get("data/opgg_all.json");
      if (bundle && bundle.summary) {
        S.opggAll = bundle.summary;
        Object.assign(S.opgg, bundle.hexes || {});
        Object.assign(S.opggBuild, bundle.builds || {});
        if (bundle.model) S.model = bundle.model;
      }
      const icons = await get("data/icons.json");
      if (icons) for (const kind of ["augments", "champions", "items"])
        for (const [id, uri] of Object.entries(icons[kind] || {})) if (S.game[kind][id]) S.game[kind][id].icon = uri;
    }
    makeGrader();
    return true;
  }
  function makeGrader() {
    S.grader = new Grader(S.game, S.stats, { lang: S.lang, personal: S.personal, opgg: S.opgg, opggBuild: S.opggBuild, opggAll: S.opggAll, model: S.model });
  }
  /* OP.GG hex stats for one champion (local helper only). Calls back once loaded. */
  async function loadOpgg(cid, then) {
    if (!S.local || !cid) return;
    if (!S.opggBuild[cid] && S.settings.use_opgg !== false) {
      S.opggBuild[cid] = { loading: true };
      fetch("api/opgg_build?champ=" + cid).then((x) => x.json()).then((r) => {
        if (r && r.play) { S.opggBuild[cid] = r; makeGrader(); if (then) then(); } else delete S.opggBuild[cid];
      }).catch(() => { delete S.opggBuild[cid]; });
    }
    if (S.opgg[cid]) return;
    S.opgg[cid] = { loading: true };
    const r = await fetch("api/opgg?champ=" + cid).then((x) => x.json()).catch(() => null);
    if (r && r.augments) { S.opgg[cid] = r; makeGrader(); if (then) then(); }
    else delete S.opgg[cid];
  }
  const hasStats = () => (S.stats.meta.total_games || 0) > 0;

  /* ---------- pages ---------- */
  function pageHexes(q) {
    const g = S.grader, players = n(S.stats.global) || 1;
    let rarity = q.rarity || store.get("rarity", "all"), term = "";
    const box = el("div");
    function draw() {
      const rows = Object.values(S.game.augments).filter((a) => (rarity === "all" || a.rarity === rarity)
        && (!term || [a.name, ...Object.values(a.names || {})].some((n) => n.toLowerCase().includes(term)))).map((a) => {
        const c = S.stats.hex_all ? S.stats.hex_all[a.id] : null;
        const d = g.hexAllDelta(a.id);
        const op = S.opggAll && S.opggAll.hexes[a.id];
        const useOp = !hasStats() && op && op.strength != null;
        return { a, name: nameOf("augments", a.id), tierv: hasStats() ? d : useOp ? op.strength : -99,
                 tier: hasStats() && n(c) ? g.hexTier(a.id) : useOp ? g.opggTier(a.id) : "-",
                 ops: op && op.score != null ? op.score : -99, opn: op ? op.listed : 0,
                 optop: op && op.strength != null ? op.top_champs : -1,
                 wr: wr(c) ?? 0, d, pick: n(c) ? n(c) / players : op && op.pick_rate != null ? op.pick_rate : 0,
                 pickOp: !n(c) && op && op.pick_rate != null, games: n(c), rar: a.rarity };
      });
      const cols = [
        { label: T("tier"), key: "tierv", render: (r) => (r.tier === "-" ? el("span", { class: "muted" }, "-") : gradeBadge(r.tier)) },
        { label: T("hex"), key: "name", cls: "name", render: (r) => el("a", { class: "ent", href: `#/hex/${r.a.id}` }, img(r.a.icon), r.name) },
        { label: T("rarity"), key: "rar", render: (r) => el("span", { class: "rar rar-" + r.a.rarity }, T(r.a.rarity)) },
        { label: T("winrate"), key: "wr", num: true, render: (r) => (r.games ? pct(r.wr) : "-") },
        { label: T("delta"), key: "d", num: true, render: (r) => (r.games ? signed(r.d) : "-") },
        { label: T("pickrate") + (hasStats() ? "" : " (OP.GG)"), key: "pick", num: true,
          render: (r) => (r.games || r.pickOp ? pct(r.pick) : "-") },
        { label: T("games"), key: "games", num: true, render: (r) => num(r.games) },
      ];
      if (S.opggAll) cols.splice(3, 0,
        { label: T("opggTopCol"), key: "optop", num: true, render: (r) => (r.optop < 0 ? el("span", { class: "muted" }, "-")
          : el("span", { title: T("opggAllR2").replace("{k}", r.optop).replace("{n}", S.opggAll.champions) }, r.optop + " / " + S.opggAll.champions)) });

      box.replaceChildren(table(cols, rows, hasStats() || S.opggAll ? "tierv" : "name", hasStats() || !!S.opggAll));
    }
    const tabs = el("div", { class: "tabs", role: "tablist" }, ["all", "silver", "gold", "prismatic"].map((r) =>
      el("button", { type: "button", class: r === rarity ? "on" : "", onclick: (e) => {
        rarity = r; store.set("rarity", r); [...e.target.parentNode.children].forEach((b) => b.classList.toggle("on", b === e.target)); draw();
      } }, T(r))));
    const search = el("input", { type: "search", placeholder: T("search"), oninput: (e) => { term = e.target.value.trim().toLowerCase(); draw(); } });
    draw();
    return [el("h1", {}, T("hexListTitle")), el("p", { class: "muted" }, T("hexListSub")), summary(),
            el("div", { class: "row" }, tabs, el("div", { class: "grow" }), search), box];
  }

  function summary() {
    const m = S.stats.meta;
    if (!hasStats() && S.opggAll) return el("div", { class: "banner" }, T("opggTierNote"));
    if (!hasStats()) return el("div", { class: "banner" }, el("b", {}, T("noStats")), " ", el("span", { html: T("noStatsHelp") }));
    const patches = Object.keys(m.patches || {});
    return el("div", { class: "stats" },
      el("div", { class: "stat" }, el("b", {}, num(m.total_games)), el("span", {}, T("games"))),
      el("div", { class: "stat" }, el("b", {}, patches[0] || "-"), el("span", {}, T("patch"))),
      el("div", { class: "stat" }, el("b", {}, Object.keys(S.game.augments).length), el("span", {}, T("hexes"))),
      el("div", { class: "stat" }, el("b", {}, (m.generated || "").slice(0, 10)), el("span", {}, T("updated"))));
  }

  function pageChampions() {
    let term = "";
    const box = el("div", { class: "grid" });
    const g = S.grader;
    function draw() {
      const ops = (S.opggAll && S.opggAll.champ_stats) || {};
      const opWr = (c) => (ops[c.id] && ops[c.id].win_rate) || 0;
      const list = Object.values(S.game.champions).filter((c) => !term || [c.name, ...Object.values(c.names || {}), ...(c.aka || [])].some((n) => n.toLowerCase().includes(term)))
        .map((c) => ({ c, cell: (S.stats.champ || {})[c.id], op: ops[c.id] }))
        // Ranked by champRating: OP.GG's large samples first; never your personal record
        .sort((a, b) => (hasStats() || Object.keys(ops).length ? g.champRating(b.c.id).wr - g.champRating(a.c.id).wr
          : nameOf("champions", a.c.id).localeCompare(nameOf("champions", b.c.id))));
      box.replaceChildren(...list.map(({ c, cell, op }) => el("a", { class: "card-champ", href: `#/champion/${c.id}` },
        el("img", { src: c.icon, alt: "", loading: "lazy", width: 56, height: 56 }), el("span", {}, nameOf("champions", c.id)),
        el("small", {}, op && op.win_rate ? el("span", { title: T("opggWr") }, `${pct(op.win_rate)} · T${op.tier}`)
          : n(cell) ? `${pct(wr(cell))} · ${num(n(cell))}` : "-"))));
    }
    draw();
    return [el("h1", {}, T("champsTitle")), summary(),
            S.opggAll && S.opggAll.champ_stats ? el("p", { class: "muted small" }, T("opggWr")) : null,
            el("div", { class: "row" }, el("input", { type: "search", placeholder: T("search"), oninput: (e) => { term = e.target.value.trim().toLowerCase(); draw(); } })),
            el("div", { style: "height:12px" }), box];
  }

  function hexRowsFor(cid, style) {
    const g = S.grader;
    return Object.values(S.game.augments).filter((a) => !a.disabled).map((a) => {
      const r = g.gradeHex({ champ: cid, style: style || undefined }, a.id);
      const cell = ((S.stats.hex || {})[cid] || {})[a.id];
      const ope = S.opgg[cid] && S.opgg[cid].augments && S.opgg[cid].augments[a.id];
      return { a, r, name: r.name, total: r.total, wr: wr(cell) ?? 0, games: n(cell), sc: r.score,
               pick: n(cell) ? n(cell) / (n((S.stats.champ || {})[cid]) || 1) : ope ? ope[2] : 0, pickOp: !n(cell) && !!ope, rar: a.rarity };
    });
  }

  function pageChampion(cid) {
    if (S.local && !S.opgg[cid]) loadOpgg(cid, () => { if (location.hash.startsWith("#/champion/" + cid)) route(); });
    const c = S.game.champions[cid];
    if (!c) return [el("p", {}, "Unknown champion")];
    const g = S.grader, cell = (S.stats.champ || {})[cid];
    let rarity = store.get("rarity", "all");
    const styles = S.grader.stylesFor(cid);
    let style = styles.length ? store.get("style." + cid, null) : null;
    const rows = hexRowsFor(cid, style);
    const hexCols = [
      { label: T("grade_"), key: "total", render: (r) => gradeBadge(r.r.grade) },
      { label: T("scoreCol"), key: "sc", num: true, render: (r) => el("b", {}, Math.round(r.sc)) },
      { label: T("hex"), key: "name", cls: "name", render: (r) => el("a", { class: "ent", href: `#/hex/${r.a.id}`, title: r.r.parts.map((p) => `${p.v >= 0 ? "+" : ""}${p.v.toFixed(1)} ${p.text}`).join("\n") }, img(r.a.icon), r.name) },
      { label: T("rarity"), key: "rar", render: (r) => el("span", { class: "rar rar-" + r.a.rarity }, T(r.a.rarity)) },
      { label: T("winrate"), key: "wr", num: true, render: (r) => (r.games ? pct(r.wr) : "-") },
      { label: T("pickrate"), key: "pick", num: true, render: (r) => (r.games ? pct(r.pick) : r.pickOp ? el("span", { title: "OP.GG" }, pct(r.pick)) : "-") },
      { label: T("games"), key: "games", num: true, render: (r) => num(r.games) },
    ];
    // OP.GG tier for this champion: listed hexes are T3-T5; a tracked hex left out is T1-T2 (see README)
    const opAug = S.opgg[cid] && S.opgg[cid].augments;
    for (const r of rows) {
      const e = opAug && opAug[r.a.id], all = S.opggAll && S.opggAll.hexes[r.a.id];
      const gap = S.opggAll && S.opggAll.gaps && (S.opggAll.gaps[cid] || []).map(String).includes(String(r.a.id));
      if (e) { r.opTier = "T" + e[0]; r.opRank = 6 - e[0]; }
      else if (opAug && gap) { r.opTier = T("gapCol"); r.opRank = 0.5; }
      else if (opAug && S.opggAll && S.opggAll.unknown && (S.opggAll.unknown[cid] || []).map(String).includes(String(r.a.id))) {
        const v = S.model && S.model.pred[cid] && S.model.pred[cid][r.a.id];
        r.opTier = v != null ? "≈" + window.AugurGrade.tierLabel(v) : "-"; r.opRank = v != null ? Math.max(0.5, v + 2) - 0.01 : 0; r.est = true;
      }
      else if (opAug && all && all.infer_top) { r.opTier = "T1-T2"; r.opRank = 4; }
      else if (S.model && S.model.useful && (S.model.pred[cid] || {})[r.a.id] != null) {
        const v = S.model.pred[cid][r.a.id]; r.opTier = "≈" + window.AugurGrade.tierLabel(v); r.opRank = Math.max(0.5, v + 2) - 0.01; r.est = true;
      } else { r.opTier = "-"; r.opRank = 0; }
    }
    if (opAug) hexCols.splice(3, 0, { label: T("opggTierCol"), key: "opRank", num: true, render: (r) =>
      el("span", { class: r.est ? "muted" : r.opRank >= 4 ? "pos" : r.opRank === 1 ? "neg" : r.opRank ? "" : "muted",
                   title: r.est ? T("opggModelNote") : "" }, r.opTier) });
    const best = el("div"), worst = el("div");
    function drawHexes() {
      const f = rows.filter((r) => rarity === "all" || r.rar === rarity).sort((a, b) => b.total - a.total);
      best.replaceChildren(table(hexCols, f.slice(0, 15), "total"));
      worst.replaceChildren(table(hexCols, f.slice(-8), "total", false));
    }
    drawHexes();
    const tabs = el("div", { class: "tabs" }, ["all", "silver", "gold", "prismatic"].map((r) =>
      el("button", { type: "button", class: r === rarity ? "on" : "", onclick: (e) => {
        rarity = r; store.set("rarity", r); [...e.target.parentNode.children].forEach((b) => b.classList.toggle("on", b === e.target)); drawHexes();
      } }, T(r))));

    // combos: pairs whose win rate beats what the two hexes give separately
    const pairs = Object.entries((S.stats.pair || {})[cid] || {}).map(([k, pc]) => {
      const [a, b] = k.split("_"), hc = (S.stats.hex || {})[cid] || {};
      const cW = g.champWR(cid);
      const pw = smooth(pc, cW, 60);
      return { a, b, games: n(pc), wr: wr(pc), lift: (pw - cW) * 100 };
    }).filter((p) => p.games >= 5 && S.game.augments[p.a] && S.game.augments[p.b]).sort((x, y) => y.lift - x.lift).slice(0, 8);
    const comboCols = [
      { label: T("hexes"), key: "lift", cls: "name", render: (p) => el("div", { class: "row" },
        el("a", { class: "ent", href: `#/hex/${p.a}` }, img(S.game.augments[p.a].icon), nameOf("augments", p.a)), "+",
        el("a", { class: "ent", href: `#/hex/${p.b}` }, img(S.game.augments[p.b].icon), nameOf("augments", p.b))) },
      { label: T("winrate"), key: "wr", num: true, render: (p) => pct(p.wr) },
      { label: T("delta"), key: "lift", num: true, render: (p) => signed(p.lift) },
      { label: T("games"), key: "games", num: true, render: (p) => num(p.games) },
    ];

    const items = g.gradeItems({ champ: cid, items: [] }, 10);
    const itemCols = [
      { label: T("grade_"), key: "total", render: (r) => gradeBadge(r.grade) },
      { label: T("items"), key: "name", cls: "name", render: (r) => el("span", { class: "ent", title: r.parts.map((p) => `${p.v >= 0 ? "+" : ""}${p.v.toFixed(1)} ${p.text}`).join("\n") }, img(r.icon), r.name) },
      { label: T("popularity"), key: "popularity", num: true, render: (r) => (r.games ? pct(r.popularity) : "-") },
      { label: T("games"), key: "games", num: true, render: (r) => num(r.games) },
    ];
    const slotTable = itemSlots(cid);
    const ob = S.opggBuild[cid];
    const itemChips = (rec) => el("div", { class: "chips" }, rec.ids.filter((i) => S.game.items[i] || S.game.item_alias && S.game.item_alias[i]).map((i) => {
      const id = S.game.items[i] ? i : S.game.item_alias[i];
      return el("span", { class: "chip" }, img(S.game.items[id].icon), nameOf("items", id));
    }), el("small", { class: "muted" }, ` ${pct(rec.win / rec.play)} · ${num(rec.play)}`));
    const opggPanel = ob && ob.play ? [el("h2", {}, T("opggBuildTitle")), el("div", { class: "panel" },
      el("p", { style: "margin-top:0" }, el("b", {}, T("opggChampLine").replace("{t}", ob.tier).replace("{wr}", pct(ob.win_rate)).replace("{n}", num(ob.play)))),
      el("div", { class: "form-grid" },
        ob.core ? [el("label", {}, T("opggCore")), itemChips(ob.core)] : null,
        ob.boots ? [el("label", {}, T("opggBoots")), itemChips(ob.boots)] : null,
        Object.entries(ob.slots || {}).flatMap(([sl, recs]) => [el("label", {}, T("opggSlot").replace("{s}", sl)),
          el("div", {}, recs.map(itemChips))])),
      el("p", { class: "muted small", style: "margin-bottom:0" }, "Source: ", el("a", { href: `https://www.op.gg/modes/aram/${c.key.toLowerCase()}/build`, target: "_blank", rel: "noopener" }, "OP.GG")))] : null;
    const prof = (S.stats.profile || {})[cid];
    const opStat = (S.opggAll && S.opggAll.champ_stats && S.opggAll.champ_stats[cid]) || (ob && ob.play ? ob : null);
    const opgg = `https://www.op.gg/modes/aram/${c.key.toLowerCase()}/build`;
    return [
      el("div", { class: "row", style: "margin-top:20px" },
        el("div", { class: "ent big" }, el("img", { src: c.icon, alt: "", width: 64, height: 64 }),
          el("div", {}, el("h1", { style: "margin:0" }, nameOf("champions", cid)), el("div", { class: "muted" }, (c.titles && c.titles[S.lang]) || c.tags.join(" · ")))),
        el("div", { class: "grow" }), el("a", { class: "btn", href: opgg, target: "_blank", rel: "noopener" }, T("openOpgg") + " ↗"),
        el("a", { class: "btn", href: `#/grade?champ=${cid}` }, T("grade") + " →")),
      el("div", { class: "stats" },
        n(cell) || !opStat ? el("div", { class: "stat" }, el("b", {}, n(cell) ? pct(wr(cell)) : "-"), el("span", {}, T("winrate")))
          : el("div", { class: "stat" }, el("b", {}, pct(opStat.win_rate)), el("span", {}, T("opggWr") + " · T" + opStat.tier)),
        n(cell) || !opStat ? el("div", { class: "stat" }, el("b", {}, num(n(cell))), el("span", {}, T("games")))
          : el("div", { class: "stat" }, el("b", {}, num(opStat.play)), el("span", {}, T("games") + " (OP.GG)")),
        el("div", { class: "stat" }, el("b", {}, prof && prof.ap != null ? Math.round(prof.ap * 100) + "%" : Math.round(c.ap * 100) + "%"), el("span", {}, T("apDamage"))),
        el("div", { class: "stat" }, el("b", {}, prof ? prof.taken.toFixed(2) + "×" : "-"), el("span", {}, T("takenVsAvg")))),
      opggPanel,
      el("h2", {}, T("bestHexes")),
      styles.length ? el("div", { class: "tabs" }, [[null, "styleMixed"], ["ap", "styleAP"], ["ad", "styleAD"]].map(([v, k]) =>
        el("button", { type: "button", class: v === style ? "on" : "", onclick: () => { store.set("style." + cid, v); route(); } }, T(k)))) : null,
      styles.length ? el("p", { class: "muted small" }, T("styleNote")) : null,
      tabs, best,
      pairs.length ? [el("h2", {}, T("bestCombos")), table(comboCols, pairs, "lift")] : null,
      el("div", { class: "cols" }, el("div", {}, el("h2", {}, T("items")), table(itemCols, items, "total")),
        el("div", {}, el("h2", {}, T("itemOrder")), slotTable)),
      el("h2", {}, T("worstHexes")), worst,
    ];
  }

  function itemSlots(cid) {
    const t = (S.stats.item || {})[cid] || {};
    const rows = [];
    for (let s = 0; s < 6; s++) {
      const top = Object.entries(t).map(([i, v]) => [i, v[2][s]]).filter(([i, c]) => n(c) > 0 && S.game.items[i])
        .sort((a, b) => n(b[1]) - n(a[1])).slice(0, 3);
      if (top.length) rows.push({ s: s + 1, top });
    }
    if (!rows.length) return el("p", { class: "muted" }, T("noStats"));
    return table([
      { label: T("slot"), key: "s", render: (r) => "#" + r.s },
      { label: T("items"), cls: "name", render: (r) => el("div", { class: "chips" }, r.top.map(([i, c]) =>
        el("span", { class: "chip", title: `${pct(wr(c))} · ${num(n(c))}` }, img(S.game.items[i].icon), nameOf("items", i), el("small", { class: "muted" }, pct(wr(c)))))) },
    ], rows, "s", false);
  }

  function pageHex(hid) {
    const a = S.game.augments[hid];
    if (!a) return [el("p", {}, "Unknown hex")];
    const g = S.grader, all = (S.stats.hex_all || {})[hid];
    const champRows = Object.entries(S.stats.hex || {}).map(([cid, t]) => {
      const c = t[hid]; if (!n(c) || !S.game.champions[cid]) return null;
      const cW = g.champWR(cid);
      return { cid, name: nameOf("champions", cid), games: n(c), wr: wr(c), lift: (smooth(c, cW + (g.hexAllDelta(hid) / 100), K.champHex) - cW) * 100 };
    }).filter(Boolean);
    const champCols = [
      { label: T("champion"), key: "name", cls: "name", render: (r) => el("a", { class: "ent", href: `#/champion/${r.cid}` }, img(S.game.champions[r.cid].icon), r.name) },
      { label: T("winrate"), key: "wr", num: true, render: (r) => pct(r.wr) },
      { label: T("delta"), key: "lift", num: true, render: (r) => signed(r.lift) },
      { label: T("games"), key: "games", num: true, render: (r) => num(r.games) },
    ];
    const bestC = champRows.filter((r) => r.games >= 5).sort((x, y) => y.lift - x.lift);
    const partners = Object.entries(S.stats.pair_all || {}).filter(([k]) => k.split("_").includes(String(hid))).map(([k, c]) => {
      const other = k.split("_").find((x) => x !== String(hid));
      return { other, games: n(c), wr: wr(c), lift: (smooth(c, wr(all) || g.g, 60) - (wr(all) || g.g)) * 100 };
    }).filter((p) => S.game.augments[p.other] && p.games >= 5).sort((x, y) => y.lift - x.lift).slice(0, 10);
    const opAll = S.opggAll && S.opggAll.hexes[hid] && S.opggAll.hexes[hid].best.length ? S.opggAll.hexes[hid] : null;
    const rounds = (S.stats.round_all || {})[hid] || {};
    const roundKeys = Object.keys(rounds).sort();
    const maxWr = Math.max(0.01, ...roundKeys.map((r) => wr(rounds[r]) || 0));
    return [
      el("div", { class: "row", style: "margin-top:20px" },
        el("div", { class: "ent big" }, el("img", { src: a.icon, alt: "", width: 64, height: 64 }),
          el("div", {}, el("h1", { style: "margin:0" }, nameOf("augments", hid)),
            el("span", { class: "rar rar-" + a.rarity }, T(a.rarity)), S.lang !== "en" && nameOf("augments", hid) !== a.name ? el("span", { class: "muted" }, " · " + a.name) : null)),
        el("div", { class: "grow" }), n(all) ? gradeBadge(g.hexTier(hid), true) : null),
      el("div", { class: "stats" },
        el("div", { class: "stat" }, el("b", {}, n(all) ? pct(wr(all)) : "-"), el("span", {}, T("winrate"))),
        el("div", { class: "stat" }, el("b", {}, n(all) ? signed(g.hexAllDelta(hid)) : "-"), el("span", {}, T("delta"))),
        n(all) || !(S.opggAll && S.opggAll.hexes[hid] && S.opggAll.hexes[hid].pick_rate != null)
          ? el("div", { class: "stat" }, el("b", {}, n(all) ? pct(n(all) / (n(S.stats.global) || 1)) : "-"), el("span", {}, T("pickrate")))
          : el("div", { class: "stat" }, el("b", {}, pct(S.opggAll.hexes[hid].pick_rate)), el("span", {}, T("pickrate") + " (OP.GG)")),
        el("div", { class: "stat" }, el("b", {}, num(n(all))), el("span", {}, T("games")))),
      a.desc ? el("div", { class: "panel desc" }, a.desc) : null,
      a.tags.length ? el("p", { class: "muted small" }, "tags: " + a.tags.join(", ")) : null,
      roundKeys.length ? [el("h2", {}, T("byRound")), el("div", { class: "panel" }, el("div", { class: "bars" }, roundKeys.map((r) => {
        const w = wr(rounds[r]) || 0;
        return el("div", { class: "bar", title: `${num(n(rounds[r]))} ${T("games")}` }, el("b", {}, pct(w)), el("i", { style: `height:${Math.max(2, ((w - 0.4) / Math.max(0.01, maxWr - 0.4)) * 80)}%` }), `${T("round")} ${r}`);
      })))] : null,
      el("div", { class: "cols" },
        el("div", {}, el("h2", {}, T("bestChamps")), bestC.length ? table(champCols, bestC.slice(0, 12), "lift") : el("p", { class: "muted" }, T("noStats"))),
        el("div", {}, el("h2", {}, T("partners")), partners.length ? table([
          { label: T("hex"), key: "other", cls: "name", render: (p) => el("a", { class: "ent", href: `#/hex/${p.other}` }, img(S.game.augments[p.other].icon), nameOf("augments", p.other)) },
          { label: T("winrate"), key: "wr", num: true, render: (p) => pct(p.wr) },
          { label: T("lift"), key: "lift", num: true, render: (p) => signed(p.lift) },
          { label: T("games"), key: "games", num: true, render: (p) => num(p.games) },
        ], partners, "lift") : el("p", { class: "muted" }, T("noStats")))),
      bestC.length > 12 ? [el("h2", {}, T("worstChamps")), table(champCols, bestC.slice(-8), "lift", false)] : null,
      opAll ? [el("h2", {}, T("opggBestChamps")), el("p", { class: "muted small" }, T("opggAllR").replace("{s}", (opAll.score >= 0 ? "+" : "") + (opAll.score ?? 0).toFixed(1)).replace("{n}", opAll.listed)),
        el("div", { class: "grid" }, opAll.best.filter((b) => S.game.champions[b[0]]).map(([c, d]) => el("a", { class: "card-champ", href: `#/champion/${c}` },
          el("img", { src: S.game.champions[c].icon, alt: "", loading: "lazy", width: 56, height: 56 }), el("span", {}, nameOf("champions", c)), el("small", {}, (d >= 0 ? "+" : "") + d))))] : null,
    ];
  }

  /* ---------- match helper ---------- */
  function saveMatch() { store.set("match", S.match); }

  function resultCard(r, isBest, onPick) {
    return el("div", { class: "result" + (isBest ? " best" : "") },
      el("div", { class: "result-head" }, img(r.icon), el("div", { class: "grow" },
        el("div", {}, el("b", {}, r.name)), el("span", { class: "rar rar-" + (r.rarity || "") }, r.rarity ? T(r.rarity) : ""),
        r.confidence ? el("span", { class: "muted small" }, " · " + T("confidence")[r.confidence]) : null),
        el("div", { style: "text-align:center" }, gradeBadge(r.grade, true), r.score != null ? el("div", { class: "muted small" }, Math.round(r.score)) : null)),
      el("ul", { class: "reasons" }, r.parts.slice(0, 7).map((p) =>
        el("li", {}, el("span", { class: "v " + (p.v >= 0 ? "pos" : "neg") }, (p.v >= 0 ? "+" : "") + p.v.toFixed(1)), el("span", {}, p.text)))),
      onPick ? el("button", { type: "button", onclick: onPick }, T("pickThis")) : null);
  }

  function pageGrade(q) {
    const M = S.match;
    if (q.champ) { M.champ = Number(q.champ); saveMatch(); }
    const root = el("div");
    let followTimer = null;

    function teamSlots(key, count) {
      return el("div", { class: "chips" }, M[key].map((cid, i) => chip("champions", cid, () => { M[key].splice(i, 1); saveMatch(); draw(); })),
        M[key].length < count ? picker("champions", T("pickChamp"), (id) => { M[key].push(id); saveMatch(); draw(); }) : null);
    }
    function hexSlots(key, count) {
      const taken = new Set([...M.owned, ...M.offers].map(String));
      return el("div", { class: "chips" }, M[key].map((h, i) => chip("augments", h, () => { M[key].splice(i, 1); saveMatch(); draw(); })),
        M[key].length < count ? picker("augments", T("addHex"), (id) => { M[key].push(id); saveMatch(); draw(); },
          (a) => !taken.has(String(a.id)) && !a.disabled) : null);
    }

    async function fromGame(silent) {
      const r = await fetch("api/live").then((x) => x.json()).catch(() => null);
      if (!r || r.error) { if (!silent) alert(T("noGame")); return; }
      M.champ = r.champ; M.allies = r.allies; M.enemies = r.enemies; M.items = r.items;
      saveMatch(); draw();
    }
    let readTimer = null, readNote = "", lastSig = "", readChoices = [];
    async function applyRead(r, silent) {
      if (!r || r.error) { readNote = r ? r.error : T("noClient"); draw(); return; }
      const ids = r.cards.filter((c) => c.id).map((c) => c.id);
      const choices = r.cards.map((c, i) => ({ n: i + 1, text: c.text, alts: c.alternatives || [] })).filter((c, i) => !r.cards[i].id && c.alts.length);
      const sig = ids.join() + "|" + choices.map((c) => c.alts.join()).join("|");
      if (silent && (!r.on_screen || sig === lastSig)) return; // nothing new on screen
      lastSig = sig;
      if (ids.length || choices.length) M.offers = ids.filter((h) => !M.owned.map(String).includes(String(h))).slice(0, 3);
      readChoices = choices;
      readNote = r.on_screen ? T("readSome").replace("{n}", ids.length) : T("readNone");
      saveMatch(); draw();
    }
    async function readScreen(silent) {
      if (!silent) { readNote = T("reading"); draw(); }
      applyRead(await fetch("api/screen").then((x) => x.json()).catch(() => null), silent);
    }
    async function readImage(blob) {
      readNote = T("reading"); draw();
      applyRead(await fetch("api/screen", { method: "POST", body: blob }).then((x) => x.json()).catch(() => null), false);
    }
    const onPaste = (e) => {
      const f = [...(e.clipboardData || {}).items || []].find((i) => i.type.startsWith("image/"));
      if (f && S.local && location.hash.startsWith("#/grade")) { e.preventDefault(); readImage(f.getAsFile()); }
    };
    document.removeEventListener("paste", window.__augurPaste || (() => {}));
    window.__augurPaste = onPaste;
    document.addEventListener("paste", onPaste);
    window.addEventListener("hashchange", () => { clearInterval(readTimer); clearInterval(followTimer); }, { once: true });

    async function benchNow() {
      const r = await fetch("api/champselect").then((x) => x.json()).catch(() => null);
      if (!r || r.error) { alert(r && r.error ? r.error : T("noClient")); return; }
      M.champ = r.me; M.allies = r.team; M.enemies = r.enemies || []; saveMatch();
      draw(r);
    }

    function draw(bench) {
      if (M.champ && S.local && !S.opgg[M.champ]) loadOpgg(M.champ, () => draw(bench));
      const g = S.grader;
      const form = el("div", { class: "panel" }, el("div", { class: "form-grid" },
        el("label", {}, T("yourChamp")), el("div", { class: "chips" },
          M.champ ? chip("champions", M.champ, () => { M.champ = null; saveMatch(); draw(); }) : picker("champions", T("pickChamp"), (id) => { M.champ = id; saveMatch(); draw(); })),
        el("label", {}, T("allies")), teamSlots("allies", 4),
        el("label", {}, T("enemies")), teamSlots("enemies", 5),
        el("label", {}, T("owned")), hexSlots("owned", 6),
        el("label", {}, T("offers")), hexSlots("offers", 3),
        el("label", {}, T("ownedItems")), el("div", { class: "chips" }, M.items.map((it, i) => chip("items", it, () => { M.items.splice(i, 1); saveMatch(); draw(); })),
          M.items.length < 6 ? picker("items", T("addItem"), (id) => { M.items.push(id); saveMatch(); draw(); }, (it) => it.completed) : null)),
        el("div", { class: "row", style: "margin-top:12px" },
          S.local ? el("button", { type: "button", class: "primary", onclick: () => fromGame(false) }, T("fromGame")) : null,
          S.local ? el("label", { class: "row small" }, el("input", { type: "checkbox", checked: !!followTimer, onchange: (e) => {
            clearInterval(followTimer); followTimer = e.target.checked ? setInterval(() => fromGame(true), 5000) : null;
          } }), T("follow")) : null,
          S.local ? el("button", { type: "button", onclick: benchNow }, T("champSelect")) : null,
          S.local ? el("button", { type: "button", class: "primary", onclick: () => readScreen(false) }, T("readScreen")) : null,
          S.local ? el("label", { class: "row small" }, el("input", { type: "checkbox", checked: !!readTimer, onchange: (e) => {
            clearInterval(readTimer); readTimer = e.target.checked ? setInterval(() => readScreen(true), 4000) : null;
          } }), T("autoRead")) : null,
          el("div", { class: "grow" }),
          el("button", { type: "button", class: "ghost", onclick: () => { S.match = { champ: null, allies: [], enemies: [], owned: [], offers: [], items: [] }; Object.assign(M, S.match); saveMatch(); draw(); } }, T("clear"))));

      const out = [];
      if (S.local) {
        const drop = el("div", { class: "dropzone small muted", tabindex: 0,
          ondragover: (e) => { e.preventDefault(); drop.classList.add("over"); },
          ondragleave: () => drop.classList.remove("over"),
          ondrop: (e) => { e.preventDefault(); drop.classList.remove("over"); const f = e.dataTransfer.files[0]; if (f) readImage(f); } },
          readNote ? el("b", { class: "", style: "color:var(--text)" }, readNote) : null, readNote ? " · " : null, T("dropShot"),
          readChoices.map((c) => el("div", { class: "choice" },
            T("unsureCard").replace("{n}", c.n).replace("{t}", c.text ? ` ("${c.text}")` : ""), " ",
            c.alts.map((h) => el("button", { type: "button", onclick: () => {
              if (M.offers.length < 3 && !M.offers.map(String).includes(String(h))) M.offers.push(h);
              readChoices = readChoices.filter((x) => x !== c); saveMatch(); draw();
            } }, chip("augments", h))))));
        out.push(drop);
      }
      if (bench) {
        const b = g.gradeBench({ me: bench.me, bench: bench.bench, team: bench.team });
        out.push(el("h2", {}, T("bench")), el("p", { class: "muted" }, T("benchHelp")),
          el("div", { class: "results" }, b.map((r, i) => resultCard(r, i === 0))));
      }
      if (!M.champ) out.push(el("p", { class: "muted", style: "margin-top:14px" }, T("enterChamp")));
      else {
        const ctx = { champ: M.champ, allies: M.allies, enemies: M.enemies, owned: M.owned, offers: M.offers, items: M.items };
        out.push(el("h2", {}, T("gradesFor")));
        if (!M.offers.length) out.push(el("p", { class: "muted" }, T("enterOffers")));
        else {
          const res = g.gradeOffers(ctx);
          const bestTotal = Math.max(...res.offers.map((o) => o.total));
          out.push(el("div", { class: "results" }, res.offers.map((r) => resultCard(r, r.total === bestTotal, () => pick(r, res)))));
          if (res.reroll) out.push(el("div", { class: "advice" }, res.reroll.text));
        }
        const items = g.gradeItems(ctx, 6);
        if (items.length) out.push(el("h2", {}, T("nextItems")), el("div", { class: "results" }, items.map((r, i) => resultCard(r, i === 0))));
      }
      root.replaceChildren(form, ...out);
    }

    function pick(r, res) {
      const entry = { time: Date.now(), champ: M.champ, allies: M.allies, enemies: M.enemies, owned: M.owned.slice(),
                      offers: res.offers.map((o) => ({ id: o.id, total: o.total, grade: o.grade })), picked: r.id };
      if (S.local) fetch("api/history", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(entry) }).catch(() => {});
      else { const h = store.get("history", []); h.push(entry); store.set("history", h.slice(-300)); }
      M.owned.push(r.id); M.offers = []; saveMatch(); draw();
    }

    draw();
    return [el("h1", {}, T("grade")), S.local ? el("p", { class: "muted small" }, "● " + T("local")) : null, root];
  }

  async function pageHistory() {
    const box = el("div", {}, T("loading"));
    (async () => {
      let h = S.local ? await fetch("api/history").then((r) => r.json()).catch(() => []) : store.get("history", []);
      if (!h.length) { box.replaceChildren(el("p", { class: "muted" }, T("historyEmpty"))); return; }
      h = h.slice().reverse();
      const counts = { best: 0, good: 0, ok: 0, missed: 0 };
      const rows = h.map((e) => {
        const best = e.offers.reduce((a, b) => (b.total > a.total ? b : a));
        const mine = e.offers.find((o) => o.id === e.picked) || best;
        const gap = best.total - mine.total;
        const v = gap <= 0.01 ? "best" : gap < 1 ? "good" : gap < 2.5 ? "ok" : "missed";
        counts[v]++;
        return { e, best, mine, v, gap, t: e.time };
      });
      box.replaceChildren(
        el("div", { class: "stats" }, Object.entries(counts).map(([k, c]) => el("div", { class: "stat" }, el("b", {}, c), el("span", {}, T("verdict")[k])))),
        table([
          { label: "", key: "t", render: (r) => new Date(r.t).toLocaleString() },
          { label: T("champion"), cls: "name", render: (r) => el("span", { class: "ent" }, img((S.game.champions[r.e.champ] || {}).icon), nameOf("champions", r.e.champ)) },
          { label: T("picked"), cls: "name", render: (r) => el("span", {}, gradeBadge(r.mine.grade), " ", nameOf("augments", r.mine.id)) },
          { label: T("bestWas"), cls: "name", render: (r) => (r.v === "best" ? "-" : el("span", {}, gradeBadge(r.best.grade), " ", nameOf("augments", r.best.id))) },
          { label: "", key: "gap", render: (r) => el("b", { class: r.v === "missed" ? "neg" : r.v === "best" ? "pos" : "" }, T("verdict")[r.v]) },
        ], rows, "t"));
    })();
    return [el("h1", {}, T("historyTitle")), box];
  }

  function pageAbout() {
    const m = S.stats.meta;
    const zh = S.lang === "zh" || S.lang === "zh-TW";
    return [el("h1", {}, T("aboutTitle")), el("div", { class: "panel" }, el("div", { html: zh ? `
      <p><b>Augur</b> 是免费开源的海克斯大乱斗工具：海克斯排行、英雄海克斯和出装，以及对局中每张海克斯卡的评分和理由。</p>
      <h3>数据从哪里来</h3>
      <p>所有胜率都来自 Riot 官方比赛数据（match-v5 API 或你自己的英雄联盟客户端）。海克斯列表、名称和图标来自游戏文件（CommunityDragon 镜像），说明文字来自 League of Legends Wiki（CC BY-SA）。</p>
      <h3>评分怎么算</h3>
      <p>每个评分是若干部分相加，单位是胜率百分点：这个英雄带它的实际胜率、全英雄胜率、和英雄是否契合、敌我阵容（实测）、和已有海克斯的搭配（实测）、第几轮选、以及你自己的战绩。样本少时会向先验值收缩：<code>(场次 × 实测 + K × 先验) / (场次 + K)</code>，所以 10 场的运气不会让评分乱跳。分数 = 50 + 5 × 总和，对应 S+ 到 D。</p>
      <p>只使用当前版本的对局；游戏更新新版本后，OP.GG 数据会自动重新下载，评分跟随当前版本的平衡。</p>
      <h3>局限</h3>
      <p>比赛数据只记录选了什么，不记录当时可选的另外两张卡。胜率是相关性，不完全是因果。</p>` : `
      <p><b>Augur</b> is a free, open-source ARAM Mayhem tool: hex tier lists, per-champion hexes and builds, and a grade with reasons for every hex card you are offered.</p>
      <h3>Where the data comes from</h3>
      <p>All win rates come from Riot's own match data (the match-v5 API, or your own League client). The hex list, names and icons come from the game files (mirrored by CommunityDragon); descriptions come from the League of Legends Wiki (CC BY-SA).</p>
      <h3>How grades work</h3>
      <p>A grade adds up parts, each in win-rate points: how this champion does with the hex, how it does for everyone, fit with the champion, both teams (measured), synergy with hexes you own (measured), the pick round, and your own record. Small samples are pulled toward a prior: <code>(games × measured + K × prior) / (games + K)</code>, so 10 lucky games barely move a grade. Score = 50 + 5 × total, shown as S+ to D.</p>
      <p>Only the current patch counts, and OP.GG data is re-downloaded when a new game version comes out, so grades follow the current balance.</p>
      <h3>Limits</h3>
      <p>Match data shows which hex was picked, not the two that were skipped. Win rate shows correlation, not proof of cause.</p>` }),
      el("h3", {}, T("games")), el("p", {}, hasStats()
        ? Object.entries(m.patches).map(([p, w]) => `${T("patch")} ${p}: ${num((m.games || {})[p] || 0)} (×${w})`).join(" · ")
        : T("noStats"))),
    ];
  }

  /* ---------- settings (local helper / desktop app) ---------- */
  function pageSettings() {
    if (!S.local) return [el("p", { class: "muted" }, T("noClient"))];
    const st = Object.assign({}, S.settings);
    const msg = el("span", { class: "muted small" });
    const row = (label, input) => [el("label", {}, label), el("div", {}, input)];
    const check = (key) => el("input", { type: "checkbox", checked: !!st[key], onchange: (e) => { st[key] = e.target.checked; } });
    const lines = (key) => el("textarea", { rows: 3, style: "width:100%", oninput: (e) => {
      st[key] = e.target.value.split("\n").map((x) => x.trim()).filter(Boolean); } }, (st[key] || []).join("\n"));
    const langSel = el("select", { onchange: (e) => { st.ui_lang = e.target.value; } },
      Object.entries(I18N.LANGS).map(([c, l]) => el("option", { value: c, selected: c === (st.ui_lang || S.lang) }, l)));
    const posSel = el("select", { onchange: (e) => { st.overlay_position = e.target.value; } },
      [["top-right", "posTR"], ["top-left", "posTL"], ["bottom-right", "posBR"], ["bottom-left", "posBL"]].map(([v, k]) =>
        el("option", { value: v, selected: v === st.overlay_position }, T(k))));
    const interval = el("input", { type: "number", min: 1, max: 30, step: 1, value: st.read_interval || 3, style: "width:80px",
      oninput: (e) => { st.read_interval = Number(e.target.value) || 3; } });
    const opacity = el("input", { type: "range", min: 0.3, max: 1, step: 0.05, value: st.overlay_opacity || 0.92,
      oninput: (e) => { st.overlay_opacity = Number(e.target.value); } });
    const ocr = el("div", { class: "row" }, [["ko", "한국어"], ["ja", "日本語"]].map(([c, l]) => el("label", { class: "row small" },
      el("input", { type: "checkbox", checked: (st.ocr_extra || []).includes(c), onchange: (e) => {
        const set = new Set(st.ocr_extra || []); e.target.checked ? set.add(c) : set.delete(c); st.ocr_extra = [...set]; } }), l)));
    async function save() {
      const body = {};
      for (const k of ["ui_lang", "auto_read", "read_interval", "overlay", "overlay_position", "overlay_opacity", "use_opgg", "my_riot_ids", "lockfile_paths", "ocr_extra"])
        if (st[k] !== undefined && st[k] !== null) body[k] = st[k];
      const r = await fetch("api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
        .then((x) => x.json()).catch(() => ({ error: "offline" }));
      if (r.error) { msg.textContent = r.error; return; }
      S.settings = r;
      if (r.ui_lang && r.ui_lang !== S.lang) { S.lang = r.ui_lang; store.set("lang", S.lang); makeGrader(); chrome(); route(); return; }
      msg.textContent = T("sSaved");
    }
    const jobBox = el("pre", { class: "small muted", style: "white-space:pre-wrap;max-height:200px;overflow:auto" });
    async function job(name) {
      await fetch("api/" + name, { method: "POST" }).catch(() => null);
      const poll = async () => {
        const j = await fetch("api/job").then((x) => x.json()).catch(() => null);
        if (!j) return;
        const cur = j[name];
        jobBox.textContent = (cur.running ? T("sRunning") + "\n" : "") + cur.log.join("\n") + (cur.error ? "\n" + cur.error : "")
          + (!cur.running && !cur.error ? "\n" + T("sDone") : "");
        if (cur.running) setTimeout(poll, 1500);
        else if (name !== "settings") { S.stats = await fetch("data/stats.json", { cache: "no-cache" }).then((x) => x.json()).catch(() => S.stats); makeGrader(); }
      };
      poll();
    }
    return [el("h1", {}, T("settings")),
      el("div", { class: "panel" }, el("div", { class: "form-grid" },
        row(T("language"), langSel),
        row(T("sReading"), el("div", {}, el("label", { class: "row" }, check("auto_read"), T("sAutoRead")),
          el("div", { class: "row small", style: "margin-top:6px" }, T("sInterval"), interval),
          S.settings.ocr_available === false ? el("p", { class: "neg small" }, T("sNoOcr")) : null)),
        row(T("sOcr"), ocr),
        row("Overlay", el("div", {}, el("label", { class: "row" }, check("overlay"), T("sOverlay")),
          el("div", { class: "row small", style: "margin-top:6px" }, T("sPosition"), posSel),
          el("div", { class: "row small", style: "margin-top:6px" }, T("sOpacity"), opacity))),
        row("OP.GG", el("label", { class: "row" }, check("use_opgg"), T("sOpgg"))),
        row("Riot ID", lines("my_riot_ids")), el("div"), el("p", { class: "muted small", style: "margin:0" }, T("sRiotIds")),
        row("Lockfile", lines("lockfile_paths")), el("div"), el("p", { class: "muted small", style: "margin:0" }, T("sLockfile"))),
        el("div", { class: "row", style: "margin-top:12px" }, el("button", { type: "button", class: "primary", onclick: save }, T("sSave")), msg)),
      el("h2", {}, T("sData")),
      el("div", { class: "panel" },
        el("p", { class: "small" }, T("sDataFolder"), " ", el("code", {}, S.settings.data_folder || "")),
        el("p", { class: "muted small" }, T("sCollectHelp")),
        el("div", { class: "row" }, el("button", { type: "button", class: "primary", onclick: () => job("collect") }, T("sCollect")),
          el("button", { type: "button", onclick: () => job("build") }, T("sRebuild")),
          el("button", { type: "button", onclick: () => job("opgg_all") }, T("opggAllBtn"))),
        jobBox)];
  }

  /* ---------- overlay: small always-on-top window with the grades ---------- */
  function pageOverlay(q) {
    const box = el("div", { class: "ov" }, el("p", { class: "muted small" }, T("ovWaiting")));
    const call = (fn, ...a) => { try { const api = window.pywebview && window.pywebview.api; if (api && api[fn]) api[fn](...a); } catch (e) { /* not in the app */ } };
    let misses = 0, lastLive = 0, lastIds = "";
    const opacity = () => (S.settings && S.settings.overlay_opacity) || 0.92;

    function render(sc) {
      const M = store.get("match", { champ: null, allies: [], enemies: [], owned: [], offers: [], items: [] });
      const ids = sc.cards.filter((c) => c.id).map((c) => c.id);
      if (!M.champ) { box.replaceChildren(el("p", { class: "small" }, T("ovSetChamp"))); return; }
      if (S.local && !S.opgg[M.champ]) loadOpgg(M.champ, () => render(sc));
      const res = S.grader.gradeOffers({ champ: M.champ, allies: M.allies, enemies: M.enemies, owned: M.owned, items: M.items, offers: ids });
      const totals = res.offers.map((o) => o.total);
      const best = totals.length && Math.max(...totals) - Math.min(...totals) > 0.05 ? Math.max(...totals) : null;
      const rows = res.offers.map((o) => el("button", { type: "button", class: "ov-row" + (o.total === best ? " best" : ""), title: T("pickThis"),
        onclick: () => {
          const m = store.get("match", M); m.owned = [...(m.owned || []), o.id].slice(0, 6); store.set("match", m);
          const entry = { time: Date.now(), champ: m.champ, allies: m.allies, enemies: m.enemies, owned: M.owned,
                          offers: res.offers.map((x) => ({ id: x.id, total: x.total, grade: x.grade })), picked: o.id };
          fetch("api/history", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(entry) }).catch(() => {});
          call("hide");
        } },
        gradeBadge(o.grade), el("span", { class: "ov-text" }, el("b", {}, o.name),
          o.parts.filter((p, i) => i === 0 || Math.abs(p.v) >= 0.3).slice(0, 2).map((p) => el("span", { class: "ov-why " + (p.v > 0.05 ? "pos" : p.v < -0.05 ? "neg" : "muted") },
            (p.v >= 0 ? "+" : "") + p.v.toFixed(1) + " " + p.text)))));
      const unsure = sc.cards.filter((c) => !c.id && (c.alternatives || []).length).map((c) =>
        el("div", { class: "ov-why muted" }, "? " + c.alternatives.map((h) => nameOf("augments", h)).join(" / ")));
      box.replaceChildren(el("div", { class: "ov-head small muted" }, nameOf("champions", M.champ)), ...rows, ...unsure,
        res.reroll ? el("div", { class: "ov-why ov-reroll" }, res.reroll.text) : null);
      box.style.opacity = opacity();
    }

    async function tick() {
      if (!location.hash.startsWith("#/overlay")) return;
      const st = S.settings || {};
      if (st.overlay === false) { call("hide"); setTimeout(tick, 5000); return; }
      try {
        if (Date.now() - lastLive > 10000) {
          lastLive = Date.now();
          const r = await fetch("api/live").then((x) => x.json()).catch(() => null);
          if (r && !r.error && r.champ) {
            const m = store.get("match", { owned: [], offers: [], items: [] });
            if (m.champ !== r.champ) m.owned = []; // a new game
            Object.assign(m, { champ: r.champ, allies: r.allies, enemies: r.enemies, items: r.items });
            store.set("match", m);
            if (S.local && !S.opgg[r.champ]) loadOpgg(r.champ);
          }
        }
        // ?test=<image> reads that picture instead of the screen (for trying the overlay without a game)
        const shot = q && q.test ? await fetch(q.test).then((x) => x.blob()).catch(() => null) : null;
        const sc = st.auto_read === false ? null
          : await fetch("api/screen", shot ? { method: "POST", body: shot } : {}).then((x) => x.json()).catch(() => null);
        if (sc && sc.on_screen) {
          misses = 0;
          const sig = sc.cards.map((c) => c.id).join();
          if (sig !== lastIds) { lastIds = sig; render(sc); }
          call("show");
        } else if (++misses >= 2) {
          lastIds = ""; call("hide");
          box.replaceChildren(el("p", { class: "muted small" }, T("ovWaiting")));
        }
      } catch (e) { /* keep watching */ }
      setTimeout(tick, Math.max(1, st.read_interval || 3) * 1000);
    }
    setTimeout(tick, 500);
    return [box];
  }

  /* ---------- router ---------- */
  const ROUTES = [
    ["", "hexes", pageHexes], ["champions", "champions", pageChampions], ["grade", "grade", pageGrade],
    ["history", "history", pageHistory], ["settings", "settings", pageSettings], ["about", "about", pageAbout],
    ["overlay", "overlay", pageOverlay],
  ];
  async function route() {
    const [path, qs] = location.hash.replace(/^#\/?/, "").split("?");
    const q = Object.fromEntries(new URLSearchParams(qs || ""));
    const [head, arg] = path.split("/");
    const app = document.getElementById("app");
    document.body.classList.toggle("is-overlay", head === "overlay");
    let view;
    if (head === "champion") view = pageChampion(arg);
    else if (head === "hex") view = pageHex(arg);
    else view = await (ROUTES.find((r) => r[0] === head) || ROUTES[0])[2](q);
    app.replaceChildren(...[view].flat(3).filter(Boolean));
    const active = head === "champion" ? "champions" : head === "hex" ? "" : head;
    document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("on", a.dataset.r === active));
    window.scrollTo(0, 0);
  }
  function chrome() {
    document.documentElement.lang = S.lang === "zh" ? "zh-CN" : S.lang;
    document.getElementById("nav").replaceChildren(...ROUTES.filter((r) => r[1] !== "overlay" && (r[1] !== "settings" || S.local)
      && (r[1] !== "history" || S.local || store.get("history", []).length))
      .map((r) => el("a", { href: "#/" + r[0], "data-r": r[0] }, T(r[1]))));
    const sel = document.getElementById("lang");
    sel.replaceChildren(...Object.entries(I18N.LANGS).map(([code, label]) => el("option", { value: code, selected: code === S.lang }, label)));
    sel.title = T("language");
    const m = S.stats.meta;
    document.getElementById("banner").replaceChildren(m.demo ? el("div", { class: "banner warn" }, "⚠ " + T("demo")) : "");
    document.getElementById("foot").replaceChildren(
      el("p", {}, `Augur · game data ${S.game.version} · ${hasStats() ? num(m.total_games) + " games" : "no games yet"}`),
      el("p", {}, "Augur isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc."),
      el("p", {}, "Hex descriptions: League of Legends Wiki, CC BY-SA 3.0."),
      S.local ? el("p", {}, "Lines marked OP.GG: ARAM hex stats from ", el("a", { href: "https://op.gg", target: "_blank", rel: "noopener" }, "OP.GG"),
        " (official public data server), fetched by your copy of Augur.") : null);
  }
  document.getElementById("lang").addEventListener("change", (e) => {
    S.lang = e.target.value; store.set("lang", S.lang); makeGrader(); chrome(); route();
  });
  window.addEventListener("hashchange", route);
  load().then((ok) => { if (ok) { chrome(); route(); } });
})();
