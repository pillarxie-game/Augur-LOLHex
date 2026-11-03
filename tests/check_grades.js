// Checks the grader recovers the effects planted by tools/make_demo_db.py.
const fs = require("fs"), path = require("path");
const { Grader } = require("../augur/web/grade.js");
const root = path.join(__dirname, "..");
const game = JSON.parse(fs.readFileSync(path.join(root, "data/gamedata.json")));
const stats = JSON.parse(fs.readFileSync(path.join(root, "data-demo/stats.json")));
const truth = JSON.parse(fs.readFileSync(path.join(root, "data-demo/truth.json")));
const G = new Grader(game, stats, { lang: process.argv[2] || "en" });
const id = (name) => Number(Object.values(game.champions).find((c) => c.key === name).id);
const hex = (name) => Object.values(game.augments).find((a) => a.name === name).id;
let fails = 0;
const check = (ok, msg) => { console.log((ok ? "PASS " : "FAIL ") + msg); if (!ok) fails++; };
const show = (r) => console.log(`  ${r.grade} ${r.name} (${r.total.toFixed(1)})\n` + r.parts.map((p) => `     ${p.v >= 0 ? "+" : ""}${p.v.toFixed(1)} ${p.text}`).join("\n"));

const tanks = ["Malphite", "Sejuani", "Ornn", "Lux", "Jinx"].map(id);
const squish = ["Lux", "Jinx", "Zed", "Xerath", "Caitlyn"].map(id);
const a = G.gradeHex({ champ: id("Yasuo"), enemies: tanks, allies: [] }, truth.giant);
const b = G.gradeHex({ champ: id("Yasuo"), enemies: squish, allies: [] }, truth.giant);
show(a); show(b);
check(a.total > b.total + 1.5, "Giant Slayer grades much higher vs 3 tanks than vs no tanks");

const apHex = Object.values(game.augments).find((x) => x.tags.includes("ap") && !x.tags.includes("ad") && !x.tags.includes("adaptive") && !x.disabled);
const onAd = G.gradeHex({ champ: id("Draven") }, apHex.id), onAp = G.gradeHex({ champ: id("Lux") }, apHex.id);
show(onAd); show(onAp);
check(onAp.total > onAd.total + 1, `AP hex ${apHex.name} grades higher on Lux than Draven`);

const [h1, h2] = truth.combo;
const withC = G.gradeHex({ champ: id("Ahri"), owned: [h1] }, h2), without = G.gradeHex({ champ: id("Ahri"), owned: [] }, h2);
show(withC);
const syn = withC.parts.find((p) => p.text.includes(game.augments[h1].name));
check(syn && syn.v > 0.2, "Hidden combo detected as synergy");

const offers = G.gradeOffers({ champ: id("Yasuo"), enemies: tanks, owned: [], offers: [truth.giant, hex("Goliath"), hex("Tank Engine")] });
console.log("  reroll:", offers.reroll.text);
check(offers.offers.length === 3 && offers.reroll && offers.reroll.text, "Offers graded with reroll advice");

const golds = Object.values(game.augments).filter((x) => x.rarity === "gold" && !x.disabled)
  .map((x) => G.gradeHex({ champ: id("Lux") }, x.id)).sort((x, y) => x.total - y.total);
const weak = G.gradeOffers({ champ: id("Lux"), owned: [], offers: golds.slice(0, 3).map((x) => x.id) });
console.log("  weak cards reroll:", weak.reroll.text);
check(weak.reroll.card !== null && weak.reroll.gain > 1, "Reroll suggested when all three cards are weak");

const items = G.gradeItems({ champ: id("Yasuo"), items: [], enemies: ["Soraka", "Aatrox", "Malphite", "Ornn", "Lux"].map(id) });
items.slice(0, 3).forEach(show);
check(items.length > 0, "Item grades returned");

const bench = G.gradeBench({ me: id("Lux"), bench: [id("Malphite"), id("Jinx")], team: ["Xerath", "Ahri", "Zoe", "Lux"].map(id).slice(0, 3) });
bench.forEach(show);
check(bench.length === 3, "Bench graded");
process.exit(fails ? 1 : 0);
