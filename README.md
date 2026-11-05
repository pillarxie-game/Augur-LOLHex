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

## Download the app

**Windows:** download `Augur-windows.zip` from the [Releases](../../releases) page, unzip it anywhere, and double-click **`Augur.exe`**. No Python or anything else to install.

- The main window has the hex tier list, champion pages, the match helper and **Settings** (language, card reading, overlay position and opacity, OP.GG on/off, your Riot IDs, client location, and collecting games).
- During a game, a small **overlay** pops up in a corner when hex cards appear, showing each card's grade and why, and hides itself after you pick. Click a card in the overlay to record your pick.
- Play in **borderless** or **windowed** mode so Augur can see the screen.
- Windows may show "Windows protected your PC" because the app isn't signed: click **More info → Run anyway**.
- Your data and settings live in `%APPDATA%\Augur`.

**macOS:** `Augur-macos.zip` works the same way (Apple silicon). Right-click `Augur.app` → **Open** the first time, and allow **Screen Recording** when asked.

### Building the app yourself

The workflow `.github/workflows/build-app.yml` builds both apps on GitHub for free: open **Actions → Build app → Run workflow**, then download the files from the finished run. Pushing a tag such as `v1.0.0` also attaches them to a release. Each build runs `Augur.exe --selftest`, which draws 3 hex cards, reads them back and fails the build if anything is wrong.

Locally: `pip install -r requirements-app.txt pyinstaller`, `python -m augur update`, then `pyinstaller packaging/augur.spec`. Run from source without packaging: `python -m augur.desktop`.

## Quick start from source (Windows)

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
- It lists about 130 of the current Mayhem hexes per champion, in its **tiers 3–5**, which follow popularity. A hex it leaves out for a champion is **either one of that champion's most picked hexes or one almost nobody picks on it**. (BEES!!!, the most picked hex overall, is unlisted for 172 of 173 champions; so is Group Hug, one of the least picked.) So "not listed" is never shown as a tier: the page says "not listed" and the score is Augur's estimate.
- For an unlisted hex, Augur uses (1) how popular the hex is overall this patch, (2) whether its damage stat fits the champion's real OP.GG build (Eureka, "ability haste equal to 30% AP", on Darius, who builds about 10% AP items: no), and (3) similar champions. Hexes the game itself makes useless (range hexes on melee champions, mana hexes without mana, upgrades of items the champion doesn't build) score near 0.
- OP.GG's performance score (compared with the champion's other hexes, trusted by how many games it comes from) counts more than its tier. It is shown in its own column. It is not a win rate: nobody publishes per-champion Mayhem hex win rates. Win rates shown come from games you collect.
- Your own collected games count more as they grow, and OP.GG counts less.

The app also shows **OP.GG's ARAM build** on each champion page (tier, win rate, core items, boots and 4th/5th item options), and item grades include OP.GG's numbers. Later items are compared with the other options for the same slot, because players who are already winning buy more items.

**Recommended hexes per champion.** A small model (`augur/model.py`) learns from every champion's OP.GG data at once: similar champions, similar hexes, and champion traits × hex traits (including the AP/AD fit above). Checked on held-out OP.GG tiers: 58% exact tier accuracy vs 48% for a simple baseline. The champion page lists every hex the champion can be offered (Show all), with Augur score, OP.GG tier, OP.GG performance, pick rate and your games' win rate where there is data.

**Augur score (0–100).** Every champion + hex pair gets a score: its position among that champion's own hexes (96 = better than about 96% of them). It is computed by the model each time a new game version's OP.GG data is downloaded.

