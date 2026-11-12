# ForeverCrafter

A profession profit finder for **World of Warcraft: Forever**. It reads your professions and skill, takes one snapshot of the whole auction house, and lists every craft, or chain of crafts, that makes a profit when you sell the result on the auction house or to a vendor.

- **Your recipes and the ones you could learn:** recipes you know, plus recipes your current skill already allows but you have not learned yet. For those it shows how to learn them (trainer and cost, recipe item on the AH or at a vendor, drop, quest) and how many crafts pay the recipe back.
- **One AH snapshot:** `C_AuctionHouse.ReplicateItems` reads every auction in one go. For each item it keeps the lowest buyout per item, how many listings and items are on sale, and the 20 cheapest price steps.
- **Chains of any depth:** every reagent costs the cheapest of buying it on the AH (walking up the listings for the quantity you need), buying it from a vendor, or crafting it yourself from its own reagents, recursively (e.g. Linen Cloth → Bolt of Linen Cloth → Brown Linen Vest). Loops between recipes are detected and skipped.
- **Selling:** the AH value is the lowest buyout minus 1 copper, after the AH cut and the deposit; the vendor value is the item's sell price. The better of the two is used. Bind-on-pickup items count as vendor only.
- **Learns from the game:** opening a profession window reads your real recipe list and reagents; opening any merchant records its exact prices; AH sale invoices in your mailbox measure the AH cut. All of this overrides the static data.
- **Advisor only:** it never buys or posts anything.

All game facts come from World of Warcraft: Forever sources only (the Forever client data tables, Wowhead Forever, the Forever UI code), never Classic or Retail. See [SOURCES.md](SOURCES.md), which also lists what can only be checked in the game or in a browser.

## Releases

