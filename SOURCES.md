# Sources

Every game fact in ForeverCrafter comes from a **World of Warcraft: Forever** source: the Forever client data tables, Wowhead Forever, or the Forever UI code. Classic and Retail pages and data were never used, because Forever changed many recipes (for example, Minor Healing Potion is a First Aid recipe in Forever, spell 1244431).

All data was taken from client **1.60.1.70888** (wago.tools product `wowf`) on **2026-11-12**. Each entry in `ForeverCrafter/Data/*.lua` has a `src` key, made of one or more keys of the table below joined by `+`, and a `verified` date. `make check` fails if an entry has no `src` or `verified`, or if a `src` key is not in this table.

## Sources

| Key | Source | Used for |
|---|---|---|
| `db2` | Forever client DB2 tables exported by wago.tools, product `wowf`, build **1.60.1.70888**: `https://wago.tools/db2/<Table>/csv?build=1.60.1.70888` for SkillLine, SkillLineAbility, SpellName, SpellEffect, SpellReagents, Item, ItemSparse, ItemEffect, ItemXItemEffect. Filtered snapshots, with row counts and SHA-256 of the full downloads, are in `research/db2/` (`manifest.json`). | Profession skill lines and whether each is a primary profession or a secondary skill (`SkillLine.CategoryID`: 11 = professions, 9 = secondary skills Cooking and First Aid; `cat` in `Data/Recipes.lua`, used by what-if mode); every recipe (spell, skill line, `MinSkillLineRank`, `TrivialSkillLineRankLow/High`, `AcquireMethod`); reagents and counts (`SpellReagents`); the created item and count (`SpellEffect` "Create Item", effect 24); recipe items that teach a recipe (`Item` class 9 + `ItemEffect`); item names, quality, `SellPrice`, `BuyPrice`, `VendorStackCount`, max stack, bind type (`ItemSparse`). |
| `wh_list` | Wowhead Forever list views, read in a browser on 2026-11-11 with `tools/wowhead_dump.js` (www.wowhead.com returns 403 to scripts): the profession spell lists (`https://www.wowhead.com/forever/spells/professions/<profession>`, `.../secondary-skills/cooking`, `.../secondary-skills/first-aid`), the recipe item lists (`https://www.wowhead.com/forever/items/recipes/<profession>`) and the item lists for trade goods, consumables, armour, weapons, quest and miscellaneous items. Trimmed copies with the page URLs and fetch times: `research/wowhead/`. The recipe item lists were dumped again on 2026-11-12 for their `sourcemore` column (`research/wowhead/recipe_item_sourcemore.json`, via `python3 tools/gen_data.py wowhead-sourcemore`). | Which DB2 recipes exist in Forever (a recipe on no list is left out, see below); how a recipe is learned (trainer and training cost, recipe item, drop, quest, vendor) and how an item is obtained (source codes, e.g. 5 = Vendor), used for the vendor reagent list and the "how to learn" text. |
| `wh_tt` | Wowhead Forever tooltips, `https://nether.wowhead.com/forever/tooltip/spell/<id>` and `.../tooltip/item/<id>` (scriptable). Never add `?dataEnv=`: `dataEnv=8` returns **WotLK** data (its links point to `/wotlk/`). | Cross-check of a sample of recipes against the DB2 data: `tools/crosscheck_wowhead.py`, results in `research/crosscheck_2026-11-12.txt`. `make check` also checks one tooltip fact: Minor Troll's Blood Elixir (3170) takes Peacebloom (2447), Earthroot ×2 (2449) and Empty Vial (3371). Name, quality and sell price of the items that have no `ItemSparse` row: `python3 tools/gen_data.py wowhead-tooltips`, 2026-11-12, `research/wowhead/tooltips_items.json`. |
| `wh_item` | Wowhead Forever item and spell pages, `https://www.wowhead.com/forever/item=<id>` and `.../spell=<id>`, plus the zone list `https://www.wowhead.com/forever/zones`. Read in a browser on 2026-11-12 with `tools/wowhead_crawl.js` (see "Reading Wowhead Forever pages" below), trimmed by `python3 tools/gen_data.py wowhead-pages <folder>` into `research/wowhead/pages_items.json`, `pages_spells.json` and `zones.json`. | Item pages: the "Sold by" list (NPC name, zone, faction, unlimited or limited stock) of the vendor reagents and of some recipe items, and the source lists ("Dropped by", "Contained in", ...) of reagents that have no source on the list views. Spell pages: a sample of recipes with no source and of left-out recipes (see below). |
| `ui` | Blizzard UI code for Forever 1.60.1 ([reckhou/WoWBlzCode](https://github.com/reckhou/WoWBlzCode), @ `7245053`, folder `Forever/BlizzardInterfaceCode/Interface/AddOns`: `Blizzard_APIDocumentationGenerated/` `AuctionHouseDocumentation.lua`, `TradeSkillUIDocumentation.lua`, `SkillInfoDocumentation.lua`, `ItemDocumentation.lua`, `SpellBookDocumentation.lua`, `MailInfoDocumentation.lua`; `Blizzard_UIPanels_Game/{Vanilla,Mainline}/MerchantFrame.lua`; `Blizzard_MailFrame/MailFrame.lua`) | API names, arguments, return values and events: `C_AuctionHouse.ReplicateItems`, `GetNumReplicateItems`, `GetReplicateItemInfo` (18 returns), `GetReplicateItemLink`, `REPLICATE_ITEM_LIST_UPDATE`, `CalculateCommodityDeposit` (duration index 1 = 12 h), `C_TradeSkillUI.GetAllRecipeIDs`, `GetRecipeInfo`, `GetRecipeSchematic`, `SetShowUnlearned`, `GetBaseProfessionInfo`, `GetChildProfessionInfo`, `TRADE_SKILL_SHOW` / `LIST_UPDATE` / `CLOSE`, `C_SkillInfo.GetSkillLineInfoByID`, the merchant API (`GetMerchantNumItems`, `GetMerchantItemID`, `GetMerchantItemInfo`), mail invoices (`GetInboxInvoiceInfo`), the frame templates. The UI code has no AH cut constant. |
| `in-game` | The live Forever client while the addon runs | Overrides static data where the game knows better: recipes and reagents of the open profession window (`C_TradeSkillUI`), prices of every merchant the player opens, the AH cut measured from sale invoices in the mailbox, AH deposits (`CalculateCommodityDeposit`), item sell prices (`C_Item.GetItemInfo`). Stored in the SavedVariables, never in `Data/`. |
| `client` | The live Forever client, saved by `/crafter dump` in game (`C_TradeSkillUI.GetAllRecipeIDs`, `GetRecipeInfo`, `GetRecipeSchematic`, `GetRecipeSourceText`, `C_Item.GetItemInfo`) and merged from the SavedVariables file by `python3 tools/gen_data.py client-dump <ForeverCrafter.lua>` into `research/client/dump.json`. No character names or skills are kept; which recipes some dumped character knows is kept without saying who (`known`). `GetRecipeSourceText` is not in the generated API docs; Forever's own profession window calls it for unlearned recipes (`Blizzard_ProfessionsTemplates/Blizzard_ProfessionsRecipeSchematicForm.lua`, `ui` above). | Comes **before** Wowhead Forever: a recipe a dumped character knows exists (`known`), even if no Wowhead list has it; a DB2 recipe missing from a profession's full listing is left out; the game's reagents and output replace the DB2 ones where they differ; the game's "how to learn" text (`learnText`) if it gives one; name, quality and sell price of items with no `ItemSparse` row. Being in the game's list alone proves nothing: the list holds every DB2 recipe of the profession (see "Client dump" below). Wowhead fills what the client does not say (vendor NPCs, drop sources, which recipes can be learned). |
| `tsm` | [TradeSkillMaster](https://tradeskillmaster.com) public region data for WoW: Forever, `https://public-data.tradeskillmaster.com/forever/{us,eu}/region/items.csv` (no key, updated daily; columns `itemId,name,marketValue,historical,avgSalePrice,saleRate,soldPerDay,updatedAt`), downloaded by `python3 tools/gen_data.py tsm` (`make tsm`); in game the TSM addon's `TSM_API.GetCustomPriceValue("DBRegionSoldPerDay" | "DBRegionSaleRate", "i:<id>")` when it is loaded. Data by TradeSkillMaster, offered free and public on the terms published with it; there is no explicit redistribution clause, so only the derived subset is bundled (below), with this attribution, and the raw CSVs are not kept in `research/`. | Sold per day and sale rate of recipe outputs (`Data/Sales.lua`), for the **Sold/day** column and the **Min sold/day** filter. Never used for prices or profit. |

## How the data is built

`tools/gen_data.py` reads only `research/` and is deterministic; `make check` runs `gen_data.py verify`, which fails if `ForeverCrafter/Data/*.lua` differs from what `research/` gives.

- **Recipes** (`Data/Recipes.lua`, 2038): every `SkillLineAbility` row of the professions (Alchemy 171, Blacksmithing 164, Enchanting 333, Engineering 202, Leatherworking 165, Tailoring 197, Cooking 185, First Aid 129, Mining 186, and their child lines 2937-2948) whose spell has a "Create Item" effect. Enchants that create no item are out of scope.
- **Left out** (264, listed with reasons in `research/excluded_recipes.txt`): DB2 recipes that are on no Wowhead Forever profession list, or that Wowhead lists as learned at 9999 (nobody teaches them). A recipe the player really knows still comes in at runtime from the profession window.
- **Items** (`Data/Items.lua`, 4044): every reagent, created item and recipe item, with the DB2 prices. 194 IDs are in the `Item` table but have no `ItemSparse` row in this export (`missing=true`; the name comes from Wowhead when it has one).
- **Vendor reagents** (`Data/Vendor.lua`, 814): items whose Wowhead Forever source list has "Vendor" and whose DB2 `BuyPrice` is above 0. 303 are treated as unlimited stock (source only "Vendor" and quality Common or lower); the rest are marked `limited` and are not used as a buy price until the player sees them at a merchant.
- **Recipe learning:** `AcquireMethod` (DB2) plus the Wowhead source codes and training cost. 338 recipes have no Wowhead source of their own: for 70 the addon names their recipe item's source, for 6 it says a character knew them in a client dump, and for the other 262 it says "source unknown".

## What-if confidence

What-if mode (README, "What-if mode") rates how sure it is that each recipe can be learned, from the data fields below, first match wins. A chain takes the level of its least sure recipe. Nothing here is a new fact: the levels only sort the sources the data already has.

| Level | Data fields (source) |
|---|---|
| 1 Confirmed | `known` in `Data/Recipes.lua` (a character knew it in a client dump, `client`), or the current character knows it (profession window or spellbook, in game) |
| 2 Trainer/vendor | The recipe's Wowhead source codes `how` have 6 Trainer, 5 Vendor or 10 Starter (`wh_list`); or one of its recipe items (`items`, `db2`) is a vendor recipe in `Data/Vendor.lua` (`recipe=true`, `wh_list`/`wh_item`), was seen at a merchant in game, has source code 5 in `Data/Items.lua` `how`, or has a `vendor` entry in its `from` list (`wh_item`) |
| 4 Drop/quest/other | Any other source code or `from` entry on the recipe or its recipe items (drop, quest, world object, ...) |
| 3 Likely | No source, but DB2 `SkillLineAbility.AcquireMethod` is 1 (see "Where sources disagree": all 6 such recipes in the client dump were known) |
| 5 Unknown | None of the above |

The left-out recipes (`research/excluded_recipes.txt`) are not in the data and never count; a recipe that only the profession window knows (no `learn` rank in the data) is not used in what-if mode. A recipe the profession window hides counts as hidden in both modes.

## TradeSkillMaster sales data

How many of a recipe's output sell per day, to hide crafts that are profitable on paper but hardly sell (README, "Sold per day").

- **Scope:** TSM publishes sales only **region-wide** (all realms, all realm types, both factions together). Its Forever realm files (`.../forever/<region>/realm/<normal|pvp|roleplay|roleplay-pvp>-<horde|alliance>/items.csv`) have prices only (`marketValue,minBuyout,recent,historical`), no sales, and are not used. A region figure says nothing about one realm's faction AH.
- **Kept:** `soldPerDay` and `saleRate` (0-1) of the recipe outputs in `Data/Recipes.lua` only; no prices, no names, no other items. An output that is not in TSM's file has **no data** (usually never sold on the AH); the window shows "—" and hides it while the filter is above 0. `make check` checks `Data/Sales.lua` for structure, `src`/`verified`, value ranges, that every item is a recipe output, and that the snapshot below names the same files. Unlike the other data it is not rebuilt from `research/` (it changes daily).
- **Order in game, per item:** the TSM addon's own region value when it is loaded and returns one (its AuctionDB data from the TSM Desktop App, loaded at login or `/reload`), otherwise the bundled snapshot of the game's region. The region is `GetCurrentRegionName()` ("US", "EU", as Forever's own UI code uses it, `ui`), else `GetCurrentRegion()` (1 = US, 3 = EU, assumed); any other region has no snapshot.
- **Scale of the TSM addon's values:** not verified (TSM's API documentation site was not reachable). The addon compares the live values of up to 25 snapshot items with the snapshot and picks the scale (1, 100 or 1000) nearest to the median ratio, for sold per day and sale rate separately. With no snapshot for the region it reads the sale rate (raw 0-1, so a larger value is scaled) and uses that scale for both. `/crafter status` shows the scale and how it was found.

Snapshot in `Data/Sales.lua` (rewritten by `gen_data.py tsm`):

<!-- tsm-snapshot -->
| Region | File | updatedAt | Rows | sha256 | Recipe outputs kept (sold/day >= 1) |
|---|---|---|---|---|---|
| US | `https://public-data.tradeskillmaster.com/forever/us/region/items.csv` | 2026-11-11T08:47:34Z | 6653 | `33bbe7a6f2b1bc077ed2fde18d9b38a45b99ca858972bd85871adc44ba2e324d` | 939 (650) |
| EU | `https://public-data.tradeskillmaster.com/forever/eu/region/items.csv` | 2026-11-11T00:20:19Z | 7008 | `24fe47dbf0be4ab3ca20964430437c03b4e047909d16fefeee0644a31f0b8639` | 1021 (662) |

Downloaded 2026-11-12; 2032 recipe outputs in Data/Recipes.lua.
<!-- /tsm-snapshot -->

## Cross-check with the Wowhead Forever tooltips

`tools/crosscheck_wowhead.py` (2026-11-12): 45 recipes (every 50th by spell ID, plus 3170, 2963, 2385, 3275, 1244431).
- Name, reagents and created item: **45 of 45 agree**. Recipe 435610 (Gneuro-Linked Arcano-Filament Monocle) has a sixth DB2 reagent, 213372, which has no item row and no Wowhead page; Wowhead leaves it out. The addon can never price it, so this recipe never shows as a result.
- **Sell price: 10 of 45 created items disagree** between DB2 `ItemSparse.SellPrice` and the tooltip. Most have 0 in DB2 but a price on Wowhead (e.g. Veteran's Chain Helm 250498: 0 vs 12s 74c); some are higher in DB2 (Filigreed Silky Circlet 253977: 16s 16c vs 7s 92c). So the addon uses the client's own price (`C_Item.GetItemInfo`) whenever the item is loaded, and marks a vendor value that only comes from DB2 with `~` (estimate).

## Client dump

The first `/crafter dump` file (2026-11-12): client 1.60.1.70888, toc 16001, a Horde character with Blacksmithing (rank 140: 507 recipe IDs, 506 with recipe info, 62 known) and Mining (rank 145: 18 recipes, 6 known). Merged into `research/client/dump.json`.

- **The game's list is the DB2, unfiltered.** With unlearned recipes shown, `C_TradeSkillUI.GetAllRecipeIDs` lists exactly the `SkillLineAbility` rows of the line whose spell creates an item: 506 of 506 for Blacksmithing and 18 of 18 for Mining; only rank, specialisation and gathering spells are missing. It includes 65 recipes that no Wowhead Forever profession list has (64 Blacksmithing, e.g. the Golden Scale, Obsidian, Razorspike, Ironvine, Icebane and Scarlet Soldier's sets, Sulfuron Hammer; 1 Mining, Smelt Obsidian-Infused Thorium Bar), all with DB2 `MinSkillLineRank` 1. So a listing is no proof that a recipe can be learned; these 65 stay left out (`research/excluded_recipes.txt`), and only a recipe someone **knows** is taken as proof.
- **Reagents and output: 524 of 524 agree** between `GetRecipeSchematic` and the DB2 (`SpellReagents`, `SpellEffect`), learned and unlearned alike.
- **`GetRecipeSourceText` returns nothing in Forever:** no text for any of the 456 unlearned recipes. The data therefore has no `learnText`; the addon still shows a text if the game ever gives one.
- **`AcquireMethod` 1:** the character knows all 6 `AcquireMethod` 1 recipes of the two professions (Rough Sharpening Stone, Copper Bracers, Rough Weightstone, Rough Copper Vest, Copper Rod; Smelt Copper), none of which has a Wowhead Forever source. This supports reading 1 as "learned with the profession"; they are now listed as known, with no source named.
- **Items:** the dump asked `GetItemInfo` about the 194 items with no `ItemSparse` row. It answered for 74, all among the 85 that have a Wowhead Forever tooltip: name and quality agree for all 74, the sell price for 73 (Schematic: 9-60 Battery Pack 274049: 0 in game, 10s on Wowhead; the game's 0 is used). No answer within 10 seconds for the 109 items Wowhead does not have, nor for 11 Tinkerbox items it does (238734-238737, 238782-238788). This first dump did not record unanswered items (inferred from `Dump.lua`, which asks for every `missing` item); later dumps record them in `noItem`.

## Where sources disagree, or are assumed

| Topic | What we know | Used |
|---|---|---|
| Vendor sell prices | DB2 and the Wowhead tooltips disagree for about 1 in 5 crafted items (above) | Client price first; DB2 only as an estimate (`~`) |
| AH cut | No constant in the Forever UI code | 5% until the addon measures it from a sale invoice in the mailbox (`consignment / bid`), or `/crafter cut <pct>` |
| AH deposit | `CalculateCommodityDeposit(item, 1, 1)` per item, after each scan | Subtracted from the AH value as a cost (it is lost if the item does not sell) |
| `BuyPrice` and `VendorStackCount` | DB2 `BuyPrice` read as the price of one vendor bundle of `VendorStackCount` items | Unit cost = `BuyPrice / VendorStackCount`, marked `~` until the merchant is seen |
| Unlimited vendor stock | Not in the client data | Heuristic: Wowhead source only "Vendor" and quality Common or lower |
| `AcquireMethod` | DB2 values 0 (2570 rows), 1 (38) and 3 (15); the meaning is not documented in the client data. In the client dump a character knew all 6 Blacksmithing and Mining recipes with value 1 | Wowhead's sources and training cost decide the "how to learn" text; a recipe with no Wowhead source and `AcquireMethod` 1 says it may be learned automatically, and is "Likely" in what-if mode |
| Primary or secondary | DB2 `SkillLine.CategoryID` 11 (professions) or 9 (secondary skills: Cooking 185, First Aid 129). Mining is 11; Fishing has no recipes and is not in the data | What-if "Max primaries" counts only category 11 |
| Sales per day | TradeSkillMaster has sales only per region (all realms and factions); the TSM addon's value scale is not documented where we could read it | Region figure, output item only, filter only (profit unchanged); scale detected against the snapshot ("TradeSkillMaster sales data") |

## Open: verify in game

These cannot be checked offline. The addon is built so that each one fails safely (a guarded call, a fallback, or an estimate mark).

1. `C_AuctionHouse.ReplicateItems` works in Forever, how often it may be called (assumed once per 15 minutes), whether `GetReplicateItemInfo` indices start at 0 (the addon reads `0..n`), whether `buyoutPrice` is for the whole stack (assumed), whether commodities (cloth, herbs, ore) are in the snapshot, and how long a full snapshot takes.
2. The AH cut in Forever (assumed 5%) and the deposit; whether `CalculateCommodityDeposit` returns a value for non-commodity items, and whether the deposit is returned when an item sells.
3. ~~`SetShowUnlearned(true)` lists unlearned recipes; `GetRecipeSchematic` reagents match the data~~: verified in the client dump (2026-11-12, Blacksmithing and Mining). Still open: the other professions, and `GetAllRecipeIDs` against `GetFilteredRecipeIDs`.
4. `C_SkillInfo.GetSkillLineInfoByID` and `GetProfessions` / `GetProfessionInfo` return the Forever skill ranks, for the main and the child skill lines.
5. `C_SpellBook.IsSpellKnown` / `IsPlayerSpell` for recipe spells before the profession window was opened.
6. DB2 `BuyPrice` is per `VendorStackCount` bundle (compare with a merchant, e.g. Empty Vial 3371).
7. Limited-stock and faction-only vendors; the "Common or lower = unlimited" heuristic.
8. The meaning of `SkillLineAbility.AcquireMethod` (value 1 looks like "learned with the profession", see "Client dump").
9. The merchant API (`GetMerchantItemInfo` price per `stackCount`) and mail invoices (`GetInboxInvoiceInfo`) in the Forever client.
10. The minimap and compartment icon `Interface\Icons\INV_Misc_Coin_01` exists.
11. What-if mode's run over every recipe (one profession set per frame) does not stutter: offline it takes about 2-15 ms per frame and 0.04-0.11 s in total at cap 150 with 2 primaries (Lua 5.1 via lupa).
12. `GetCurrentRegionName()` returns "US" or "EU" in Forever, and `GetCurrentRegion()` 1 for US and 3 for EU (the fallback).
13. With TradeSkillMaster 4.15+ loaded: `TSM_API.GetCustomPriceValue("DBRegionSoldPerDay", "i:<id>")` and `"DBRegionSaleRate"` return values, and their scale (raw, x100 or x1000; `/crafter status` shows the one detected) matches the TSM addon's own tooltip.
14. The **Min sold/day** box and the other boxes in the second toolbar row do not overlap at the default window size.

## Reading Wowhead Forever pages

`www.wowhead.com/forever` returns 403 to scripts, so `tools/wowhead_crawl.js` runs in a browser tab on Wowhead Forever (same-origin fetches with the browser's own session). Wowhead's bot check ("Let's confirm you are human", HTTP 405 "Human Verification") trips after roughly 30-70 pages; the crawl then stops, keeps the IDs it has not read, and a person solves the check in the tab before it goes on at a slower pace. Nothing the crawl did not read was filled in.

- **Item pages** (2026-11-12): 269 pages: every reagent with no source on the list views, the vendor reagents, and part of the vendor recipe items. 2 redirect to Wowhead's "Forever Items" page (no such item on Wowhead Forever).
- **Spell pages, a sample** (2026-11-12): 35 pages picked at random (`random.Random(20261112)`) from the 338 kept recipes with no source of their own (20) and the 264 left-out recipes (15). None lists a trainer, vendor, drop or quest for the recipe itself. 16 list a "Taught by item" recipe item, and for the kept recipes it is always the item the DB2 already links (`ItemXItemEffect`); the item rows there carry the same source codes as the recipe item lists. The other spell pages were therefore not read: the DB2 links and the recipe item lists give the same facts for all recipes (see `research/excluded_recipes.txt` and `research/open_sources.txt`).
- **`sourcemore`** (2026-11-12): the recipe item lists name one NPC, quest, object or zone when an item has a single source of that kind (631 recipe items, `from` in `Data/Items.lua`). Wowhead does not say which source kind the entry belongs to. Our reading, shown in the addon: an NPC is the vendor when "Vendor" is the item's only source, the dropper when "Drop" is the only one, otherwise just "NPC"; a quest entry is the quest that rewards it; an entry with only a zone is shown as the zone.
- **Tooltips** (2026-11-12): of the 194 items with no `ItemSparse` row, 85 have a Wowhead Forever tooltip (name, quality, sell price; no buy price) and 109 return 404.

## Open: browser and game checks

Everything below is listed item by item in `research/open_sources.txt`, which `make data` regenerates.
- **Client dumps so far: Blacksmithing and Mining** (Horde). More dumps, of other professions and of characters that know more recipes, can prove more recipes exist (README, "Verify in game").
- **6 recipes known in game with no source named** (the `AcquireMethod` 1 recipes above): they exist; how they are learned is open.
- **262 recipes with no source at all**: neither the recipe nor its DB2 recipe item has one on Wowhead Forever, and no dumped character knows them (23 of them have `AcquireMethod` 1, maybe learned with the skill). Of the 338 recipes with no source of their own, 70 have a recipe item with one, which the addon shows, and 6 are known in game (above).
- **27 reagents with no source** on the list views or their page.
- **109 items with no `ItemSparse` row and no Wowhead Forever item.** The game gave no item info for them either in the first client dump, so they are most likely not in the game; the addon would still read `GetItemInfo` in game if they appear.
- **399 vendor items with no NPC named** (their page was not read and the lists name no single vendor), mostly recipe items; their stock limits are unknown.
- **The 264 left-out recipes.** `research/excluded_recipes.txt` now shows, per recipe, the DB2 recipe items that teach it and what Wowhead Forever says about those items. 3 have a recipe item with a Wowhead source although the recipe is on no profession list: 10550 Nightscape Cloak (Pattern 8388, drop, Shen'dralas), 12063 Stormcloth Gloves (Pattern 254682, quest "I Need a Tailor" and vendor) and 12090 Stormcloth Boots (Pattern 254686, Hatecrest Serpent Guard). They stay left out until a game check shows they can be learned; if the player knows one, the profession window brings it in.
- **Capped item lists:** 7 item lists hit Wowhead's 1000-row cap (`"capped": true` in `research/wowhead/item_sources.json`). Every reagent that missed its source codes because of the cap is among the pages read above, so the cap no longer leaves a reagent without a source that Wowhead has; a created item can still miss its codes, which the addon does not use.