**Checked against arammayhem.com.** [arammayhem.com](https://arammayhem.com)'s open data (CC BY 4.0, "Data: arammayhem.com") tags champion + hex combos as god / strong / trap. These tags are used as extra training labels. On combos the model was **not** trained on, a good combo scores above a trap 63% of the time. Earlier versions counted every unlisted hex as top tier, which showed hexes like Eureka as T1 for nearly every champion; that is fixed. arammayhem.com's pick rates are used only when its data is for the current patch. arammayhem.com also notes that Riot asks developers not to publish Mayhem hex win rates per champion.

**Scores up to 90 by position; above 90 only for standouts.** A hex's position among the champion's hexes gives at most 90; 91–100 is kept for a hex clearly ahead of the champion's other top hexes (about 1 in 700 pairs).

**AP / AD builds.** For champions OP.GG shows building both AP and AD items in real numbers (AP and AD items each at least 12% of item purchases: Kai'Sa, Kayle, Kog'Maw, Katarina, Shyvana, Twisted Fate, Bard…), OP.GG's numbers mix both styles. Augur gives each style its own scores: hexes of that damage type rank as top tier, the other type's hexes rank at the bottom, and for AP on-hit builds (Kai'Sa with Nashor's Tooth) hexes that make abilities apply on-hit (Ethereal Weapon) rank highest. Champion pages have a Mixed / AP / AD switch; in a game the style is picked from the items you own.

**Hexes a champion can't get.** Draw Your Sword ("become melee") is only offered to ranged champions, so it doesn't appear for melee ones (Poppy) and isn't ranked for them. OP.GG's listing pattern can't show availability (a hex listed only for ranged champions is usually just top tier, so hidden, for melee ones), so only the hex description decides this.

**Inputs to the model.** OP.GG tier per champion, OP.GG pick rate (within a tier, hexes picked more often rank higher), and real hex win rates from your collected games (current patch, weighted by games, outweighing OP.GG once there are enough).

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
2. **Current patch only.** Only games from the newest patch count, so grades follow the current balance. (Set `"patches_kept": 3` in `config.local.json` to also use older patches at half weight each.) OP.GG data is re-downloaded whenever a new game version comes out.
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
| Deleted hexes, tagged champion + hex combos | [arammayhem.com](https://arammayhem.com) open data, CC BY 4.0 — Data: arammayhem.com |

Run `python -m augur update` after each patch to pick up new or changed hexes (the app does this by itself).

**Only hexes that can be chosen.** The hex list comes from the live game version's files (CommunityDragon's `16.22` folder, not "latest", which can follow the test server). Riot's files still contain some disabled hexes, so Augur also leaves out the ones in `augur/removed_hexes.json` (e.g. Sneakerhead) and the ones arammayhem.com marks as Deleted, unless OP.GG's data for the current version shows players picking them. You can hide any other hex yourself in Settings → Hidden hexes.

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

Augur 是免费开源的**海克斯大乱斗**助手：海克斯排行、英雄的最佳海克斯和组合、出装，以及对局中每张海克斯卡的 S+ 到 D 评分和理由（例如「敌方有 3 个坦克（墨菲特、瑟庄妮、奥恩）→ 巨人杀手更强」）。还会告诉你该不该刷新、下一件出什么装备、选人阶段备选席谁更好，并记录你每次的选择。支持 16 种语言。

### 下载使用

1. 在 [Releases](../../releases) 下载 `Augur-windows.zip`，解压后双击 **`Augur.exe`**，不需要安装 Python。
2. 如果 Windows 提示「Windows 已保护你的电脑」（软件没有签名），点 **更多信息 → 仍要运行**。
3. 游戏请用**无边框**或**窗口**模式，Augur 才能看到屏幕。

- **主窗口**：海克斯排行、英雄页面、对局助手、我的对局、**设置**。
- **设置**：界面语言、自动读卡和间隔、悬浮窗开关 / 位置 / 透明度、是否使用 OP.GG 数据、韩文 / 日文识别、你的 Riot ID、客户端位置，以及「从客户端收集对局」「重新计算统计」按钮。
- **悬浮窗**：游戏中出现海克斯卡时，在角落弹出每张卡的评分和主要理由，标出最佳选择和刷新建议；选完后自动隐藏。点悬浮窗里的卡会记录你的选择。
- 数据和设置保存在 `%APPDATA%\Augur`。

### 读卡

自动识别屏幕上的 3 张海克斯卡：先用 OCR 读卡名（支持 16 种语言的客户端，含国服中文），再用图标核对。任何分辨率都可以。认不准时不会乱填，而是给出 3 个最可能的选项让你点。已经从游戏中移除的海克斯会提示「不在列表中」。

### 数据来源

| 数据 | 来源 |
| --- | --- |
| 对局结果、选择的海克斯、装备 | Riot 官方比赛数据：你的英雄联盟客户端（任何服务器，含国服，不需要 API key），或 Riot API（外服，可选） |
| **OP.GG 数据** | 来自 [OP.GG 官方公开数据接口](https://github.com/opgginc/opgg-mcp)：每个英雄的大乱斗海克斯评级 / 表现分 / 热度，以及大乱斗出装（核心装备、鞋子、第 4 / 5 件选择和胜率）。由你电脑上的 Augur 直接获取，缓存 12 小时，不会存进本仓库或公开网站 |
| 海克斯列表、名称（含中文）、图标 | 游戏客户端数据（CommunityDragon 镜像） |
| 海克斯说明 | 英雄联盟 Wiki（CC BY-SA 3.0） |
| 英雄、装备 | Riot Data Dragon |
| 已删除的海克斯、英雄 + 海克斯组合标签 | [arammayhem.com](https://arammayhem.com) 公开数据，CC BY 4.0 —— 数据来源：arammayhem.com |

不使用 Hexdata 或 WeGame 的数据。

**每个英雄的推荐海克斯：** 一个小模型（`augur/model.py`）同时用所有英雄的 OP.GG 数据学习：相似英雄、相似海克斯，以及英雄特点 × 海克斯特点（包括 AP/AD 是否匹配）。在留出的 OP.GG 梯队上验证：准确率 58%（简单基线 48%）。英雄页面列出该英雄能遇到的所有海克斯（「显示全部」），包括 Augur 评分、OP.GG 梯队、OP.GG 表现分、选取率，以及有数据时你收集对局的胜率。

**Augur 评分（0–100）：** 每个「英雄 + 海克斯」都有一个分数，表示它在这个英雄所有海克斯中的位置（96 = 强于约 96% 的海克斯），每个新版本重新计算。OP.GG 只列出按热度划分的 T3–T5（每个英雄约 130 个）。没列出的海克斯**可能是这个英雄最常选的，也可能几乎没人选**（全场最热门的 BEES!!! 在 172/173 个英雄上都没列出，最冷门之一的 Group Hug 也是）。所以「未列出」不再显示为 T1：页面显示「未列出」，分数由 Augur 估计，依据：这个海克斯本版本的整体热度、它需要的属性是否符合该英雄的真实出装（尤里卡「获得等于 30% AP 的技能急速」，德莱厄斯只出约 10% AP 装备：不符合），以及相似英雄。游戏本身决定没用的（近战的远距离海克斯、无法力英雄的法力海克斯、不出的装备的升级）接近 0 分。OP.GG 表现分单独一列，它不是胜率：没有人公开每个英雄的大乱斗海克斯胜率；显示的胜率来自你收集的对局。

**与 arammayhem.com 对照：** [arammayhem.com](https://arammayhem.com) 的公开数据（CC BY 4.0）把英雄 + 海克斯组合标为 神 / 强 / 陷阱，作为额外的训练数据。在模型**没见过**的组合上，好组合分数高于陷阱的比例为 63%。旧版本把所有未列出的海克斯都当作顶级，导致尤里卡等对几乎所有英雄都显示 T1，现已修复。arammayhem.com 的选取率只在其数据与当前版本相同时使用。arammayhem.com 也说明 Riot 要求开发者不要公布每个英雄的大乱斗海克斯胜率。

**只显示能选的海克斯：** 海克斯列表来自当前正式服版本的游戏文件（CommunityDragon 的 `16.22` 目录，而不是可能跟随测试服的 "latest"）。Riot 的文件里仍有一些已禁用的海克斯，所以 Augur 还会去掉 `augur/removed_hexes.json` 中的（如「王中王，靴中靴」）以及 arammayhem.com 标记为已删除的——除非 OP.GG 当前版本的数据显示仍有玩家在选。你也可以在设置 → 隐藏的海克斯里自己隐藏任何海克斯。

**AP / AD 两种出装：** 对 OP.GG 数据显示 AP 和 AD 装备都有大量出装的英雄（各占出装次数 12% 以上：卡莎、凯尔、克格莫、卡特琳娜、希瓦娜、崔斯特、巴德……），OP.GG 的数字把两种玩法混在一起。Augur 为每种出装单独评分：同类伤害的海克斯算顶级，另一类排到最后；AP 攻击特效出装（例如出纳什之牙的卡莎）中，让技能触发攻击特效的海克斯（虚幻武器）排最高。英雄页面可以切换「混合 / AP / AD」；对局中会根据你已有的装备自动判断。

**英雄拿不到的海克斯：**「亮出你的剑」（变为近战）只会给远程英雄，所以近战英雄（如波比）的列表里不会出现，也不参与排名。OP.GG 的列出规律无法说明是否可选（只给远程英雄列出的海克斯，通常只是对近战英雄是顶级而被隐藏），所以只按海克斯说明判断。

**评分上限：** 按位置最多 90 分；91–100 只给明显领先于该英雄其他顶级海克斯的海克斯。目前的 OP.GG 数据中没有这样的海克斯。

**模型的输入：** 每个英雄的 OP.GG 梯队、OP.GG 选取率（同一梯队中选得越多排越前），以及你收集的对局中的真实海克斯胜率（当前版本，按场次加权，数量够多后比 OP.GG 权重更高）。

**关于 OP.GG 数据：** 每个英雄大约列出 130 个海克斯，只包含按热度划分的 **T3–T5**。没列出的海克斯可能是这个英雄最常选的，也可能几乎没人选，所以不当作任何梯队，由 Augur 估计（见上面的「Augur 评分」）。OP.GG 的表现分按场次加权，比梯队更重要。你自己收集的对局越多，OP.GG 的权重越低。

### 收集对局（不需要 API key）

在 Augur 的**设置**里点「从英雄联盟客户端收集对局」（先打开并登录客户端），或在源码目录运行：

```
python -m augur collect-client --games 500
python -m augur build
```

大约 2,000 场就能得到有用的海克斯总排行；每个英雄单独的评分需要 20,000 场以上。

### 评分怎么算

每个评分由几部分相加，单位是胜率百分点：这个英雄带它的实际胜率、全英雄的胜率、OP.GG 的数据、和英雄是否契合（AP / AD / 普攻 / 法力等）、敌我阵容（实测）、和已有海克斯的搭配（实测）、第几轮选、以及你自己的战绩。样本少时向先验值收缩：`(场次 × 实测 + K × 先验) / (场次 + K)`，所以 10 场的运气不会让评分乱跳。只使用**当前版本**的对局，评分跟随当前平衡（想同时使用旧版本，可在 `config.local.json` 设置 `"patches_kept": 3`，每旧一个版本权重 ×0.5）。游戏更新新版本后，OP.GG 数据会自动重新下载。分数 = 50 + 5 × 总和，对应 S+ 到 D。

**局限：** 比赛数据只记录选了哪个海克斯，不记录当时另外两张是什么；胜率是相关性，不完全是因果。

---

Augur 未获得 Riot Games 的认可，不代表 Riot Games 或任何官方参与制作或管理 Riot Games 产品的人的观点。Riot Games 及其相关产品是 Riot Games, Inc. 的商标或注册商标。