Download the newest zip from [Releases](https://github.com/oskar-v-karlsson/forever-crafter/releases/latest) (the asset `ForeverCrafter-v<version>-<commit>.zip`). It holds the `ForeverCrafter/` folder at its top level. Every push to `main` makes a release automatically (`.github/workflows/release.yml`). The workflow runs `make check`, builds the zip and publishes it, tagged `v<version>-<short commit>`, e.g. `v0.1.0-5f1a87c`. The newest release is marked **Latest**. If the checks fail, no release is made.

## Install on Windows

1. Get the addon:
   - **Release:** download the zip from [the latest release](https://github.com/oskar-v-karlsson/forever-crafter/releases/latest). On Windows, right-click it → **Extract All**.
   - **Zip:** or run `make zip` and use `dist/ForeverCrafter-v<version>.zip`.
   - **Copy:** or copy the `ForeverCrafter` folder from this repo.
2. In the **Battle.net** app, choose **World of Warcraft**, then the **Forever** version in the version drop-down. Click the gear next to Play → **Show in Explorer**.
3. Open the game folder for Forever (most likely `_classic_beta_`), then `Interface\AddOns`. If `AddOns` (or `Interface`) is missing, create it.
4. Put the `ForeverCrafter` folder there. The result must be `...\Interface\AddOns\ForeverCrafter\ForeverCrafter.toc`. The folder must keep exactly this name and not be nested twice (`ForeverCrafter\ForeverCrafter\...`), which happens easily with Extract All.
5. Start the game. At character select, open **AddOns** (bottom left), make sure **ForeverCrafter** is ticked, and turn on **Load out of date AddOns** if the game asks.

To update, delete the old `ForeverCrafter` folder and put the new one in its place. Prices, merchant data and recipe lists are kept, because they are stored in `WTF\Account\...\SavedVariables\ForeverCrafter.lua`.

## Usage

1. **Open each profession window once** (and your cooking and first aid). The addon reads your recipes, the unlearned ones the game lists, and the real reagents. Without this it falls back to the game data and your spellbook.
2. **Scan:** go to an auctioneer, open the auction house, and type `/crafter scan` (or right-click the minimap button, or press **Scan AH** in the window). The game allows a full snapshot only every few minutes (assumed 15); the scan takes a few seconds on a full auction house. Keep the AH open until the chat says it is done.
3. **Read the results:** `/crafter` or a left click on the minimap button opens the window.
   - Filters: profession (click to cycle), **Known** and **Learnable** recipes, **Min profit** in gold, **Min AH listings** (sell prices from thinner markets are ignored).
   - Columns: name (in the skill-up colour: orange, yellow, green, grey), profit, profit %, where to sell (AH or vendor) and AH listings. Click a header to sort.
   - Click a row for the details: the sell price and how it was worked out, the chain of crafts as a tree, a **shopping list** of what to buy where, and for unlearned recipes how to learn them and the payback.
   - `~` marks an estimate: a vendor price from game data that you have not seen at a merchant yet, or more AH items than the snapshot's 20 cheapest price steps. Visit the vendor once to make it exact.
4. **Make it more exact over time:** open the merchants you buy reagents from; collect your AH sales from the mailbox (the addon measures the AH cut from the invoices); rescan before you buy.

Prices are only as fresh as your last scan, and other players buy and post all the time. Check the AH before you buy a large batch.

### Commands

| Command | What it does |
|---|---|
| `/crafter` | Open or close the results window (also `/forevercrafter`) |
| `/crafter scan` | Full AH snapshot (the AH window must be open) |
| `/crafter status` | Your professions and skill, snapshot age, the AH cut in use |
| `/crafter cut <pct>` | Set the AH cut in percent; blank goes back to the measured or assumed cut |
| `/crafter minimap` | Show or hide the minimap button |
| `/crafter dump` | Save the open profession window's full recipe list (learned and unlearned), reagents, outputs, the game's "how to learn" text and item info, for the data in this addon (see below); `/crafter dump clear` removes it |
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
10. [ ] If your trainer or a vendor teaches a recipe listed in [`research/open_sources.txt`](research/open_sources.txt) (recipes, reagents and vendors that Wowhead Forever has no source for), or you can learn one of the left-out recipes in [`research/excluded_recipes.txt`](research/excluded_recipes.txt), please report it.
11. [ ] **Help the recipe data:** open each profession window and type `/crafter dump` (on each character, for each profession, both factions if you can). Then `/reload` or log out, and send `WTF\Account\<account>\SavedVariables\ForeverCrafter.lua` (the file also holds your character names, skills and saved prices; the import reads only its `dump` part and keeps the recipes, items, faction and date, nothing about your characters). The game's own list then decides which recipes exist, and its reagents and "how to learn" text come before Wowhead Forever.

## Development

- `make check` runs all offline checks. It needs Python 3 and `pip install --user lupa`, which provides a real Lua 5.1. It checks:
  - **TOC and policy:** `## Interface: 16001`, the file list, and no Classic or Retail source links in the data, docs or tools;
  - **data:** every entry has a `src` from the [SOURCES.md](SOURCES.md) table and a `verified` date, every referenced item exists, `Data/*.lua` matches what the pinned `research/` snapshots generate (`tools/gen_data.py verify`), and the Wowhead Forever tooltip fact for recipe 3170;
  - **runtime:** loads the addon in a fake WoW client (`tools/wow_stub.lua`) with the real data, then logs in, reads a profession window, scans an AH, opens a merchant and the mailbox, and drives the window and every command. It checks the costs, values and chains against hand-computed numbers, cycles between recipes, the chain depth limit, thin markets, missing APIs, a full run over all 2038 recipes, and that the zip holds `ForeverCrafter/` at its top level.
- `make data` regenerates `ForeverCrafter/Data/*.lua` from `research/` (offline, deterministic). To move to a new client build: change `BUILD` in `tools/gen_data.py`, run `python3 tools/gen_data.py fetch`, dump the Wowhead Forever lists again in a browser with `tools/wowhead_dump.js` and `python3 tools/gen_data.py wowhead <folder>`, read the pages in `research/wowhead/page_targets.json` and the recipe item lists with `tools/wowhead_crawl.js` (`FCcrawl`, `FCsourcemore`) and trim them with `python3 tools/gen_data.py wowhead-pages <folder>` and `wowhead-sourcemore <file>`, fetch the item tooltips with `python3 tools/gen_data.py wowhead-tooltips`, merge players' `/crafter dump` files with `python3 tools/gen_data.py client-dump <ForeverCrafter.lua ...>` (into `research/client/dump.json`), then `make data`, `make crosscheck` and update SOURCES.md.
- `make crosscheck` compares a sample of recipes with the Wowhead Forever tooltips (network) and writes `research/crosscheck_<date>.txt`.
- `make zip` builds `dist/ForeverCrafter-v<version>.zip` (unzip straight into `AddOns`).
- Layout of `ForeverCrafter/`:
  - `Core/`: init, events, slash commands, saved variables (`Init.lua`); money and item helpers (`Util.lua`);
  - `Data/`: generated recipes, items and vendor reagents, each with source and verified date;
  - `Modules/`: professions and skill (`Professions.lua`), the AH snapshot (`Scanner.lua`), buy and sell prices, merchants, invoices and deposits (`Pricing.lua`), the chain solver (`Planner.lua`), the window (`UI.lua`), the minimap button (`Minimap.lua`), `/crafter dump` (`Dump.lua`).
- The client is the 12.x API ("Camelot", `## Interface: 16001`). Use `C_*` namespaces and pcall-wrap anything that may not exist.

## Licence

GPL-2.0-or-later (see [LICENSE](LICENSE)).
