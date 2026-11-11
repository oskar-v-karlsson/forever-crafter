# Sources

Every game fact in ForeverCrafter comes from a **World of Warcraft: Forever** source: the Forever client data tables, Wowhead Forever, or the Forever UI code. Classic and Retail pages and data were never used, because Forever changed many recipes (for example, Minor Healing Potion is a First Aid recipe in Forever, spell 1244431).

All data was taken from client **1.60.1.70888** (wago.tools product `wowf`) on **2026-11-12**. Each entry in `ForeverCrafter/Data/*.lua` has a `src` key, made of one or more keys of the table below joined by `+`, and a `verified` date. `make check` fails if an entry has no `src` or `verified`, or if a `src` key is not in this table.

## Sources

| Key | Source | Used for |
|---|---|---|
| `db2` | Forever client DB2 tables exported by wago.tools, product `wowf`, build **1.60.1.70888**: `https://wago.tools/db2/<Table>/csv?build=1.60.1.70888` for SkillLine, SkillLineAbility, SpellName, SpellEffect, SpellReagents, Item, ItemSparse, ItemEffect, ItemXItemEffect. Filtered snapshots, with row counts and SHA-256 of the full downloads, are in `research/db2/` (`manifest.json`). | Profession skill lines; every recipe (spell, skill line, `MinSkillLineRank`, `TrivialSkillLineRankLow/High`, `AcquireMethod`); reagents and counts (`SpellReagents`); the created item and count (`SpellEffect` "Create Item", effect 24); recipe items that teach a recipe (`Item` class 9 + `ItemEffect`); item names, quality, `SellPrice`, `BuyPrice`, `VendorStackCount`, max stack, bind type (`ItemSparse`). |
| `wh_list` | Wowhead Forever list views, read in a browser on 2026-11-11 with `tools/wowhead_dump.js` (www.wowhead.com returns 403 to scripts): the profession spell lists (`https://www.wowhead.com/forever/spells/professions/<profession>`, `.../secondary-skills/cooking`, `.../secondary-skills/first-aid`), the recipe item lists (`https://www.wowhead.com/forever/items/recipes/<profession>`) and the item lists for trade goods, consumables, armour, weapons, quest and miscellaneous items. Trimmed copies with the page URLs and fetch times: `research/wowhead/`. | Which DB2 recipes exist in Forever (a recipe on no list is left out, see below); how a recipe is learned (trainer and training cost, recipe item, drop, quest, vendor) and how an item is obtained (source codes, e.g. 5 = Vendor), used for the vendor reagent list and the "how to learn" text. |
| `wh_tt` | Wowhead Forever tooltips, `https://nether.wowhead.com/forever/tooltip/spell/<id>` and `.../tooltip/item/<id>` (scriptable) | Cross-check of a sample of recipes against the DB2 data: `tools/crosscheck_wowhead.py`, results in `research/crosscheck_2026-11-12.txt`. `make check` also checks one tooltip fact: Minor Troll's Blood Elixir (3170) takes Peacebloom (2447), Earthroot ×2 (2449) and Empty Vial (3371). |
| `wh_item` | Wowhead Forever item and NPC pages, `https://www.wowhead.com/forever/item=<id>` ("Sold by", "Taught by") | Not used yet: these pages need a browser, and a Wowhead bot check blocked them on 2026-11-12. The facts they would give are listed under "Open: browser checks". Nothing was filled in from memory or from other game versions. |
| `ui` | Blizzard UI code for Forever 1.60.1 ([reckhou/WoWBlzCode](https://github.com/reckhou/WoWBlzCode), @ `7245053`, folder `Forever/BlizzardInterfaceCode/Interface/AddOns`: `Blizzard_APIDocumentationGenerated/` `AuctionHouseDocumentation.lua`, `TradeSkillUIDocumentation.lua`, `SkillInfoDocumentation.lua`, `ItemDocumentation.lua`, `SpellBookDocumentation.lua`, `MailInfoDocumentation.lua`; `Blizzard_UIPanels_Game/{Vanilla,Mainline}/MerchantFrame.lua`; `Blizzard_MailFrame/MailFrame.lua`) | API names, arguments, return values and events: `C_AuctionHouse.ReplicateItems`, `GetNumReplicateItems`, `GetReplicateItemInfo` (18 returns), `GetReplicateItemLink`, `REPLICATE_ITEM_LIST_UPDATE`, `CalculateCommodityDeposit` (duration index 1 = 12 h), `C_TradeSkillUI.GetAllRecipeIDs`, `GetRecipeInfo`, `GetRecipeSchematic`, `SetShowUnlearned`, `GetBaseProfessionInfo`, `GetChildProfessionInfo`, `TRADE_SKILL_SHOW` / `LIST_UPDATE` / `CLOSE`, `C_SkillInfo.GetSkillLineInfoByID`, the merchant API (`GetMerchantNumItems`, `GetMerchantItemID`, `GetMerchantItemInfo`), mail invoices (`GetInboxInvoiceInfo`), the frame templates. The UI code has no AH cut constant. |
| `in-game` | The live Forever client while the addon runs | Overrides static data where the game knows better: recipes and reagents of the open profession window (`C_TradeSkillUI`), prices of every merchant the player opens, the AH cut measured from sale invoices in the mailbox, AH deposits (`CalculateCommodityDeposit`), item sell prices (`C_Item.GetItemInfo`). Stored in the SavedVariables, never in `Data/`. |

## How the data is built

`tools/gen_data.py` reads only `research/` and is deterministic; `make check` runs `gen_data.py verify`, which fails if `ForeverCrafter/Data/*.lua` differs from what `research/` gives.

- **Recipes** (`Data/Recipes.lua`, 2038): every `SkillLineAbility` row of the professions (Alchemy 171, Blacksmithing 164, Enchanting 333, Engineering 202, Leatherworking 165, Tailoring 197, Cooking 185, First Aid 129, Mining 186, and their child lines 2937-2948) whose spell has a "Create Item" effect. Enchants that create no item are out of scope.
- **Left out** (264, listed with reasons in `research/excluded_recipes.txt`): DB2 recipes that are on no Wowhead Forever profession list, or that Wowhead lists as learned at 9999 (nobody teaches them). A recipe the player really knows still comes in at runtime from the profession window.
- **Items** (`Data/Items.lua`, 4044): every reagent, created item and recipe item, with the DB2 prices. 194 IDs are in the `Item` table but have no `ItemSparse` row in this export (`missing=true`; the name comes from Wowhead when it has one).
- **Vendor reagents** (`Data/Vendor.lua`, 814): items whose Wowhead Forever source list has "Vendor" and whose DB2 `BuyPrice` is above 0. 303 are treated as unlimited stock (source only "Vendor" and quality Common or lower); the rest are marked `limited` and are not used as a buy price until the player sees them at a merchant.
- **Recipe learning:** `AcquireMethod` (DB2) plus the Wowhead source codes and training cost. 338 recipes have no Wowhead source; the addon says "source unknown" for them.

## Cross-check with the Wowhead Forever tooltips

`tools/crosscheck_wowhead.py` (2026-11-12): 45 recipes (every 50th by spell ID, plus 3170, 2963, 2385, 3275, 1244431).
- Name, reagents and created item: **45 of 45 agree**. Recipe 435610 (Gneuro-Linked Arcano-Filament Monocle) has a sixth DB2 reagent, 213372, which has no item row and no Wowhead page; Wowhead leaves it out. The addon can never price it, so this recipe never shows as a result.
- **Sell price: 10 of 45 created items disagree** between DB2 `ItemSparse.SellPrice` and the tooltip. Most have 0 in DB2 but a price on Wowhead (e.g. Veteran's Chain Helm 250498: 0 vs 12s 74c); some are higher in DB2 (Filigreed Silky Circlet 253977: 16s 16c vs 7s 92c). So the addon uses the client's own price (`C_Item.GetItemInfo`) whenever the item is loaded, and marks a vendor value that only comes from DB2 with `~` (estimate).

## Where sources disagree, or are assumed

| Topic | What we know | Used |
|---|---|---|
| Vendor sell prices | DB2 and the Wowhead tooltips disagree for about 1 in 5 crafted items (above) | Client price first; DB2 only as an estimate (`~`) |
| AH cut | No constant in the Forever UI code | 5% until the addon measures it from a sale invoice in the mailbox (`consignment / bid`), or `/crafter cut <pct>` |
| AH deposit | `CalculateCommodityDeposit(item, 1, 1)` per item, after each scan | Subtracted from the AH value as a cost (it is lost if the item does not sell) |
| `BuyPrice` and `VendorStackCount` | DB2 `BuyPrice` read as the price of one vendor bundle of `VendorStackCount` items | Unit cost = `BuyPrice / VendorStackCount`, marked `~` until the merchant is seen |
| Unlimited vendor stock | Not in the client data | Heuristic: Wowhead source only "Vendor" and quality Common or lower |
| `AcquireMethod` | DB2 values 0 (2570 rows), 1 (38) and 3 (15); the meaning is not documented in the client data | Wowhead's sources and training cost decide the "how to learn" text; a recipe with no Wowhead source and `AcquireMethod` 1 says it may be learned automatically |

## Open: verify in game

These cannot be checked offline. The addon is built so that each one fails safely (a guarded call, a fallback, or an estimate mark).

1. `C_AuctionHouse.ReplicateItems` works in Forever, how often it may be called (assumed once per 15 minutes), whether `GetReplicateItemInfo` indices start at 0 (the addon reads `0..n`), whether `buyoutPrice` is for the whole stack (assumed), whether commodities (cloth, herbs, ore) are in the snapshot, and how long a full snapshot takes.
2. The AH cut in Forever (assumed 5%) and the deposit; whether `CalculateCommodityDeposit` returns a value for non-commodity items, and whether the deposit is returned when an item sells.
3. `C_TradeSkillUI.SetShowUnlearned(true)` lists unlearned recipes in the Camelot profession window; `GetAllRecipeIDs` against `GetFilteredRecipeIDs`; `GetRecipeSchematic` reagents match `Data/Recipes.lua`.
4. `C_SkillInfo.GetSkillLineInfoByID` and `GetProfessions` / `GetProfessionInfo` return the Forever skill ranks, for the main and the child skill lines.
5. `C_SpellBook.IsSpellKnown` / `IsPlayerSpell` for recipe spells before the profession window was opened.
6. DB2 `BuyPrice` is per `VendorStackCount` bundle (compare with a merchant, e.g. Empty Vial 3371).
7. Limited-stock and faction-only vendors; the "Common or lower = unlimited" heuristic.
8. The meaning of `SkillLineAbility.AcquireMethod`.
9. The merchant API (`GetMerchantItemInfo` price per `stackCount`) and mail invoices (`GetInboxInvoiceInfo`) in the Forever client.
10. The minimap and compartment icon `Interface\Icons\INV_Misc_Coin_01` exists.

## Open: browser checks (Wowhead Forever)

A Wowhead bot check blocked `www.wowhead.com/forever` pages on 2026-11-12, and these were not filled in from any other source:
- "Sold by" NPCs, their location and faction, and stock limits for the vendor reagents (`wh_item`).
- Where the recipe items are sold or drop, and the price of vendor-sold recipe items.
- 24 reagents with no Wowhead source data: 2570, 4397, 10518, 10576, 10577, 11040, 11184, 11185, 11186, 11188, 11754, 12753, 14044, 211422, 213369, 213372, 220688, 220689, 221021, 221312, 238737, 238786, 238787, 238788.
- 338 kept recipes with no Wowhead source (how they are learned).
- The 264 left-out recipes in `research/excluded_recipes.txt`: confirm they cannot be learned in Forever.
- The 194 items without an `ItemSparse` row.
- Item lists that hit Wowhead's 1000-row cap (`"capped": true` in `research/wowhead/item_sources.json`), so some items may miss their source codes.
