# Augur

Free, open-source stats and advice for **ARAM: Mayhem** (海克斯大乱斗).

- **Hex tier list**: win rate, pick rate and tier for every hex (augment), by rarity.
- **Champion pages**: best and worst hexes for each champion, best hex combos, items and build order.
- **Hex pages**: what a hex does, win rate by pick round, best champions, best partner hexes.
- **Match helper**: click **Read cards from screen** (or turn on **Auto-read**, or paste a screenshot) and it recognizes the 3 offered hexes, in English or 中文. Your champion and both teams load from the running game. Each card gets a grade from S+ to D, with the reasons behind it, for example:

  ```
  S  Giant Slayer
     +5.1  All champions: +5.7% with it (3,531 games)
     +3.0  Enemy has 3 tanks (Malphite, Sejuani, Ornn) · measured +3.1% in 2,399 games
     -1.0  Your team has no frontline · measured -1.8% in 353 games
  ```

  It also tells you whether a reroll is worth it, grades your next item, grades the ARAM bench in champion select, and keeps a record of your picks ("My games": best / good / OK / missed).
- **16 languages**: English, 简体中文, 繁體中文, 한국어, 日本語, Español, Português, Français, Deutsch, Italiano, Polski, Русский, Türkçe, Tiếng Việt, ไทย, Bahasa Indonesia. Hex, champion and item names come from the game's own translations; the website and every grade reason are translated.

