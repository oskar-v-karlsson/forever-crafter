# ForeverCrafter

A profession profit finder for **World of Warcraft: Forever**. It reads your professions and skill, takes one snapshot of the whole auction house, and lists every craft, or chain of crafts, that makes a profit when you sell the result on the auction house or to a vendor.

- **Your recipes and the ones you could learn:** recipes you know, plus recipes your current skill already allows but you have not learned yet. For those it shows how to learn them (trainer and cost, recipe item on the AH or at a vendor, drop, quest) and how many crafts pay the recipe back.
- **One AH snapshot:** `C_AuctionHouse.ReplicateItems` reads every auction in one go. For each item it keeps the lowest buyout per item, how many listings and items are on sale, and the 20 cheapest price steps.
- **Chains of any depth:** every reagent costs the cheapest of buying it on the AH (walking up the listings for the quantity you need), buying it from a vendor, or crafting it yourself from its own reagents, recursively (e.g. Linen Cloth → Bolt of Linen Cloth → Brown Linen Vest). Loops between recipes are detected and skipped.
- **Selling:** the AH value is the lowest buyout minus 1 copper, after the AH cut and the deposit; the vendor value is the item's sell price. The better of the two is used. Bind-on-pickup items count as vendor only.
- **Learns from the game:** opening a profession window reads your real recipe list and reagents; opening any merchant records its exact prices; AH sale invoices in your mailbox measure the AH cut. All of this overrides the static data.
- **Does it sell?** How many of each crafted item sell per day in your region, from [TradeSkillMaster](https://tradeskillmaster.com), so crafts that are profitable on paper but hardly ever sell can be hidden.
- **Advisor only:** it never buys or posts anything.

All game facts come from World of Warcraft: Forever sources only (the Forever client data tables, Wowhead Forever, the Forever UI code, TradeSkillMaster's Forever region data), never Classic or Retail. See [SOURCES.md](SOURCES.md), which also lists what can only be checked in the game or in a browser.

## Releases

Download the newest zip from [Releases](https://github.com/oskar-v-karlsson/forever-crafter/releases/latest) (the asset `ForeverCrafter-v<version>-<commit>.zip`). It holds the `ForeverCrafter/` folder at its top level. Every push to `main` makes a release automatically (`.github/workflows/release.yml`). The workflow runs `make check`, builds the zip and publishes it, tagged `v<version>-<short commit>`, e.g. `v0.1.0-5f1a87c`. The newest release is marked **Latest**. If the checks fail, no release is made.

## Install on Windows

1. Get the addon:
   - **Release:** download the zip from [the latest release](https://github.com/oskar-v-karlsson/forever-crafter/releases/latest). On Windows, right-click it → **Extract All**.
   - **Zip:** or run `make zip` and use `dist/ForeverCrafter-v<version>.zip`.
   - **Copy:** or copy the `ForeverCrafter` folder from this repo.
2. In the **Battle.net** app, choose **World of Warcraft**, then the **Forever** version in the version drop-down. Click the gear next to Play → **Show in Explorer**.
3. Open the Forever game folder, `_forever_`, then `Interface\AddOns`. If `AddOns` (or `Interface`) is missing, create it.
4. Put the `ForeverCrafter` folder there. The result must be `_forever_\Interface\AddOns\ForeverCrafter\ForeverCrafter.toc`. The folder must keep exactly this name and not be nested twice (`ForeverCrafter\ForeverCrafter\...`), which happens easily with Extract All.
5. Start the game. At character select, open **AddOns** (bottom left), make sure **ForeverCrafter** is ticked, and turn on **Load out of date AddOns** if the game asks.

To update, delete the old `ForeverCrafter` folder and put the new one in its place. Prices, merchant data and recipe lists are kept, because they are stored in `_forever_\WTF\Account\<account>\SavedVariables\ForeverCrafter.lua`.

## Usage

1. **Open each profession window once** (and your cooking and first aid). The addon reads your recipes, the unlearned ones the game lists, and the real reagents. Without this it falls back to the game data and your spellbook.
2. **Scan:** go to an auctioneer, open the auction house, and type `/crafter scan` (or right-click the minimap button, or press **Scan AH** in the window). The game allows a full snapshot only every few minutes (assumed 15); the scan takes a few seconds on a full auction house. Keep the AH open until the chat says it is done.
3. **Read the results:** `/crafter` or a left click on the minimap button opens the window.
   - Filters: profession (click to cycle), **Known** and **Learnable** recipes, **Min profit** in gold, **Min AH listings** (sell prices from thinner markets are ignored), **Min sold/day** (see "Sold per day" below).
   - Columns: name (in the skill-up colour: orange, yellow, green, grey), profit, profit %, where to sell (AH or vendor), AH listings and **Sold/d**. Click a header to sort.
   - Click a row for the details: the sell price and how it was worked out, the chain of crafts as a tree, a **shopping list** of what to buy where, and for unlearned recipes how to learn them and the payback.
   - `~` marks an estimate: a vendor price from game data that you have not seen at a merchant yet, or more AH items than the snapshot's 20 cheapest price steps. Visit the vendor once to make it exact.
   - **Random counts:** some crafts make a random number of items (e.g. Heavy Dynamite 1-5). The list marks them with the range, e.g. `[1-5]` (or `[rnd]` when a step of the chain is random). Profit uses the average count; the details show "Makes 1-5 (avg 3)" and the profit in the worst case (1 made) and the best case (5 made), and the chain tree shows a random step's range and how many crafts the worst case needs. The ranges are worked out from the game data (assumed, see [SOURCES.md](SOURCES.md)); once you open the profession window the game's own numbers are used.
4. **Make it more exact over time:** open the merchants you buy reagents from; collect your AH sales from the mailbox (the addon measures the AH cut from the invoices); rescan before you buy.

Prices are only as fresh as your last scan, and other players buy and post all the time. Check the AH before you buy a large batch.

### What-if mode

The **Mode** button at the top of the window switches between **My character** (your recipes and skill) and **What-if**: a made-up character with every profession at a skill cap, to find profitable chains across professions you have not trained on any character.

- **Skill cap** (default 150) applies to every profession; **Overrides...** (or `/crafter cap <profession> <n|clear>`) sets a different cap for single professions. A recipe counts if its learn rank is at most its profession's cap, both as the craft you sell and as a step in a chain.
- **Max primaries** (1, 2, 3 or any; default 2): the most primary professions a chain may need. Cooking and First Aid are secondary and do not count. For each recipe the addon finds the cheapest chain that fits the limit, so a recipe whose best chain needs three professions still shows with its best two-profession chain.
- **Min conf**: how sure it must be that each recipe in the chain can be learned. A chain has the level of its least sure recipe. The default hides **Unknown**.

| Level | Meaning |
|---|---|
| 1 Confirmed | A character knew it in a client dump, or this character knows it |
| 2 Trainer/vendor | Wowhead Forever says a trainer teaches it (or it is a starter recipe), or its recipe item is sold by a vendor |
| 3 Likely | No source anywhere, but the game data marks it as learned with the profession (`AcquireMethod` 1) |
| 4 Drop/quest/other | Only other sources: a drop, quest, world object and so on |
| 5 Unknown | No source at all |

The **Profs** column lists the professions a chain needs (e.g. `Min+BS`), the **Conf** column its level, and the profession filter matches any profession in the chain. The details show each recipe in the chain with its profession and learn rank, its level and how to learn it, the total cost to learn the recipes the character does not know, and how many crafts pay that back. Profit counts only the crafting; the learning costs (and the cost of training the professions) are not taken off. `~` (an estimated price) is separate from the confidence level. The calculation runs over a few frames ("Calculating..." in the status line) so the game does not freeze. The settings are saved for the whole account.

### Sold per day

A craft can be profitable on paper and still never sell. The **Sold/d** column shows how many of the crafted item sell per day in your region, from [TradeSkillMaster](https://tradeskillmaster.com) (TSM), and **Min sold/day** (default 1) hides crafts you would sell on the AH whose item sells fewer than that, or that TSM has no data for (usually items that never sell on the AH; the column shows `—`). Set it to 0 to turn it off.

- **Only the AH:** a craft whose best sale is to a vendor is never hidden. Only the crafted item counts, not the reagents, and profit does not change. It works in both modes.
- **Where the numbers come from:** with the [TSM addon](https://tradeskillmaster.com) (4.15 or newer, with the TSM Desktop App keeping its data fresh) loaded, its own region numbers; otherwise a snapshot of TSM's free public Forever data that comes with the addon (`make tsm` refreshes it). The region (US or EU) is read from the game; other regions only get numbers from the TSM addon. The details of a craft say which source and date it used, and the sale rate (the share of TSM's seen auctions that sold); `/crafter status` shows the region, the snapshot date and whether the TSM addon is used.
- **Region-wide:** TSM publishes sales only for the whole region (every realm, both factions), not per realm. A craft that sells well in the region can still be slow on your realm.

### Commands

| Command | What it does |
|---|---|
| `/crafter` | Open or close the results window (also `/forevercrafter`) |
| `/crafter scan` | Full AH snapshot (the AH window must be open) |
| `/crafter status` | Your professions and skill, snapshot age, the AH cut in use, and where the sold-per-day numbers come from |
| `/crafter cut <pct>` | Set the AH cut in percent; blank goes back to the measured or assumed cut |
| `/crafter cap [<profession>] <n\|clear>` | What-if skill cap: `/crafter cap 150` for all professions, `/crafter cap mining 200` for one (name or short name, e.g. `bs`, `first aid`), `/crafter cap mining clear` to drop the override; `/crafter cap` prints them |
| `/crafter minimap` | Show or hide the minimap button |
| `/crafter dump` | Save the open profession window's full recipe list (learned and unlearned), reagents, outputs, the game's "how to learn" text (empty in Forever so far) and item info, for the data in this addon (see below); `/crafter dump clear` removes it |
| `/crafter reset` | Forget prices, merchant data and this character's recipe data |
| `/crafter debug` | Toggle debug output (also prints any API the client lacks) |

The minimap button and the addon compartment entry: left click opens the window, right click scans.

## Verify in game

These cannot be tested outside the game. Please go through them once and report what you see (the full list with the assumptions is in [SOURCES.md](SOURCES.md#open-verify-in-game)).

1. [ ] The addon loads without errors; `/crafter status` lists your professions with the right skill.
2. [ ] Opening a profession window: `/crafter status` then shows the number of known and learnable recipes for it. Learnable recipes appear in the ForeverCrafter window (`/crafter show`) when **Learnable** is ticked.
3. [ ] `/crafter scan` at the AH finishes with "snapshot done: N listings, M items used by recipes" in chat. Note how long it took, and what the game says if you scan again right away (the throttle).
4. [ ] Cloth, herbs and ore (commodities) have prices after a scan (e.g. Linen Cloth in a Tailoring chain).
5. [ ] A price in the window matches the AH for one item: the lowest buyout per item, not per stack.
6. [ ] Open a reagent vendor (e.g. one selling Empty Vial or Coarse Thread): its price shows without `~` afterwards and matches the merchant. The shopping list names a vendor from Wowhead Forever (e.g. "vendor (NPC name, zone +N)"); check that one of them really sells it.
7. [ ] After an AH sale, open the mailbox: `/crafter status` shows the measured cut (e.g. `AH cut 5.0% (from 1 sale invoice(s))`).
8. [ ] The minimap button and the compartment entry show a coin icon.
9. [ ] `/crafter debug` lists no missing APIs or events.
10. [ ] **What-if** mode (Mode button) with Max primaries **3**: the game does not stutter while "Calculating..." runs, and the results look sane (e.g. a Mining + Blacksmithing chain).
11. [ ] If your trainer or a vendor teaches a recipe listed in [`research/open_sources.txt`](research/open_sources.txt) (recipes, reagents and vendors that Wowhead Forever has no source for), or you can learn one of the left-out recipes in [`research/excluded_recipes.txt`](research/excluded_recipes.txt), please report it.
12. [ ] `/crafter status` names your region (US or EU) and the TSM snapshot date. Without TSM, a common crafted item shows a number in **Sold/d**.
13. [ ] With the TradeSkillMaster addon loaded (and its Desktop App data): `/crafter status` says "TradeSkillMaster live" with a scale (1, 100 or 1000), and **Sold/d** for an item matches the region sold-per-day value in TSM's own item tooltip. If `/crafter status` says TSM has no data yet, log in again after the Desktop App has run.
14. [ ] The **Min sold/day** box fits next to **Min AH listings** and **Scan AH** in the toolbar without overlapping.
15. [ ] **Random counts:** with Engineering, open the profession window and select Heavy Dynamite: the game's recipe should say it makes 1-5 (the addon's details then say "Makes 1-5 (avg 3)", read from your window). If you can, also check Coarse Dynamite (1-3) and Iron Grenade (2-4), and report any other numbers.
15. [ ] **Help the recipe data:** open each profession window and type `/crafter dump` (on each character, for each profession, both factions if you can). Then `/reload` or log out, and send `_forever_\WTF\Account\<account>\SavedVariables\ForeverCrafter.lua` (the file also holds your character names, skills and saved prices; the import reads only its `dump` part and keeps the recipes, items, faction and date, and which recipes some character knows, but not which character). A recipe a character knows counts as existing even if Wowhead Forever lists it nowhere, and the game's reagents come before the DB2 ones. The game's recipe list itself holds every recipe in the client data, learnable or not, so it is not used to add recipes. The dump also notes items the game knows nothing about.

## Development

- `make check` runs all offline checks. It needs Python 3 and `pip install --user lupa`, which provides a real Lua 5.1. It checks:
  - **TOC and policy:** `## Interface: 16001`, the file list, and no Classic or Retail source links in the data, docs or tools;
  - **data:** every entry has a `src` from the [SOURCES.md](SOURCES.md) table and a `verified` date, every referenced item exists, `Data/*.lua` matches what the pinned `research/` snapshots generate (`tools/gen_data.py verify`), and the Wowhead Forever tooltip fact for recipe 3170; `Data/Sales.lua` (TSM, changes daily) is checked for its shape, value ranges and the snapshot table in SOURCES.md instead;
  - **runtime:** loads the addon in a fake WoW client (`tools/wow_stub.lua`) with the real data, then logs in, reads a profession window, scans an AH, opens a merchant and the mailbox, and drives the window and every command. It checks the costs, values and chains against hand-computed numbers, cycles between recipes, the chain depth limit, thin markets, missing APIs, a full run over all 2038 recipes, and that the zip holds `ForeverCrafter/` at its top level.
- `make data` regenerates `ForeverCrafter/Data/*.lua` from `research/` (offline, deterministic). To move to a new client build: change `BUILD` in `tools/gen_data.py`, run `python3 tools/gen_data.py fetch`, dump the Wowhead Forever lists again in a browser with `tools/wowhead_dump.js` and `python3 tools/gen_data.py wowhead <folder>`, read the pages in `research/wowhead/page_targets.json` and the recipe item lists with `tools/wowhead_crawl.js` (`FCcrawl`, `FCsourcemore`) and trim them with `python3 tools/gen_data.py wowhead-pages <folder>` and `wowhead-sourcemore <file>`, fetch the item tooltips with `python3 tools/gen_data.py wowhead-tooltips`, merge players' `/crafter dump` files with `python3 tools/gen_data.py client-dump <ForeverCrafter.lua ...>` (into `research/client/dump.json`), then `make data`, `make crosscheck` and update SOURCES.md.
- `make tsm` downloads TradeSkillMaster's public Forever region files (US and EU, network) and rewrites `ForeverCrafter/Data/Sales.lua` and the snapshot table in SOURCES.md. Only the sold per day and sale rate of recipe outputs are kept.
- `make crosscheck` compares a sample of recipes with the Wowhead Forever tooltips (network) and writes `research/crosscheck_<date>.txt`.
- `make zip` builds `dist/ForeverCrafter-v<version>.zip` (unzip straight into `AddOns`).
- Layout of `ForeverCrafter/`:
  - `Core/`: init, events, slash commands, saved variables (`Init.lua`); money and item helpers (`Util.lua`);
  - `Data/`: generated recipes, items and vendor reagents, each with source and verified date; the TSM sales snapshot (`Sales.lua`);
  - `Modules/`: professions and skill (`Professions.lua`), the AH snapshot (`Scanner.lua`), buy and sell prices, merchants, invoices and deposits (`Pricing.lua`), sold per day from TSM (`Sales.lua`), the chain solver (`Planner.lua`), the window (`UI.lua`), the minimap button (`Minimap.lua`), `/crafter dump` (`Dump.lua`).
- The client is the 12.x API ("Camelot", `## Interface: 16001`). Use `C_*` namespaces and pcall-wrap anything that may not exist.

## Licence

GPL-2.0-or-later (see [LICENSE](LICENSE)).
