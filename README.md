# ForeverCrafter

A profession profit finder for **World of Warcraft: Forever**. It reads your professions and skill, takes one snapshot of the whole auction house, and lists every craft, or chain of crafts, that makes a profit when you sell the result on the auction house or to a vendor.

- **Your recipes and the ones you could learn:** recipes you know, plus recipes your current skill already allows but you have not learned yet. For those it shows how to learn them (trainer and cost, recipe item on the AH or at a vendor, drop, quest) and how many crafts pay the recipe back.
- **One AH snapshot:** `C_AuctionHouse.ReplicateItems` reads every auction in one go. For each item it keeps the lowest buyout per item, how many listings and items are on sale, and the 50 cheapest price steps.
- **Chains of any depth:** every reagent costs the cheapest of buying it on the AH (walking up the listings for the quantity you need), buying it from a vendor, or crafting it yourself from its own reagents, recursively (e.g. Linen Cloth → Bolt of Linen Cloth → Brown Linen Vest). Loops between recipes are detected and skipped.
- **Selling:** the AH value is the lowest buyout minus 1 copper, after the AH cut and the deposit; the vendor value is the item's sell price. The better of the two is used. Bind-on-pickup items count as vendor only.
- **Learns from the game:** opening a profession window reads your real recipe list and reagents; opening any merchant records its exact prices; AH sale invoices in your mailbox measure the AH cut. All of this overrides the static data.
- **Does it sell?** How many of each crafted item sell per day in your region, from [TradeSkillMaster](https://tradeskillmaster.com), so crafts that are profitable on paper but hardly ever sell can be hidden.
- **Reputation planner:** the cheapest way to gain reputation with Durotar Supply and Logistics (Horde) or the Azeroth Commerce Authority (Alliance) from AH and vendor prices: Craftsman's Writs and notarised Waylaid Crates, plus a plan for today.
- **Sniper:** tick crafts and it watches their AH reagents, searching while the AH is open, and offers the listings under a max price that keeps each craft at 90% of its g/h. You confirm every purchase with a click.
- **Never posts:** it buys only through the sniper's Buy button, one click per purchase, and never posts auctions.

All game facts come from World of Warcraft: Forever sources only (the Forever client data tables, Wowhead Forever, the Forever UI code, TradeSkillMaster's Forever region data), never Classic or Retail. See [SOURCES.md](SOURCES.md), which also lists what can only be checked in the game or in a browser.

## Releases

Download the newest zip from [Releases](https://github.com/oskar-v-karlsson/forever-crafter/releases/latest) (the asset `ForeverCrafter-v<version>.zip`, e.g. `ForeverCrafter-v0.1.4.zip`). It holds the `ForeverCrafter/` folder at its top level. Every push to `main` makes a release automatically (`.github/workflows/release.yml`). The workflow runs `make check`, builds the zip and publishes it, marked **Latest**. If the checks fail, no release is made.

- **Version numbers:** each release bumps the patch number: `v0.1.1`, `v0.1.2`, ... (`tools/release_version.py` takes the newest `vX.Y.Z` tag and adds one). Older releases are tagged `v0.1.0-<commit>` and are ignored.
- **The zip carries the real version.** Nothing is committed back to `main`, so the `## Version` in the repo's `.toc` stays at the base version; the zipped `.toc` gets the release's version, and the game's AddOns list shows it.
- **Minor or major bump:** raise `## Version` in `ForeverCrafter/ForeverCrafter.toc` in a pull request, e.g. to `0.2.0`. When it is above the newest tag, the next release uses it as is (`v0.2.0`), and later ones bump from there (`v0.2.1`).
- Re-running the workflow for a commit that already has a release does nothing.

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
   - Filters: profession (click to cycle), **Known** and **Learnable** recipes, **Min profit** in gold, **Min AH listings** (sell prices from thinner markets are ignored), **Min sold/day** (see "Sold per day" below), **Min batch** (see "Cheap batch" below).
   - Columns: name (in the skill-up colour: orange, yellow, green, grey), profit, **Vend. profit** (see "Vendor shuffles" below), profit %, where to sell (AH or vendor), AH listings, **Sold/d**, the **Batch** size and **Batch profit** (see "Cheap batch" below), and the crafting **Time** with **AH g/h** and **Vend g/h** (see "Crafting time" and "How paths are chosen" below). Click a header to sort; hover a header for what it means.
   - Click a row for the details: the sell price and how it was worked out, the chain of crafts as a tree, a **shopping list** of what to buy where, and for unlearned recipes how to learn them and the payback.
   - `~` marks an estimate. It has different causes, and only the first is fixed by visiting a vendor:
     - **Reagents bought from a vendor:** the price comes from game data until you open a merchant that sells the reagent. Opening it records the exact price, and chat says e.g. `ForeverCrafter: 12 vendor prices from Rachel`. If it says it could not read them, `/crafter errors` has the reason; please report it.
     - **Reagents bought on the AH:** you need more than the snapshot's 50 cheapest price steps. Rescan.
     - **The crafted item's sell-to-vendor price** (**Vend. profit**, **Vend g/h**): it comes from game data until the client has loaded the item. That happens by itself (the addon asks for it) and shows the next time the list is worked out, e.g. when you reopen the window. Visiting or selling to a vendor does not change it.
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

### Vendor shuffles

A vendor shuffle is a craft that makes a profit when you sell what it makes to a vendor: no AH, no waiting and no undercutting. The reagents can come from anywhere (AH, vendor or your own crafts, whichever is cheapest, as usual).

- **`[V]`** in green before the name marks a shuffle, even when the AH pays more and the **Sell** column says AH. Hover the row for the vendor profit.
- **Vend. profit** column: the profit if you sell to a vendor, in both modes. `—` means a vendor will not buy the item; `~` means the vendor price is an estimate from game data (it becomes exact by itself once the client has loaded the item; see `~` above); grey means a loss.
- **Vendor shuffles** checkbox (top right of the window; saved): shows only shuffles, sorted by vendor profit. **Min profit** then applies to the vendor profit, and **Min sold/day** and **Min AH listings** do not hide anything, as the items go to a vendor.
- The details of a shuffle the AH pays more for also show the vendor sale and its profit, and for a random count (e.g. `[1-5]`) the vendor profit in the worst case.

### Crafting time

How long the whole chain takes to cast: every craft of the result and of each crafted step, times its cast time (items you buy take no time). Forever has long casts: many weapons and armour take 25 s to 1 min each.

- **Time** column: the chain's casting time (`57s`, `1m15s`). Click it to sort, shortest first. When the g/h comes from a faster path (see "How paths are chosen"), the Time column shows and sorts by that path's time, also marked `*`: the vendor sale's path with **Vendor shuffles** on or on a vendor shuffle row, else the AH sale's path.
- **AH g/h** and **Vend g/h** columns: profit per hour of crafting when you sell on the AH, and when you sell to a vendor. Both are shown for every craft, whichever pays more, and each can be sorted. `—` means no AH price (none listed, or fewer than **Min AH listings**) or a vendor will not buy the item; `~` means the vendor price is an estimate; grey means a loss. The **Vendor shuffles** checkbox still sorts by **Vend. profit**; click **Vend g/h** to sort shuffles by profit per hour. These two columns use the best-g/h path, which may differ from the path behind **Profit** (marked `*`, see "How paths are chosen").
- **Cooldown recipes** (`[cd]` before the name: Mooncloth, the Alchemy transmutes, Iron to Gold, ...) make one craft per cooldown, so they have no g/h (`cd` in the g/h columns), a batch of 1 and a sniper target of 1; the details say how long the cooldown is and whether it is shared. They are never used as a step of another craft's chain (you would buy the Mooncloth or Arcanite Bar instead). See "Cooldowns" below.
- The details say e.g. "Crafting time 1 min 15 s (5 casts) | AH 12g 30s/h | vendor 3g/h", and each step of the chain shows its own time (crafts x cast time).
- Only the casting counts: buying the reagents, travelling and the time between casts are not included, so real profit per hour is lower.
- Cast times come from the game data; once you open a profession window the game's own cast times are used. If a craft of the chain has no known cast time, the time shows as "at least" (`>` in orange in the list) and there is no per-hour figure. Random-count steps count their average number of crafts, as the cost does.

### Cheap batch

The cheapest price on the AH may be only a few listings, with the bulk much dearer. So every craft also gets a **cheap batch**: how many you can craft in a row, buying the reagents up the AH price steps, before one more craft would earn less than 75% of the first craft's profit. The whole chain counts: a crafted step's own reagents get dearer too, while vendor reagents never run out.

- **Profit, AH g/h and Vend g/h are batch averages**, so a craft that is only profitable for the first two listings no longer looks like a gold mine. The details still show the first craft's profit.
- **Batch** column (both modes): the batch size; a `+` (e.g. `50+`) means it may be bigger: the search stops at 200 crafts, or the snapshot's 50 price steps end there. `—` means not profitable. With **Vendor shuffles** on, it shows the vendor batch (a vendor pays less, so its batch can be smaller).
- **Batch profit** column (both modes, next to **Batch**): the profit of the whole batch, i.e. the "batch profit" of the details. Click its header to sort high first; `—` (not profitable) sorts last. With **Vendor shuffles** on, it shows the vendor batch's profit, marked `~` when the vendor price is an estimate.
- **Min batch** (default 5; saved; 1 turns it off) hides crafts with a smaller batch; the status line counts them. With **Vendor shuffles** on it uses the vendor batch.
- The details say e.g. "Cheap batch: 23 crafts (Iron Bar up to 1s 20c) | avg profit 45s (first craft 52s) | batch profit 10g 35s", and add a shopping list for the whole batch with the highest price you pay per reagent ("up to ... each"). The chain tree and the first shopping list are for one craft.
- **The workflow:** buy the batch, craft it, let the AH restock, and repeat.
- Limits: each reagent is priced on its own, so when the same reagent appears twice in a chain, or two crafts you plan use the same reagent, both count the same cheap listings. How many of the crafted item the AH can absorb is not counted (that is what **Sold/d** is for).

### How paths are chosen

Every reagent of a chain can be bought on the AH, bought from a vendor, or crafted (if you can). The addon works out two paths per craft:

- **Most gold:** each step takes the cheapest way. This path drives **Profit**, **Vend. profit**, **Batch** and **Batch profit**, the chain tree and the shopping lists.
- **Best gold per hour:** crafting a step yourself can save a few copper but cost a long cast. E.g. buying Copper Bars instead of smelting the ore can earn less per craft but much more per hour. This path drives **AH g/h** and **Vend g/h** (worked out separately for each), and their sorts. When it differs from the most-gold path, the cell is marked `*`, and the details add "Fastest path: buy X on the AH instead of crafting it (Recipe) -> profit per craft, time, g/h (+N g/h vs the most-gold path)", with its own chain tree and shopping lists. When the AH and vendor paths are the same, it is shown once.
- How: each step is priced at its copper cost plus the current g/h times its casting time (Dinkelbach's method for the best ratio). The g/h of the chosen path becomes the new rate and the search repeats until the path stops changing (at most 6 rounds; usually 2). The best-g/h path is never shown unless it beats the most-gold path's g/h.
- Its g/h is also a batch average: its own cheap batch, priced along the same path, divided by its casting time. The batch stays on the path: when a bigger batch would switch back to another path (e.g. the cheap listings of a bought intermediate run out and crafting it becomes cheaper again), the batch ends at the last size on the path, so the sniper buys what that path uses (e.g. Heavy Blasting Powder, not Heavy Stone). Unknown cast times count as 0 s here, as in the g/h columns. In **What-if** it is worked out for the results shown (the best set per recipe) after the scan of all sets.

### Reputation planner

The **Reputation** button at the top right of the window (or `/crafter rep`) switches to the Durotar Supply and Logistics tab (the Azeroth Commerce Authority on an Alliance character); **Back to crafts** switches back. Everything is priced from the AH snapshot and merchant prices only, never by crafting.

- **Writs:** each of the 150 Craftsman's Writs (Journeyman, Expert, Artisan): the writ plus the item its quest wants (e.g. 200 Crafted Solid Shot), less the average Coin Pouch the quest gives (Journeyman about 12s, Expert 36s, Artisan 74s 56c; below 0 means the turn-in earns gold). Each writ can be turned in once per day; a writ done today is greyed out (`done`). Sealed (random) writs are left out.
- **Notarised crate:** an empty Waylaid Crate (the cheapest of the unidentified one and the identified ones) plus a Forged Delivery Receipt for 50 reputation. The receipt costs 15 Merchant's Favor, priced at the cheapest copper per favor of all crates. Crates are not recommended below Friendly (`needs Friendly`, greyed out).
- **Fill rows:** each identified Waylaid Crate with its cheapest fill bundle, and the Merchant's Favor its sealed crate gives (white crates take raw materials, green crates processed ones): Apprentice 5 white / 10 green, Journeyman 10 / 20, Expert 20 / 30, Artisan unknown (`?`). They sort as the notarised crate they would pay for.
- **Columns:** Option, Tier, Cost, Gives (reputation, or favor for a fill), **Cost/rep** (copper per reputation point; fills show copper per favor), where to buy, and **Today** (`plan`, `done`, `needs Friendly`). Click a header to sort; the default is Cost/rep, cheapest first.
- **Today's plan** (in the details): the cheapest copper per reputation first, step by step, priced after what the plan already bought (the AH price steps rise), up to the next standing or the **Rep goal** box. Notarised crates come first when they are cheaper, using any Merchant's Favor you already have. Below Friendly the plan uses writs until it reaches Friendly. It ends with the shopping list, what you spend and roughly what the Coin Pouches give back.
- **Unverified amounts:** the writ reputation (75, 125, 150), the Coin Pouch averages, the favor per crate and the receipt price come from guides, not from Forever game data. They show in orange. The addon learns the real numbers when you turn in (the reputation or favor that changes within 3 seconds of a writ quest, a sealed crate or a receipt leaving your bags) and uses them from then on, on every character. `/crafter rep forget` clears what it learned.

### Sniper

The sniper buys the reagents of crafts you pick when someone lists them cheaply, so you can stock a whole batch over time instead of at today's prices.

1. **Tick the crafts:** the **S** checkbox at the left of a result row (both modes; e.g. a few vendor shuffles). The sniper watches every reagent of that craft that its path buys on the AH, with the craft's cheap-batch quantity. Reagents shared by several ticked crafts are merged. The name of a ticked craft that has no room (below) shows `no room` in orange; its details list the max price of each reagent under "Sniping for this craft".
2. **Open the AH** and press **Sniper** at the top right of the window (or `/crafter snipe`), then **Start**. The sniper searches the watched reagents one at a time (one search every 1.5 s, each item again after 6 s at the earliest; the AH allows 100 searches per minute), only while the AH is open. It stops when the AH closes.
3. **Buy:** listings at or under the max price show in **Deal qty** and **Deal avg**; the **Buy** button names the best deal (the one furthest under its max). Every purchase takes one click on **Buy** (the game only allows AH purchases from a click). A commodity purchase asks the AH for a price quote first; the addon confirms it only if the quoted total is at or under the deal's budget and cancels it otherwise. If the game blocks the confirm because it did not come from a click, the button turns into **Confirm** for one more click. If the price changes after the confirm, the new quote is checked against the budget again and waits for a **Confirm** click (an unconfirmed quote is cancelled after a minute). If the AH does not answer a confirm within 10 s, the addon tells you to check your mail and still counts the purchase if it goes through later.
4. **Need** counts down: the target less what is in your bags and what the sniper bought that is still in the mail (it tracks its purchases until the items reach your bags). **Untick all** (`/crafter snipe clear`) stops watching every craft; **Forget bought** (`/crafter snipe forget`) forgets the purchases still counted as in the mail.

**Target.** The top of the Sniper tab lists the ticked crafts: Ticked craft, Sale (AH or Vendor), Batch, **Target**, Time, Profit (at max) and Floor g/h (the g/h a craft keeps at worst). By default the sniper buys reagents for one cheap batch, the batch the last scan found. If cheap listings keep reappearing, type a bigger number of crafts into the craft's **Target** box and press Enter (1 to 9999; blank = the batch): each reagent's need becomes its batch quantity / batch x target, rounded up, and the reagent list updates at once. Buying past the batch relies on new cheap listings appearing; the max prices are per craft and do not change, so every craft bought past the batch still keeps Keep g/h. When every need is met the sniper stops and says to raise a Target to keep buying. Unticking a craft (or **Untick all**) drops its target. The craft's details show "target N crafts (batch B)". **Time** is Target x the time of one craft; **Profit (at max)** is Target x what one craft earns at today's sale price if every AH reagent is bought at its max (sale - batch-average cost - room; `~` if the vendor price is an estimate, "—" with no room or no AH reagents). The line under the list totals both over the ticked crafts with room, with their overall g/h (crafts with an unknown time are left out of the g/h). All three update as soon as you change a Target.

**Max price.** Each ticked craft keeps at least **Keep g/h %** (default 90) of the g/h in its row: **Vend g/h** for a vendor shuffle, **AH g/h** for any other craft, along the path of that column (the faster path, if it has one). For an AH-sold item, the floor is measured after a 10% fall of its sale price; a vendor sale has no such cushion. With W the worth of one craft (vendor price, or AH price after the cut and deposit, times the output count), Wc = W less the cushion, C the batch-average cost of one craft, and f = Keep g/h:

- the room is (1 - f) x (Wc - C) per craft;
- it is spread as one markup over all the craft's AH reagents: markup = room / (their batch-average cost per craft);
- each reagent's max price is its batch-average price x (1 + markup).

Buying every reagent at its max costs exactly C + room, so the craft still makes f x (Wc - C): no mix of deals at the max can push it below the floor. A craft with Wc ≤ C has no room. When several ticked crafts share a reagent, each unit of a deal must fit a craft whose max allows its price, so the deal at e.g. 25c only takes as many as the crafts with a max of 25c or more still need.

Example: a vendor shuffle sells for 3s and needs 1 of reagent A (batch price 10c) and 2 of reagent B (20c each), so C = 50c. With Keep g/h 90% the room is 10% of 2s 50c = 25c per craft, a markup of 25 / 50 = 50%: A's max is 15c and B's max 30c. Bought entirely at those prices the craft costs 75c and earns 2s 25c, 90% of the 2s 50c in the row.

The Sniper tab's columns: Reagent, Need, Have (bags plus mail), Max price, Cheapest (the last search, without your own listings), Deal qty, Deal avg, Under max, Searched (seconds ago) and For (the ticked crafts). The ticked crafts, their targets, the Keep g/h % box and the purchases still in the mail are saved per character.

### Cooldowns

Some recipes can only be made once per cooldown: Mooncloth (3 days 23 h), Transmute: Arcanite (1 day 23 h), the elemental transmutes (23 h), Iron to Gold and Mithril to Truesilver (1 h). All the Alchemy transmutes except the last two share one cooldown: after any of them, all of them wait (DB2 cooldown category 310, "Transmute - Alchemy"). The lengths come from the Forever game data.

The **Cooldowns** button in the title row (or `/crafter cd`) lists them for every character you have logged in with: Character, Recipe (`[L]` = not learned yet), **Profit** of one craft at today's AH prices with every reagent bought, where to sell, the Cooldown (`sh` = shared) and **Ready**: `Ready`, `in 5h12m`, "open the profession window" (that character's ready time was never read), "learn now" or "learn at Tailoring 230 (you 180)". The ready times are read when a character opens the profession window and after each craft, and kept across logins, so you can see when an alt's cooldown is up. Rows of recipes a character could level into show what that alt would earn per cooldown.

At login, chat says e.g. `3 cooldowns ready (best: Mooncloth 36g on Hana) - /crafter cd` (a shared cooldown counts once per character). `/crafter cd login` turns that line off and on.

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
| `/crafter cd [login]` | The Cooldowns tab (see "Cooldowns" above); `login` turns the "N cooldowns ready" chat line at login off or on |
| `/crafter rep` | The reputation planner (see "Reputation planner" above); `/crafter rep forget` clears the learned reputation and favor amounts |
| `/crafter snipe [start\|stop\|clear\|forget]` | The sniper (see "Sniper" above): open its tab, start or stop searching, untick all crafts, or forget the purchases still counted as in the mail |
| `/crafter reset` | Forget prices, merchant data and this character's recipe data (not the learned reputation amounts) |
| `/crafter debug` | Toggle debug output (also prints any API the client lacks) |

The minimap button and the addon compartment entry: left click opens the window, right click scans.

## Verify in game

These cannot be tested outside the game. Please go through them once and report what you see (the full list with the assumptions is in [SOURCES.md](SOURCES.md#open-verify-in-game)).

1. [ ] The addon loads without errors; `/crafter status` lists your professions with the right skill.
2. [ ] Opening a profession window: `/crafter status` then shows the number of known and learnable recipes for it. Learnable recipes appear in the ForeverCrafter window (`/crafter show`) when **Learnable** is ticked.
3. [ ] `/crafter scan` at the AH finishes with "snapshot done: N listings, M items used by recipes" in chat. Note how long it took, and what the game says if you scan again right away (the throttle).
4. [ ] Cloth, herbs and ore (commodities) have prices after a scan (e.g. Linen Cloth in a Tailoring chain).
5. [ ] A price in the window matches the AH for one item: the lowest buyout per item, not per stack.
6. [ ] Open a reagent vendor (e.g. one selling Empty Vial or Coarse Thread): chat says `ForeverCrafter: N vendor prices from <NPC>`, `/crafter status` counts them, and the reagent's price shows without `~` afterwards and matches the merchant. A limited-stock item (a number on its icon) and a sold-out one count as limited, an unlimited one does not (`numAvailable` -1). `/crafter errors` shows no `merchant:` line. The shopping list names a vendor from Wowhead Forever (e.g. "vendor (NPC name, zone +N)"); check that one of them really sells it.
7. [ ] After an AH sale, open the mailbox: `/crafter status` shows the measured cut (e.g. `AH cut 5.0% (from 1 sale invoice(s))`).
8. [ ] The minimap button and the compartment entry show a coin icon.
9. [ ] `/crafter debug` lists no missing APIs or events.
10. [ ] **What-if** mode (Mode button) with Max primaries **3**: the game does not stutter while "Calculating..." runs, and the results look sane (e.g. a Mining + Blacksmithing chain).
11. [ ] If your trainer or a vendor teaches a recipe listed in [`research/open_sources.txt`](research/open_sources.txt) (recipes, reagents and vendors that Wowhead Forever has no source for), or you can learn one of the left-out recipes in [`research/excluded_recipes.txt`](research/excluded_recipes.txt), please report it.
12. [ ] `/crafter status` names your region (US or EU) and the TSM snapshot date. Without TSM, a common crafted item shows a number in **Sold/d**.
13. [ ] With the TradeSkillMaster addon loaded (and its Desktop App data): `/crafter status` says "TradeSkillMaster live" with a scale (1, 100 or 1000), and **Sold/d** for an item matches the region sold-per-day value in TSM's own item tooltip. If `/crafter status` says TSM has no data yet, log in again after the Desktop App has run.
14. [ ] The **Min sold/day** box fits next to **Min AH listings** and **Scan AH** in the toolbar without overlapping.
15. [ ] **Random counts:** with Engineering, open the profession window and select Heavy Dynamite: the game's recipe should say it makes 1-5 (the addon's details then say "Makes 1-5 (avg 3)", read from your window). If you can, also check Coarse Dynamite (1-3) and Iron Grenade (2-4), and report any other numbers.
16. [ ] **Vendor shuffles:** the **Vendor shuffles** checkbox fits at the right end of the title row next to the **Mode** button, and the **Vend. profit** column fits between **Profit** and **%** in both modes, without overlapping or cut-off text.
17. [ ] **Crafting time columns:** the window is now 1204 pixels wide (was 1120, and 940 before the time columns) and still fits on your screen. The **Time**, **AH g/h** and **Vend g/h** columns fit at the right of the list in both modes, without cut-off text (e.g. `1m15s`, `12345g`), and the details pane is as wide as before.
18. [ ] **Cheap batch:** the **Batch** and **Batch profit** columns fit between **Sold/d** and **Time** (Batch profit e.g. `1234g 56s` or `12g 34s 56c`, without cut-off text), and the **Min batch** box fits at the right end of the filter row before **Scan AH**, in both modes. A capped batch shows as e.g. `200+`, and the `—` of a result with no data (e.g. **Batch**, **Sold/d**) shows as a dash, not a box (if not, please report it). A scan with the addon's deeper price steps (50, was 20) takes about as long as before; note the time in chat for a full AH.
19. [ ] **Cast times:** open a profession window, then check a few crafts in the details: Heavy Dynamite should take 5.1 s per craft and Truesilver Champion 1 min, as on the game's own cast bar. If a gear item or buff changes your crafting speed, note whether the addon's time follows it (it reads `C_Spell.GetSpellInfo(spell).castTime`).
20. [ ] **Best-g/h path:** with Engineering or Alchemy, find a result whose **AH g/h** or **Vend g/h** ends in `*` (e.g. a crafted shot or rocket where buying the powder or bars is faster). The `*` fits in the cell without cutting off the number (e.g. `12345g*`), the footer line with "* = g/h and time of a faster path" is not cut off, the **Time** cell of such a row also ends in `*` (e.g. `5.1s*`) without cutting off the number, and the details' "Fastest path" section reads sensibly (what to buy instead, its chain tree and shopping list).
21. [ ] **Help the recipe data:** open each profession window and type `/crafter dump` (on each character, for each profession, both factions if you can). Then `/reload` or log out, and send `_forever_\WTF\Account\<account>\SavedVariables\ForeverCrafter.lua` (the file also holds your character names, skills and saved prices; the import reads only its `dump` part and keeps the recipes, items, faction and date, and which recipes some character knows, but not which character). A recipe a character knows counts as existing even if Wowhead Forever lists it nowhere, and the game's reagents come before the DB2 ones. The game's recipe list itself holds every recipe in the client data, learnable or not, so it is not used to add recipes. The dump also notes items the game knows nothing about.
22. [ ] **Reputation tab:** the **Reputation** button fits at the right of the title row (left of the close button), and in the tab the 7 columns fit the list without cut-off text (e.g. a long writ name, `1g 23s 45c ~`, `needs Friendly`). The status line shows your standing, e.g. `Durotar Supply and Logistics: Friendly 500/6000`, and your Merchant's Favor. On an Alliance character it names the Azeroth Commerce Authority, and the writs and crates are the same; please report if they are not.
23. [ ] **Writ reputation:** turn in a Journeyman, an Expert and an Artisan writ. Is it 75, 125 and 150 reputation? After each, the writ's **Gives** turns white (learned). Note the Coin Pouch's gold, so the averages (Journeyman 5-19s, about 12s; Expert 36s; Artisan 74s 56c) can be checked.
24. [ ] **Once per day:** a writ you turned in shows `done` until the daily reset, and then not (it reads `C_QuestLog.IsQuestFlaggedCompleted` for the writ's quest).
25. [ ] **Merchant's Favor:** hand in a sealed crate: is it 5 / 10 (Apprentice white / green), 10 / 20 (Journeyman), 20 / 30 (Expert)? What does an Artisan crate give (the addon shows `?`)? Does handing it in also give reputation (the details then show it)? Are white crates the raw materials and green ones the processed ones?
26. [ ] **Notarised crate:** does a Forged Delivery Receipt cost 15 Merchant's Favor, does an empty crate with a receipt give 50 reputation, and does a receipt work on the unidentified Waylaid Crate (248549) as well as on an identified one? Are crates really for Friendly and above?
27. [ ] **Learning:** after a turn-in, chat in `/crafter debug` says "reputation: learned ...", and the number matches what the game showed. Report it if it learned a wrong number (`/crafter rep forget` clears it).
28. [ ] **Sniper tab:** the **S** checkbox column fits at the left of the list in both modes, the **Sniper** button fits in the title row left of **Reputation**, and in the tab the 10 columns and the controls (**Keep g/h %**, **Start**, **Buy ...**, **Untick all**, **Forget bought**) fit without overlapping or cut-off text. The window size is unchanged.
29. [ ] **Searches:** with a few crafts ticked and the AH open, **Start**: **Searched** counts up for each reagent, **Cheapest** matches the AH's own list for that item, and the AH does not complain about too many searches. Note whether cloth, herbs and ore (commodities) and gear-like reagents (item auctions, e.g. a crafted part) both get results.
30. [ ] **Commodity purchase:** press **Buy** on a commodity deal. Does it buy at once, or does the button turn into **Confirm ...** (the game blocked the confirm from the price quote; `/crafter errors` then shows a `blocked` line)? Is the amount and the total what the button said? If the price rose, does the addon cancel and say so in chat?
31. [ ] **Item auction purchase:** for an item that is not a commodity, does **Buy** buy the whole lot at the listed buyout (is the shown price the lot's total)?
32. [ ] **Mail:** after a purchase, **Have** includes it at once and **Need** drops; when you take it from the mailbox, it moves from the mail to the bags and is not counted twice.
33. [ ] **Ticked crafts and Target:** on the Sniper tab, the ticked-crafts list (5 rows, scroll with the mouse wheel when more are ticked, 7 columns) and its Total line fit above the reagent list (now 11 rows) without overlapping the status line or each other, and the window is still 1204 px wide. The **Target** box fits in its column; typing a number and pressing Enter raises **Need** at once, a blank resets it to the batch, and a refresh while you type does not overwrite the box.
34. [ ] **Vendor costs:** at Mister Graphed (Riverglades) Black Lotus should cost 52g 63s 15c, not 40s, and at Lokhtos Darkbargainer (Blackrock Depths) the elemental essences cost 30 Firelands Ember each, not gold; a Horde character should not be told to buy Rhapsody Malt or Thunder Ale (Alliance innkeepers only). Can both factions trade with Mister Graphed (Wowhead shows him neutral to both)?
35. [ ] **Cooldowns tab and API:** the **Cooldowns** button fits in the title row left of **Sniper** and its 6 columns fit the list. with the Tailoring window open on a character that made Mooncloth, the Cooldowns tab shows "in ..." with about the time the game shows on the recipe. The addon reads `C_TradeSkillUI.GetRecipeCooldown(recipe)` (assumed: nil when ready) and falls back to `C_Spell.GetSpellCooldown`. If it says "open the profession window" after you did, `/crafter errors` has the reason.
36. [ ] **Shared transmute cooldown:** after Transmute: Arcanite, do the other transmutes (e.g. Air to Fire) show the same wait in the game and in the tab? Do Iron to Gold and Mithril to Truesilver keep their own 1 h cooldown (no shared category in the data)? Does Elemental Fire (category 310 but a 10 min cooldown) really block the others?
37. [ ] **Ready time after a relog:** craft Mooncloth, log out and in (and log in an alt): the tab still shows when it is ready, and the login line counts it once it is.

## Development

- `make check` runs all offline checks. It needs Python 3 and `pip install --user lupa`, which provides a real Lua 5.1. It checks:
  - **TOC and policy:** `## Interface: 16001`, the file list, and no Classic or Retail source links in the data, docs or tools;
  - **data:** every entry has a `src` from the [SOURCES.md](SOURCES.md) table and a `verified` date, every referenced item exists, `Data/*.lua` matches what the pinned `research/` snapshots generate (`tools/gen_data.py verify`), and the Wowhead Forever tooltip fact for recipe 3170; `Data/Sales.lua` (TSM, changes daily) is checked for its shape, value ranges and the snapshot table in SOURCES.md instead;
  - **runtime:** loads the addon in a fake WoW client (`tools/wow_stub.lua`) with the real data, then logs in, reads a profession window, scans an AH, opens a merchant and the mailbox, and drives the window and every command. It checks the costs, values and chains against hand-computed numbers, cycles between recipes, the chain depth limit, thin markets, missing APIs, a full run over all 2038 recipes, and that the zip holds `ForeverCrafter/` at its top level.
- `make data` regenerates `ForeverCrafter/Data/*.lua` from `research/` (offline, deterministic). To move to a new client build: change `BUILD` in `tools/gen_data.py`, run `python3 tools/gen_data.py fetch`, dump the Wowhead Forever lists again in a browser with `tools/wowhead_dump.js` and `python3 tools/gen_data.py wowhead <folder>`, read the pages in `research/wowhead/page_targets.json` and the recipe item lists with `tools/wowhead_crawl.js` (`FCcrawl`, `FCsourcemore`) and trim them with `python3 tools/gen_data.py wowhead-pages <folder>` and `wowhead-sourcemore <file>`, fetch the item tooltips with `python3 tools/gen_data.py wowhead-tooltips`, merge players' `/crafter dump` files with `python3 tools/gen_data.py client-dump <ForeverCrafter.lua ...>` (into `research/client/dump.json`), then `make data`, `make crosscheck` and update SOURCES.md.
- `make tsm` downloads TradeSkillMaster's public Forever region files (US and EU, network) and rewrites `ForeverCrafter/Data/Sales.lua` and the snapshot table in SOURCES.md. Only the sold per day and sale rate of recipe outputs are kept.
- `make crosscheck` compares a sample of recipes with the Wowhead Forever tooltips (network) and writes `research/crosscheck_<date>.txt`.
- `make zip` builds `dist/ForeverCrafter-v<version>.zip` (unzip straight into `AddOns`). `make zip RELEASE=0.1.4` names it after that version and writes it into the zipped `.toc` (the release workflow does this); `python3 tools/release_version.py` prints the next release's version (nothing when `HEAD` is already released).
- Layout of `ForeverCrafter/`:
  - `Core/`: init, events, slash commands, saved variables (`Init.lua`); money and item helpers (`Util.lua`);
  - `Data/`: generated recipes, items and vendor reagents, each with source and verified date; the TSM sales snapshot (`Sales.lua`);
  - `Modules/`: professions and skill (`Professions.lua`), the AH snapshot (`Scanner.lua`), buy and sell prices, merchants, invoices and deposits (`Pricing.lua`), sold per day from TSM (`Sales.lua`), the chain solver (`Planner.lua`), the window (`UI.lua`), the minimap button (`Minimap.lua`), `/crafter dump` (`Dump.lua`), the reputation planner (`Reputation.lua`), the reagent sniper (`Sniper.lua`).
- The client is the 12.x API ("Camelot", `## Interface: 16001`). Use `C_*` namespaces and pcall-wrap anything that may not exist.

## Licence

GPL-2.0-or-later (see [LICENSE](LICENSE)).