Everything is free. Statistics come from Riot's own match data, plus **OP.GG's ARAM hex stats** fetched live from [OP.GG's official public data server](https://github.com/opgginc/opgg-mcp) by the local helper. No Hexdata or WeGame data is used.

## Quick start (Windows)

1. Install [Python 3.9+](https://www.python.org/downloads/) (tick "Add Python to PATH"). Nothing else is needed.
2. Double-click `start.bat`. It downloads the hex list, builds the site and opens the match helper at `http://127.0.0.1:8765`.

macOS / Linux: `./start.sh`.

The website starts **without statistics**. Collect games first (next section), and grades become meaningful as data grows.

## Reading the cards from your screen

The match helper reads the 3 hex cards from your screen: OCR reads each card's name, and its icon is compared with the official hex icons as a second check. It works at any resolution (tested 720p, 1080p, 1440p, ultrawide) and with clients in any of the 16 languages: names are matched against every translation, Korean and Japanese use extra OCR models (downloaded on first use, about 7 MB), and when a name can't be read (for example Russian, or a very long name) the card's rarity color and icon are used. If Augur isn't sure, it never fills the card in: it shows its 3 best guesses for you to tap. A hex that is no longer in the current pool is reported instead of being guessed.

`start.bat` installs what this needs the first time (`requirements-screen.txt`: Pillow, numpy, RapidOCR, all free and offline). To try it on a saved screenshot: `python -m augur read screenshot.png`. Play in **borderless** or **windowed** mode so screenshots can see the game.

## OP.GG hex data

When you run the local helper (`start.bat`), Augur asks OP.GG's official data server for your champion's ARAM hex stats (tier, performance and popularity) and adds a line to every grade, for example `+0.9 OP.GG: tier 4 for Yasuo, performance 96.5 (median 88.0)`. Answers are cached for 12 hours in `data/opgg/` on your PC. OP.GG data is never saved into this repository or the published website, and the source is credited on the page.

What OP.GG gives and doesn't give:
- It lists about 95 of the current Mayhem hexes per champion. It **leaves out its own top 2 tiers**, so the strongest hexes show "Not in OP.GG's list", which counts as neutral, not bad.
- Rarely picked hexes have unreliable scores, so a hex's OP.GG score counts less the less popular it is.
- Your own collected games count more as they grow, and OP.GG counts less.

Try it: `python -m augur opgg Yasuo`.

## Collecting games

**No API key needed: your League client (any server, including 国服).** With the client open and logged in, this reads match history through the client itself:

```
python -m augur collect-client --games 500
```

On Windows, just double-click `collect.bat` (it collects, then rebuilds the stats). Run it again any time to add more games.

**Riot API (KR, NA, EUW, …), optional, faster**

1. Sign in at <https://developer.riotgames.com> and copy your development key (`RGAPI-…`, valid for 24 hours).
2. Copy `config.example.json` to `config.local.json` and fill in your key and region (`americas`, `asia`, `europe` or `sea`). This file is never committed.
3. Start from any Mayhem player (yourself is fine):

   ```
   python -m augur collect --riot-id "YourName#TAG" --games 2000
   ```

   It keeps adding the other players of each game, so it spreads across the server. A dev key does roughly 1,000–1,500 games an hour (`--no-timeline` doubles that, but skips item order).

**Then rebuild:** `python -m augur build`, and check progress with `python -m augur info`.

How much data is enough? About 2,000 games give useful overall hex rankings. Champion-specific grades need around 20,000+ games. Until then, grades lean on the all-champion numbers and on simple rules (e.g. "AP hex on an AD champion"), and the reasons say how many games each number comes from.

### Sharing data

`python -m augur export` writes all your games to `dataset.jsonl.gz` with player names and ids removed. Others can add it with `python -m augur import dataset.jsonl.gz` (duplicates are skipped), so several people can pool their games.

## Publishing the website (GitHub Pages)

`python -m augur build` writes a complete static site to `docs/`. Push the repo, then in **Settings → Pages** choose "Deploy from a branch", branch `main`, folder `/docs`.

To update it automatically every day, add a repository secret `RIOT_API_KEY` and a variable `SEED_RIOT_ID` (a Riot ID to start from). The workflow in `.github/workflows/update.yml` collects games, rebuilds and commits `docs/`. Dev keys expire daily, so for unattended runs [register the app](https://developer.riotgames.com) for a personal or production key. Riot requires a registered key for public projects.

## How the grades work

All numbers are win-rate points (+1.0 ≈ one percent more wins).

1. **Counting.** Every game adds 10 rows (one per player) to tables of games and wins: champion, champion + hex, hex by round, hex pairs, hex × team situation, champion + item + slot.
2. **Recent patches count more.** Only the newest 3 patches are used, each older patch counting half as much, so grades follow the current balance.
3. **Small samples are pulled toward a prior:** `estimate = (games × measured + K × prior) / (games + K)`. 10 lucky games barely move a grade. 3,000 games mostly speak for themselves.
4. **The parts of a hex grade:**
   - *Champion data*: this champion's win rate with the hex, minus the champion's own average.
   - *All champions*: how the hex does for everyone (the prior for thin champion data).
   - *Fit rules*: AP/AD/attack-speed/mana/support/tank fit, from the hex description. These fade out as champion data grows.
   - *Team situation (measured)*: enemy has 2+ tanks, is mostly AP, mostly AD, has healers, or your team has no frontline. The effect of each on each hex is measured from games.
   - *Synergy (measured)*: how much better the hex does when you already own another hex.
   - *Pick round* and *your own record* (your games only, from `my_riot_ids`; never published).
5. **Score** = 50 + 5 × total, shown as S+ (≥ +4.5), S, A, B, C, D (< −1.5).
6. **Reroll advice** compares your best card with the average card you could get from the same rarity pool.

**Limits.** Riot's data shows which hexes were picked, not which three were offered. Win rate is correlation: better players may favor some hexes. Comparing against each champion's own average and using large samples reduce this, but don't remove it.

## Data sources

| Data | Source |
| --- | --- |
| Game results, hexes picked, items, damage | Riot API match-v5 / your League client |
| Hex pool, names (EN + 中文), rarity, icons | League client game data, mirrored by [CommunityDragon](https://www.communitydragon.org) |
| Hex descriptions | [League of Legends Wiki](https://wiki.leagueoflegends.com/en-us/ARAM:_Mayhem/Augments), CC BY-SA 3.0 |
| Champions, items | Riot Data Dragon |

Run `python -m augur update` after each patch to pick up new or changed hexes.

## Commands

```
python -m augur update            download hex list, champions, items
python -m augur collect ...       collect games (Riot API)
python -m augur collect-client    collect games (League client, any server)
python -m augur build             compute stats and build docs/
python -m augur serve             local match helper (reads your live game and champ select)
python -m augur info              games per patch
python -m augur opgg Yasuo        OP.GG's ARAM hex stats for a champion
python -m augur read [image]      recognize the offered hexes (screenshot file, or the screen now)
python -m augur tierlist --champ Yasuo
python -m augur export / import   share games
```

## Development

- `python tools/make_demo_db.py` creates fake games with known effects (e.g. Giant Slayer is strong against tanks, one hidden hex combo). `python -m augur --demo serve` shows them with a "DEMO DATA" banner. Demo data never goes into `docs/`.
- Tests: `python -m unittest discover tests` and `node tests/check_grades.js` (after building the demo).
- The grading engine is `augur/web/grade.js`. The website and the local helper both use it.

---

Augur isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.

---

## 中文说明

Augur 是免费开源的**海克斯大乱斗**工具：海克斯排行、英雄最佳海克斯和组合、出装，以及对局中每张海克斯卡的 S+ 到 D 评分和理由（比如「敌方有 3 个坦克 → 巨人杀手更强」）。还会告诉你该不该刷新、下一件装备、选人阶段备选席评分，并记录你的选择。

**使用：** 安装 Python 3.9+，双击 `start.bat`。在对局助手中点「从屏幕读取海克斯」（或打开「自动读取」），会自动识别屏幕上的 3 张海克斯卡并评分。游戏请用无边框或窗口模式。

**收集数据（不需要 API key，任何服务器包括国服）：** 打开并登录英雄联盟客户端，运行 `python -m augur collect-client --games 500`，然后 `python -m augur build`。外服可以用 Riot API（见上方英文说明）。

数据全部来自 Riot 官方比赛数据，不使用 Hexdata、OP.GG 或 WeGame 的数据。
