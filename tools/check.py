#!/usr/bin/env python3
"""tools/check.py: offline checks for ForeverCrafter (no game needed).

1. Static checks: the TOC (Interface 16001, every file listed and present), every data entry carries `src` (a key
   from SOURCES.md) and a `verified` date, recipes/vendor entries only reference items in Data/Items.lua, the
   generated data matches the pinned research/ snapshots (tools/gen_data.py verify), a Wowhead Forever tooltip
   fact (recipe 3170), and no Classic/Retail source links anywhere in the data or docs.
2. Runtime: loads the addon in real Lua 5.1 (lupa) with a fake client (tools/wow_stub.lua) and real data, then
   drives it: skills, trade-skill window capture (learned, unlearned, hidden), AH snapshot (ladder, cancel),
   merchant and invoice capture, the solver (chains, vendor vs AH, cycle guard, depth limit, thin markets,
   learnable gating), the results window and the /crafter commands, a client without the APIs, and a full run
   over every recipe. What-if mode: skill cap and overrides, chains across professions, the max primary
   professions limit, confidence levels, the window controls and /crafter cap, "My character" results unchanged,
   and a timed what-if run over every recipe.
3. The release zip layout.

Usage: python3 tools/check.py      (exit code 1 on any problem)
"""
import os
import re
import subprocess
import sys
import json
import math
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "ForeverCrafter"
ADDON = os.path.join(ROOT, NAME)

try:
    import lupa.lua51 as lupa_mod
except ImportError:  # pragma: no cover
    try:
        import lupa as lupa_mod
    except ImportError:
        sys.exit("needs lupa: python3 -m pip install --user lupa")

problems = []


def problem(msg):
    problems.append(msg)


def expect(cond, msg):
    if not cond:
        problem(msg)
    return cond


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def toc():
    """→ (metadata {field: value}, files [relative paths with /])."""
    meta, files = {}, []
    for line in read(os.path.join(ADDON, NAME + ".toc")).splitlines():
        line = line.strip()
        m = re.match(r"^## ([\w-]+): (.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
        elif line and not line.startswith("#"):
            files.append(line.replace("\\", "/"))
    return meta, files


def version():
    return toc()[0]["Version"]


def build_zip(dist=None, release=None):
    """dist/ForeverCrafter-v<version>.zip with ForeverCrafter/ at the top (unzip straight into AddOns).
    release: the version of a release (tools/release_version.py); the zipped .toc gets it as its ## Version."""
    import zipfile
    dist = dist or os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    path = os.path.join(dist, f"{NAME}-v{release or version()}.zip")
    toc_path = os.path.join(ADDON, NAME + ".toc")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirs, files in os.walk(ADDON):
            dirs.sort()
            for fn in sorted(files):
                if fn.startswith("."):
                    continue
                full = os.path.join(dirpath, fn)
                if release and full == toc_path:
                    text, n = re.subn(r"^## Version: .*$", f"## Version: {release}", read(full), count=1, flags=re.M)
                    assert n == 1, "no ## Version line in the .toc"
                    z.writestr(os.path.relpath(full, ROOT), text)
                    continue
                z.write(full, os.path.relpath(full, ROOT))
        z.write(os.path.join(ROOT, "LICENSE"), f"{NAME}/LICENSE")
    return path


# Static ----------------------------------------------------------------------------------------------------------

def source_keys():
    """Keys of the sources table in SOURCES.md (rows like | `db2` | ...)."""
    return set(re.findall(r"^\| `([\w-]+)` \|", read(os.path.join(ROOT, "SOURCES.md")), re.M))


def check_toc():
    meta, files = toc()
    expect(meta.get("Interface") == "16001", f"TOC Interface is {meta.get('Interface')}, not 16001 (Forever)")
    expect(meta.get("SavedVariables") == "ForeverCrafterDB", "TOC SavedVariables is not ForeverCrafterDB")
    expect(re.match(r"^\d+\.\d+\.\d+$", meta.get("Version", "")), "TOC Version is not x.y.z")
    for rel in files:
        expect(os.path.exists(os.path.join(ADDON, rel)), f"TOC lists {rel}, which does not exist")
    for dirpath, _, names in os.walk(ADDON):
        for fn in names:
            if fn.endswith(".lua"):
                rel = os.path.relpath(os.path.join(dirpath, fn), ADDON).replace(os.sep, "/")
                expect(rel in files, f"{rel} is not in the TOC")


def check_policy():
    """Only WoW: Forever sources: no Classic/Retail Wowhead or wago builds in data, docs or tools."""
    bad = re.compile(r"wowhead\.com/(?!forever)(classic|tbc|wotlk|cata|mop-classic|item=|spell=|npc=)"
                     r"|classic\.wowhead|(?:product|branch)[=: ]+\"?(?:wow_classic|wow_classic_era|wow)\b")
    for folder in ("ForeverCrafter", "research", "tools"):
        for dirpath, _, names in os.walk(os.path.join(ROOT, folder)):
            for fn in names:
                if not fn.endswith((".lua", ".md", ".txt", ".json", ".py", ".csv")) or fn == "check.py":
                    continue
                path = os.path.join(dirpath, fn)
                m = bad.search(read(path))
                expect(not m, f"{os.path.relpath(path, ROOT)}: non-Forever source {m.group(0) if m else ''}")
    for doc in ("README.md", "SOURCES.md"):
        m = bad.search(read(os.path.join(ROOT, doc)))
        expect(not m, f"{doc}: non-Forever source {m.group(0) if m else ''}")


def check_gen_data():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tools", "gen_data.py"), "verify"],
                       capture_output=True, text=True, cwd=ROOT)
    expect(r.returncode == 0, "gen_data.py verify: " + (r.stdout + r.stderr).strip().replace("\n", " / "))


def check_data(ns):
    keys = source_keys()
    expect({"db2", "wh_list", "wh_tt", "wh_item", "ui", "in-game", "client", "tsm", "user"} <= keys,
           f"SOURCES.md sources table misses keys (has {sorted(keys)})")
    expect(ns.DATA_BUILD in read(os.path.join(ROOT, "SOURCES.md")), "SOURCES.md does not name the pinned DB2 build")
    date = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    counts = {}
    for table in ("SkillLines", "Recipes", "Items", "Vendor", "CooldownCategories"):
        t = ns[table]
        n = 0
        for k, e in t.items():
            n += 1
            src, ver = e.src, e.verified
            if not expect(isinstance(src, str) and src, f"Data {table}[{k}] has no src"):
                continue
            for part in src.split("+"):
                expect(part in keys, f"Data {table}[{k}] src {part!r} is not a SOURCES.md key")
            expect(isinstance(ver, str) and date.match(ver), f"Data {table}[{k}] has no verified date")
        counts[table] = n
        expect(n > 0, f"Data {table} is empty")
    items = ns.Items
    zero_count = 0
    for spell, r in ns.Recipes.items():
        ids = [r.out[1]] + [rg[1] for rg in r.reagents.values()] + list(r["items"].values())
        for i in ids:
            expect(items[i] is not None, f"Recipes[{spell}] uses item {i}, missing from Data/Items.lua")
        expect(ns.SkillLines[r.skill] is not None, f"Recipes[{spell}] skill line {r.skill} not in SkillLines")
        if r.out[2] == 0 and r.out[3] == 0:
            zero_count += 1  # DB2 and Wowhead give no count; Planner counts 1 and marks the result "~"
        else:
            expect(r.out[2] >= 1 and r.out[3] >= r.out[2], f"Recipes[{spell}] output count {r.out[2]}-{r.out[3]}")
    # Cooldowns (DB2 SpellCooldowns / SpellCategories): a shared category is named; Mooncloth and the transmutes wait.
    for spell, r in ns.Recipes.items():
        if r.cdCat is not None:
            expect(r.cd and r.cd > 0 and ns.CooldownCategories[r.cdCat] is not None,
                   f"Recipes[{spell}] cooldown category {r.cdCat} without a cd or a CooldownCategories entry")
    expect(ns.Recipes[18560].cd == 342000 and ns.Recipes[18560].cdCat is None
           and ns.Recipes[17187].cd == 169200 and ns.Recipes[17187].cdCat == 310
           and ns.Recipes[25146].cdCat == 310 and ns.Recipes[3170].cd is None,
           "cooldown data (Mooncloth 342000 s alone; Arcanite and Elemental Fire share category 310)")
    # 73 at build 1.60.1.70888 (e.g. Lesser Wizard Oil 25126; its tooltip also says "(0)"). A jump means a parse bug.
    expect(zero_count <= 80, f"{zero_count} recipes have output count 0")
    expect(ns.Recipes[2963].out[2] == 1, "Bolt of Linen Cloth should make 1")
    counts["zero output count"] = zero_count
    for i in ns.Vendor.keys():
        expect(items[i] is not None, f"Vendor[{i}] is not in Data/Items.lua")
    # Wowhead Forever pages, tooltips and list sourcemore (wh_item, wh_tt, wh_list).
    sides = {"Alliance", "Horde", "both", "hostile"}
    named = None
    for i, v in ns.Vendor.items():
        if v.npcs is None:
            continue
        npcs = list(v.npcs.values())
        expect("wh_item" in v.src.split("+") and npcs and v.nNpc >= len(npcs),
               f"Vendor[{i}] npcs need src wh_item and nNpc >= {len(npcs)}")
        for n in npcs:
            expect(isinstance(n[1], str) and n[1] and isinstance(n[2], str) and n[3] in sides,
                   f"Vendor[{i}] npc entry {list(n.values())}")
        if named is None and v.npcs[1][2] != "":
            named = i
    expect(named is not None, "no Data/Vendor.lua entry names an NPC and zone")
    if named is not None:
        txt = ns.Util.VendorNPC(named)
        expect(ns.Vendor[named].npcs[1][1] in txt and ns.Vendor[named].npcs[1][2] in txt,
               f"Util.VendorNPC({named}) = {txt!r}")
    roles = {"vendor", "drop", "npc", "quest", "object", "item", "zone"}
    n_from = 0
    for i, e in items.items():
        if e["from"] is not None:
            n_from += 1
            for f in e["from"].values():
                expect(f[1] in roles and (f[2] or f[3]), f"Items[{i}] from entry {list(f.values())}")
            expect(ns.Util.FromText(i), f"Util.FromText({i}) is empty")
        if e.missing and (e.sell is not None or e.q is not None):
            expect({"wh_item", "wh_tt", "client"} & set(e.src.split("+")),
                   f"Items[{i}] has values without an ItemSparse row but src {e.src}")
    expect(n_from > 500, f"only {n_from} recipe items carry Wowhead sourcemore")
    counts["recipe items with from"] = n_from
    for spell, r in ns.Recipes.items():
        if r.known is not None:
            expect("client" in r.src.split("+") and r.known <= r.verified,
                   f"Recipes[{spell}] known needs src client")
        if r.learnText is not None:
            expect("client" in r.src.split("+") and r.learnText, f"Recipes[{spell}] learnText needs src client")
    # wh_tt cross-check (nether.wowhead.com/forever/tooltip/spell/3170, 2026-11-11) = DB2 SpellReagents.
    r = ns.Recipes[3170]
    got = sorted((rg[1], rg[2]) for rg in r.reagents.values()) if r else None
    expect(got == [(2447, 1), (2449, 2), (3371, 1)], f"Recipes[3170] reagents {got} differ from Wowhead Forever")
    counts.update(check_sales_data(ns, keys, date))
    counts.update(check_shelves_data(ns, keys, date))
    counts.update(check_rep_data(ns, keys, date))
    counts.update(check_farms_data(ns, keys, date))
    return counts


def check_rep_data(ns, keys, date):
    """Data/Reputation.lua: src + verified on every entry; the unverified amounts (src "user") say verified=false."""
    expect(ns.Rep.build in read(os.path.join(ROOT, "SOURCES.md")), "SOURCES.md does not name the reputation DB2 build")
    for table in ("RepWrits", "RepCrates", "RepSealed", "RepItems"):
        for k, e in ns[table].items():
            src = e.src or ""
            expect(src and all(p in keys and p != "user" for p in src.split("+")), f"Data {table}[{k}] src {src!r}")
            expect(isinstance(e.verified, str) and date.match(e.verified), f"Data {table}[{k}] has no verified date")
    for k in ("factions", "currency"):
        expect(ns.Rep[k].src in keys and date.match(ns.Rep[k].verified or ""), f"ns.Rep.{k} needs src + verified")
    for k, e in ns.RepAmounts.items():
        if e.src == "user":
            expect(e.verified is False, f"RepAmounts.{k} is from the user: verified must be false")
        else:
            expect(e.src in keys and isinstance(e.verified, str) and date.match(e.verified),
                   f"RepAmounts.{k} needs src + verified")
    writs = list(ns.RepWrits.items())
    expect(len(writs) == 150 and min(k for k, _ in writs) == 264011 and max(k for k, _ in writs) == 264160,
           f"{len(writs)} writs, expected 264011-264160")
    expect(len({w.quest for _, w in writs}) == 150, "writ quest IDs are not unique")
    shot = ns.RepWrits[264037]
    expect(shot and shot.item == 8069 and shot.n == 200, "Crafted Solid Shot writ should want 200 of item 8069")
    # Names with two item IDs resolve to the classic (lower) one.
    items = {w.item for _, w in writs}
    expect({3385, 5634, 4383, 9366} <= items, "writ item names resolve to the wrong item IDs")
    named = [i for i in items | {b[1] for c in ns.RepCrates.values() for b in c.bundles.values()}
             if ns.Items[i] is None and ns.RepItems[i] is None]
    expect(not named, f"writ/crate items without names: {named[:5]}")
    crates = list(ns.RepCrates.values())
    expect(len(crates) == 30 and sum(c.q == 1 for c in crates) == 18, "expected 18 white and 12 green crates")
    return {"reputation writs": len(writs), "crates": len(crates)}


def check_sales_data(ns, keys, date):
    """Data/Sales.lua (gen_data.py tsm): fetched from TSM and changing daily, so it is checked for shape, ranges and
    src, and against the snapshot table in SOURCES.md, not rebuilt from research/."""
    d = ns.SalesData
    if not expect(d is not None, "Data/Sales.lua does not set ns.SalesData"):
        return {}
    expect(d.src in keys and d.src == "tsm", f"SalesData src {d.src!r}")
    expect(isinstance(d.verified, str) and date.match(d.verified), "SalesData has no verified date")
    outputs = {r.out[1] for r in ns.Recipes.values()}
    sources = read(os.path.join(ROOT, "SOURCES.md"))
    counts = {}
    for reg in ("us", "eu"):
        e = d.regions[reg]
        if not expect(e is not None, f"SalesData has no {reg} region"):
            continue
        expect(isinstance(e.updated, str) and re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", e.updated),
               f"SalesData {reg} updated {e.updated!r}")
        expect(isinstance(e.sha256, str) and re.match(r"^[0-9a-f]{64}$", e.sha256), f"SalesData {reg} sha256")
        expect(e.sha256 in sources and e.updated in sources, f"SOURCES.md TSM snapshot table does not name the {reg} file")
        n = 0
        for i, v in e["items"].items():
            n += 1
            ok = i in outputs and v[1] >= 0 and 0 <= v[2] <= 1
            if not expect(ok, f"SalesData {reg}[{i}] = {list(v.values())} (must be a recipe output, sold/day >= 0, "
                              f"rate 0-1)"):
                break
        expect(n > 500 and n <= e.rows, f"SalesData {reg} keeps {n} of {e.rows} rows")
        counts[f"TSM {reg} items"] = n
    return counts


# Runtime ---------------------------------------------------------------------------------------------------------

def new_runtime(remove=(), bad_events=(), saved=None):
    """A fresh fake client with the addon loaded and ADDON_LOADED fired (not logged in). remove: global API tables
    or functions to delete before loading (a client without them). bad_events: events RegisterEvent rejects.
    saved: SavedVariables text from an earlier session (STUB.savedVariables), loaded before ADDON_LOADED."""
    lua = lupa_mod.LuaRuntime(unpack_returned_tuples=True)
    lua.execute(read(os.path.join(ROOT, "tools", "wow_stub.lua")))
    stub = lua.globals().STUB
    meta, files = toc()
    stub.meta = lua.table_from(meta)
    for e in bad_events:
        stub.badEvents[e] = True
    for g in remove:
        lua.execute(f"{g} = nil")
    loader = lua.eval(
        """function(path, src, ns)
          local f, err = loadstring(src, "@" .. path)
          if not f then error(err, 0) end
          f("ForeverCrafter", ns)
        end""")
    ns = lua.table()
    for rel in files:
        try:
            loader(rel, read(os.path.join(ADDON, rel)), ns)
        except Exception as e:  # noqa: BLE001
            problem(f"load {rel}: {e}")
    if saved:
        lua.execute(saved)
    stub.fire("ADDON_LOADED", NAME)
    return lua, ns, stub


def login(lua, stub, skills=None, known=()):
    for line, rank in (skills or {}).items():
        stub.skills[line] = lua.table_from({"rank": rank, "max": 300})
    for s in known:
        stub.known[s] = True
    stub.fire("PLAYER_LOGIN")
    lua.globals().STUB.runTimers()


def slash(lua, text):
    lua.globals().SlashCmdList.FOREVERCRAFTER(text)
    lua.globals().STUB.runTimers()


def prints(stub, start=0):
    return [stub.prints[i] for i in range(start + 1, len(stub.prints) + 1)]


def results(ns):
    """Planner.Run returns every evaluated craft, losses included (the window shows profit >= 1c only)."""
    res, stats = ns.Planner.Run()
    return {r.spell: r for r in res.values()}, stats


def profitable(res, spell):
    return spell in res and res[spell].profit > 0


def ltable(lua, v):
    if isinstance(v, (list, tuple)):
        return lua.table_from([ltable(lua, x) for x in v])
    if isinstance(v, dict):
        return lua.table_from({k: ltable(lua, x) for k, x in v.items()})
    return v


def open_ts(lua, stub, line, rank, recipes, show_unlearned=False, casts=None):
    """recipes: {spell: (learned, difficulty, schematic or None[, GetRecipeSourceText])}; casts: {spell: castTime ms}
    for C_Spell.GetSpellInfo (else it returns nil)."""
    t = {"line": line, "rank": rank, "max": 300, "showUnlearned": show_unlearned, "recipes": {}}
    for spell, (learned, diff, schem, *source) in recipes.items():
        t["recipes"][spell] = {"learned": learned, "difficulty": diff, "schematic": schem,
                               "source": source[0] if source else None}
        if casts and spell in casts:
            t["recipes"][spell]["cast"] = casts[spell]
    stub.ts = ltable(lua, t)
    stub.fire("TRADE_SKILL_SHOW")
    stub.runTimers()


def set_auctions(lua, stub, listings):
    """listings: [(itemID, stack, buyout for the stack)]"""
    stub.auctions = ltable(lua, [list(x) for x in listings])


def scan(lua, stub):
    stub.fire("AUCTION_HOUSE_SHOW")
    slash(lua, "scan")
    stub.fire("REPLICATE_ITEM_LIST_UPDATE")
    stub.runTimers()


LINEN, BOLT, THREAD, VEST, SHIRT, DYE, BOOTS, ROBE = 2589, 2996, 2320, 2568, 2575, 2604, 2569, 2572
TAILORING = 197
R_BOLT, R_VEST, R_SHIRT, R_BOOTS, R_ROBE = 2963, 2385, 2392, 2386, 2389


def tailoring_world(lua, stub, rank=30):
    """A Tailoring character: Bolt + Vest learned; Shirt (25) and Boots (40) unlearned; Robe not listed."""
    login(lua, stub, skills={TAILORING: rank})
    set_auctions(lua, stub, [
        (LINEN, 20, 200), (LINEN, 5, 75),       # 20 @ 10c, 5 @ 15c
        (BOLT, 1, 200), (BOLT, 1, 220),
        (VEST, 1, 10000), (VEST, 1, 10500), (VEST, 1, 11000),
        (SHIRT, 1, 5000),
        (BOOTS, 1, 90000),
        (ROBE, 1, 90000),
        (999999, 1, 1),                          # an item no recipe uses: ignored
    ])
    stub.deposits[VEST] = 15
    open_ts(lua, stub, TAILORING, rank, {
        R_BOLT: (True, 0, None), R_VEST: (True, 1, None), R_SHIRT: (False, None, None), R_BOOTS: (False, None, None),
    })


def check_core_flow():
    lua, ns, stub = new_runtime()
    g = lua.globals()
    tailoring_world(lua, stub)
    expect(ns.Professions.Rank(TAILORING) == 30, "skill rank not read from C_SkillInfo")
    listed = ns.char.listed[TAILORING]
    expect(listed and listed.complete, "trade-skill listing not complete after the one-shot SetShowUnlearned")
    expect(stub.ts.showUnlearned is False, "SetShowUnlearned not restored to the player's setting")
    expect(ns.char.known[R_BOLT] and ns.char.known[R_VEST], "learned recipes not captured from the window")
    expect(ns.Professions.IsHidden(R_ROBE, TAILORING), "a recipe missing from the full window list is not hidden")
    expect(not ns.Professions.IsHidden(R_SHIRT, TAILORING), "an unlearned listed recipe is hidden")

    # Scan.
    n0 = len(stub.prints)
    slash(lua, "scan")
    expect(any("open the auction house" in p for p in prints(stub, n0)), "scan without the AH open does not refuse")
    scan(lua, stub)
    expect(stub.replicateCalls == 1, f"ReplicateItems called {stub.replicateCalls} times")
    linen = ns.Scanner.Price(LINEN)
    expect(linen and linen["min"] == 10 and linen.qty == 25 and linen.n == 2, "linen price summary wrong")
    expect(ns.Scanner.Price(999999) is None, "an item no recipe uses was stored")
    expect(ns.db.deposit[VEST] == 15, "deposit not captured after the scan")
    total, deep, _ = ns.Pricing.AHBuy(LINEN, 22)
    expect(total == 230 and not deep, f"AH ladder: 22 linen cost {total}, want 230")
    expect(ns.Pricing.AHBuy(LINEN, 26) is None, "AH ladder sells more than is listed")

    res, stats = results(ns)
    vest = res.get(R_VEST)
    if expect(vest, "Brown Linen Vest (known, AH 1g) not profitable"):
        # Bolt crafted from 2 linen (20c) beats the AH bolt (200c); thread from the vendor list (10c, estimate).
        expect(vest.cost1 == 30, f"vest first craft cost {vest.cost1}, want 30 (bolt crafted 20c + thread 10c)")
        # 25 linen (20 @ 10c, 5 @ 15c) make 12 bolts; then neither 13 bolts nor 26 linen are listed.
        expect(vest.batch == 12 and not vest.batchCapped and vest.cost == 32,
               f"vest batch {vest.batch} avg cost {vest.cost}, want 12 crafts at 32c ((260 + 120) / 12 rounded up)")
        expect(vest.value == 9999 * 95 // 100 - 15, f"vest value {vest.value}, want AH 1g-1c after 5% and deposit")
        expect(vest.where == "ah" and vest.est, "vest should sell on the AH with an estimated reagent")
        expect(ns.Planner.Steps(vest.tree) == 2, "vest chain is not bolt -> vest")
        expect(vest.color == "yellow", f"vest colour {vest.color}, want the window's difficulty (yellow)")
        shop = {(e.id, e.src): e.qty for e in ns.Planner.ShoppingList(vest.tree).values()}
        expect(shop == {(LINEN, "ah"): 2, (THREAD, "vendor"): 1}, f"vest shopping list {shop}")
    shirt = res.get(R_SHIRT)
    if expect(shirt, "Red Linen Shirt (unlearned, skill 30 >= 25) not offered"):
        expect(shirt.learnable and not shirt.known, "shirt should be learnable, not known")
        expect("Trainer" in shirt.acquire.text, f"shirt acquisition: {shirt.acquire.text}")
        expect(shirt.payback == 1, f"shirt payback {shirt.payback}")
    expect(R_BOOTS not in res, "Linen Boots (needs 40, skill 30) offered")
    expect(R_ROBE not in res, "Red Linen Robe (hidden by the window) offered")

    # Merchant: exact price replaces the estimate.
    stub.merchant = ltable(lua, {"npc": "Rachel", "items": [[THREAD, 12, 1], [DYE, 50, 1, 5]]})
    stub.fire("MERCHANT_SHOW")
    stub.runTimers()
    seen = ns.db.vendorSeen[THREAD]
    expect(seen and seen.unit == 12 and not seen.limited and seen.npc == "Rachel", "merchant price not captured")
    expect(ns.db.vendorSeen[DYE].limited, "limited merchant stock not flagged")
    vest = results(ns)[0].get(R_VEST)
    expect(vest and vest.cost1 == 32 and not vest.est, "merchant price did not replace the estimate")

    # Invoices and the cut.
    stub.invoices = ltable(lua, [["seller", 20000, 1000], ["seller", 40000, 2000], ["buyer", 100, 0]])
    stub.fire("MAIL_INBOX_UPDATE")
    cut, label = ns.Pricing.Cut()
    expect(cut == 0.05 and "2 sale" in label, f"cut from invoices {cut} ({label})")
    slash(lua, "cut 6")
    expect(ns.Pricing.Cut()[0] == 0.06, "/crafter cut 6 not applied")
    slash(lua, "cut")
    expect(ns.Pricing.Cut()[1].startswith("from"), "/crafter cut (blank) does not go back to the invoices")

    # Thin markets and the minimum listings.
    vest = results(ns)[0].get(R_VEST)
    expect(vest and not vest.sell.thin, "3 listings flagged thin")
    expect(results(ns)[0][R_SHIRT].sell.thin, "1 listing not flagged thin")
    ns.settings.minListings = 4
    vest = results(ns)[0].get(R_VEST)
    expect(not vest or vest.where == "vendor", "AH sale counted below the minimum listings")
    ns.settings.minListings = 1

    # Runtime schematic overrides the static reagents; NEW_RECIPE_LEARNED.
    stub.ts.recipes[R_SHIRT].learned = True
    stub.ts.recipes[R_SHIRT].schematic = ltable(lua, {"name": "Red Linen Shirt", "out": [SHIRT, 1, 1],
                                                      "reagents": [[BOLT, 1]]})
    stub.fire("TRADE_SKILL_LIST_UPDATE")
    stub.runTimers()
    shirt = results(ns)[0].get(R_SHIRT)
    expect(shirt and shirt.known and shirt.cost1 == 20 and shirt.runtime, "window schematic did not override reagents")
    stub.fire("NEW_RECIPE_LEARNED", R_ROBE)
    expect(ns.Professions.IsKnown(R_ROBE, TAILORING), "NEW_RECIPE_LEARNED not recorded")

    # Results window.
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    if expect(frame and frame.__shown, "/crafter does not open the window"):
        rows = [f for f in stub.frames.values() if f.result is not None]
        expect(rows, "the window lists no results")
        first = rows[0]
        first.Click(first)
        detail = frame.detail.__text
        expect("Shopping list" in detail and "Profit" in detail, "detail pane misses the chain/shopping list")
        expect(ns.UI.selected is not None, "clicking a row does not select it")
        before = ns.settings.sort
        frame.headers[2].Click(frame.headers[2])
        expect(ns.settings.sort == "name" and before == "profit", "header click does not sort by name")
        frame.prof.Click(frame.prof)
        expect(ns.settings.profession == TAILORING, "profession button does not cycle to Tailoring")
        frame.minProfit.SetText(frame.minProfit, "1")
        frame.minProfit.__scripts.OnEnterPressed(frame.minProfit)
        expect(ns.settings.minProfit == 10000, f"min profit 1 -> {ns.settings.minProfit}")
        expect(all(r.profit >= 10000 for r in ns.UI.view.values()), "min profit filter not applied")
        ns.settings.minProfit = 0
        slash(lua, "")
        expect(not frame.__shown, "/crafter does not toggle the window closed")

    # Minimap and status/help/reset.
    expect(g.ForeverCrafterMinimapButton is not None, "no minimap button")
    n0 = len(stub.prints)
    slash(lua, "status")
    out = " ".join(prints(stub, n0))
    expect("Tailoring 30/300" in out and "AH snapshot" in out and "AH cut" in out, f"/crafter status: {out}")
    expect(re.search(r"Tailoring 30/300 - window read .*: \d+ known, \d+ learnable", out),
           f"/crafter status does not count known/learnable recipes: {out}")
    slash(lua, "nonsense")
    expect(any("/crafter scan" in p for p in prints(stub, n0)), "unknown command does not print help")
    slash(lua, "reset")
    expect(ns.Scanner.Price(LINEN) is None and not ns.char.known[R_VEST], "/crafter reset left data behind")

    # AH closed during the read.
    stub.fire("AUCTION_HOUSE_SHOW")
    slash(lua, "scan")
    stub.fire("REPLICATE_ITEM_LIST_UPDATE")
    stub.fire("AUCTION_HOUSE_CLOSED")
    n0 = len(stub.prints)
    stub.runTimers()
    expect(any("cancelled" in p for p in prints(stub, n0)), "closing the AH does not cancel the read")
    expect(ns.Scanner.state == "idle", "scanner stuck after a cancelled read")
    return lua, ns


def synthetic(lua, ns, stub, recipes, items):
    """Adds made-up recipes/items (IDs 990000+) to test solver shapes the real data may not have."""
    for i in items:
        ns.Items[i] = ltable(lua, {"name": f"Test {i}", "q": 1, "sell": 0, "buy": 0, "src": "db2",
                                   "verified": "2026-11-12"})
    for spell, (out, reagents) in recipes.items():
        ns.Recipes[spell] = ltable(lua, {"name": f"Make {out}", "skill": TAILORING, "learn": 1, "trivLo": 1,
                                         "trivHi": 2, "out": [out, 1, 1], "reagents": reagents, "how": [6], "cost": 0,
                                         "items": [], "acquire": 0, "src": "db2", "verified": "2026-11-12"})
        stub.known[spell] = True


def check_solver_shapes():
    lua, ns, stub = new_runtime()
    login(lua, stub, skills={TAILORING: 300})
    A, B = 990001, 990002
    chain = [990100 + i for i in range(11)]          # C0 .. C10, each made from the previous one
    recipes = {991001: (A, [[B, 1]]), 991002: (B, [[A, 1]])}
    for i in range(1, 11):
        recipes[992000 + i] = (chain[i], [[chain[i - 1], 1]])
    synthetic(lua, ns, stub, recipes, [A, B] + chain)
    set_auctions(lua, stub, [(A, 1, 100), (B, 1, 500), (chain[0], 50, 50)] + [(c, 1, 1000000) for c in chain[1:]])
    scan(lua, stub)
    start = time.time()
    res, _ = results(ns)
    expect(time.time() - start < 5, "solver too slow on the cycle/depth scenario")
    b = res.get(991002)
    expect(b and b.cost == 100 and b.profit == 499 * 95 // 100 - 100, "cycle: B from AH-bought A is wrong")
    a = res.get(991001)
    expect(a and a.cost == 100 and not profitable(res, 991001),
           "cycle: A from B must price B from AH-bought A (100), never from A crafted from B")
    # Depth limit 8: C9 is reachable (8 nested crafts below the top one), C10 is not.
    expect(profitable(res, 992009) and res[992009].cost == 1, "depth: C9 chain from 1 C0 not found")
    expect(992010 in res and res[992010].cost == 1000000 and not profitable(res, 992010),
           "depth: C10 should buy C9 on the AH (a chain from C0 is beyond the depth limit)")
    if 992009 in res:
        expect(ns.Planner.Steps(res[992009].tree) == 9, "depth: C9 chain is not 9 crafts")


def check_sniper():
    """The reagent sniper: max prices per ticked craft, the merged watch list, the search loop and the buy steps."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub, skills={TAILORING: 300})
    expect(ns.settings.snipeFloor == 0.9, "Keep g/h must default to 90%")
    R1, R2, R3, R4, OV, OA, ON = 990601, 990602, 990603, 990604, 990611, 990612, 990613
    V, A, N = 991601, 991602, 991603
    synthetic(lua, ns, stub, {V: (OV, [[R1, 1], [R2, 2]]), A: (OA, [[R1, 1], [R3, 1]]), N: (ON, [[R4, 1]])},
              [R1, R2, R3, R4, OV, OA, ON])
    ns.Recipes[V].cast = 5000
    ns.Items[OV].sell = 300
    stub["items"][OV] = lua.table_from({"name": f"Test {OV}", "sell": 300})
    set_auctions(lua, stub, [(OA, 1, 1000), (ON, 1, 100),
                             (R1, 50, 500), (R1, 100, 100000), (R2, 100, 2000), (R2, 100, 200000),
                             (R3, 50, 1500), (R3, 100, 150000), (R4, 10, 900)])
    scan(lua, stub)
    res, _ = results(ns)
    S = ns.Sniper
    v, a, n = res.get(V), res.get(A), res.get(N)
    if not expect(v and a and n, "sniper test recipes not evaluated"):
        return
    # Vendor shuffle: W 300, C 50 (10c + 2 x 20c), room 10% of 250 = 25 spread over 50c of AH reagents: +50%.
    expect(S.Kind(v) == "vendor" and S.Kind(a) == "ah", "sale kind of a row")
    lv = S.RowLimit(v, "vendor")
    expect((lv.W, lv.Wc, lv.C, lv.batch, lv.room, lv.markup) == (300, 300, 50, 50, 25, 0.5)
           and (lv.reagents[R1].qty, lv.reagents[R1].max, lv.reagents[R2].qty, lv.reagents[R2].max) == (50, 15, 100, 30),
           f"vendor row limits {(lv.W, lv.Wc, lv.C, lv.batch, lv.room, lv.markup)}")
    expect(abs(lv.floorGh - 0.9 * 250 / 5 * 3600) < 1e-6, f"vendor row floor g/h {lv.floorGh}")
    # AH sale: measured after a 10% price drop.
    la = S.RowLimit(a, "ah")
    W = int(a.sell.ah * a.n)
    Wc = int(0.9 * W)
    room = 0.1 * (Wc - 40)
    mk = room / 40
    expect((la.W, la.Wc, la.C, la.batch) == (W, Wc, 40, 50) and abs(la.room - room) < 1e-9
           and la.reagents[R1].max == int(10 * (1 + mk)) and la.reagents[R3].max == int(30 * (1 + mk))
           and la.floorGh is None, f"AH row limits {(la.W, la.Wc, la.C, la.batch, la.room)}")
    # Any mix of buys at the max prices keeps the floor.
    for lim, worth in ((lv, 300), (la, Wc)):
        spend = sum(gg.qty * gg.max for gg in lim.reagents.values()) / lim.batch
        expect(worth - (lim.C - lim.ahCost + spend) >= lim.floor * (worth - lim.C) - 1e-9,
               f"buying at the max breaks the floor of {lim.name}")
    print(f"sniper example: vendor row W {lv.W}, C {lv.C}, room {lv.room:g}, markup {lv.markup:.0%}, "
          f"R1 10->{lv.reagents[R1].max}c, R2 20->{lv.reagents[R2].max}c; AH row W {W}, Wc {Wc}, C 40, "
          f"room {la.room:g}, markup {mk:.1%}, R1 10->{la.reagents[R1].max}c, R3 30->{la.reagents[R3].max}c")
    # 4c profit, 84 - 90 after a 10% drop: no room.
    ln = S.RowLimit(n, "ah")
    expect(ln.noRoom and not any(True for _ in ln.reagents.values() if _.max), "no-room row")

    # Ticking (the window) and the merged watch list.
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    UI = ns.UI
    ns.settings.minSoldPerDay = 0
    ns.settings.minBatch = 1
    UI.Recompute()
    UI.Refresh()
    heads = [h.col.key for h in frame.headers.values() if h.col]
    expect(heads[0] == "snipe", f"craft columns {heads}")
    rows = {f.result.spell: f for f in stub.frames.values() if f.cells is not None and f.result is not None}
    if not expect(V in rows and A in rows and N in rows, f"sniper rows not listed: {list(rows)}"):
        return
    for spell in (V, A, N):
        cb = rows[spell].snipe
        expect(cb.__shown, "snipe checkbox hidden")
        cb.Click(cb)
    expect(S.IsTicked(V) and S.IsTicked(A) and S.IsTicked(N), "checkbox does not tick")
    UI.Refresh()
    rows = {f.result.spell: f for f in stub.frames.values() if f.cells is not None and f.result is not None}
    expect(rows[V].snipe.__checked and "no room" in UI.CellText(n, "name")
           and "no room" not in UI.CellText(v, "name"), "no room marker / checked state")
    by = {r.spell: r for r in UI.results.values()}
    expect("Sniping for this craft|r (vendor sale, keep 90% g/h" in UI.DetailText(by[V])
           and f"max {ns.Util.Money(15)}" in UI.DetailText(by[V]), "craft detail has no snipe lines")
    w = {e.id: e for e in S.Watch().values()}
    expect(set(w) == {R1, R2, R3}, f"watched reagents {set(w)}")
    r1 = w.get(R1)
    expect(r1 and [x.spell for x in r1.rows.values()] == [A, V] and r1.max == la.reagents[R1].max
           and r1.need == 100, "merged reagent: rows highest max first, need of both")
    stub.bags[R1] = 20
    r1 = {e.id: e for e in S.Watch().values()}[R1]
    expect((r1.need, S.NeedAt(r1, 20)) == (80, 50), f"owned fill the lowest max first: {r1.need}, {S.NeedAt(r1, 20)}")
    stub.bags[R1] = 0

    # The Sniper tab and the search loop.
    slash(lua, "snipe")
    expect(ns.settings.tab == "snipe" and [h.col.key for h in frame.headers.values() if h.col][0] == "name"
           and frame.sn.start.__shown and not frame.minProfit.__shown, "Sniper tab not shown")
    expect(len(UI.view) == 3 and "3 reagents for 3 crafts" in frame.status.__text
           and "1 with no room" in frame.status.__text, f"sniper status {frame.status.__text!r}")
    n0 = len(stub.searches)
    stub.throttled = True
    frame.sn.start.Click(frame.sn.start)
    expect(S.running and len(stub.searches) == n0, "searched while the AH was throttled")
    stub.throttled = False
    stub.runTimers(1)
    expect(len(stub.searches) == n0 + 1, "the loop sent no search")
    first = stub.searches[len(stub.searches)].key.itemID
    stub.runTimers(1)
    expect(len(stub.searches) == n0 + 1, "a second search while the first has no answer")
    # Commodity results: 12c and 25c fit (the 25c ones only for A), 40c is over every max.
    stub.commodity[R1] = ltable(lua, [[12, 30], [25, 40], [40, 100], [5, 7, 7]])
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R1)
    stub.runTimers(0.2)
    r1 = {e.id: e for e in S.Watch().values()}[R1]
    d = r1.deal
    expect(d and (d.qty, d.total, d.budget) == (70, 30 * 12 + 40 * 25, 30 * r1.rows[2].max + 40 * r1.rows[1].max),
           f"commodity deal {d and (d.qty, d.total, d.budget)}")
    expect(S.seen[R1].listings[1].unit == 12, "own listings must be left out")
    label, target = S.BuyTarget(None)
    expect(target is not None and label.startswith("Buy "), f"Buy button {label}")
    # Buy: the quote is checked; a rise over the budget cancels.
    stub.purchases = lua.table()
    S.Buy(r1)
    expect(stub.purchases[1][1] == "Start" and stub.purchases[1][2] == R1 and stub.purchases[1][3] == 70,
           "StartCommoditiesPurchase not called")
    stub.fire("COMMODITY_PRICE_UPDATED", 30, d.budget + 1)
    expect(stub.purchases[2][1] == "Cancel" and S.pending is None, "a dearer quote was not cancelled")
    S.Buy(r1)
    stub.fire("COMMODITY_PRICE_UPDATED", 20, d.total)
    expect(stub.purchases[4][1] == "Confirm" and stub.purchases[4][3] == 70, "an OK quote was not confirmed")
    stub.fire("COMMODITY_PURCHASE_SUCCEEDED")
    r1 = {e.id: e for e in S.Watch().values()}[R1]
    expect(S.pending is None and (r1.owned, r1.mail, r1.need) == (70, 70, 30), f"bought: {r1.owned} {r1.mail}")
    stub.bags[R1] = 50                           # 50 of them arrived from the mail
    r1 = {e.id: e for e in S.Watch().values()}[R1]
    expect((r1.owned, r1.bags, r1.mail) == (70, 50, 20), f"mail arrival {(r1.owned, r1.bags, r1.mail)}")
    # A blocked Confirm (from the event): the button becomes Confirm, a click confirms.
    stub.commodity[R2] = ltable(lua, [[20, 10]])
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    r2 = {e.id: e for e in S.Watch().values()}[R2]
    S.Buy(r2)
    stub.fire("COMMODITY_PRICE_UPDATED", 20, 200)
    stub.fire("ADDON_ACTION_BLOCKED", "ForeverCrafter", "C_AuctionHouse.ConfirmCommoditiesPurchase()")
    expect(S.pending and S.pending.stage == "click" and S.BuyTarget(None).startswith("Confirm 10"), "blocked confirm")
    k = len(stub.purchases)
    frame.sn.buy.Click(frame.sn.buy)
    expect(stub.purchases[k + 1][1] == "Confirm", "the Confirm click does not confirm")
    stub.fire("COMMODITY_PURCHASE_SUCCEEDED")
    expect(S.pending is None and ns.char.snipe.bought[R2].n == 10, "purchase after the click")
    expect(not S.seen[R2].listings[1], "a purchase must take the bought listings off the last search")
    # A new quote after the confirm (the price changed) is not confirmed by itself; unconfirmed, it is cancelled.
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    r2 = {e.id: e for e in S.Watch().values()}[R2]
    S.Buy(r2)
    stub.fire("COMMODITY_PRICE_UPDATED", 20, 200)
    k = len(stub.purchases)
    stub.fire("COMMODITY_PRICE_UPDATED", 21, 210)
    expect(S.pending and S.pending.stage == "click" and len(stub.purchases) == k, "a new quote must wait for a click")
    stub.runTimers(S.CLICK_WAIT + 1)
    expect(S.pending is None and stub.purchases[len(stub.purchases)][1] == "Cancel", "an unconfirmed quote stays open")
    # A confirm the AH does not answer in time is not cancelled, and a late success still counts.
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    S.Buy({e.id: e for e in S.Watch().values()}[R2])
    stub.fire("COMMODITY_PRICE_UPDATED", 20, 200)
    k = len(stub.purchases)
    stub.runTimers(S.TIMEOUT + 1)
    expect(S.pending is None and S.late and len(stub.purchases) == k, "a slow confirm was cancelled")
    stub.fire("COMMODITY_PURCHASE_SUCCEEDED")
    expect(S.late is None and ns.char.snipe.bought[R2].n == 20, "a late purchase is not counted")
    # The budget: each unit at the max of the row it fills (owned items fill the lowest max first).
    d = lua.execute("""
      local S = ...
      S.seen[990699] = { commodity = true, listings = { { unit = 40, qty = 20 } } }
      local w = { id = 990699, max = 100, owned = 10,
        rows = { { spell = 1, max = 100, qty = 10 }, { spell = 2, max = 50, qty = 10 } } }
      w.need = S.NeedAt(w, 0)
      local d = S.Deal(w)
      S.seen[990699] = nil
      return d
    """, S)
    expect(d and (d.qty, d.total, d.budget) == (10, 400, 1000), f"budget per row {d and (d.qty, d.budget)}")
    # Item auctions: bought whole with PlaceBid.
    key = ltable(lua, {"itemID": R3, "itemLevel": 0, "itemSuffix": 0, "battlePetSpeciesID": 0})
    stub.itemResults[R3] = ltable(lua, [[501, 100 * 60, 100], [502, 40 * 20, 20], [503, 1, 1, True]])
    stub.fire("ITEM_SEARCH_RESULTS_UPDATED", key)
    r3 = {e.id: e for e in S.Watch().values()}[R3]
    expect(r3.deal and (r3.deal.qty, r3.deal.total, r3.deal.auctionID) == (20, 800, 502), "item auction deal")
    S.Buy(r3)
    expect(stub.purchases[len(stub.purchases)][1] == "PlaceBid" and stub.purchases[len(stub.purchases)][2] == 502,
           "PlaceBid not called")
    stub.fire("AUCTION_HOUSE_PURCHASE_COMPLETED", 502)
    expect(S.pending is None and ns.char.snipe.bought[R3].n == 20, "item auction purchase")
    # Keep g/h box: 80% doubles the room.
    frame.sn.floor.SetText(frame.sn.floor, "80")
    frame.sn.floor.__scripts.OnEnterPressed(frame.sn.floor)
    expect(ns.settings.snipeFloor == 0.8 and abs(S.Limit(V).room - 50) < 1e-9
           and S.Limit(V).reagents[R1].max == 20, f"Keep g/h 80: room {S.Limit(V).room}")
    # Closing the AH stops the loop and cancels a quote.
    stub.fire("AUCTION_HOUSE_CLOSED")
    expect(not S.running and "closed" in (S.stopReason or ""), "AH close does not stop the sniper")
    UI.Refresh()
    expect(UI.SortValue(UI.view[1], ns.settings.snipeSort) is not None and first in (R1, R2, R3),
           "sniper tab sort")

    # Saved: the floor, the ticked rows and what was bought.
    saved = stub.savedVariables("ForeverCrafterDB")
    lua2, ns2, stub2 = new_runtime(saved=saved)
    login(lua2, stub2, skills={TAILORING: 300})
    expect(ns2.settings.snipeFloor == 0.8 and ns2.Sniper.IsTicked(V) and ns2.char.snipe.bought[R3].n == 20,
           "sniper state not restored")
    slash(lua2, "snipe clear")
    slash(lua2, "snipe forget")
    expect(not ns2.Sniper.IsTicked(V) and not any(True for _ in ns2.char.snipe.bought), "snipe clear/forget")
    errs = list(ns.errors.values())
    expect(not [e for e in errs if "blocked" not in e], f"errors in the sniper checks: {errs[:3]}")

    # A client without the AH search API: Start says so.
    lua3, ns3, stub3 = new_runtime(remove=("C_AuctionHouse.SendSearchQuery",))
    login(lua3, stub3, skills={TAILORING: 300})
    stub3.fire("AUCTION_HOUSE_SHOW")
    ns3.char.snipe.rows[V] = ltable(lua3, {"name": "x", "kind": "ah", "reagents": {R1: {"qty": 1, "max": 5}}})
    n0 = len(stub3.prints)
    slash(lua3, "snipe start")
    expect(not ns3.Sniper.running and any("no AH search API" in p for p in prints(stub3, n0))
           and any("SendSearchQuery missing" in e for e in ns3.errors.values()), "missing search API")


MOONCLOTH, ARCANITE, ELEM_FIRE, ALCHEMY = 18560, 17187, 25146, 171
FELCLOTH, MOONCLOTH_ITEM, THORIUM_BAR, ARCANE_CRYSTAL, ARCANITE_BAR = 14256, 14342, 12359, 12363, 12360


def check_cooldowns():
    """Cooldown recipes: one craft per cooldown, never a chain step; the ready times per character, kept across a
    relog; the Cooldowns tab and the login line."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub, skills={TAILORING: 300, ALCHEMY: 300}, known=(MOONCLOTH, ARCANITE, ELEM_FIRE))
    # A made-up craft that uses Mooncloth: it must buy it, never make it (one per cooldown is not a chain step).
    X, OX = 991901, 990901
    synthetic(lua, ns, stub, {X: (OX, [[MOONCLOTH_ITEM, 1]])}, [OX])
    set_auctions(lua, stub, [(FELCLOTH, 100, 100 * 500), (MOONCLOTH_ITEM, 5, 5 * 40000), (OX, 1, 90000),
                             (THORIUM_BAR, 100, 100 * 3000), (ARCANE_CRYSTAL, 50, 50 * 60000),
                             (ARCANITE_BAR, 10, 10 * 200000)])
    scan(lua, stub)
    res, _ = results(ns)
    m, x = res.get(MOONCLOTH), res.get(X)
    if not expect(m and x, "cooldown test recipes not evaluated"):
        return
    expect(m.cd == 342000 and m.batch == 1 and m.ahPerHour is None and m.vendorPerHour is None
           and m.fastAH is None and m.fastVendor is None and m.profit > 0,
           f"Mooncloth: batch {m.batch}, g/h {m.ahPerHour}/{m.vendorPerHour}, profit {m.profit}")
    kid = x.tree.children[1]
    expect(kid.src == "ah" and kid.id == MOONCLOTH_ITEM, f"Mooncloth used as a chain step ({kid.src})")
    cell = ns.UI.CellText
    expect("[cd]" in cell(m, "name") and "cd" in cell(m, "ahgh") and "cd" in cell(m, "vgh"),
           f"craft list cooldown cells {cell(m, 'name')!r} {cell(m, 'ahgh')!r}")
    S = ns.Sniper
    S.Toggle(m)
    expect(not S.SetTarget(MOONCLOTH, 3) and S.SetTarget(MOONCLOTH, 1) and S.Target(MOONCLOTH) is None,
           "a cooldown recipe's sniper target must stay 1")
    expect(S.Limit(MOONCLOTH).cd == 342000 and S.CraftCellText(S.Limit(MOONCLOTH), "floorgh").find("per cooldown"),
           "sniper floor of a cooldown craft")
    S.Toggle(m)

    # Read at the profession window: Mooncloth waits an hour; the other window was not opened.
    t0 = g.time()
    stub.cooldowns[MOONCLOTH] = t0 + 3600
    open_ts(lua, stub, TAILORING, 300, {MOONCLOTH: (True, 0, None)})
    cds = ns.char.cooldowns
    expect(cds[MOONCLOTH] == t0 + 3600, f"Mooncloth ready time {cds[MOONCLOTH]} (expected {t0 + 3600})")
    C = ns.Cooldowns

    def rows():
        return {(o.char, o.recipe): o for o in C.Rows()[0].values()}
    me = ns.CharKey()
    r = rows()
    expect(r[(me, MOONCLOTH)].state == "wait" and r[(me, ARCANITE)].state == "unread"
           and "open the profession window" in C.CellText(r[(me, ARCANITE)], "cready"),
           f"states {r[(me, MOONCLOTH)].state} {r[(me, ARCANITE)].state}")
    stub.now = stub.now + 3700
    expect(rows()[(me, MOONCLOTH)].state == "ready", "Mooncloth not ready after its cooldown expired")
    # Ready means the API says nil: a read after it expired stores 0.
    open_ts(lua, stub, TAILORING, 300, {MOONCLOTH: (True, 0, None)})
    expect(cds[MOONCLOTH] == 0, f"an expired cooldown reads as {cds[MOONCLOTH]}")

    # A craft starts the cooldown: Elemental Fire makes every transmute (category 310) wait, Mooncloth not.
    t1 = g.time()
    stub.fire("UNIT_SPELLCAST_SUCCEEDED", "player", "Cast-1", ELEM_FIRE)
    expect(cds[ARCANITE] == t1 + 600 and cds[ELEM_FIRE] == t1 + 600 and cds[17559] == t1 + 600 and cds[MOONCLOTH] == 0,
           f"shared category after Elemental Fire: {cds[ARCANITE]} {cds[MOONCLOTH]} (t {t1})")
    stub.fire("UNIT_SPELLCAST_SUCCEEDED", "player", "Cast-2", ARCANITE)
    stub.fire("UNIT_SPELLCAST_SUCCEEDED", "target", "Cast-3", MOONCLOTH)
    expect(cds[ELEM_FIRE] == t1 + 169200 and cds[MOONCLOTH] == 0, "Arcanite must make the whole category wait")
    n, _ = C.Ready(C.Rows()[0])
    expect(n == 1, f"{n} cooldowns ready (Mooncloth only; the transmutes wait)")

    # Alts: one below Mooncloth's skill, one that could learn it now; neither has Alchemy.
    ns.db.chars["Alt-Test"] = ltable(lua, {"skills": {TAILORING: {"rank": 180, "max": 300}}, "known": {},
                                           "listed": {}, "cooldowns": {}})
    ns.db.chars["Ivy-Other"] = ltable(lua, {"skills": {TAILORING: {"rank": 250, "max": 300}}, "known": {},
                                            "listed": {TAILORING: {"time": 1}}, "cooldowns": {}})
    r = rows()
    alt, ivy = r.get(("Alt-Test", MOONCLOTH)), r.get(("Ivy-Other", MOONCLOTH))
    expect(alt and alt.state == "skill" and alt.charName == "Alt"
           and "learn at Tailoring 230|r (you 180)" in C.CellText(alt, "cready") and "[L]" in C.CellText(alt, "crecipe")
           and ("Alt-Test", ARCANITE) not in r, f"alt row {alt and alt.state} {alt and C.CellText(alt, 'cready')!r}")
    expect(ivy and ivy.state == "learn" and ivy.charName == "Ivy-Other" and "learn now" in C.CellText(ivy, "cready")
           and "Learn: Tailoring 230" in C.DetailText(ivy), f"learnable alt row {ivy and ivy.state}")
    order = sorted(r.values(), key=lambda o: C.SortValue(o, "cready"))
    expect(order[0].state == "ready" and order[-1].state == "skill", "Ready sort: ready first, skill gaps last")

    # The Cooldowns tab.
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    slash(lua, "cd")
    UI = ns.UI
    expect(ns.settings.tab == "cd" and len(UI.view) == len(r) and frame.cdTab.GetText(frame.cdTab) == "Crafts"
           and "Cooldowns: 1 ready" in UI.StatusText(), f"Cooldowns tab: {ns.settings.tab} {len(UI.view)} rows")
    first = UI.view[1]
    expect(first.state == "ready" and first.recipe == MOONCLOTH and "Ready" in UI.CellText(first, "cready")
           and "Reagents (one craft)" in UI.DetailText(first) and "Felcloth" in UI.DetailText(first),
           f"first Cooldowns row {first.recipe} {first.state}")
    spans = []
    for tab in (frame.cdTab, frame.snipeTab, frame.repTab):
        p = tab.__points
        expect(p[1] == "TOPRIGHT", "tabs are placed from the top right")
        spans.append((p[2] - tab.__w, p[2]))
    spans.sort()
    expect(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), f"tab buttons overlap: {spans}")
    frame.cdTab.Click(frame.cdTab)
    expect(ns.settings.tab != "cd" and frame.cdTab.GetText(frame.cdTab) == "Cooldowns", "Cooldowns tab back to crafts")

    # Kept across a relog; the login line names the best one ready.
    saved = stub.savedVariables("ForeverCrafterDB")
    lua2, ns2, stub2 = new_runtime(saved=saved)
    stub2.now = stub.now
    start = len(stub2.prints)
    login(lua2, stub2, skills={TAILORING: 300, ALCHEMY: 300}, known=(MOONCLOTH, ARCANITE, ELEM_FIRE))
    expect(ns2.char.cooldowns[ARCANITE] == t1 + 169200, "the ready times did not survive a relog")
    line = [p for p in prints(stub2, start) if "cooldown" in p]
    expect(len(line) == 1 and "1 cooldown ready (best: Mooncloth" in line[0] and "on Hana" in line[0]
           and line[0].endswith("/crafter cd"), f"login line {line}")
    slash(lua2, "cd login")
    expect(ns2.settings.cdLogin is False, "/crafter cd login must turn the login line off")
    lua3, ns3, stub3 = new_runtime(saved=stub2.savedVariables("ForeverCrafterDB"))
    stub3.now = stub.now
    login(lua3, stub3, skills={TAILORING: 300})
    expect(not [p for p in prints(stub3) if "cooldowns ready" in p or "cooldown ready" in p],
           "login line printed while turned off")
    errs = list(ns.errors.values()) + list(ns2.errors.values()) + list(ns3.errors.values())
    expect(not errs, f"errors in the cooldown checks: {errs[:3]}")


TSM_MONEY_STUB = """
  TSM_STUB = { live = {}, money = {} }
  TSM_API = { GetCustomPriceValue = function(key, s)
    local id = tonumber(s:match("^i:(%d+)$"))
    local m = TSM_STUB.money[id]
    if m and m[key] then return m[key] end
    local e = TSM_STUB.live[id]
    if not e then return nil end
    if key == "DBRegionSoldPerDay" then return e[1] end
    if key == "DBRegionSaleRate" then return e[2] end
  end }
"""


def tsm_money(lua, ns, items):
    """A TSM_API stub: the region snapshot's sold/day and sale rate unscaled (so the scale is 1), plus items =
    {id: {key: value}} for any price source (DBMarket, DBRegionSaleAvg, DBRegionSoldPerDay, DBRegionSaleRate)."""
    lua.execute(TSM_MONEY_STUB)
    tsm = lua.globals().TSM_STUB
    for i, v in ns.SalesData.regions.eu["items"].items():
        tsm.live[i] = lua.table_from([v[1], v[2]])
    for i, m in items.items():
        tsm.money[i] = lua.table_from(m)
    ns.Sales.Reset()
    return tsm


def check_shelves_data(ns, keys, date):
    """Data/Shelves.lua (gen_data.py tsm): the empty-shelf candidate IDs from the same TSM download as Data/Sales.lua."""
    d = ns.ShelfCandidates
    if not expect(d is not None, "Data/Shelves.lua does not set ns.ShelfCandidates"):
        return {}
    expect(d.src in keys and d.src == "tsm", f"ShelfCandidates src {d.src!r}")
    expect(isinstance(d.verified, str) and date.match(d.verified), "ShelfCandidates has no verified date")
    expect(d.minSold > 0 and 0 < d.minRate < 1 and d.minAvg > 0, "ShelfCandidates thresholds")
    sources = read(os.path.join(ROOT, "SOURCES.md"))
    counts = {}
    for reg in ("us", "eu"):
        e, sales = d.regions[reg], ns.SalesData.regions[reg]
        if not expect(e is not None and sales is not None, f"ShelfCandidates has no {reg} region"):
            continue
        expect(e.sha256 == sales.sha256 and e.updated == sales.updated,
               f"ShelfCandidates {reg} is not from the same TSM download as SalesData")
        ids = list(e["items"].values())
        expect(ids == sorted(set(ids)) and all(isinstance(i, int) and i > 0 for i in ids),
               f"ShelfCandidates {reg} IDs must be sorted, unique item IDs")
        expect(100 < len(ids) <= sales.rows, f"ShelfCandidates {reg} keeps {len(ids)} of {sales.rows} rows")
        row = re.search(r"^\| " + reg.upper() + r" \|.*\| (\d+) \|$", sources, re.M)
        expect(row and int(row.group(1)) == len(ids), f"SOURCES.md shelf candidates for {reg} != {len(ids)}")
        counts[f"shelf {reg} candidates"] = len(ids)
    return counts


def check_shelves():
    """Empty shelves: candidates, the score and supply math, the filters, the price suggestion and the tab."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub)
    S, UI = ns.Shelves, ns.UI
    E0, E1, BOP, QUEST, GEAR, MANY, CHEAP, VEND, LOAD, NOVAL = range(995001, 995011)
    items = {E0: {}, E1: {}, BOP: {"bind": 1}, QUEST: {"class": 12}, GEAR: {"class": 4, "bind": 2}, MANY: {},
             CHEAP: {}, VEND: {"sell": 5000}, NOVAL: {}}
    for i, d in items.items():
        stub["items"][i] = lua.table_from({"name": f"Shelf {i}", "sell": d.get("sell", 10), "class": d.get("class", 7),
                                           "bind": d.get("bind", 0)})
    ns.ShelfCandidates = ltable(lua, {"src": "tsm", "verified": "2026-11-20",
                                      "regions": {"eu": {"items": [E0, BOP, QUEST, GEAR, CHEAP, VEND, LOAD, NOVAL]}}})
    # No TSM, no snapshot: the status says what is missing.
    slash(lua, "shelves")
    expect(ns.settings.tab == "shelves" and len(UI.view) == 0 and "needs TradeSkillMaster" in UI.StatusText(),
           f"no TSM: {UI.StatusText()!r}")
    sales = {"DBRegionSoldPerDay": 60, "DBRegionSaleRate": 0.5}
    tsm_money(lua, ns, {E0: dict(sales, DBMarket=30000, DBRegionSaleAvg=28000),
                        E1: {"DBRegionSaleAvg": 25000, "DBRegionSoldPerDay": 30, "DBRegionSaleRate": 0.6},
                        BOP: dict(sales, DBMarket=40000), QUEST: dict(sales, DBMarket=40000),
                        GEAR: dict(sales, DBMarket=90000), MANY: dict(sales, DBMarket=40000),
                        CHEAP: dict(sales, DBMarket=1000), VEND: dict(sales, DBMarket=2000),
                        LOAD: dict(sales, DBMarket=20000), NOVAL: {"DBMarket": 50000}})
    UI.Recompute()
    expect("Scan" in UI.StatusText() and len(UI.view) == 0, f"no snapshot: {UI.StatusText()!r}")
    # E1 is listed 3 (a candidate from the snapshot only), MANY 8 (over Max listed 5).
    set_auctions(lua, stub, [(E1, 3, 3 * 20000), (MANY, 8, 8 * 1000), (LINEN, 20, 20 * 50)])
    scan(lua, stub)
    snap = ns.db.realms[ns.RealmKey()]
    expect(snap.others[E1][1] == 20000 and snap.others[E1][2] == 3 and snap.total == 3,
           f"snapshot others/total: {snap.others[E1] and list(snap.others[E1].values())} {snap.total}")
    expect(ns.Scanner.Listed(E0) == (None, 0, True) and ns.Scanner.Listed(E1)[:2] == (20000, 3),
           f"Scanner.Listed {ns.Scanner.Listed(E0)} {ns.Scanner.Listed(E1)}")
    ns.settings.shelfMinValue = 1500
    rows, info = S.Rows()
    by = {r.id: r for r in rows.values()}
    expect(set(by) == {E0, E1, VEND, LOAD}, f"shelf rows {sorted(by)} (want E0, E1, VEND, LOAD)")
    expect(info.bound == 2 and info.gear == 1 and info.noValue == 1 and info.loading == 1,
           f"hidden: bound {info.bound} gear {info.gear} noValue {info.noValue} loading {info.loading}")
    a, b = by.get(E0), by.get(E1)
    if a and b:
        # 1/15 of 60/day = 4 a day, nothing listed: score = 30000 x 4 x 0.5 / 1.
        expect(abs(a.expected - 4) < 1e-9 and a.supply == 0 and abs(a.score - 60000) < 1e-6 and a.valueSrc == "realm"
               and a.price == 30000 and a.stack == 8, f"E0 {a.expected} {a.supply} {a.score} {a.price} {a.stack}")
        # No realm value: the region average. 2 a day, 3 listed = 1.5 days: 25000 x 2 x 0.6 / 2.5.
        expect(abs(b.expected - 2) < 1e-9 and abs(b.supply - 1.5) < 1e-9 and abs(b.score - 12000) < 1e-6
               and b.valueSrc == "region" and b.min == 20000 and b.stack == 4,
               f"E1 {b.expected} {b.supply} {b.score} {b.valueSrc}")
    v = by.get(VEND)
    expect(v and v.price == 5000 and "vendor sell price" in S.DetailText(v), "the suggestion is never below vendor")
    expect(by.get(LOAD) and by[LOAD].loading and "loading" in S.CellText(by[LOAD], "sname"), "loading row")
    expect(S.Suggest(100, 0, 0.2) == (100, 1) and S.Suggest(None, 300, 3.5) == (300, 7), "Suggest stack/floor")
    e, sup, sc = S.Score(10000, ltable(lua, {"perDay": 0, "rate": 0.5}), 2, 1 / 15)
    expect(e == 0 and sup == float("inf") and sc == 0, "no sales: infinite supply, score 0")
    # The toggles: gear on, more realms, max listed 8.
    ns.settings.shelfGear, ns.settings.shelfRealms, ns.settings.shelfMaxListed = True, 30, 8
    by = {r.id: r for r in S.Rows()[0].values()}
    expect(GEAR in by and "[G]" in S.CellText(by[GEAR], "sname") and MANY in by and abs(by[E0].expected - 2) < 1e-9,
           f"gear/realms/max listed toggles: {sorted(by)}")
    ns.settings.shelfGear, ns.settings.shelfRealms, ns.settings.shelfMaxListed = False, 15, 5
    # The tab.
    UI.Recompute()
    UI.Refresh()
    first = UI.view[1]
    expect(first and first.id == E0 and UI.CellText(first, "slisted").find("0") >= 0
           and "/d" in UI.CellText(first, "sscore") and "Suggested: list 8" in UI.DetailText(first)
           and "overstate" in UI.DetailText(first) and "Empty shelves: 4 items" in UI.StatusText(),
           f"Shelves tab: first {first and first.id}, status {UI.StatusText()!r}")
    widths = sum(c.width for c in S.COLUMNS.values())
    expect(widths <= 796, f"Empty shelves columns are {widths} px wide (796 max)")
    frame = g.ForeverCrafterFrame
    expect(frame.shelfTab.GetText(frame.shelfTab) == "Crafts" and frame.sh.max.IsShown(frame.sh.max)
           and not frame.minProfit.IsShown(frame.minProfit), "Shelves tab controls")
    frame.sh.max.SetText(frame.sh.max, "0")
    frame.sh.max.__scripts.OnEnterPressed(frame.sh.max)
    expect(ns.settings.shelfMaxListed == 0 and {r.id for r in UI.view.values()} == {E0, VEND, LOAD},
           f"Max listed 0: {[r.id for r in UI.view.values()]}")
    ns.settings.shelfMaxListed = 5
    frame.shelfTab.Click(frame.shelfTab)
    expect(ns.settings.tab == "craft" and frame.shelfTab.GetText(frame.shelfTab) == "Shelves", "Shelves tab back")
    expect(not list(ns.errors.values()), f"errors in the shelves checks: {list(ns.errors.values())[:3]}")


def check_farm():
    """Farm sessions: loot and money lines, pause / AFK / logout, item values, g/h, saved sessions, Best farms."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub)
    F, UI = ns.Farm, ns.UI
    SHELF, VEND, NOPRICE = 995101, 995102, 995103
    for i, sell in ((SHELF, 10), (VEND, 700), (NOPRICE, 0)):
        stub["items"][i] = lua.table_from({"name": f"Loot {i}", "sell": sell})
    tsm_money(lua, ns, {SHELF: {"DBMarket": 50000}})
    set_auctions(lua, stub, [(LINEN, 20, 20 * 300)])
    scan(lua, stub)
    cut = ns.Pricing.Cut()[0]

    def link(i):
        return f"|cffffffff|Hitem:{i}::::::::60:::::|h[Loot {i}]|h|r"
    # Parsing.
    expect(F.ParseLoot(f"You receive loot: {link(LINEN)}.") == (LINEN, 1)
           and F.ParseLoot(f"You receive loot: {link(LINEN)}x12.") == (LINEN, 12)
           and F.ParseLoot(f"Bob receives loot: {link(LINEN)}.") is None
           and F.ParseLoot(f"You receive item: {link(LINEN)}.") is None, "loot line parsing")
    expect(F.ParseMoney("You loot 1 Gold, 2 Silver, 3 Copper") == 10203 and F.ParseMoney("You loot 45 Copper") == 45
           and F.ParseMoney("Your share of the loot is 5 Silver.") == 500
           and F.ParseMoney("Your share of the loot is 1 Silver, 20 Copper. (6 Copper deposited to guild bank)") == 120
           and F.ParseMoney("Du plünderst 5 Silber") is None, "money line parsing")
    expect(F.Pattern("a.b%sc(%d)") == "^a%.b(.-)c%((%d+)%)$", f"Pattern {F.Pattern('a.b%sc(%d)')}")

    # A session.
    stub.zone = "Durotar"
    expect(F.Start() and not F.Start() and F.Running(), "Start")
    t0 = g.time()

    def loot(i, n=1):
        stub.fire("CHAT_MSG_LOOT", f"You receive loot: {link(i)}x{n}." if n > 1 else f"You receive loot: {link(i)}.",
                  "Hana")

    def money_line(text):
        stub.fire("CHAT_MSG_MONEY", text)

    def gain(c):
        stub.money = stub.money + c
        stub.fire("PLAYER_MONEY")
    loot(LINEN, 5)
    loot(LINEN)
    loot(SHELF)
    loot(VEND, 2)
    loot(NOPRICE)
    stub.fire("CHAT_MSG_LOOT", f"Bob receives loot: {link(LINEN)}x9.", "Bob")
    money_line("You loot 1 Gold, 2 Silver, 3 Copper")
    gain(10203)                           # its PLAYER_MONEY: counted once
    gain(5000)                            # a vendor sale: not loot
    stub.clock = stub.clock + 5
    gain(777)
    money_line("Du plünderst 7 Silber")   # unread line right after a rise: the rise counts
    stub.clock = stub.clock + 5
    money_line("Tu ramasses 3 Argent")    # unread line, then its rise
    gain(300)
    stub.clock = stub.clock + 5
    cur = F.Current()
    expect(cur["items"][LINEN] == 6 and cur["items"][SHELF] == 1 and cur["items"][VEND] == 2,
           f"looted items {dict(cur['items'])}")
    expect(cur.money == 10203 + 777 + 300, f"looted money {cur.money} (want {10203 + 777 + 300})")
    # Pause: no loot, no time.
    stub.now = stub.now + 600
    expect(F.Pause("you") and not F.Running(), "Pause")
    stub.now = stub.now + 1000
    loot(LINEN, 50)
    expect(cur["items"][LINEN] == 6, "loot counted while paused")
    expect(F.Resume(), "Resume")
    # AFK pauses and resumes on its own; another zone.
    stub.zone = "The Barrens"
    stub.fire("ZONE_CHANGED_NEW_AREA")
    stub.now = stub.now + 1200
    stub.afk = True
    stub.fire("PLAYER_FLAGS_CHANGED", "player")
    expect(cur.paused == "afk", "AFK must pause the session")
    stub.now = stub.now + 5000
    stub.afk = False
    stub.fire("PLAYER_FLAGS_CHANGED", "player")
    expect(F.Running(), "back from AFK must resume")
    stub.now = stub.now + 600
    el = F.Elapsed(cur)
    expect(abs(el - 2400) <= 20, f"elapsed {el}: paused and AFK time must not count")
    # Values: the shelf suggestion less the cut, the AH min less the cut, the vendor price; the best of them.
    vals = {r.id: r for r in F.ItemRows(cur)[0].values()}
    expect(vals[SHELF].how == "shelf" and vals[SHELF].each == int(50000 * (1 - cut)), f"shelf value {vals[SHELF].each}")
    expect(vals[LINEN].how == "AH" and vals[LINEN].each == int(300 * (1 - cut)), f"AH value {vals[LINEN].each}")
    expect(vals[VEND].how == "vendor" and vals[VEND].each == 700 and vals[NOPRICE].how is None
           and vals[NOPRICE].each == 0, "vendor / no price")
    t = F.Totals(cur)
    want = cur.money + 6 * int(300 * (1 - cut)) + int(50000 * (1 - cut)) + 1400
    expect(t.total == want and abs(t.gph - want * 3600 / t.elapsed) < 1e-6 and t.zone in ("Durotar", "The Barrens"),
           f"totals {t.total} (want {want}) {t.gph} {t.zone}")
    # The tab while running.
    slash(lua, "farm")
    frame = g.ForeverCrafterFrame
    expect(ns.settings.tab == "farm" and len(UI.view) == 4 and frame.fm.start.GetText(frame.fm.start) == "Stop"
           and "running" in UI.StatusText() and frame.farmTab.GetText(frame.farmTab) == "Crafts",
           f"Farm tab: {len(UI.view)} rows, status {UI.StatusText()!r}")
    expect(UI.view[1].id == SHELF and UI.CellText(UI.view[1], "fhow") == "shelf", "Farm rows by value")
    stub.runTimers(5)
    expect(not list(ns.errors.values()), f"errors in the farm tick: {list(ns.errors.values())[:3]}")
    # Stop freezes the values.
    s = F.Stop()
    expect(s and s.saved and F.Current() is None and ns.char.farm.sessions[1].stop == s.stop and s.total == want
           and s.zoneName == "The Barrens", f"Stop: {s and s.total} (want {want}) {s and s.zoneName}")
    g.TSM_STUB.money[SHELF] = lua.table_from({"DBMarket": 1})
    expect(F.Totals(s).total == want, "a saved session's item values must be frozen at Stop")
    # Logout pauses, login resumes.
    F.Start()
    stub.fire("PLAYER_LOGOUT")
    expect(F.Current().paused == "logout", "logout must pause the session")
    lua2, ns2, stub2 = new_runtime(saved=stub.savedVariables("ForeverCrafterDB"))
    stub2.now = stub.now + 3600
    n0 = len(stub2.prints)
    login(lua2, stub2)
    expect(ns2.Farm.Running() and any("farm session resumed" in p for p in prints(stub2, n0)),
           "login must resume a session paused by logout")
    expect(ns2.Farm.Elapsed(ns2.Farm.Current()) < 60, "the logged-out hour must not count")
    # Keep the last 20.
    stub.zone = "Durotar"
    for i in range(25):
        F.Start()
        stub.now = stub.now + 60
        F.Stop()
    expect(len(ns.char.farm.sessions) == 20, f"{len(ns.char.farm.sessions)} sessions kept (20)")
    # Best farms: by zone over every character.
    ns.db.chars["Alt-Test"] = ltable(lua, {"farm": {"sessions": [
        {"zoneName": "Durotar", "elapsed": 3600, "total": 3600000, "money": 100, "saved": True},
        {"zoneName": "Felwood", "elapsed": 1800, "total": 900000, "money": 0, "saved": True}]}})
    best = {o.zone: o for o in F.BestRows().values()}
    d = best.get("Durotar")
    expect(d and d.nChars == 2 and d.sessions == 21 and d.best == 3600000 and best["Felwood"].gph == 1800000
           and abs(d.gph - d.gold * 3600 / d.time) < 1e-6, f"Best farms {d and (d.nChars, d.sessions, d.best)}")
    frame.fm.view.Click(frame.fm.view)
    expect(ns.settings.farmView == "best" and UI.view[1].zone == "Durotar" and "Hana" in UI.CellText(UI.view[1], "fchars")
           and frame.fm.view.GetText(frame.fm.view) == "This session", "Best farms view")
    for cols in (F.SESSION_COLUMNS, F.BEST_COLUMNS):
        w = sum(c.width for c in cols.values())
        expect(w <= 796, f"Farm columns are {w} px wide (796 max)")
    expect(not list(ns.errors.values()) and not list(ns2.errors.values()),
           f"errors in the farm checks: {list(ns.errors.values())[:3]}")


def check_farms_data(ns, keys, date):
    """Data/Farms.lua (gen_data.py from research/wowhead/farms_*.json): src + verified on every farm, page and item;
    the assumed rates say verified=false; every page is a Wowhead Forever NPC or object page."""
    info = ns.FarmInfo
    expect(info and all(p in keys for p in info.src.split("+")) and date.match(info.verified or ""),
           "ns.FarmInfo needs src + verified")
    pages = ns.FarmPages
    used = set()
    nfarms = 0
    for _, d in ns.FarmDefs.items():
        nfarms += 1
        expect(d.src and all(p in keys for p in d.src.split("+")) and date.match(d.verified or ""),
               f"FarmDefs {d.key} needs src + verified")
        # A farm with no zone is a generic herb or ore node, counted in any zone.
        expect(d.kind in ("kill", "node") and ((isinstance(d.zone, int) and d.zoneName)
                                              or (d.zone is None and d.zoneName is None and d.kind == "node")),
               f"FarmDefs {d.key} kind/zone")
        expect(d.rate.n > 0 and d.rate.src in keys and (d.rate.src != "assumed" or d.rate.verified is False),
               f"FarmDefs {d.key} rate {d.rate.n} {d.rate.src}: assumed rates must say verified=false")
        for _, pk in d.pages.items():
            pg = pages[pk]
            used.add(pk)
            expect(pg is not None and pg.kind == ("npc" if d.kind == "kill" else "object"),
                   f"FarmDefs {d.key} page {pk} is missing or the wrong kind")
    npages, nrows = 0, 0
    for pk, pg in pages.items():
        npages += 1
        expect(pk == f"{pg.kind}{pg.id}" and pg.src == "wh_" + pg.kind and date.match(pg.verified or ""),
               f"FarmPages {pk} src {pg.src!r}")
        expect(re.match(r"^https://www\.wowhead\.com/forever/(npc|object)=" + str(pg.id) + r"/[a-z0-9-]+$", pg.url),
               f"FarmPages {pk} url {pg.url}")
        for lname in ("drops", "skinning", "pickpocketing", "herbalism", "mining"):
            for _, r in (pg[lname] or {}).items():
                nrows += 1
                item, count, outof, lo, hi = r[1], r[2], r[3], r[4], r[5]
                if not expect(0 < count <= outof and 1 <= lo <= hi, f"FarmPages {pk} {lname} row {list(r.values())}"):
                    break
                d = ns.Items[item] or ns.RepItems[item] or ns.FarmItems[item]
                expect(d is not None and d.name, f"FarmPages {pk} item {item} has no name")
    expect(used == set(pages.keys()), "FarmPages has pages no farm uses")
    for i, e in ns.FarmItems.items():
        expect(e.src in keys and date.match(e.verified or "") and e.name, f"FarmItems[{i}] needs src + verified")
        expect(ns.Items[i] is None and ns.RepItems[i] is None, f"FarmItems[{i}] duplicates Items or RepItems")
    expect(nfarms == 53 and npages == 75, f"{nfarms} farms, {npages} pages (53, 75)")
    # Wowhead Forever npc=5982 Black Slayer (2026-11-20): Vulture Gizzard 8396.
    expect(any(r[1] == 8396 for r in pages.npc5982.drops.values()), "Black Slayer must drop Vulture Gizzard")
    # Wowhead Forever object=142145 Gromsblood (2026-11-21): Gromsblood 8846 in 316 of 328 nodes, 1-3.
    expect(list(pages.object142145.herbalism[1].values()) == [8846, 316, 328, 1, 3]
           and ns.FarmDefs[53].zone is None, "Gromsblood node: Gromsblood 316/328 x1-3, any zone")
    return {"farms": nfarms, "farm pages": npages, "farm loot rows": nrows}


FARM_FIXTURE = """
  local ns = ...
  ns.FarmDefs = {
    {key="kfarm",name="Testlands: mobs",zone=9001,zoneName="Testlands (wh)",kind="kill",pages={"npc7001","npc7002"},
     rate={n=120,src="assumed",verified=false},src="wh_npc+wh_item",verified="2026-11-20"},
    {key="nfarm",name="Testlands: herbs",zone=9001,zoneName="Testlands (wh)",kind="node",pages={"object8001"},
     rate={n=60,src="assumed",verified=false},src="wh_object+wh_item",verified="2026-11-20"},
    {key="gfarm",name="Herb: Generic",kind="node",pages={"object8002"},
     rate={n=60,src="assumed",verified=false},src="wh_object",verified="2026-11-21"},
  }
  ns.FarmPages = {
    npc7001={kind="npc",id=7001,name="Mob A",url="https://www.wowhead.com/forever/npc=7001/mob-a",
      drops={{996001,1,2,1,3},{996002,1,4,2,2},{996006,1,1,1,1}},skinning={{996003,1,1,1,1}},
      pickpocketing={{996004,1,2,1,1}},src="wh_npc",verified="2026-11-20"},
    npc7002={kind="npc",id=7002,name="Mob B",url="https://www.wowhead.com/forever/npc=7002/mob-b",
      drops={{996001,1,1,1,1}},src="wh_npc",verified="2026-11-20"},
    object8001={kind="object",id=8001,name="Herb",url="https://www.wowhead.com/forever/object=8001/herb",
      herbalism={{996005,1,1,2,2}},src="wh_object",verified="2026-11-20"},
    object8002={kind="object",id=8002,name="Generic herb",url="https://www.wowhead.com/forever/object=8002/generic-herb",
      herbalism={{996005,1,1,1,1},{996001,1,10,1,1}},src="wh_object",verified="2026-11-21"},
  }
  ns.FarmGuide.Reset()
"""


def check_farm_guide():
    """Built-in farms: EV, skinning / pickpocket gating, rates (assumed, learned, yours), kill and node counting
    without double counting, learned coin and mix, the demand flag and the Farms view."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub)
    G, F, UI = ns.FarmGuide, ns.Farm, ns.UI
    A, B, S, P, H, Q = range(996001, 996007)
    for i, d in {A: {"sell": 10}, B: {"quality": 0, "sell": 500}, S: {"sell": 5}, P: {"sell": 300},
                 H: {"sell": 1}, Q: {"quality": 2, "sell": 50, "bind": 1}}.items():
        stub["items"][i] = lua.table_from(dict({"name": f"Farm {i}", "quality": 1}, **d))
    set_auctions(lua, stub, [(A, 10, 10000), (B, 1, 99999), (S, 5, 10000), (H, 20, 8000), (Q, 1, 99999)])
    tsm_money(lua, ns, {A: {"DBRegionSoldPerDay": 150, "DBRegionSaleRate": 0.5},
                        H: {"DBRegionSoldPerDay": 1000000, "DBRegionSaleRate": 0.5}})
    scan(lua, stub)
    lua.eval("function(src, ns) assert(loadstring(src))(ns) end")(FARM_FIXTURE, ns)
    cut = ns.Pricing.Cut()[0]
    vA, vS, vH = int(1000 * (1 - cut)), int(2000 * (1 - cut)), int(400 * (1 - cut))

    def rows():
        return {o.spell: o for o in G.List().values()}
    near = lambda a, b: abs(a - b) < 1e-6
    # EV: equal mix of the two mobs; greys and bound items at the vendor price; no Skinning, not a Rogue.
    k = rows()["kfarm"]
    ev = 0.5 * (1 * vA + 0.5 * 500 + 1 * 50) + 0.5 * vA
    expect(near(k.ev, ev) and near(k.parts.loot, ev) and near(k.skipped.skinning, 0.5 * vS)
           and near(k.skipped.pickpocket, 0.5 * 0.5 * 300) and k.rateSrc == "assumed" and k.rate == 120
           and near(k.gph, ev * 120) and k.coin == 0, f"kill farm EV {k.ev} (want {ev}), g/h {k.gph}")
    its = {(it.id, it.part): it for it in k["items"].values()}
    expect(its[(B, "loot")].how == "vendor" and its[(Q, "loot")].how == "vendor" and its[(A, "loot")].how == "AH"
           and k.top.id == A, "grey and bound items are valued at the vendor price")
    # Skinning with Skinning, pickpocketing as a Rogue.
    ns.char.gather = ltable(lua, {393: 300})
    stub["class"] = "ROGUE"
    k = rows()["kfarm"]
    expect(near(k.ev, ev + 0.5 * vS + 0.5 * 0.5 * 300) and k.skipped.skinning is None and k.skipped.pickpocket is None,
           f"with Skinning and as a Rogue: EV {k.ev}")
    stub["class"] = "WARRIOR"
    n = rows()["nfarm"]
    expect(near(n.ev, 2 * vH) and n.need == "Herbalism" and near(n.gph, 2 * vH * 60), f"node farm {n.ev} {n.need}")
    ns.char.gather = None
    expect(rows()["nfarm"].need is None, "unknown gathering skills: no warning")
    # Demand: A drops 1 a kill x 120/h, the realm buys 150 / 15 = 10 a day.
    k = rows()["kfarm"]
    d = {x.id: x for x in k.demand.values()}
    expect(k.over and d[A].over and near(d[A].perHour, 120) and near(d[A].realmDay, 10) and not rows()["nfarm"].over,
           f"demand flag {k.over} {d.get(A) and (d[A].perHour, d[A].realmDay)}")
    # Your own nodes per hour beats a learned rate.
    n = rows()["nfarm"]
    expect(not G.SetRate(n, "abc") and not G.SetRate(n, "0") and not G.SetRate(k, "90") and G.SetRate(n, "90")
           and rows()["nfarm"].rate == 90 and rows()["nfarm"].rateSrc == "you", "Nodes/h 90")
    expect(G.RateBoxText(n) == "90" and G.RateBoxText(k) == "", "the Nodes/h box text")
    G.SetRate(n, "")
    expect(rows()["nfarm"].rateSrc == "assumed" and rows()["nfarm"].rate == 60, "a blank Nodes/h clears it")

    # Counting kills and nodes in a session.
    stub.areas[9001] = "Testlands"
    G.Reset()
    stub.zone = "Testlands"
    stub.fire("ZONE_CHANGED_NEW_AREA")
    F.Start()
    guid = lambda npc, n: f"Creature-0-1-2-3-{npc}-0000AA{n:04d}"
    node = lambda n: f"GameObject-0-1-2-3-8001-0000BB{n:04d}"

    def link(i):
        return f"|cffffffff|Hitem:{i}::::::::60:::::|h[Farm {i}]|h|r"

    def target(gd, dead=False, **kw):
        stub.target = ltable(lua, dict(guid=gd, dead=dead, **kw)) if gd else None

    def loot(*slots, source_info=True):
        stub.noSourceInfo = not source_info
        stub.loot = ltable(lua, [{"link": link(i), "sources": src} if src else {"link": link(i)} for i, src in slots])
        stub.fire("LOOT_OPENED")
        stub.loot = ltable(lua, [])

    def counted():
        cur = F.Current()
        return {key: t.n for key, t in (cur.guide or {}).items()}
    target(guid(7001, 1), dead=True)
    stub.fire("UNIT_DIED", guid(7001, 1))
    loot((A, [guid(7001, 1), 1]))                       # its corpse: the same kill
    stub.fire("CHAT_MSG_MONEY", "You loot 50 Copper")
    stub.money = stub.money + 50
    stub.fire("PLAYER_MONEY")
    stub.fire("UNIT_DIED", guid(7002, 2))                # not your target
    target(guid(7002, 3), dead=True, tapDenied=True)
    stub.fire("UNIT_DIED", guid(7002, 3))                # someone else's tap
    target(None)
    loot((A, [guid(7002, 2), 1, guid(7001, 4), 1]), (B, [guid(7002, 2), 1]))   # area loot: 2 corpses
    target(guid(7001, 5))
    loot((P, [guid(7001, 5), 1]))                       # pickpocketing the living target
    target(guid(7001, 5), dead=True)
    stub.fire("UNIT_DIED", guid(7001, 5))                # then the kill
    target(guid(7002, 6), dead=True)
    loot((A, None), source_info=False)                  # no GetLootSourceInfo: the dead target
    target(None)
    loot((H, [node(1), 2]))
    loot((H, [node(1), 2]))                             # the same node again
    loot((H, None), source_info=False)                  # no source info: the node's herb
    stub.target = ltable(lua, {"secret": True, "dead": True})
    stub.fire("UNIT_DIED", guid(7001, 7))                # a secret target GUID: never counted
    c = counted()
    expect(c == {"kfarm": 5, "nfarm": 2}, f"counted {c} (want kfarm 5, nfarm 2)")
    cur = F.Current()
    expect(cur.guide.kfarm.money == 50 and dict(cur.guide.kfarm.mix) == {"npc7001": 3, "npc7002": 2},
           f"coin {cur.guide.kfarm.money}, mix {dict(cur.guide.kfarm.mix)}")
    stub.zone = "Elsewhere"
    stub.fire("ZONE_CHANGED_NEW_AREA")
    target(guid(7001, 8), dead=True)
    stub.fire("UNIT_DIED", guid(7001, 8))
    expect(counted() == c, "kills outside the farm's zone must not count")
    stub.zone = "Testlands"
    stub.fire("ZONE_CHANGED_NEW_AREA")
    for i in range(10, 20):                             # 10 more kills, all Mob A
        target(guid(7001, i), dead=True)
        stub.fire("UNIT_DIED", guid(7001, i))
    stub.now = stub.now + 1400
    strip = lambda t: re.sub(r"\|c\w{8}|\|r", "", t)
    k = rows()["kfarm"]
    expect(k.session == 15 and strip(G.CellText(k, "grate")) == "120/h assumed (15)",
           f"this session's count: {strip(G.CellText(k, 'grate'))!r}")
    F.Stop()
    L = ns.char.farmGuide.farms.kfarm
    secs = L.secs
    k = rows()["kfarm"]
    expect(L.n == 15 and L.money == 50 and near(secs, 1400 * 15 / 17)
           and near(k.rate, 15 * 3600 / secs) and k.rateSrc == "learned" and near(k.coin, 50 / 15)
           and k.learnedMix and near(k.weights.npc7001, 13 / 15), f"learned {L.n} kills in {secs} s, rate {k.rate}")
    nL = ns.char.farmGuide.farms.nfarm
    expect(nL.n == 2 and near(nL.secs, 1400 * 2 / 17), f"the zone's time split by count: nodes {nL.secs}")
    ev = 13 / 15 * (vA + 250 + 50) + 2 / 15 * vA
    expect(near(k.ev, ev) and near(k.gph, (ev + 50 / 15) * k.rate), f"learned mix EV {k.ev} (want {ev})")
    expect(rows()["nfarm"].rateSrc == "assumed", "2 nodes are not enough to learn a rate")
    ns.char.farmGuide.farms.nfarm = ltable(lua, {"n": 20, "secs": 3600, "money": 0, "mix": {}})
    n = rows()["nfarm"]
    expect(n.rate == 20 and n.rateSrc == "learned", "a learned node rate")
    G.SetRate(n, "90")
    expect(rows()["nfarm"].rate == 90 and rows()["nfarm"].rateSrc == "you", "your Nodes/h beats the learned rate")
    # A new session forgets the counted GUIDs only when it starts.
    F.Start()
    target(guid(7001, 1), dead=True)
    stub.fire("UNIT_DIED", guid(7001, 1))
    expect(counted() == {"kfarm": 1}, f"a new session counts again: {counted()}")
    F.Stop()

    # A generic (zone-less) node farm counts in any zone; in its own zone a zone farm's herb comes first.
    gnode = lambda n: f"GameObject-0-1-2-3-8002-0000CC{n:04d}"
    F.Start()
    target(None)
    stub.zone = "Elsewhere"
    stub.fire("ZONE_CHANGED_NEW_AREA")
    loot((H, [gnode(1), 1]))                            # the node, anywhere
    loot((H, None), source_info=False)                  # no source info: its main herb
    loot((A, None), source_info=False)                  # only a side drop: not a node
    expect(counted() == {"gfarm": 2}, f"generic node farm in another zone: {counted()}")
    stub.now = stub.now + 600
    stub.zone = "Testlands"
    stub.fire("ZONE_CHANGED_NEW_AREA")
    loot((H, [gnode(2), 1]))                            # the generic node in Testlands
    loot((H, None), source_info=False)                  # the herb in Testlands: Testlands' own herb farm
    expect(counted() == {"gfarm": 3, "nfarm": 1}, f"zone farm first in its zone: {counted()}")
    stub.now = stub.now + 300
    gL0 = ns.char.farmGuide.farms.gfarm
    F.Stop()
    gL = ns.char.farmGuide.farms.gfarm
    expect(gL0 is None and gL.n == 3 and near(gL.secs, 600 + 300 / 2),
           f"generic farm time by zone: {gL.n} nodes in {gL.secs} s (want 3 in 750)")
    gr = rows()["gfarm"]
    expect(gr.zone == "Any zone" and strip(G.CellText(gr, "gzone")) == "Any zone"
           and near(gr.ev, vH + 0.1 * vA), f"generic farm row: {gr.zone} EV {gr.ev}")

    # The Farms view.
    slash(lua, "farm")
    frame = g.ForeverCrafterFrame
    frame.fm.guide.Click(frame.fm.guide)
    view = {o.spell: o for o in UI.view.values()}
    expect(ns.settings.farmView == "farms" and len(UI.view) == 3 and UI.view[1].gph >= UI.view[2].gph
           and frame.fm.guide.GetText(frame.fm.guide) == "This session" and frame.fmRate.IsShown(frame.fmRate),
           f"Farms view: {ns.settings.farmView} {len(UI.view)} rows")
    UI.selected = view["nfarm"]
    UI.Refresh()
    expect(frame.fmRate.GetText(frame.fmRate) == "90", "the Nodes/h box shows the selected farm's rate")
    frame.fmRate.SetText(frame.fmRate, "45")
    frame.fmRate.__scripts.OnEnterPressed(frame.fmRate)
    expect(ns.settings.farmRates.nfarm == 45 and UI.selected.rate == 45, "Nodes/h edit")
    text = UI.DetailText(UI.selected)
    expect("Loot per node" in text and "object=8001" in text and "Rate 45 nodes/h: set by you" in text, "Farms details")
    UI.selected = [o for o in UI.view.values() if o.spell == "kfarm"][0]
    text = UI.DetailText(UI.selected)
    expect("Coin per kill" in text and "learned from 16 kills" in text and "Realm demand" in text
           and "npc=7001" in text and "Not counted: skinning" in text, f"kill farm details:\n{text}")
    for o in UI.view.values():
        for c in G.COLUMNS.values():
            UI.CellText(o, c.key)
    w = sum(c.width for c in G.COLUMNS.values())
    expect(w <= 796, f"Farms columns are {w} px wide (796 max)")
    frame.fm.view.Click(frame.fm.view)
    expect(ns.settings.farmView == "best" and not frame.fmRate.IsShown(frame.fmRate), "Best farms from the Farms view")
    expect(not list(ns.errors.values()), f"errors in the farm guide checks: {list(ns.errors.values())[:3]}")


def farm_summary():
    """The built-in farms on the test snapshot (every item listed at a pseudo-random price): top g/h."""
    lua, ns, stub = new_runtime()
    login(lua, stub)
    ids = set(ns.Items.keys()) | set(ns.FarmItems.keys())
    listings = []
    for i in sorted(ids):
        p = 100 + (i * 7919) % 50000
        listings += [(i, 5, p * 5), (i, 1, p + 10)]
    set_auctions(lua, stub, listings)
    scan(lua, stub)
    G, U = ns.FarmGuide, ns.Util
    strip = lambda t: re.sub(r"\|c\w{8}|\|r", "", t)
    rows = sorted(G.List().values(), key=lambda o: -o.gph)
    out = [f"built-in farms (test snapshot, {len(rows)} farms, no gathering skill, not a Rogue): top g/h"]
    for o in rows[:8]:
        out.append(f"  {o['def'].name}: {strip(G.CellText(o, 'gev'))} x {strip(G.CellText(o, 'grate'))} = "
                   f"{strip(G.CellText(o, 'ggph'))}, top {strip(G.CellText(o, 'gtop'))}")
    expect(not list(ns.errors.values()), f"errors in the farm summary: {list(ns.errors.values())[:3]}")
    return out


def check_filter_row():
    """The filter row: the Shelves and Farm tabs and Scan AH sit right of every crafting filter and panel control."""
    lua, ns, stub = new_runtime()
    login(lua, stub)
    slash(lua, "")
    frame = lua.globals().ForeverCrafterFrame
    spans = []
    for b in (frame.shelfTab, frame.farmTab, frame.scan):
        p = b.__points
        expect(p[1] == "TOPRIGHT", "filter-row tabs are placed from the top right")
        spans.append((1204 + p[2] - b.__w, 1204 + p[2]))
    spans.sort()
    expect(all(a[1] <= b[0] for a, b in zip(spans, spans[1:])), f"filter-row buttons overlap: {spans}")

    def right(e, chars):   # an edit box: its label (about 6 px a character), 8 px, the box
        return e.label.__points[2] + 6 * chars + 8 + e.__w
    ends = [right(frame.minBatch, len("Min batch")), right(frame.sh.realms, len("Realm share 1 /")),
            frame.fm.view.__points[2] + frame.fm.view.__w, frame.fm.guide.__points[2] + frame.fm.guide.__w,
            right(frame.fmRate, len("Nodes/h"))]
    expect(max(ends) < spans[0][0], f"filter controls end at {max(ends)}, the tabs start at {spans[0][0]}")


def check_sniper_target():
    """A per-craft sniper Target: needs scale with it, it survives a recompute, and deals go past the batch."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub, skills={TAILORING: 300})
    R1, R2, R3, OV, OA = 990601, 990602, 990603, 990611, 990612
    V, A = 991601, 991602
    synthetic(lua, ns, stub, {V: (OV, [[R1, 1], [R2, 2]]), A: (OA, [[R1, 1], [R3, 1]])}, [R1, R2, R3, OV, OA])
    ns.Recipes[V].cast = 5000
    ns.Items[OV].sell = 300
    stub["items"][OV] = lua.table_from({"name": f"Test {OV}", "sell": 300})
    set_auctions(lua, stub, [(OA, 1, 1000), (R1, 50, 500), (R1, 100, 100000), (R2, 100, 2000), (R2, 100, 200000),
                             (R3, 50, 1500), (R3, 100, 150000)])
    scan(lua, stub)
    res, _ = results(ns)
    S, UI = ns.Sniper, ns.UI
    v, a = res.get(V), res.get(A)
    if not expect(v and a, "target test recipes not evaluated"):
        return
    S.Toggle(v)
    S.Toggle(a)

    def watch():
        return {e.id: e for e in S.Watch().values()}

    # No Target: the need is the batch, exactly as before (V: batch 50, 1 R1 + 2 R2; A: batch 50, 1 R1 + 1 R3).
    w = watch()
    expect(S.Target(V) is None and (w[R1].need, w[R2].need, w[R3].need) == (100, 100, 50)
           and all(row.qty == S.Limit(row.spell).reagents[i].qty for i, e in w.items() for row in e.rows.values()),
           f"default target need {(w[R1].need, w[R2].need, w[R3].need)}")
    # 3 x the batch triples V's needs; the shared R1 sums V at its target and A at its batch.
    expect(S.SetTarget(V, 150), "SetTarget refused 150")
    w = watch()
    expect((w[R1].need, w[R2].need, w[R3].need) == (200, 300, 50), f"3x target need {(w[R1].need, w[R2].need)}")
    expect(S.SetTarget(A, 75) and watch()[R1].need == 225 and watch()[R3].need == 75, "shared reagent at two targets")
    # Fractional per-craft amounts round up: 5 for a batch of 2 = 2.5 a craft, x 3 crafts = 8.
    S.SetTarget(A, 3)
    expect(S.TargetQty(A, lua.table_from({"batch": 2}), lua.table_from({"qty": 5})) == 8, "ceil of 7.5")
    S.SetTarget(A, None)
    # Bad input is refused and changes nothing.
    for bad in (0, 10000, 2.5, "abc", -3):
        expect(not S.SetTarget(V, bad) and S.Target(V) == 150, f"SetTarget accepted {bad!r}")
    expect(S.SetTarget(V, "9999") and S.Target(V) == 9999 and S.SetTarget(V, 150), "string target")
    # A recompute replaces the ticked rows; the target stays.
    old = S.Limit(V)
    UI.Recompute()
    expect(S.Limit(V) is not None and S.Limit(V) != old and S.Target(V) == 150 and watch()[R2].need == 300,
           "target lost on recompute")
    # A deal past the batch: 250 R2 at 20c (max 30c) are all wanted at target 150, only 100 without.
    stub.fire("AUCTION_HOUSE_SHOW")
    stub.commodity[R2] = ltable(lua, [[20, 250]])
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    d = watch()[R2].deal
    expect(d and d.qty == 250 and d.qty > S.Limit(V).reagents[R2].qty, f"deal past the batch {d and d.qty}")
    S.SetTarget(V, None)
    d = watch()[R2].deal
    expect(d and d.qty == 100, f"deal without a target {d and d.qty}")
    S.SetTarget(V, 150)
    # Saved and restored; untick and Clear drop it.
    saved = stub.savedVariables("ForeverCrafterDB")
    lua2, ns2, stub2 = new_runtime(saved=saved)
    login(lua2, stub2, skills={TAILORING: 300})
    expect(ns2.Sniper.Target(V) == 150, "target not restored")
    S.Toggle(v)
    expect(not S.IsTicked(V) and S.Target(V) is None, "untick keeps the target")
    S.Toggle(v)
    expect(watch()[R2].need == 100, "re-ticked craft keeps an old target")
    S.SetTarget(V, 120)
    S.Clear()
    expect(S.Target(V) is None and not any(True for _ in ns.char.snipe.targets), "Clear keeps targets")
    expect("raise a craft's Target" in S.MET, "stop message does not mention Target")

    # The Sniper page: ticked crafts above a shorter reagent list, Target typed into a box.
    S.Toggle(v)
    S.Toggle(a)
    slash(lua, "snipe")
    frame = g.ForeverCrafterFrame
    crafts = frame.crafts
    expect(crafts.__shown and not crafts.empty.__shown, "crafts list hidden on the Sniper page")
    crows = {f.lim.spell: f for f in crafts.rows.values() if f.lim is not None and f.__shown}
    if not expect(set(crows) == {V, A}, f"crafts rows {set(crows)}"):
        return
    rv = crows[V]
    cells = [c.__text for c in rv.cells.values()]
    expect(any("Vendor" == c for c in cells) and "50" in cells and rv.target.__text == "", f"crafts row {cells}")
    box = rv.target
    box.SetFocus(box)
    box.SetText(box, "150")
    UI.Refresh()
    expect(box.__text == "150" and box.HasFocus(box), "a refresh overwrote a Target being typed")
    box.__scripts.OnEnterPressed(box)
    expect(S.Target(V) == 150 and not box.HasFocus(box) and box.__text == "150", "Target box did not set")
    r2 = [e for e in UI.view.values() if e.id == R2]
    expect(r2 and r2[0].need == 300, "the reagent list was not refreshed right away")
    expect("target 150 crafts (batch 50)" in UI.DetailText(r2[0]), "sniper detail has no target")
    box.SetText(box, "abc")
    box.__scripts.OnEnterPressed(box)
    expect(S.Target(V) == 150 and box.__text == "150", "a bad Target was not refused")
    box.SetText(box, "")
    box.__scripts.OnEnterPressed(box)
    expect(S.Target(V) is None and [e for e in UI.view.values() if e.id == R2][0].need == 100, "blank Target")
    # Time and Profit (at max) scale with Target; the total sums them over the crafts with room.
    lv, la = S.Limit(V), S.Limit(A)
    pv = 300 - (50 + 25)                                      # W - (C + room) for the vendor shuffle
    expect(S.ProfitAtMax(lv) == pv and lv.time == 5, f"profit at max {S.ProfitAtMax(lv)}, time {lv.time}")
    expect(S.CraftTotals(lv) == (50 * pv, 250), f"batch totals {S.CraftTotals(lv)}")
    tot1 = S.Totals()
    pa, ta = S.CraftTotals(la)
    expect(abs(tot1.profit - (50 * pv + pa)) < 1e-6 and tot1.crafts == 2, f"total {tot1.profit}")
    box.SetText(box, "150")
    box.__scripts.OnEnterPressed(box)
    expect(S.CraftTotals(lv) == (150 * pv, 750), f"3x totals {S.CraftTotals(lv)}")
    tot = S.Totals()
    expect(abs(tot.profit - (150 * pv + pa)) < 1e-6 and tot.time == 750 + (ta or 0), f"3x total {tot.profit}")
    expect(abs(tot.gh - (150 * pv + (pa if ta else 0)) / tot.time * 3600) < 1e-6, f"total g/h {tot.gh}")
    cells = {h.col.key: rv.cells[k].__text for k, h in crafts.headers.items() if rv.cells[k] is not None}
    expect(cells["time"] == "12m30s" and cells["profit"] == ns.Util.Money(150 * pv), f"crafts row cells {cells}")
    expect(ns.Util.Money(round(tot.profit)) in crafts.total.__text and "Total for 2 crafts" in crafts.total.__text,
           f"total line {crafts.total.__text!r}")
    # A no-room craft is left out of the sums and shows "-".
    la.noRoom = True
    tot2 = S.Totals()
    expect(tot2.crafts == 1 and tot2.profit == 150 * pv and tot2.time == 750
           and S.CraftCellText(la, "profit") == "—", f"no-room craft in the totals {tot2.profit}")
    la.noRoom = None
    box.SetText(box, "")
    box.__scripts.OnEnterPressed(box)
    # The reagent list shows SNIPE_ROWS rows on the Sniper page, ROWS on the craft list.
    expect(frame.list.__h == (UI.SNIPE_ROWS + 1) * 20 + 4 and UI.CRAFT_ROWS + UI.SNIPE_ROWS + 2 == 18,
           f"reagent list height {frame.list.__h}")
    frame.snipeTab.Click(frame.snipeTab)
    expect(not crafts.__shown and frame.list.__h == 19 * 20 + 4, "crafts list shown on the craft list")
    S.SetTarget(V, 150)
    expect("keep 90% g/h, target 150 crafts (batch 50)" in UI.DetailText(v), "craft detail has no target")
    errs = list(ns.errors.values())
    expect(not errs, f"errors in the sniper target checks: {errs[:3]}")


def check_sniper_quick():
    """Scroll to buy (one purchase per wheel step, never while one is in flight), the estimated cost, and met
    reagents that are not searched again until a Target rises."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub, skills={TAILORING: 300})
    R1, R2, R3, OV, OA = 990601, 990602, 990603, 990611, 990612
    V, A = 991601, 991602
    synthetic(lua, ns, stub, {V: (OV, [[R1, 1], [R2, 2]]), A: (OA, [[R1, 1], [R3, 1]])}, [R1, R2, R3, OV, OA])
    ns.Recipes[V].cast = 5000
    ns.Items[OV].sell = 300
    stub["items"][OV] = lua.table_from({"name": f"Test {OV}", "sell": 300})
    set_auctions(lua, stub, [(OA, 1, 1000), (R1, 50, 500), (R1, 100, 100000), (R2, 100, 2000), (R2, 100, 200000),
                             (R3, 50, 1500), (R3, 100, 150000)])
    scan(lua, stub)
    res, _ = results(ns)
    S, UI = ns.Sniper, ns.UI
    v, a = res.get(V), res.get(A)
    if not expect(v and a, "quick-buy test recipes not evaluated"):
        return
    S.Toggle(v)
    S.Toggle(a)
    done = ns.char.snipe.done

    def watch():
        return {e.id: e for e in S.Watch().values()}

    # The estimate: the scan's price steps when there is no search (R1: 50 at 10c, then 100 at 10g; max 15c+).
    w = watch()
    est = S.Estimate(w[R1])
    expect((est["from"], est.listed, est.atMax) == ("scan", 50, 50)
           and est.total == 50 * 10 + sum(r.qty * r.max for r in w[R1].rows.values() if r.spell == A),
           f"estimate from the scan {(est['from'], est.listed, est.atMax, est.total)}")
    # From the last search: owned fill the lowest max first, listings go cheapest first to rows whose max takes
    # them, units not listed under the max count at the max.
    d = lua.execute("""
      local S = ...
      local w = { id = 990699, max = 30, owned = 10, need = 50,
        rows = { { spell = 1, max = 30, qty = 40 }, { spell = 2, max = 22, qty = 30 } } }
      S.seen[990699] = { time = 0, commodity = true, listings = { { unit = 20, qty = 30 }, { unit = 25, qty = 50 } } }
      local a = S.Estimate(w)
      S.seen[990699] = { time = 0, commodity = true, listings = { { unit = 20, qty = 5 }, { unit = 31, qty = 99 } } }
      local b = S.Estimate(w)
      S.seen[990699] = nil
      return { a.total, a.listed, a.atMax, a.from, b.total, b.listed, b.atMax }
    """, S)
    expect(list(d.values()) == [20 * 20 + 10 * 20 + 30 * 25, 60, 0, "search", 5 * 20 + 15 * 22 + 40 * 30, 5, 55],
           f"estimate from a search {list(d.values())}")
    slash(lua, "snipe")
    frame = g.ForeverCrafterFrame
    expect("est. ~" in frame.status.__text and "spent " in frame.status.__text, f"status {frame.status.__text!r}")
    r1row = [e for e in UI.view.values() if e.id == R1][0]
    expect(S.CellText(r1row, "est") == "~" + ns.Util.Money(est.total)
           and "Est. cost of the need: ~" in UI.DetailText(r1row), "Est. cost cell / detail")

    # Scroll to buy: shown on the Sniper tab only; a wheel step buys the deal, one at a time.
    pad = frame.sn.wheel
    expect(pad.__shown and "no deal" in pad.__text, f"pad {pad.__text!r}")
    stub.fire("AUCTION_HOUSE_SHOW")
    stub.commodity[R2] = ltable(lua, [[20, 30], [40, 500]])
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    UI.Refresh()
    expect("Scroll to buy|r" in pad.__text, f"pad when a deal is ready {pad.__text!r}")
    stub.purchases = lua.table()
    wheel = lambda: pad.__scripts.OnMouseWheel(pad, -1)
    wheel()
    expect(len(stub.purchases) == 1 and stub.purchases[1][1] == "Start" and stub.purchases[1][2] == R2
           and stub.purchases[1][3] == 30, f"a wheel step does not buy {len(stub.purchases)}")
    stub.runTimers(1)
    wheel()
    wheel()
    expect(len(stub.purchases) == 1 and "buying" in S.WheelLabel(True), "a wheel step bought while a quote was open")
    stub.fire("COMMODITY_PRICE_UPDATED", 20, 600)
    expect(stub.purchases[2][1] == "Confirm", "an OK quote was not confirmed")
    stub.runTimers(1)
    wheel()
    expect(len(stub.purchases) == 2, "a wheel step during the confirm")
    stub.fire("COMMODITY_PURCHASE_SUCCEEDED")
    expect(ns.char.snipe.spent[R2] == 600 and S.Spend(S.Watch()).spent == 600, "spent not counted")
    # The bought listings are gone: the next wheel step has no deal (the 40c ones are over the max).
    stub.runTimers(1)
    wheel()
    expect(len(stub.purchases) == 2 and watch()[R2].deal is None, "a wheel step bought a listing already bought")
    # A quote waiting for a click (the confirm was blocked): the wheel confirms it, but not twice within the gap.
    stub.commodity[R2] = ltable(lua, [[21, 10]])
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    wheel()
    stub.fire("COMMODITY_PRICE_UPDATED", 21, 210)
    stub.fire("ADDON_ACTION_BLOCKED", "ForeverCrafter", "C_AuctionHouse.ConfirmCommoditiesPurchase()")
    expect(S.pending and S.pending.stage == "click" and "confirm" in S.WheelLabel(False), "blocked confirm")
    k = len(stub.purchases)
    wheel()
    expect(len(stub.purchases) == k, "the wheel confirmed within the gap")
    stub.runTimers(S.QUICK_GAP + 0.01)
    wheel()
    expect(len(stub.purchases) == k + 1 and stub.purchases[k + 1][1] == "Confirm", "the wheel does not confirm")
    stub.fire("COMMODITY_PURCHASE_SUCCEEDED")
    # The key binding does the same; nothing when there is no deal or the AH is closed.
    stub.commodity[R2] = ltable(lua, [[22, 5]])
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    stub.runTimers(1)
    k = len(stub.purchases)
    g.ForeverCrafter_SniperBuy()
    expect(len(stub.purchases) == k + 1 and stub.purchases[k + 1][1] == "Start" and stub.purchases[k + 1][3] == 5,
           "the key binding does not buy")
    stub.fire("COMMODITY_PRICE_UPDATED", 22, 110)
    stub.fire("COMMODITY_PURCHASE_SUCCEEDED")
    stub.runTimers(1)
    k = len(stub.purchases)
    expect(not S.QuickBuy(None) and len(stub.purchases) == k, "a quick buy without a deal")
    stub.commodity[R2] = ltable(lua, [[22, 5]])
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    stub.fire("AUCTION_HOUSE_CLOSED")
    stub.runTimers(1)
    expect(not S.QuickBuy(None) and len(stub.purchases) == k, "a quick buy with the AH closed")
    expect(g.BINDING_NAME_FOREVERCRAFTER_SNIPER_BUY == "Sniper: buy" and g.BINDING_HEADER_FOREVERCRAFTER, "binding names")
    xml = read(os.path.join(ADDON, "Bindings.xml"))
    expect(re.search(r'<Binding name="FOREVERCRAFTER_SNIPER_BUY" header="FOREVERCRAFTER" category="ADDONS">\s*'
                     r'ForeverCrafter_SniperBuy\(\)\s*</Binding>', xml), "Bindings.xml")
    frame.snipeTab.Click(frame.snipeTab)
    expect(not pad.__shown, "Scroll to buy shown on the craft list")
    slash(lua, "snipe")

    # Met: R2 (V: 100 at its batch) is met by bags; it stays met when crafting takes them, and is not searched.
    ns.char.snipe.bought = lua.table()
    ns.char.snipe.spent = lua.table()
    stub.bags[R2] = 100
    expect(watch()[R2].met and done[R2] == 100, f"met latch {done[R2]}")
    stub.bags[R2] = 0
    w = watch()
    expect(w[R2].met and w[R2].need == 0 and S.Estimate(w[R2]).total == 0 and S.CellText(w[R2], "need").find("done") > 0
           and "Met|r for 100" in UI.DetailText(w[R2]), "met reagent searched again after crafting")
    stub.fire("AUCTION_HOUSE_SHOW")
    n0 = len(stub.searches)
    S.Start()
    stub.runTimers(30)
    ids = {stub.searches[i].key.itemID for i in range(n0 + 1, len(stub.searches) + 1)}
    expect(R2 not in ids and R1 in ids, f"searched {ids}")
    # A higher Target resumes it, for the difference only; buying that latches it again.
    S.SetTarget(V, 75)
    w = watch()
    expect(not w[R2].met and w[R2].need == 50 and done[R2] == 100, f"after a raise: need {w[R2].need}")
    n0 = len(stub.searches)
    stub.runTimers(30)
    ids = {stub.searches[i].key.itemID for i in range(n0 + 1, len(stub.searches) + 1)}
    expect(R2 in ids, f"a raised Target is not searched {ids}")
    S.Stop()
    stub.commodity[R2] = ltable(lua, [[20, 50]])
    stub.fire("COMMODITY_SEARCH_RESULTS_UPDATED", R2)
    stub.runTimers(1)
    S.Buy(watch()[R2])
    stub.fire("COMMODITY_PRICE_UPDATED", 20, 1000)
    stub.fire("COMMODITY_PURCHASE_SUCCEEDED")
    expect(done[R2] == 150 and watch()[R2].met, f"bought the difference: done {done[R2]}")
    # Untick takes the craft's share off a shared reagent: R1 met at 125 (V 75 + A 50), A unticked → 75 for V.
    stub.bags[R1] = 125
    watch()
    stub.bags[R1] = 0
    S.Toggle(a)
    expect(done[R1] == 75 and watch()[R1].met, f"untick share {done[R1]}")
    S.ForgetBought()
    expect(not any(True for _ in ns.char.snipe.done) and not watch()[R1].met, "Forget keeps the met reagents")
    errs = list(ns.errors.values())
    expect(not [e for e in errs if "blocked" not in e], f"errors in the quick-buy checks: {errs[:3]}")


def check_merchant():
    """Merchant capture. Forever loads the Mainline MerchantFrame (C_MerchantFrame.GetItemInfo → a table); the
    global GetMerchantItemInfo is a fallback. Failures go to /crafter errors and say so in chat."""
    # id, price, stack, numAvailable (-1 unlimited, 0 sold out), extended cost, currency
    items = [[THREAD, 12, 1], [DYE, 250, 5, 0], [LINEN, 30, 1, 3],
             [VEST, 500, 1, -1, True], [BOOTS, 1000, 1, -1, False, 1792]]

    def visit(lua, stub, npc="Rachel", event="MERCHANT_SHOW"):
        n0 = len(stub.prints)
        if event == "MERCHANT_SHOW":
            stub.merchant = ltable(lua, {"npc": npc, "items": items})
        stub.fire(event)
        stub.runTimers()
        return prints(stub, n0)

    def captured(ns, how):
        seen = ns.db.vendorSeen
        t, d, l = seen[THREAD], seen[DYE], seen[LINEN]
        expect(t and t.unit == 12 and t.stack == 1 and not t.limited and t.npc == "Rachel", f"{how}: unlimited item")
        expect(d and d.unit == 50 and d.stack == 5 and d.limited, f"{how}: sold-out bundle of 5 (0 available)")
        expect(l and l.unit == 30 and l.limited, f"{how}: limited stock (3 available)")
        expect(seen[VEST] is None and seen[BOOTS] is None, f"{how}: extended-cost or currency item recorded")
        expect(ns.Pricing.VendorUnit(THREAD) == (12, "merchant", False), f"{how}: VendorUnit does not use it")

    def errors(ns):
        return list(ns.errors.values())

    # Forever: no global GetMerchantItemInfo.
    lua, ns, stub = new_runtime(remove=("GetMerchantItemInfo",))
    login(lua, stub)
    changes = lua.eval('function(ns) local c = {n = 0}; ns.Listen("DATA_CHANGED", function() c.n = c.n + 1 end); '
                       'return c end')(ns)
    out = visit(lua, stub)
    captured(ns, "C_MerchantFrame")
    calls = dict(stub.merchantCalls.items())
    expect(calls.get("C_MerchantFrame.GetItemInfo", 0) >= 5 and "GetMerchantItemInfo" not in calls,
           f"C_MerchantFrame.GetItemInfo not used: {calls}")
    expect(out == ["|cff33ccffForeverCrafter|r: 3 vendor prices from Rachel"], f"merchant chat line {out}")
    expect(changes.n == 1 and not errors(ns), f"merchant: {changes.n} recomputes, errors {errors(ns)[:2]}")
    out = visit(lua, stub, event="MERCHANT_UPDATE")
    expect(not out and changes.n == 1, f"unchanged MERCHANT_UPDATE: chat {out}, {changes.n} recomputes")
    stub.merchant["items"][1][2] = 15
    out = visit(lua, stub, event="MERCHANT_UPDATE")
    expect(not out and changes.n == 2 and ns.db.vendorSeen[THREAD].unit == 15,
           f"price change on MERCHANT_UPDATE: chat {out}, {changes.n} recomputes")
    stub.fire("MERCHANT_CLOSED")
    expect(len(visit(lua, stub)) == 1, "no chat line on the next visit")
    stub.merchant = ltable(lua, {"npc": "Empty", "items": []})
    n0 = len(stub.prints)
    stub.fire("MERCHANT_SHOW")
    stub.runTimers()
    expect(not prints(stub, n0) and not errors(ns), "a merchant with no items is not silent")
    n0 = len(stub.prints)
    slash(lua, "status")
    expect(any("3 merchant prices captured" in p for p in prints(stub, n0)), "status does not count merchant prices")

    # Legacy only (Classic frames), and the item id from the link.
    lua, ns, stub = new_runtime(remove=("C_MerchantFrame", "GetMerchantItemID"))
    login(lua, stub)
    out = visit(lua, stub)
    captured(ns, "GetMerchantItemInfo")
    calls = dict(stub.merchantCalls.items())
    expect(calls.get("GetMerchantItemInfo", 0) >= 5 and calls.get("GetMerchantItemLink", 0) >= 3,
           f"legacy merchant API / item link not used: {calls}")
    expect(len(out) == 1 and "3 vendor prices from Rachel" in out[0] and not errors(ns),
           f"legacy path: chat {out}, errors {errors(ns)[:2]}")

    # No price API at all: an error once per session and a chat line per visit.
    lua, ns, stub = new_runtime(remove=("C_MerchantFrame", "GetMerchantItemInfo"))
    login(lua, stub)
    out = visit(lua, stub)
    stub.fire("MERCHANT_CLOSED")
    out2 = visit(lua, stub)
    errs = errors(ns)
    expect(len(errs) == 1 and "merchant: no API for merchant prices" in errs[0], f"missing price API errors {errs}")
    expect(out == out2 == ["|cff33ccffForeverCrafter|r: could not read the vendor prices from Rachel; see /crafter errors"],
           f"missing price API chat {out} {out2}")
    expect(not dict(ns.db.vendorSeen.items()), "prices recorded without a price API")

    # One slot fails: the rest are kept, the failure is visible.
    lua, ns, stub = new_runtime()
    login(lua, stub)
    lua.execute('local f = C_MerchantFrame.GetItemInfo; '
                'C_MerchantFrame.GetItemInfo = function(i) if i == 2 then error("boom") end return f(i) end')
    out = visit(lua, stub)
    errs = errors(ns)
    expect(ns.db.vendorSeen[THREAD] and ns.db.vendorSeen[DYE] is None, "a failing slot stops the others")
    expect(len(errs) == 1 and "could not read 1 of 5 items from Rachel (C_MerchantFrame.GetItemInfo:" in errs[0]
           and "boom" in errs[0], f"failing slot errors {errs}")
    expect(out == ["|cff33ccffForeverCrafter|r: 2 vendor prices from Rachel"], f"failing slot chat {out}")


def check_missing_apis():
    lua, ns, stub = new_runtime(remove=("C_AuctionHouse", "C_SkillInfo", "C_TradeSkillUI", "GetMerchantNumItems"),
                                bad_events=("REPLICATE_ITEM_LIST_UPDATE",))
    login(lua, stub)
    expect("REPLICATE_ITEM_LIST_UPDATE" in dict(ns.missingEvents.items()), "rejected event not recorded")
    stub.fire("AUCTION_HOUSE_SHOW")
    n0 = len(stub.prints)
    slash(lua, "scan")
    expect(any("not available" in p for p in prints(stub, n0)), "scan without ReplicateItems does not say so")
    stub.fire("MERCHANT_SHOW")
    stub.fire("TRADE_SKILL_SHOW")
    stub.runTimers()
    slash(lua, "")
    expect(lua.globals().ForeverCrafterFrame.__shown, "window does not open without the APIs")
    errs = [e for e in ns.errors.values() if "merchant: cannot count the merchant's items" not in e]
    expect(not errs, f"errors without the APIs: {errs[:3]}")
    expect(len(ns.errors) == 1, "a merchant without GetMerchantNumItems is not recorded once in /crafter errors")


def check_full_run():
    """Every recipe known, every profession 300, every item on the AH: the whole solver in one go."""
    lua, ns, stub = new_runtime()
    login(lua, stub, skills={line: 300 for line in (171, 164, 333, 202, 165, 197, 185, 129, 186)},
          known=list(ns.Recipes.keys()))
    listings = []
    for i in ns.Items.keys():
        price = 100 + (i * 7919) % 50000
        listings += [(i, 5, price * 5), (i, 1, price + 10)]
    set_auctions(lua, stub, listings)
    scan(lua, stub)
    start = time.time()
    res, stats = results(ns)
    took = time.time() - start
    expect(took < 20, f"full solver run took {took:.1f} s")
    expect(stats.evaluated > 1500, f"full run evaluated only {stats.evaluated} recipes")
    n = sum(1 for r in res.values() if r.profit > 0)
    expect(n > 100, f"full run found only {n} profitable crafts")
    for r in res.values():
        if not expect(r.value - r.cost == r.profit and r.cost >= 0, f"result {r.spell} profit maths"):
            break
    errs = list(ns.errors.values())
    expect(not errs, f"errors in the full run: {errs[:3]}")
    hidden = sales_hidden(lua, ns, stub, lambda: ns.Planner.Run(), "char")
    check_gold_unchanged(ns, lambda: results(ns)[0], "full run")
    return n, stats.evaluated, took, hidden, shuffle_stats(list(res.values())), time_stats(list(res.values())), \
        batch_stats(ns, list(res.values())), fast_stats(ns, list(res.values()))


MINING, BLACKSMITHING, ENGINEERING, ALCHEMY, COOKING = 186, 164, 202, 171, 185
WI_DEFAULT = {"cap": 150, "overrides": {}, "minConf": 4, "maxPrimaries": 2}

# Random output counts: SpellEffect.Variance at build 1.60.1.70888 read as base x (1 -/+ variance/2) (assumed, see
# SOURCES.md). spell: (base, variance, min, max)
RANDOM_OUTPUT = {3962: (3, 0.6667, 2, 4), 3937: (3, 0.6667, 2, 4), 3950: (3, 0.6667, 2, 4), 3931: (2, 1.0, 1, 3),
                 3946: (3, 1.3333, 1, 5), 3941: (2, 1.0, 1, 3), 8339: (2, 1.0, 1, 3), 435964: (3, 1.0, 2, 4),
                 435966: (3, 1.0, 2, 4)}
R_HEAVY_DYNAMITE, HEAVY_DYNAMITE, HEAVY_POWDER, WOOL = 3946, 4378, 4377, 2592


def check_random_output():
    lua, ns, stub = new_runtime()
    # 1. The generated ranges: these 9 vary, every other recipe makes a fixed count.
    for spell, r in ns.Recipes.items():
        want = RANDOM_OUTPUT.get(spell)
        got = (r.out[2], r.out[3])
        if want:
            expect(got == want[2:], f"Recipes[{spell}] {r.name} makes {got[0]}-{got[1]}, expected {want[2]}-{want[3]}")
        elif not expect(got[0] == got[1], f"Recipes[{spell}] {r.name} makes {got[0]}-{got[1]}: not a random recipe"):
            break

    # 2. Heavy Dynamite (1-5): cost and value use the average 3; worst and best case at 1 and 5.
    login(lua, stub, skills={ENGINEERING: 300}, known=[R_HEAVY_DYNAMITE])
    set_auctions(lua, stub, [(HEAVY_POWDER, 2, 2), (WOOL, 1, 1), (HEAVY_DYNAMITE, 1, 5000), (HEAVY_DYNAMITE, 1, 5200)])
    scan(lua, stub)
    unit = ns.Pricing.SellValue(HEAVY_DYNAMITE).unit
    hd = results(ns)[0].get(R_HEAVY_DYNAMITE)
    if expect(hd is not None, "Heavy Dynamite not evaluated"):
        expect(hd.n == 3 and hd.cost == 3 and hd.value == int(unit * 3) and hd.profit == hd.value - 3,
               f"Heavy Dynamite average: n {hd.n} cost {hd.cost} value {hd.value} (unit {unit})")
        expect(hd.outMin == 1 and hd.outMax == 5 and hd.var, "Heavy Dynamite range not on the result")
        expect(hd.worst == int(unit * 1) - 3 and hd.best == int(unit * 5) - 3,
               f"Heavy Dynamite worst {hd.worst} best {hd.best} (unit {unit})")
        t = ns.UI.DetailText(hd)
        expect("Makes 1-5 (avg 3) x " in t, "detail has no 'Makes 1-5 (avg 3)' line")
        expect(f"worst case (1) profit {ns.Util.Money(hd.worst)}, best case (5) profit {ns.Util.Money(hd.best)}" in t,
               "detail has no worst/best case line")
        expect("makes 1-5 each (avg 3)" in t, "chain tree does not show the range of the craft")
        expect(ns.UI.CellText(hd, "name").replace("|cff40ff40[V]|r ", "").startswith("|cffc080ff[1-5]|r "),
               "list has no [1-5] marker")
        expect("Worst case" in (ns.UI.RandomHint(hd) or ""), "row hint does not explain the random count")

    # 3. The profession window's schematic overrides the static range.
    def schematic_run(out):
        open_ts(lua, stub, ENGINEERING, 300, {R_HEAVY_DYNAMITE: (True, 0, {
            "name": "Heavy Dynamite", "out": [HEAVY_DYNAMITE] + out, "reagents": [[HEAVY_POWDER, 2], [WOOL, 1]]})})
        return results(ns)[0].get(R_HEAVY_DYNAMITE)
    r = schematic_run([2, 6])
    expect(r and r.runtime and r.outMin == 2 and r.outMax == 6 and r.n == 4 and r.value == int(unit * 4),
           "window schematic 2-6 does not override the static 1-5")
    r = schematic_run([3, 3])
    expect(r and r.runtime and r.outMin is None and not r.var and r.n == 3 and "Random count" not in
           ns.UI.DetailText(r), "window schematic 3-3 still shows a random count")

    # 4. A random-count craft as a step of a chain: 7 X needed, X makes 1-5 (avg 3) -> 3 crafts, worst case 7.
    lua, ns, stub = new_runtime()
    login(lua, stub, skills={TAILORING: 300})
    X, Y, TOP = 990301, 990302, 990303
    synthetic(lua, ns, stub, {991301: (X, [[Y, 1]]), 991302: (TOP, [[X, 7]])}, [X, Y, TOP])
    ns.Recipes[991301].out[3] = 5
    set_auctions(lua, stub, [(Y, 10, 100), (X, 1, 100000), (TOP, 1, 1000000)])
    scan(lua, stub)
    top = results(ns)[0].get(991302)
    if expect(top is not None, "chain with a random-count step not evaluated"):
        step = top.tree.children[1]
        expect(step.src == "craft" and step.crafts == 3 and step.outMin == 1 and step.outMax == 5 and top.cost == 30,
               f"random-count step: {step.src} x{step.crafts}, cost {top.cost}")
        expect(top.var and top.outMin is None and top.worst is None, "chain result should be var without its own range")
        t = ns.UI.DetailText(top)
        expect("makes 1-5 each (avg 3), worst case 7 crafts" in t, "chain tree does not show the step's worst case")
        expect("a step of the chain makes a random count" in t, "detail does not mention the random step")
        expect(ns.UI.CellText(top, "name").startswith("|cffc080ff[rnd]|r "), "list has no [rnd] marker")
    errs = list(ns.errors.values())
    expect(not errs, f"errors in the random output checks: {errs[:3]}")


def shuffle_stats(res):
    """Vendor shuffles among results (each must have vendorProfit <= profit, equal when sold to a vendor).
    → (shuffles, of them best sold on the AH, on estimated vendor prices, top 10 by vendor profit)"""
    for r in res:
        if r.vendorProfit is not None and not expect(
                r.vendorProfit <= r.profit and (r.where != "vendor" or r.vendorProfit == r.profit),
                f"result {r.spell}: vendor profit {r.vendorProfit}, profit {r.profit} ({r.where})"):
            break
    sh = [r for r in res if r.vendorProfit is not None and r.vendorProfit > 0]
    top = sorted(sh, key=lambda r: (-r.vendorProfit, r.spell))[:10]
    return len(sh), sum(1 for r in sh if r.where == "ah"), sum(1 for r in sh if r.vendorEst), top


def shuffle_text(st):
    return f"{st[0]} ({st[1]} best sold on the AH, {st[2]} on an estimated vendor price)"


def check_vendor_costs():
    """Data/Vendor.lua against the pinned Wowhead Forever sold-by rows (cost = [[copper, currencies, items]]), and
    entries that cost items, a currency or serve one faction are never a gold source."""
    lua, ns, stub = new_runtime()
    pages = json.load(open(os.path.join(ROOT, "research", "wowhead", "pages_items.json"), encoding="utf-8"))
    pi = {p["id"]: p for p in pages["pages"]}
    n = 0
    for i, v in ns.Vendor.items():
        sb = (pi.get(i) or {}).get("lists", {}).get("sold-by")
        if v.limited or not sb or "wh_item" not in v.src.split("+"):
            continue
        n += 1
        gold, alt, cur = set(), [], []
        for r in sb["rows"]:
            c = r["cost"][0]
            if len(c) > 1 and (c[1] or c[2]):
                alt += [list(x) for x in c[2]]
                cur += [list(x) for x in c[1]]
            else:
                gold.add(round(c[0] * v.vstack / (r.get("stack") or 1)))
        got_alt = [list(x.values()) for x in v.alt.values()] if v.alt else []
        got_cur = [list(x.values()) for x in v.currency.values()] if v.currency else []
        if gold:
            expect(v.price in gold and not got_alt and not got_cur,
                   f"Vendor[{i}] price {v.price} is not a Wowhead sold-by cost {sorted(gold)}")
            buy = ns.Items[i].buy
            expect(buy not in gold or v.price == buy, f"Vendor[{i}] price {v.price}: DB2 BuyPrice {buy} is listed")
        else:
            expect(v.price == 0 and got_alt == alt[:len(got_alt)] and got_cur == cur[:len(got_cur)]
                   and (got_alt or got_cur), f"Vendor[{i}] costs {alt or cur} on Wowhead, has alt/currency "
                   f"{got_alt} {got_cur}")
    expect(n >= 90, f"only {n} unlimited vendor entries checked against Wowhead pages")
    # The reported bug: Lokhtos wants 30x Firelands Ember, Mister Graphed charges 52g 63s 15c for Black Lotus.
    expect(ns.Vendor[7078].alt[1][1] == 227801 and ns.Vendor[7078].alt[1][2] == 30 and ns.Vendor[7078].price == 0,
           "Essence of Fire must cost 30x item 227801")
    expect(ns.Vendor[13468].price == 526315 and ns.Vendor[13468].src == "wh_item", "Black Lotus vendor price")
    expect(ns.Vendor[17010].currency[1][1] == 3469, "Fiery Core costs currency 3469")

    login(lua, stub, skills={TAILORING: 300})
    P = ns.Pricing
    expect(P.VendorUnit(7078) is None and P.VendorUnit(17010) is None, "an item or currency cost used as gold")
    expect(P.VendorUnit(13468) == (526315, "estimate", False), "Black Lotus vendor unit")
    # Rhapsody Malt: every NPC that sells it is Alliance (Wowhead react).
    expect(ns.Vendor[2894].side == "Alliance" and P.VendorUnit(2894) == (50, "estimate", False), "Alliance vendor")
    stub.faction = "Horde"
    expect(P.VendorUnit(2894) is None and P.VendorBlock(ns.Vendor[2894]) == "Alliance vendor",
           "a Horde character must not buy from an Alliance-only vendor")
    stub.faction = "Alliance"
    # A craft from Essence of Fire: no AH listing = no source (the old 16s vendor price is gone); listed = AH.
    OUT, FIRE, THREAD = 990501, 7078, 2320
    synthetic(lua, ns, stub, {995001: (OUT, [[FIRE, 1]]), 995002: (OUT + 1, [[THREAD, 1]])}, [OUT, OUT + 1])
    set_auctions(lua, stub, [(OUT, 1, 100000), (OUT + 1, 1, 100000)])
    scan(lua, stub)
    res, _ = results(ns)
    expect(995001 not in res or res[995001].cost is None, "Essence of Fire priced from a gold vendor")
    expect(995002 in res and res[995002].cost == ns.Vendor[THREAD].price, "a gold vendor reagent must still count")
    set_auctions(lua, stub, [(OUT, 1, 100000), (OUT + 1, 1, 100000), (FIRE, 1, 5000)])
    scan(lua, stub)
    res, _ = results(ns)
    expect(995001 in res and res[995001].cost == 5000, "Essence of Fire from the AH")
    return n


def check_vendor_shuffles():
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub, skills={TAILORING: 300})
    expect(ns.settings.vendorShuffles is False, "Vendor shuffles must default to off")
    R, OA, OB, OC, OD, OE = 990401, 990402, 990403, 990404, 990405, 990406
    A, B, C, D, E = 991401, 991402, 991403, 991404, 991405
    synthetic(lua, ns, stub, {A: (OA, [[R, 2]]), B: (OB, [[R, 2]]), C: (OC, [[R, 2]]), D: (OD, [[R, 2]]),
                              E: (OE, [[R, 2]])}, [R, OA, OB, OC, OD, OE])
    ns.Recipes[E].out[3] = 5                     # E makes 1-5 (avg 3)
    for item, sell in ((OA, 50), (OC, 5), (OE, 30)):
        stub["items"][item] = lua.table_from({"name": f"Test {item}", "sell": sell})   # seen by the client: exact
    ns.Items[OB].sell = 100                      # game data only: an estimate
    set_auctions(lua, stub, [(R, 20, 200), (OA, 1, 1000), (OC, 1, 1000), (OD, 1, 1000), (OE, 1, 1000)])
    scan(lua, stub)
    res, _ = results(ns)
    ah = 999 * 95 // 100
    want = {A: ("ah", ah - 20, 30, False), B: ("vendor", 80, 80, True), C: ("ah", ah - 20, -15, False),
            D: ("ah", ah - 20, None, None), E: ("ah", ah * 3 - 20, 70, False)}
    for spell, (where, profit, vprofit, est) in want.items():
        r = res.get(spell)
        if expect(r is not None, f"shuffle test recipe {spell} not evaluated"):
            got = (r.where, r.profit, r.vendorProfit, r.vendorEst)
            expect(got == (where, profit, vprofit, est), f"recipe {spell}: (where, profit, vendor profit, est) {got}")
    expect(res[E].vendorWorst == 30 - 20 and res[A].vendorWorst is None, "vendor worst case of a random count")

    # The window: off, the AH results with no TSM data are hidden by Min sold/day; on, only shuffles by vendor profit.
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    UI = ns.UI
    view = lambda: [r.spell for r in UI.view.values()]
    expect(not frame.shuffles.__checked and view() == [B], f"checkbox off: {view()}")
    frame.shuffles.SetChecked(frame.shuffles, True)
    frame.shuffles.Click(frame.shuffles)
    expect(ns.settings.vendorShuffles is True and ns.settings.sort == "vprofit", "checkbox does not set the setting")
    expect(view() == [B, E, A] and UI.salesHidden == 0, f"vendor shuffles (Min sold/day 1): {view()}")
    expect("3 vendor shuffles" in frame.status.__text, f"status line {frame.status.__text!r}")
    ns.settings.minListings = 5                  # A's single listing no longer counts: A sells to the vendor
    UI.Recompute()
    expect({r.spell: r.where for r in UI.results.values()}.get(A) == "vendor", "Min AH listings 5: A not sold to vendor")
    expect(view() == [B, E, A] and UI.salesHidden == 0, f"vendor shuffles (Min AH listings 5): {view()}")
    ns.settings.minListings = 1
    UI.Recompute()
    ns.settings.minProfit = 50
    UI.ApplyFilter()
    expect(view() == [B, E], f"Min profit 50 must apply to the vendor profit: {view()}")
    ns.settings.minProfit = 0
    UI.ApplyFilter()

    # Column, marker, hint and detail.
    by = {r.spell: r for r in UI.results.values()}
    cell = UI.CellText
    expect(cell(by[D], "vprofit") == "—" and cell(by[B], "vprofit").endswith(" ~")
           and cell(by[A], "vprofit") == ns.Util.Money(30) and cell(by[C], "vprofit").startswith("|cff808080"),
           f"Vend. profit cells {[cell(by[s], 'vprofit') for s in (A, B, C, D)]}")
    expect(cell(by[A], "name").startswith("|cff40ff40[V]|r ") and "[V]" not in cell(by[C], "name")
           and cell(by[E], "name").startswith("|cff40ff40[V]|r |cffc080ff[1-5]|r "), "[V] marker")
    expect("no AH needed" in (UI.ShuffleHint(by[A]) or "") and UI.ShuffleHint(by[C]) is None
           and "estimate" in UI.ShuffleHint(by[B]), "shuffle row hint")
    t = UI.DetailText(by[A])
    expect(f"Vendor shuffle:|r sell to a vendor instead for {ns.Util.Money(50)} -> profit {ns.Util.Money(30)}" in t,
           "detail of an AH-best shuffle has no vendor shuffle line")
    expect(f"(worst case (1) {ns.Util.Money(10)})" in UI.DetailText(by[E]), "detail has no vendor worst case")
    expect("Vendor shuffle:" not in UI.DetailText(by[B]) and "Vendor shuffle:" not in UI.DetailText(by[C]),
           "vendor shuffle line on a vendor-best result or a non-shuffle")
    UI.Refresh()
    expect("[V] = vendor shuffle" in frame.footer.__text, "footer legend has no [V]")

    # Saved and restored with the other settings; turning it off goes back to sorting by profit.
    saved = stub.savedVariables("ForeverCrafterDB")
    lua2, ns2, stub2 = new_runtime(saved=saved)
    login(lua2, stub2, skills={TAILORING: 300})
    slash(lua2, "")
    f2 = lua2.globals().ForeverCrafterFrame
    expect(ns2.settings.vendorShuffles is True and f2.shuffles.__checked, "Vendor shuffles not restored")
    f2.shuffles.SetChecked(f2.shuffles, False)
    f2.shuffles.Click(f2.shuffles)
    expect(ns2.settings.vendorShuffles is False and ns2.settings.sort == "profit", "checkbox off")
    errs = list(ns.errors.values()) + list(ns2.errors.values())
    expect(not errs, f"errors in the vendor shuffle checks: {errs[:3]}")


def check_cheap_batch():
    """Cheap batch: the most crafts whose own (marginal) profit stays >= 75% of the first craft's, from the AH price
    steps of the snapshot. Profit and g/h become batch averages; the first craft's numbers are kept."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub, skills={TAILORING: 300})
    expect(ns.settings.minBatch == 5, "Min batch must default to 5")
    R1, R2, R3, R4, R5, R6, R7 = 990501, 990502, 990503, 990504, 990505, 990506, 990507
    O1, O2, O3, O4, O5, O6, MID = 990511, 990512, 990513, 990514, 990515, 990516, 990517
    T1, T2, T3, T4, T5, T6, TM = 991501, 991502, 991503, 991504, 991505, 991506, 991507
    synthetic(lua, ns, stub, {T1: (O1, [[R1, 1]]), T2: (O2, [[R2, 1]]), T3: (O3, [[R3, 1]]), T4: (O4, [[R4, 1]]),
                              T5: (O5, [[R5, 1]]), TM: (MID, [[R6, 2]]), T6: (O6, [[MID, 1]])},
              [R1, R2, R3, R4, R5, R6, R7, O1, O2, O3, O4, O5, O6, MID])
    ns.Items[O4].sell = 300
    stub["items"][O4] = lua.table_from({"name": f"Test {O4}", "sell": 300})   # seen by the client: exact
    listings = [(o, 1, 1000) for o in (O1, O2, O3, O4, O5, O6)] + [(MID, 1, 50000)]
    listings += [(R1, 1, 10), (R1, 1, 10)] + [(R1, 1, 1000)] * 100              # 2 cheap, then the bulk
    listings += [(R2, 1, 10), (R2, 1, 20), (R2, 1, 30)] + [(R2, 100, 1000000)]  # rising, then a wall
    listings += [(R3, 1000, 5000)]                                                # deep: 1000 @ 5c
    listings += [(R4, 1, 10), (R4, 1, 50), (R4, 1, 100), (R4, 1, 200), (R4, 100, 500000)]
    listings += [(R5, 1, 10 + i) for i in range(60)]                              # more steps than the snapshot keeps
    listings += [(R6, 4, 40), (R6, 100, 40000)]                                   # the intermediate's reagent
    set_auctions(lua, stub, listings)
    scan(lua, stub)
    res, _ = results(ns)
    worth = 999 * 95 // 100
    got = lambda r: (r.batch, bool(r.batchCapped), r.profit1, r.profit, r.cost1, r.cost)
    # 1. Two cheap listings, then 10s each: 2 crafts.
    r = res.get(T1)
    expect(r and got(r) == (2, False, worth - 10, worth - 10, 10, 10), f"2 cheap listings: {r and got(r)}")
    # 2. Averages vs the first craft: 10c, 20c, 30c, then 100s: 3 crafts at an average cost of 20c.
    r = res.get(T2)
    expect(r and got(r) == (3, False, worth - 10, worth - 20, 10, 20) and r.batchProfit == 3 * worth - 60
           and r.ahProfit == worth - 20, f"rising price steps: {r and got(r)} batch profit {r and r.batchProfit}")
    # 3. Deep supply: the search stops at the cap; shown as at least.
    r = res.get(T3)
    cap = ns.Planner.BATCH_CAP
    expect(r and got(r) == (cap, True, worth - 5, worth - 5, 5, 5), f"deep reagent: {r and got(r)}")
    # 4. Vendor batch vs AH batch: AH first profit 939 allows +245c per craft (4 crafts), vendor 290 only +72c (2).
    r = res.get(T4)
    if expect(r, "vendor batch recipe not evaluated"):
        expect((r.batch, r.vendorBatch, r.vendorProfit1, r.vendorProfit, r.vendorBatchProfit)
               == (4, 2, 290, 270, 600 - 60) and r.profit == worth - 90,
               f"vendor batch: {(r.batch, r.vendorBatch, r.vendorProfit1, r.vendorProfit, r.vendorBatchProfit)}")
    # 5. More price steps than the snapshot keeps: the batch stops where the steps end, as at least.
    r = res.get(T5)
    steps = ns.Scanner.LADDER_STEPS
    expect(r and r.batch == steps and r.batchCapped, f"batch at the end of the price steps: {r and got(r)}")
    # 6. A chain: the intermediate's own reagent gets pricier after 4 (2 crafts of the top recipe); the intermediate
    # itself (sold for 5g) keeps a big batch: 104 reagents make 52.
    r = res.get(T6)
    if expect(r and got(r) == (2, False, worth - 20, worth - 20, 20, 20), f"chain batch {r and got(r)}"):
        shop = {e.id: (e.qty, e.src) for e in ns.Planner.ShoppingList(r.batchTree).values()}
        expect(shop == {R6: (4, "ah")} and r.batchTree.crafts == 2, f"batch shopping list {shop}")
    expect(res.get(TM) and res[TM].batch == 52 and not res[TM].batchCapped, "intermediate batch limited by supply")

    # The window: Min batch 5 hides the small batches; the status line counts them.
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    UI = ns.UI
    ns.settings.minSoldPerDay = 0
    UI.ApplyFilter()
    UI.Refresh()
    view = lambda: {r.spell for r in UI.view.values()}
    expect(view() == {T3, T5, TM} and UI.batchHidden == 4, f"Min batch 5: {view()} hidden {UI.batchHidden}")
    expect("4 hidden: cheap batch under 5" in frame.status.__text, f"status line {frame.status.__text!r}")
    by = {r.spell: r for r in UI.results.values()}
    expect(UI.CellText(by[T3], "batch") == f"{cap}+" and UI.CellText(by[T1], "batch") == "2"
           and UI.CellText(by[T5], "batch") == f"{steps}+", "Batch cells")
    t = UI.DetailText(by[T2])
    expect("Cheap batch:|r 3 crafts" in t and f"avg profit {ns.Util.Money(worth - 20)} (first craft "
           f"{ns.Util.Money(worth - 10)})" in t and "Batch shopping list (3 crafts):" in t
           and f"up to {ns.Util.Money(30)} each" in t, "batch detail of a rising reagent")
    t = UI.DetailText(by[T3])
    expect(f"at least {cap} crafts (the search stops at {cap})" in t, "capped batch detail")
    expect("Vendor batch:|r 2 crafts" in UI.DetailText(by[T4]), "vendor batch line in the detail")
    frame.minBatch.SetText(frame.minBatch, "2")
    frame.minBatch.__scripts.OnEnterPressed(frame.minBatch)
    expect(ns.settings.minBatch == 2 and view() == {T1, T2, T3, T4, T5, T6, TM}, f"Min batch 2: {view()}")
    # Batch profit column: the whole batch's profit; sorted high first, no value last.
    money = ns.Util.Money
    expect(UI.CellText(by[T1], "bprofit") == money(2 * (worth - 10))
           and UI.CellText(by[T4], "bprofit") == money(4 * (worth - 90)), "Batch profit cells")
    order = lambda: [r.spell for r in UI.view.values()]
    heads = {h.col.key: h for h in frame.headers.values() if h.col}
    heads["bprofit"].Click(heads["bprofit"])
    want = sorted((s for s in by if s in view()), key=lambda s: (-by[s].batchProfit, s))
    expect(ns.settings.sort == "bprofit" and ns.settings.sortDesc and order() == want and want[0] == TM,
           f"sorted by Batch profit: {order()} expected {want}")
    none = ltable(lua, {"spell": 1})
    expect(UI.CellText(none, "bprofit") == "—" and UI.SortValue(none, "bprofit") == -math.inf
           and UI.SortValue(by[T1], "bprofit") > UI.SortValue(none, "bprofit"), "no batch profit: — and sorted last")
    frame.minBatch.SetText(frame.minBatch, "0")
    frame.minBatch.__scripts.OnEnterPressed(frame.minBatch)
    expect(ns.settings.minBatch == 2 and frame.minBatch.__text == "2", "Min batch below 1 accepted")
    # Vendor shuffles: the vendor batch counts (T4's is 2; the others have no vendor price).
    ns.settings.minBatch = 3
    frame.shuffles.SetChecked(frame.shuffles, True)
    frame.shuffles.Click(frame.shuffles)
    expect(view() == set() and UI.batchHidden == 1 and UI.CellText(by[T4], "batch") == "2",
           f"vendor shuffles, Min batch 3: {view()} hidden {UI.batchHidden}")
    expect(UI.CellText(by[T4], "bprofit") == money(600 - 60) and UI.SortValue(by[T4], "bprofit") == 540
           and UI.CellText(by[T1], "bprofit") == "—", "vendor shuffles: Batch profit is the vendor batch's")
    by[T4].vendorEst = True
    expect(UI.CellText(by[T4], "bprofit") == money(540) + " ~", "estimated vendor price marked ~")
    by[T4].vendorEst = False
    expect("vendor cheap batch under 3" in frame.status.__text, f"status line {frame.status.__text!r}")
    frame.shuffles.SetChecked(frame.shuffles, False)
    frame.shuffles.Click(frame.shuffles)

    # Saved and restored.
    saved = stub.savedVariables("ForeverCrafterDB")
    lua2, ns2, stub2 = new_runtime(saved=saved)
    login(lua2, stub2, skills={TAILORING: 300})
    expect(ns2.settings.minBatch == 3, f"Min batch not restored: {ns2.settings.minBatch}")
    errs = list(ns.errors.values()) + list(ns2.errors.values())
    expect(not errs, f"errors in the cheap batch checks: {errs[:3]}")


def batch_stats(ns, res):
    """Cheap batch over the profitable results. → (distribution text, hidden at Min batch 5, top AH g/h, top vendor g/h)"""
    prof = [r for r in res if r.profit > 0]
    for r in prof:
        ok = (r.batch is not None and r.batch >= 1 and r.profit1 >= r.profit > 0 and r.profit >= 0.75 * r.profit1
              and r.cost == r.cost1 + r.profit1 - r.profit
              and (r.vendorBatch is None or r.vendorProfit1 > 0 and r.vendorProfit >= 0.75 * r.vendorProfit1))
        if not expect(ok, f"result {r.spell}: batch {r.batch} profit {r.profit1} -> {r.profit}"):
            break
    buckets = [("1", 1, 1), ("2-4", 2, 4), ("5-9", 5, 9), ("10-49", 10, 49), ("50-199", 50, 199), ("200", 200, 200)]
    dist = []
    for label, lo, hi in buckets:
        rs = [r for r in prof if lo <= r.batch <= hi]
        capped = sum(1 for r in rs if r.batchCapped)
        dist.append(f"{label}: {len(rs)}" + (f" ({capped} capped)" if capped else ""))
    hidden = sum(1 for r in prof if r.batch < 5)
    changed = sum(1 for r in prof if r.profit != r.profit1)
    ah = sorted([r for r in prof if r.ahPerHour is not None], key=lambda r: (-r.ahPerHour, r.spell))[:10]
    vend = sorted([r for r in prof if r.vendorPerHour is not None and r.vendorBatch is not None],
                  key=lambda r: (-r.vendorPerHour, r.spell))[:10]
    return f"{', '.join(dist)}; profit below the first craft's: {changed}", hidden, ah, vend


def batch_text(ns, st, label):
    def fmt(r, v, k, capped):
        return (f"{r.name} {re.sub(r'[|]c[0-9a-f]{8}|[|]r', '', ns.UI.PerHourText(v))}/h "
                f"(batch {k}{'+' if capped else ''})")
    return [f"  cheap batch ({label}): {st[0]}; hidden at Min batch 5: {st[1]}",
            "    top AH g/h: " + "; ".join(fmt(r, r.ahPerHour, r.batch, r.batchCapped) for r in st[2]),
            "    top Vend g/h: " + "; ".join(fmt(r, r.vendorPerHour, r.vendorBatch, r.vendorBatchCapped)
                                           for r in st[3])]


def deep_listings(ns, kind):
    """Synthetic snapshots for the cheap batch. infinite: one stack of 100000 per item (the first-craft price never
    runs out); graded: per item 3, 15 or 60 listings of 1-5, each step 3% dearer, or one stack of 500."""
    out = []
    for i in ns.Items.keys():
        price = 100 + (i * 7919) % 50000
        if kind == "infinite":
            out.append((i, 100000, price * 100000))
            continue
        depth = (3, 15, 60, 0)[i % 4]
        if depth == 0:
            out.append((i, 500, price * 500))
        for j in range(depth):
            q = 1 + (i + j) % 5
            out.append((i, q, int(price * 1.03 ** j) * q))
    return out


def check_batch_depth():
    """Infinite depth: every result equals the first craft (= main). Graded depth: distribution, timings, top 10."""
    lines = []
    for kind in ("infinite", "graded"):
        lua, ns, stub = new_runtime()
        login(lua, stub, skills={line: 300 for line in (171, 164, 333, 202, 165, 197, 185, 129, 186)},
              known=list(ns.Recipes.keys()))
        set_auctions(lua, stub, deep_listings(ns, kind))
        t0 = time.time()
        scan(lua, stub)
        scan_took = time.time() - t0
        t0 = time.time()
        res, _ = results(ns)
        took = time.time() - t0
        char = list(res.values())
        t0 = time.time()
        wres, _ = wi_run(lua, ns)
        wtook = time.time() - t0
        frames, last = [], [time.time()]

        def progress(i, n):
            now = time.time()
            frames.append(now - last[0])
            last[0] = now

        ns.Planner.RunAsync(ltable(lua, {"whatIf": WI_DEFAULT}), progress, lambda r, st: None)
        stub.runTimers()
        wi = list(wres.values())
        if kind == "infinite":
            for r in char + wi:
                ok = (r.profit == r.profit1 and r.cost == r.cost1 and r.vendorProfit == r.vendorProfit1
                      and (r.profit <= 0 or r.batchCapped and (r.vendorBatch is None or r.vendorBatchCapped)
                           or r.cd and r.batch == 1 and r.vendorBatch in (None, 1)
                           # A bigger batch crafts an intermediate the first craft buys (a step that makes several,
                           # e.g. Gold Power Core x3 in Steam Tonk Controller): the extra cost per craft steps, so the
                           # search may end early. The profit still equals the first craft's.
                           or r.batchTree and ns.Planner.PathSig(r.batchTree) != ns.Planner.PathSig(r.tree)))
                if not expect(ok, f"infinite depth: {r.spell} profit {r.profit1} -> {r.profit} batch {r.batch} "
                                  f"capped {r.batchCapped}"):
                    break
            caps = sum(1 for r in char if r.profit > 0 and r.batch == ns.Planner.BATCH_CAP)
            lines.append(f"  infinite depth: every profit equals the first craft's; batch at the cap "
                         f"{caps} of {sum(1 for r in char if r.profit > 0)}; full run {took:.2f} s, what-if "
                         f"{wtook:.2f} s, slowest frame async {max(frames) * 1000:.0f} ms")
        else:
            lines.append(f"  graded depth: scan {scan_took:.2f} s, full run {took:.2f} s, what-if {wtook:.2f} s, "
                         f"slowest frame async {max(frames) * 1000:.0f} ms")
            lines += batch_text(ns, batch_stats(ns, char), "graded, My character")
            lines += batch_text(ns, batch_stats(ns, wi), "graded, What-if")
            check_gold_unchanged(ns, lambda: results(ns)[0], "graded full run")
            check_gold_unchanged(ns, lambda: wi_run(lua, ns)[0], "graded what-if")
            lines += fast_text(fast_stats(ns, char), "graded, My character")
            lines += fast_text(fast_stats(ns, wi), "graded, What-if")
        errs = list(ns.errors.values())
        expect(not errs, f"errors in the {kind} depth run: {errs[:3]}")
    return lines


def time_stats(res):
    """Crafting time over results: each time is the chain's crafts x cast, per hour = profit / time.
    → (results with an unknown time, top 10 by AH g/h, top 10 by vendor g/h)"""
    for r in res:
        ok = r.time is not None and r.casts >= 1 and (r.timeUnknown or r.time > 0)
        if ok and r.cd:
            # One craft per cooldown: no g/h, no fast path, a batch of 1.
            ok = (r.ahPerHour is None and r.vendorPerHour is None and r.fastAH is None and r.fastVendor is None
                  and r.batch in (None, 1))
        elif ok and r.time > 0 and not r.timeUnknown:
            ok = ((r.ahProfit is None) == (r.ahPerHour is None)
                  and (r.vendorProfit is None) == (r.vendorPerHour is None)
                  and (r.ahPerHour is None or abs(r.ahPerHour - r.ahProfit / r.time * 3600) < 1e-6)
                  and (r.ahProfit is None or r.ahProfit <= r.profit))
        if not expect(ok, f"result {r.spell}: time {r.time} casts {r.casts} unknown {r.timeUnknown} "
                          f"ah {r.ahProfit}/{r.ahPerHour} vendor {r.vendorProfit}/{r.vendorPerHour}"):
            break
    prof = [r for r in res if r.profit > 0]
    unknown = sum(1 for r in res if r.timeUnknown)
    ah = sorted([r for r in prof if r.ahPerHour is not None], key=lambda r: (-r.ahPerHour, r.spell))[:10]
    vend = sorted([r for r in prof if r.vendorPerHour is not None], key=lambda r: (-r.vendorPerHour, r.spell))[:10]
    return unknown, ah, vend


def time_text(ns, st, label):
    def fmt(r, v):
        return f"{r.name} {re.sub(r'[|]c[0-9a-f]{8}|[|]r', '', ns.UI.PerHourText(v))}/h ({ns.UI.TimeText(r.time)})"
    return [f"  crafting time ({label}): {st[0]} results with an unknown time",
            "  top AH g/h: " + "; ".join(fmt(r, r.ahPerHour) for r in st[1]),
            "  top Vend g/h: " + "; ".join(fmt(r, r.vendorPerHour) for r in st[2])]


R_TRUESILVER_CHAMPION = 10015


def check_crafting_time():
    lua, ns, stub = new_runtime()
    g = lua.globals()
    # 1. Cast times from SpellMisc -> SpellCastTimes.Base (build 1.60.1.70888); every recipe has one.
    expect(ns.Recipes[R_HEAVY_DYNAMITE].cast == 5125 and ns.Recipes[R_TRUESILVER_CHAMPION].cast == 60000,
           "cast times of Heavy Dynamite / Truesilver Champion")
    missing = [k for k, r in ns.Recipes.items() if r.cast is None]
    expect(not missing, f"recipes without a cast time: {missing[:5]}")

    # 2. A 3-step chain: ORE -> BAR (3 s), 2 BAR -> POWDER (5 s), 4 POWDER + 1 BAR -> TOP (10 s).
    #    1 TOP + 4 POWDER + (8 + 1) BAR crafts = 14 casts, 10 + 20 + 27 = 57 s.
    login(lua, stub, skills={TAILORING: 300})
    ORE, BAR, POWDER, TOP, VOUT, AOUT = 990501, 990502, 990503, 990504, 990505, 990506
    R_BAR, R_POWDER, R_TOP, R_VOUT, R_AOUT = 991501, 991502, 991503, 991504, 991505
    synthetic(lua, ns, stub, {R_BAR: (BAR, [[ORE, 1]]), R_POWDER: (POWDER, [[BAR, 2]]),
                              R_TOP: (TOP, [[POWDER, 4], [BAR, 1]]), R_VOUT: (VOUT, [[ORE, 1]]),
                              R_AOUT: (AOUT, [[ORE, 1]])}, [ORE, BAR, POWDER, TOP, VOUT, AOUT])
    for spell, ms in ((R_BAR, 3000), (R_POWDER, 5000), (R_TOP, 10000), (R_VOUT, 2000), (R_AOUT, 4000)):
        ns.Recipes[spell].cast = ms
    stub["items"][TOP] = lua.table_from({"name": "Test top", "sell": 0})
    stub["items"][VOUT] = lua.table_from({"name": "Test vendor", "sell": 500})    # vendor only: not on the AH
    set_auctions(lua, stub, [(ORE, 50, 500), (BAR, 1, 100000), (POWDER, 1, 100000), (TOP, 1, 1000000),
                             (AOUT, 1, 20000)])
    scan(lua, stub)
    res, _ = results(ns)
    top, vout, aout = res.get(R_TOP), res.get(R_VOUT), res.get(R_AOUT)
    if expect(top is not None and vout is not None and aout is not None, "crafting time recipes not evaluated"):
        expect((top.time, top.casts, top.timeUnknown) == (57, 14, False),
               f"chain time {top.time} s, {top.casts} casts, unknown {top.timeUnknown}")
        expect(top.profit == top.ahProfit and top.vendorProfit is None and top.vendorPerHour is None
               and abs(top.ahPerHour - top.profit / 57 * 3600) < 1e-6, "AH-only item: AH g/h, no vendor g/h")
        expect(vout.where == "vendor" and vout.ahProfit is None and vout.ahPerHour is None
               and vout.vendorPerHour == vout.vendorProfit / 2 * 3600 == (500 - 10) * 1800, "vendor-only item")
        expect(aout.ahPerHour == aout.ahProfit / 4 * 3600, "AH g/h of a single craft")
        t = ns.UI.DetailText(top)
        expect(f"Crafting time 57 s (14 casts)  |  AH {ns.Util.Money(math.floor(top.ahPerHour + 0.5))}/h  |  vendor —"
               in t, "detail has no crafting time line")
        expect("time between casts are not included" in t, "detail has no note on what the time leaves out")
        expect("(1 craft of Make 990504, 10 s)" in t and "(4 crafts of Make 990503, 20 s)" in t
               and "(8 crafts of Make 990502, 24 s)" in t and "(1 craft of Make 990502, 3 s)" in t,
               "chain tree does not show each step's time")
        cell = ns.UI.CellText
        expect(cell(top, "time") == "57s" and cell(top, "vgh") == "—" and cell(vout, "ahgh") == "—"
               and cell(vout, "vgh") == ns.UI.PerHourText(vout.vendorPerHour) and cell(top, "ahgh").endswith("g"),
               f"time/g/h cells {[cell(top, k) for k in ('time', 'ahgh', 'vgh')]} {cell(vout, 'ahgh')}")
        expect(ns.UI.TimeText(75) == "1 min 15 s" and ns.UI.TimeText(75, True) == "1m15s"
               and ns.UI.TimeText(5.125) == "5.1 s" and ns.UI.TimeText(7380, True) == "2h03m", "time formats")
        expect(ns.UI.PerHourText(-250) == "|cff808080-2s|r" and ns.UI.PerHourText(12, True) == "12c ~",
               "per-hour text")

    # Every column fits in a list row, in both modes.
    for mode, cols in ns.UI.COLUMNS.items():
        w = sum(c.width for c in cols.values())
        expect(w <= ns.UI.ROW_W, f"{mode} columns are {w} px wide, a row only {ns.UI.ROW_W}")
    w = sum(c.width for c in ns.Sniper.CRAFT_COLUMNS.values())
    expect(w <= ns.UI.ROW_W, f"sniper crafts columns are {w} px wide, a row only {ns.UI.ROW_W}")

    # 3. Sorting: AH g/h and Vend g/h high first (no value last); Time short first.
    ns.settings.minSoldPerDay = 0
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    UI = ns.UI
    view = lambda: [r.spell for r in UI.view.values()]
    heads = {h.col.key: h for h in frame.headers.values() if h.col}

    def order(key):
        return [s for s, _ in sorted(((s, getattr(res[s], key)) for s in (R_TOP, R_VOUT, R_AOUT, R_BAR, R_POWDER)
                                      if s in res and res[s].profit > 0),
                                     key=lambda x: (-(x[1] if x[1] is not None else -1e18), x[0]))]
    heads["ahgh"].Click(heads["ahgh"])
    expect(ns.settings.sort == "ahgh" and ns.settings.sortDesc and view() == order("ahPerHour"),
           f"sorted by AH g/h: {view()} expected {order('ahPerHour')}")
    expect(view()[-1] == R_VOUT, "a result with no AH g/h must sort last")
    heads["vgh"].Click(heads["vgh"])
    expect(ns.settings.sort == "vgh" and view() == order("vendorPerHour") and view()[0] == R_VOUT,
           f"sorted by Vend g/h: {view()}")
    heads["time"].Click(heads["time"])
    times = [res[s].time for s in view()]
    expect(ns.settings.sort == "time" and not ns.settings.sortDesc and times == sorted(times),
           f"sorted by Time (short first): {times}")

    # 4. Unknown time: a step with no cast time -> "at least", ">", no per hour, sorted after known times.
    ns.Recipes[R_POWDER].cast = None
    UI.Recompute()
    by = {r.spell: r for r in UI.results.values()}
    top = by[R_TOP]
    expect(top.timeUnknown and top.time == 37 and top.ahPerHour is None and top.vendorPerHour is None
           and top.profit == res[R_TOP].profit, f"unknown time: {top.time} s, AH g/h {top.ahPerHour}")
    expect("at least 37 s" in UI.DetailText(top) and "time unknown" in UI.DetailText(top)
           and UI.CellText(top, "time") == "|cffff8040>37s|r" and UI.CellText(top, "ahgh") == "—",
           "unknown time in the detail and cells")
    expect(view()[-1] == R_TOP, f"unknown time must sort after known times: {view()}")
    ns.Recipes[R_POWDER].cast = 5000

    # 5. The profession window's cast time (C_Spell.GetSpellInfo castTime) overrides the game data.
    open_ts(lua, stub, TAILORING, 300, {s: (True, 0, None) for s in (R_BAR, R_POWDER, R_TOP, R_VOUT, R_AOUT)},
            casts={R_TOP: 2500, R_BAR: 0})
    # castTime 0 (an unknown or unlearned spell) must not replace the game data's time with "instant".
    expect(ns.char.casts[R_TOP] == 2500 and ns.char.casts[R_BAR] is None and ns.char.casts[R_POWDER] is None,
           "cast times from the window not stored (or a 0 stored)")
    expect(ns.Planner.CastMs(R_TOP) == (2500, "game") and ns.Planner.CastMs(R_POWDER) == (5000, "db2")
           and ns.Planner.CastMs(R_BAR) == (3000, "db2"), "CastMs source")
    res2, _ = results(ns)
    expect(res2[R_TOP].time == 2.5 + 20 + 27 and res2[R_TOP].ahPerHour is not None and res2[R_TOP].casts == 14 and res2[R_TOP].profit == res[R_TOP].profit,
           f"window cast times: chain {res2[R_TOP].time} s")
    saved = stub.savedVariables("ForeverCrafterDB")
    lua2, ns2, stub2 = new_runtime(saved=saved)
    login(lua2, stub2, skills={TAILORING: 300})
    expect(ns2.char.casts[R_TOP] == 2500, "window cast times not saved")
    errs = list(ns.errors.values()) + list(ns2.errors.values())
    expect(not errs, f"errors in the crafting time checks: {errs[:3]}")


FAST_MARK = "|cff66e0ff*|r"


def gold_fields(ns, r):
    """The most-gold path's numbers: they must not depend on the best-g/h paths."""
    return (r.profit, r.cost, r.cost1, r.profit1, r.value, r.where, r.ahProfit, r.vendorProfit, r.vendorProfit1,
            r.batch, r.batchCapped, r.batchProfit, r.vendorBatch, r.vendorBatchCapped, r.vendorBatchProfit, r.time,
            r.casts, r.timeUnknown, r.ahPerHour, r.vendorPerHour, ns.Planner.PathSig(r.tree))


def check_gold_unchanged(ns, run, label):
    """run() → {spell: result}. The Profit-side fields with and without the best-g/h paths must be equal."""
    on = run()
    ns.Planner.FAST_PATHS = False
    try:
        off = run()
    finally:
        ns.Planner.FAST_PATHS = True
    expect(set(on) == set(off), f"{label}: best-g/h paths change the result set")
    for spell, r in on.items():
        o = off.get(spell)
        if o is None:
            continue
        if not expect(gold_fields(ns, r) == gold_fields(ns, o) and o.fastAH is None and o.fastVendor is None,
                      f"{label}: result {spell} most-gold fields differ with best-g/h paths on"):
            break
    return on


def fast_stats(ns, res):
    """Best-g/h paths over the results: each one beats its most-gold path (Dinkelbach never does worse) and its
    numbers add up. → (results, differ on AH, differ on vendor, top 10 by AH g/h, top 10 by vendor g/h)"""
    PL = ns.Planner
    for r in res:
        ok = True
        for side, gold, worth in (("fastAH", r.ahPerHour, r.ahProfit is not None and r.ahProfit + r.cost),
                                  ("fastVendor", r.vendorPerHour, r.vendorProfit is not None and r.vendorProfit + (
                                      r.cost if r.vendorBatch is None or r.vendorBatch == r.batch else 0))):
            f = getattr(r, side)
            if f is None:
                continue
            ok = (gold is not None and gold > 0 and f.perHour > gold and f.time > 0 and f.batch >= 1
                  and f.profit1 >= f.profit > 0 and f.profit >= 0.75 * f.profit1 and f.cost1 + f.profit1 == f.cost + f.profit
                  and abs(f.perHour - f.profit / f.time * 3600) < 1e-6 and PL.PathSig(f.tree) != PL.PathSig(r.tree)
                  and PL.PathSig(f.batchTree) == PL.PathSig(f.tree) and f.batchTree.crafts == f.batch)
            if not ok:
                break
        bah, _ = PL.AHPerHour(r)
        bv, _ = PL.VendorPerHour(r)
        ok = ok and (r.ahPerHour is None or bah >= r.ahPerHour) and (r.vendorPerHour is None or bv >= r.vendorPerHour)
        if not expect(ok, f"result {r.spell}: best-g/h path below or equal to the most-gold path"):
            break
    prof = [r for r in res if r.profit > 0]
    ah = sorted([r for r in prof if PL.AHPerHour(r)[0] is not None], key=lambda r: (-PL.AHPerHour(r)[0], r.spell))[:10]
    vend = sorted([r for r in prof if PL.VendorPerHour(r)[0] is not None],
                  key=lambda r: (-PL.VendorPerHour(r)[0], r.spell))[:10]

    def fmt(r, get):
        v, f = get(r)
        k, capped, t = (f.batch, f.batchCapped, f.time) if f else (r.batch, r.batchCapped, r.time)
        return (f"{r.name} {re.sub(r'[|]c[0-9a-f]{8}|[|]r', '', ns.UI.PerHourText(v))}/h{'*' if f else ''} "
                f"({ns.UI.TimeText(t)}, batch {k}{'+' if capped else ''})")
    return (len(prof), sum(1 for r in prof if r.fastAH), sum(1 for r in prof if r.fastVendor),
            [fmt(r, PL.AHPerHour) for r in ah], [fmt(r, PL.VendorPerHour) for r in vend])


def fast_text(st, label):
    return [f"  best-g/h paths ({label}): differ from the most-gold path for {st[1]} of {st[0]} profitable results on "
            f"the AH, {st[2]} on the vendor",
            "    top AH g/h (* = best-g/h path): " + "; ".join(st[3]),
            "    top Vend g/h: " + "; ".join(st[4])]


def check_fast_path():
    """Best-g/h path: buying bars beats smelting them on g/h but not on gold; equal paths; no path when the
    most-gold g/h is <= 0; a two-reagent mix against brute force; vendor-only output; the list and details."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    PL = ns.Planner
    login(lua, stub, skills={TAILORING: 300})
    ORE, BAR, TOP, VTOP, BAR2, EQ, LOSS = 990601, 990602, 990603, 990604, 990605, 990606, 990607
    A_ORE, A, B_ORE, B, MIX, SOLO = 990608, 990609, 990610, 990611, 990612, 990613
    R_BAR, R_TOP, R_VTOP, R_BAR2, R_EQ, R_LOSS = 991601, 991602, 991603, 991604, 991605, 991606
    R_A, R_B, R_MIX, R_SOLO = 991607, 991608, 991609, 991610
    recipes = {R_BAR: (BAR, [[ORE, 1]]), R_TOP: (TOP, [[BAR, 2]]), R_VTOP: (VTOP, [[BAR, 2]]),
               R_BAR2: (BAR2, [[ORE, 1]]), R_EQ: (EQ, [[BAR2, 1]]), R_LOSS: (LOSS, [[BAR, 2]]),
               R_A: (A, [[A_ORE, 1]]), R_B: (B, [[B_ORE, 1]]), R_MIX: (MIX, [[A, 1], [B, 1]]), R_SOLO: (SOLO, [[ORE, 3]])}
    synthetic(lua, ns, stub, recipes, [ORE, BAR, TOP, VTOP, BAR2, EQ, LOSS, A_ORE, A, B_ORE, B, MIX, SOLO])
    casts = {R_BAR: 30000, R_TOP: 5000, R_VTOP: 5000, R_BAR2: 3000, R_EQ: 5000, R_LOSS: 5000, R_A: 20000,
             R_B: 4000, R_MIX: 2000, R_SOLO: 5000}
    for spell, ms in casts.items():
        ns.Recipes[spell].cast = ms
    stub["items"][VTOP] = lua.table_from({"name": "Test vendor top", "sell": 50000})
    deep = lambda i, p: (i, 10000, p * 10000)
    set_auctions(lua, stub, [deep(ORE, 10), deep(BAR, 30), (TOP, 1, 100000), deep(BAR2, 100000), (EQ, 1, 50000),
                             (LOSS, 1, 20), deep(A_ORE, 10), deep(A, 400), deep(B_ORE, 10), deep(B, 2000),
                             (MIX, 1, 3200), (SOLO, 1, 100000)])
    scan(lua, stub)
    res, _ = results(ns)
    top, vtop, eq, loss, mix, solo = (res.get(s) for s in (R_TOP, R_VTOP, R_EQ, R_LOSS, R_MIX, R_SOLO))
    if not expect(None not in (top, vtop, eq, loss, mix, solo), "best-g/h recipes not evaluated"):
        return
    # 1. Smelting 2 bars costs 20c and 60 s; buying them 60c and 0 s: Profit keeps smelting, AH g/h buys.
    f = top.fastAH
    expect(top.cost == 20 and top.tree.children[1].src == "craft" and top.time == 65, "TOP's most-gold path smelts")
    if expect(f is not None, "TOP has no best-g/h path"):
        expect(f.cost1 == 60 and f.time == 5 and f.tree.children[1].src == "ah" and f.profit == top.value - 60
               and f.perHour == f.profit / 5 * 3600 and f.perHour > top.ahPerHour and f.batch == PL.BATCH_CAP
               and f.batchCapped, f"TOP best-g/h path: cost {f.cost1} time {f.time} batch {f.batch}")
        expect(PL.AHPerHour(top)[0] == f.perHour and top.fastVendor is None, "TOP's AH g/h is the best-g/h path's")
        expect(top.profit == top.value - 20, "TOP's Profit must stay on the most-gold path")
    # Vendor-only output: the vendor sale gets its own best-g/h path.
    expect(vtop.where == "vendor" and vtop.fastAH is None and vtop.fastVendor is not None
           and vtop.fastVendor.cost1 == 60 and vtop.fastVendor.perHour == (vtop.value - 60) / 5 * 3600,
           "vendor-only output: best-g/h path for the vendor sale")
    # 2. Equal: a bar from 10c of ore in 3 s against 100000c on the AH; and a recipe with nothing to craft.
    expect(eq.profit > 0 and eq.fastAH is None and PL.AHPerHour(eq)[0] == eq.ahPerHour, "EQ: paths are equal")
    expect(solo.profit > 0 and solo.fastAH is None, "SOLO: nothing crafted below the root, no best-g/h path")
    # 3. lambda <= 0: an unprofitable craft gets no best-g/h path (buying would only lose faster).
    expect(loss.profit <= 0 and loss.ahPerHour <= 0 and loss.fastAH is None, "LOSS: no best-g/h path at g/h <= 0")
    # 4. Two reagents, each crafted or bought: Dinkelbach finds the best of the four by brute force.
    w, best = mix.value, None
    for buy_a in (False, True):
        for buy_b in (False, True):
            c = (400 if buy_a else 10) + (2000 if buy_b else 10)
            t = 2 + (0 if buy_a else 20) + (0 if buy_b else 4)
            gh = (w - c) / t * 3600
            if best is None or gh > best[0]:
                best = (gh, buy_a, buy_b)
    expect(best[1:] == (True, False), f"MIX brute force should buy A and craft B: {best}")
    fm = mix.fastAH
    if expect(fm is not None, "MIX has no best-g/h path"):
        expect(abs(fm.perHour - best[0]) < 1e-6 and [c.src for c in fm.tree.children.values()] == ["ah", "craft"]
               and 1 <= fm.rounds <= PL.FAST_ROUNDS, f"MIX best-g/h path {fm.perHour} vs brute force {best[0]}")
    # 5. The list: g/h cells marked *, sorted on the best-g/h path; the details show what differs.
    cell = ns.UI.CellText
    expect(cell(top, "ahgh") == ns.UI.PerHourText(f.perHour) + FAST_MARK and cell(eq, "ahgh") == ns.UI.PerHourText(
        eq.ahPerHour) and cell(vtop, "vgh").endswith(FAST_MARK), "g/h cells and their * marker")
    t = re.sub(r"[|]c[0-9a-f]{8}|[|]r", "", ns.UI.DetailText(top))
    expect(f"Fastest path (AH): buy Test {BAR} on the AH instead of crafting it (Make {BAR}) -> profit" in t
           and "(this path; a faster one below)" in t and "Fastest path (AH), 1 craft, 5 s:" in t
           and f"Buy Test {BAR} x2 from AH" in t and "Its shopping list (first craft):" in t
           and "Its batch shopping list (200 crafts):" in t, "details: the fastest path section")
    expect("Fastest path" not in ns.UI.DetailText(eq), "details: no fastest path when the paths are equal")
    # The Time cell follows the g/h: the AH best-g/h path's time with * (not a shuffle), else the most-gold time.
    expect(not ns.UI.IsShuffle(top) and cell(top, "time") == ns.UI.TimeText(f.time, True) + FAST_MARK
           and ns.UI.SortValue(top, "time") == f.time and top.time == 65, f"TOP time cell {cell(top, 'time')!r}")
    expect(cell(eq, "time") == ns.UI.TimeText(eq.time, True) and ns.UI.SortValue(eq, "time") == eq.time,
           f"EQ time cell {cell(eq, 'time')!r}")
    ns.settings.minSoldPerDay = 0
    ns.settings.minBatch = 0
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    heads = {h.col.key: h for h in frame.headers.values() if h.col}
    heads["ahgh"].Click(heads["ahgh"])
    view = [r for r in ns.UI.view.values()]
    vals = [PL.AHPerHour(r)[0] for r in view if PL.AHPerHour(r)[0] is not None]
    spells = [r.spell for r in view]
    # TOP's most-gold g/h is below EQ's, its best-g/h path's above.
    expect(len(vals) >= 4 and vals == sorted(vals, reverse=True) and top.ahPerHour < eq.ahPerHour < f.perHour
           and spells.index(R_TOP) < spells.index(R_EQ), f"sorted on the best-g/h AH g/h: {spells}")
    # The Profit side is the same with the best-g/h paths off.
    check_gold_unchanged(ns, lambda: results(ns)[0], "best-g/h synthetic")
    errs = list(ns.errors.values())
    expect(not errs, f"errors in the best-g/h checks: {errs[:3]}")


def tree_ids(node, out=None):
    out = set() if out is None else out
    out.add(node.id)
    if node.src == "craft":
        for c in node.children.values():
            tree_ids(c, out)
    return out


def check_fast_batch_path():
    """Heavy Dynamite: the best-g/h path buys the powder, but its few cheap listings run out and crafting the powder
    wins again at a bigger batch. The fast batch must end there (buy powder, no stone), its g/h is that batch's
    profit over the fast time, the Time cell shows the fast time, and the sniper watches the powder."""
    lua, ns, stub = new_runtime()
    PL, UI, S = ns.Planner, ns.UI, ns.Sniper
    login(lua, stub, skills={TAILORING: 300})
    STONE, POWDER, BOOM = 990701, 990702, 990703
    R_POWDER, R_BOOM = 991701, 991702
    synthetic(lua, ns, stub, {R_POWDER: (POWDER, [[STONE, 1]]), R_BOOM: (BOOM, [[POWDER, 1]])}, [STONE, POWDER, BOOM])
    ns.Recipes[R_POWDER].cast = 30000
    ns.Recipes[R_BOOM].cast = 5000
    stub["items"][BOOM] = lua.table_from({"name": "Test boom", "sell": 1000})
    # Stone is cheap and deep; three cheap powders (20, 25, 30c), then only dear ones.
    set_auctions(lua, stub, [(STONE, 10000, 10 * 10000), (POWDER, 1, 20), (POWDER, 1, 25), (POWDER, 1, 30),
                             (POWDER, 50, 50000 * 50)])
    scan(lua, stub)
    res, _ = results(ns)
    r = res.get(R_BOOM)
    if not expect(r is not None and r.where == "vendor" and UI.IsShuffle(r), "boom: a vendor shuffle"):
        return
    f = r.fastVendor
    # Most-gold: craft the powder from stone (10c, 35 s); best-g/h: buy the powder (5 s).
    expect(r.time == 35 and r.tree.children[1].src == "craft", f"boom most-gold path: time {r.time}")
    if not expect(f is not None and f.time == 5 and f.tree.children[1].src == "ah", "boom: no best-g/h vendor path"):
        return
    ids = tree_ids(f.batchTree)
    expect(f.batch == 3 and not f.batchCapped and f.batchTree.crafts == 3 and f.batchTree.children[1].src == "ah"
           and POWDER in ids and STONE not in ids, f"boom fast batch {f.batch}: {sorted(ids)}")
    expect(PL.PathSig(f.batchTree) == PL.PathSig(f.tree), "boom fast batch left its path")
    # Batch average 25c: g/h = (1000 - 25) / 5 s.
    expect(f.cost == 25 and f.batchProfit == 3 * 1000 - 75 and f.perHour == (1000 - 25) / 5 * 3600
           and abs(f.perHour - f.batchProfit / f.batch / f.time * 3600) < 1e-6, f"boom fast g/h {f.perHour}")
    cell = UI.CellText
    expect(cell(r, "vgh").endswith(FAST_MARK) and cell(r, "time") == UI.TimeText(5, True) + FAST_MARK
           and UI.SortValue(r, "time") == 5, f"boom time cell {cell(r, 'time')!r}")
    # The sniper watches the powder for the fast batch, not the stone.
    lim = S.RowLimit(r, S.Kind(r))
    watched = {k: v.qty for k, v in lim.reagents.items()}
    expect(S.Kind(r) == "vendor" and watched == {POWDER: 3}, f"boom sniper watches {watched}")
    errs = list(ns.errors.values())
    expect(not errs, f"errors in the fast batch checks: {errs[:3]}")


def wi_run(lua, ns, **kw):
    """A what-if run with the default settings changed by kw. → ({spell: result}, stats)"""
    w = dict(WI_DEFAULT)
    w.update(kw)
    res, stats = ns.Planner.Run(ltable(lua, {"whatIf": w}))
    return {r.spell: r for r in res.values()}, stats


def wi_world(lua, ns, stub, recipes, auctions):
    """Only made-up recipes (the real ones removed): recipes {spell: dict(line, learn, out, reagents[, how, acquire,
    items, known])}; auctions [(item, stack, buyout)]. A character with no professions."""
    for k in list(ns.Recipes.keys()):
        ns.Recipes[k] = None
    items = set(a[0] for a in auctions)
    for d in recipes.values():
        items.add(d["out"])
        items.update(x[0] for x in d["reagents"])
    for i in items:
        ns.Items[i] = ltable(lua, {"name": f"Test {i}", "q": 1, "sell": 0, "buy": 0, "src": "db2",
                                   "verified": "2026-11-12"})
    for spell, d in recipes.items():
        r = {"name": f"Make {d['out']}", "skill": d["line"], "learn": d["learn"], "trivLo": d["learn"],
             "trivHi": d["learn"] + 40, "out": [d["out"], 1, 1], "reagents": d["reagents"], "how": d.get("how", [6]),
             "cost": d.get("cost", 100), "items": d.get("items", []), "acquire": d.get("acquire", 0), "src": "db2",
             "verified": "2026-11-12"}
        if d.get("known"):
            r["known"] = "2026-11-12"
        ns.Recipes[spell] = ltable(lua, r)
    login(lua, stub)
    set_auctions(lua, stub, auctions)
    scan(lua, stub)


def char_fingerprint(ns):
    res, stats = ns.Planner.Run()
    return (sorted((r.spell, r.profit, r.cost, r.value, bool(r.known), bool(r.learnable), r.where, r.color)
                   for r in res.values()), stats.evaluated, stats.noPrice)


def check_what_if():
    # 1. Cap, overrides and a chain across professions: Mining smelts the bar a Blacksmithing recipe needs.
    lua, ns, stub = new_runtime()
    ORE, BAR, BRACER = 990001, 990002, 990003
    R_SMELT, R_BRACER = 991001, 991002
    wi_world(lua, ns, stub, {
        R_SMELT: dict(line=MINING, learn=50, out=BAR, reagents=[[ORE, 1]]),
        R_BRACER: dict(line=BLACKSMITHING, learn=100, out=BRACER, reagents=[[BAR, 2]]),
    }, [(ORE, 10, 100), (BAR, 5, 5000), (BRACER, 1, 10000), (BRACER, 1, 10000)])
    res, st = wi_run(lua, ns)
    b = res.get(R_BRACER)
    if expect(b and b.cost == 20 and b.whatIf, f"what-if: bracer from smelted ore should cost 20, got {b and b.cost}"):
        expect([(p.line, p.rank) for p in b.profs.values()] == [(MINING, 50), (BLACKSMITHING, 100)],
               "what-if: chain professions/ranks wrong")
        expect(b.primaries == 2 and ns.UI.ProfsText(b) == "Min+BS", f"what-if: profs text {ns.UI.ProfsText(b)}")
        expect([s.spell for s in b.steps.values()] == [R_SMELT, R_BRACER], "what-if: chain steps not leaves-first")
        expect(b.conf == 2 and b.learnCost == 200 and b.learnUnknown == 0 and b.payback == -(-200 // b.profit),
               f"what-if: conf/learning cost {b.conf} {b.learnCost} {b.payback}")
    expect(st.whatIf and st.sets == 1, "what-if: two primary professions in the data should be 1 set at max 2")
    res, _ = wi_run(lua, ns, cap=90)
    expect(R_BRACER not in res and R_SMELT in res, "what-if: cap 90 must drop the rank 100 recipe only")
    res, _ = wi_run(lua, ns, cap=90, overrides={BLACKSMITHING: 100})
    expect(R_BRACER in res, "what-if: Blacksmithing override 100 does not allow the bracer")
    res, _ = wi_run(lua, ns, overrides={MINING: 40})
    b = res.get(R_BRACER)
    expect(b and b.cost == 2000 and R_SMELT not in res and [p.line for p in b.profs.values()] == [BLACKSMITHING],
           "what-if: Mining override 40 must buy the bars on the AH")
    res, _ = wi_run(lua, ns, maxPrimaries=1)
    b = res.get(R_BRACER)
    expect(b and b.cost == 2000 and b.primaries == 1, "what-if: max 1 primary must buy the bars")
    # The profession filter matches any profession in the chain: Mining shows the Blacksmithing bracer.
    # Made-up item IDs have no TSM sales data: the Min sold/day filter is off here (check_sales tests it).
    ns.settings.mode, ns.settings.profession, ns.settings.minSoldPerDay = "whatIf", MINING, 0
    ns.UI.results, ns.UI.stats = ns.Planner.Run(ltable(lua, {"whatIf": WI_DEFAULT}))
    ns.UI.ApplyFilter()
    expect(sorted(r.spell for r in ns.UI.view.values()) == [R_SMELT, R_BRACER],
           "what-if profession filter must match any profession in the chain")
    ns.settings.mode, ns.settings.profession, ns.settings.minSoldPerDay = "char", 0, 1
    # "My character" mode is unaffected (no professions: nothing to show).
    expect(len(results(ns)[0]) == 0, "what-if recipes leak into My character results")

    # 2. Max primaries: the cheapest chain needs Alchemy + Engineering + Tailoring.
    lua, ns, stub = new_runtime()
    RAW, Q, P, X, RAW2, S, Y = 990010, 990011, 990012, 990013, 990014, 990015, 990016
    R_Q, R_P, R_X, R_S, R_Y = 991010, 991011, 991012, 991013, 991014
    wi_world(lua, ns, stub, {
        R_Q: dict(line=ALCHEMY, learn=10, out=Q, reagents=[[RAW, 1]]),
        R_P: dict(line=ENGINEERING, learn=10, out=P, reagents=[[Q, 1]]),
        R_X: dict(line=TAILORING, learn=10, out=X, reagents=[[P, 1]]),
        R_S: dict(line=COOKING, learn=10, out=S, reagents=[[RAW2, 1]]),
        R_Y: dict(line=TAILORING, learn=10, out=Y, reagents=[[S, 1]]),
    }, [(RAW, 1, 1), (Q, 1, 500), (P, 1, 5000), (X, 1, 20000), (X, 1, 20000), (RAW2, 1, 3), (S, 1, 900),
        (Y, 1, 20000), (Y, 1, 20000)])
    for mp, cost, lines in ((0, 1, [ALCHEMY, ENGINEERING, TAILORING]), (3, 1, [ALCHEMY, ENGINEERING, TAILORING]),
                            (2, 500, [ENGINEERING, TAILORING]), (1, 5000, [TAILORING])):
        res, st = wi_run(lua, ns, maxPrimaries=mp)
        x = res.get(R_X)
        expect(x and x.cost == cost and sorted(p.line for p in x.profs.values()) == sorted(lines),
               f"what-if max {mp}: X costs {x and x.cost}, needs {x and [p.line for p in x.profs.values()]}")
        y = res.get(R_Y)
        expect(y and y.cost == 3 and y.primaries == 1 and ns.UI.ProfsText(y) == "Cook+Tail",
               f"what-if max {mp}: Cooking (secondary) must not count toward the limit")
    expect(wi_run(lua, ns, maxPrimaries=2)[1].sets == 3 and wi_run(lua, ns, maxPrimaries=0)[1].sets == 1,
           "what-if: set counts")

    # 3. Confidence levels; a chain takes its least sure recipe.
    conf = {R_Q: dict(how=[6], acquire=0), R_P: dict(how=[2], acquire=0), R_X: dict(how=[], acquire=1),
            R_S: dict(how=[], acquire=0), R_Y: dict(how=[], known=True)}
    lua, ns, stub = new_runtime()
    base = {R_Q: dict(line=ALCHEMY, learn=10, out=Q, reagents=[[RAW, 1]]),
            R_P: dict(line=ENGINEERING, learn=10, out=P, reagents=[[Q, 1]]),
            R_X: dict(line=TAILORING, learn=10, out=X, reagents=[[P, 1]]),
            R_S: dict(line=COOKING, learn=10, out=S, reagents=[[RAW2, 1]]),
            R_Y: dict(line=TAILORING, learn=10, out=Y, reagents=[[S, 1]])}
    for k, v in conf.items():
        base[k].update(v)
    auctions = [(RAW, 1, 1), (Q, 1, 500), (P, 1, 5000), (X, 1, 20000), (X, 1, 20000), (RAW2, 1, 3), (S, 1, 900),
                (Y, 1, 20000), (Y, 1, 20000)]
    wi_world(lua, ns, stub, base, auctions)
    PL = ns.Planner
    levels = {s: PL.Confidence(s, ns.Recipes[s]) for s in base}
    expect(levels == {R_Q: 2, R_P: 4, R_X: 3, R_S: 5, R_Y: 1}, f"confidence levels {levels}")
    VEND_RECIPE, DROP_RECIPE = 990020, 990021
    ns.Items[VEND_RECIPE] = ltable(lua, {"name": "Pattern", "how": [5], "from": [["vendor", "A", "B"]]})
    ns.Items[DROP_RECIPE] = ltable(lua, {"name": "Pattern", "how": [2], "from": [["drop", "A", "B"]]})
    expect(PL.Confidence(1, ltable(lua, {"skill": TAILORING, "how": [], "items": [VEND_RECIPE]})) == 2,
           "confidence: recipe item sold by a vendor is not level 2")
    expect(PL.Confidence(1, ltable(lua, {"skill": TAILORING, "how": [], "items": [DROP_RECIPE], "acquire": 1})) == 4,
           "confidence: recipe item from a drop is not level 4")
    stub.known[R_S] = True
    ns.char.known[R_S] = True
    expect(PL.Confidence(R_S, ns.Recipes[R_S]) == 1, "confidence: known on this character is not level 1")
    ns.char.known[R_S] = None
    stub.known[R_S] = None
    res, st = wi_run(lua, ns, maxPrimaries=0, minConf=5)
    x, y = res.get(R_X), res.get(R_Y)
    expect(x and x.conf == 4 and x.confSpell == R_P and x.cost == 1, "confidence: chain must take its lowest (4)")
    expect(y and y.conf == 5 and y.confSpell == R_S, "confidence: Unknown step must make the chain Unknown")
    expect(list(st.byConf.values()) == [1, 1, 1, 1, 1], f"confidence counts {list(st.byConf.values())}")
    res, _ = wi_run(lua, ns, maxPrimaries=0)
    y = res.get(R_Y)
    expect(R_S not in res and y and y.cost == 900 and y.conf == 1,
           "minConf 4 must hide Unknown recipes and their chains")
    res, _ = wi_run(lua, ns, maxPrimaries=0, minConf=2)
    x = res.get(R_X)
    expect(not x, "minConf 2 must hide a Likely final recipe")
    res, _ = wi_run(lua, ns, maxPrimaries=0, minConf=3)
    x = res.get(R_X)
    expect(x and x.cost == 5000 and x.conf == 3, "minConf 3 must buy the Drop-only step's output")

    # 4. The window, settings and /crafter cap on real data; "My character" results unchanged.
    lua, ns, stub = new_runtime()
    g = lua.globals()
    tailoring_world(lua, stub)
    scan(lua, stub)
    before = char_fingerprint(ns)
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    expect(ns.settings.mode == "char" and not frame.wi.cap.__shown, "what-if controls shown in My character mode")
    frame.mode.Click(frame.mode)
    expect(ns.settings.mode == "whatIf" and ns.UI.calculating is not None, "mode button does not start a what-if run")
    stub.runTimers()
    expect(ns.UI.calculating is None and ns.UI.stats.whatIf, "what-if run does not finish through the timers")
    expect(all(r.whatIf for r in ns.UI.view.values()) and len(ns.UI.view) > 0, "what-if view is empty or mixed")
    expect(frame.wi.cap.__shown and not frame.known.__shown, "what-if controls not swapped in")
    labels = [h.col.label for h in frame.headers.values() if h.col]
    expect(labels == ["S", "Recipe", "Profit", "Vend. profit", "%", "Profs", "Conf", "Sell", "Sold/d", "Batch",
                     "Batch profit", "Time", "AH g/h", "Vend g/h"],
           f"what-if columns {labels}")
    rows = [f for f in stub.frames.values() if f.result is not None and f.result.whatIf]
    if expect(rows, "what-if rows missing"):
        rows[0].Click(rows[0])
        detail = frame.detail.__text
        expect("Recipes in the chain" in detail and "Confidence" in detail and "What-if" in detail,
               "what-if detail misses the chain recipes/confidence")
    frame.wi.conf.Click(frame.wi.conf)
    frame.wi.max.Click(frame.wi.max)
    stub.runTimers()
    expect(ns.settings.whatIf.minConf == 5 and ns.settings.whatIf.maxPrimaries == 3, "cycle buttons")
    expect(ns.UI.stats.sets == 35, f"max 3 of 7 primaries should be 35 sets, got {ns.UI.stats.sets}")
    frame.wi.cap.SetText(frame.wi.cap, "75")
    frame.wi.cap.__scripts.OnEnterPressed(frame.wi.cap)
    stub.runTimers()
    expect(ns.settings.whatIf.cap == 75, "skill cap box")
    expect(all(p.rank <= 75 for r in ns.UI.results.values() for p in r.profs.values()), "cap 75 not applied")
    ns.settings.profession = TAILORING
    ns.UI.ApplyFilter()
    expect(len(ns.UI.view) > 0 and all(any(p.line == TAILORING for p in r.profs.values())
                                       for r in ns.UI.view.values()), "what-if profession filter")
    ns.settings.profession = 0
    frame.wi.overrides.Click(frame.wi.overrides)
    pop = g.ForeverCrafterOverrides
    if expect(pop and pop.__shown, "overrides popup does not open"):
        box = pop.boxes[BLACKSMITHING]
        box.SetText(box, "200")
        box.__scripts.OnEnterPressed(box)
        expect(ns.settings.whatIf.overrides[BLACKSMITHING] == 200, "override box")
    for cmd, check, msg in (
            ("cap 150", lambda w: w.cap == 150, "cap 150"),
            ("cap bs clear", lambda w: w.overrides[BLACKSMITHING] is None, "cap bs clear"),
            ("cap first aid 75", lambda w: w.overrides[129] == 75, "cap first aid 75"),
            ("cap Mining 300", lambda w: w.overrides[MINING] == 300, "cap Mining 300"),
            ("cap first aid clear", lambda w: w.overrides[129] is None, "cap first aid clear")):
        slash(lua, cmd)
        expect(check(ns.settings.whatIf), f"/crafter {cmd}")
    n0 = len(stub.prints)
    slash(lua, "cap")
    slash(lua, "cap nothing 5")
    out = " ".join(prints(stub, n0))
    expect("what-if skill cap 150" in out and "Mining 300" in out and "no profession" in out, f"/crafter cap: {out}")
    ns.settings.whatIf.overrides[MINING] = None
    frame.mode.Click(frame.mode)
    stub.runTimers()
    expect(ns.settings.mode == "char" and not any(r.whatIf for r in ns.UI.view.values()), "back to My character")
    expect(char_fingerprint(ns) == before, "My character results changed after what-if runs")
    errs = list(ns.errors.values())
    expect(not errs, f"errors in what-if mode: {errs[:3]}")


def check_what_if_full():
    """Real data, nothing known, every item on the AH: what-if at cap 150 and max 2 primaries. → summary, top 10"""
    lua, ns, stub = new_runtime()
    login(lua, stub)
    listings = []
    for i in ns.Items.keys():
        price = 100 + (i * 7919) % 50000
        listings += [(i, 5, price * 5), (i, 1, price + 10)]
    set_auctions(lua, stub, listings)
    scan(lua, stub)
    out = {}
    for mp in (2, 0):
        start = time.time()
        res, st = wi_run(lua, ns, maxPrimaries=mp)
        out[mp] = (res, st, time.time() - start)
    res, st, took = out[2]
    expect(took < 20, f"what-if run took {took:.1f} s")
    expect(st.sets == 21, f"max 2 of 7 primaries should be 21 sets, got {st.sets}")
    profit = [r for r in res.values() if r.profit > 0]
    expect(len(profit) > 50, f"what-if found only {len(profit)} profitable crafts")
    for r in res.values():
        if not expect(r.value - r.cost == r.profit and r.primaries <= 2 and r.conf <= 4
                      and all(p.rank <= 150 for p in r.profs.values()), f"what-if result {r.spell}"):
            break
    # Async: one set per frame; the slowest frame is what the player feels.
    frames, last = [], [time.time()]

    def progress(i, n):
        now = time.time()
        frames.append(now - last[0])
        last[0] = now

    done = {}
    ns.Planner.RunAsync(ltable(lua, {"whatIf": WI_DEFAULT}), progress, lambda r, s: done.update(n=len(r)))
    stub.runTimers()
    expect(done.get("n") == len(res), "RunAsync results differ from Run")
    errs = list(ns.errors.values())
    expect(not errs, f"errors in the what-if run: {errs[:3]}")
    top = sorted(profit, key=lambda r: -r.profit)[:10]
    hidden = sales_hidden(lua, ns, stub, lambda: ns.Planner.Run(ltable(lua, {"whatIf": WI_DEFAULT})), "whatIf")
    check_gold_unchanged(ns, lambda: wi_run(lua, ns)[0], "what-if")
    return (f"what-if run (cap 150, max 2 primaries): {st.sets} sets, {st.evaluated} recipes evaluated, "
            f"{len(profit)} profitable, {took:.2f} s in one go (any number of primaries: {out[0][2]:.2f} s), "
            f"slowest frame async {max(frames) * 1000:.0f} ms"), top, hidden, shuffle_stats(list(res.values())), \
        time_stats(list(res.values())), batch_stats(ns, list(res.values())), fast_stats(ns, list(res.values()))


def sales_hidden(lua, ns, stub, run, mode):
    """Profitable results the default Min sold/day filter (1) hides, with the test snapshot's region set to EU, then
    US. run() → the Planner's results. → {region: (hidden, no data, under 1, shown at filter 0)}"""
    out = {}
    for reg in ("EU", "US"):
        stub.regionName = reg
        ns.Sales.Reset()
        ns.UI.results, ns.UI.stats = run()
        ns.settings.mode, ns.settings.profession = mode, 0
        ns.settings.minSoldPerDay, ns.settings.minBatch = 0, 1
        ns.UI.ApplyFilter()
        all_view = list(ns.UI.view.values())
        ns.settings.minSoldPerDay = 1
        ns.UI.ApplyFilter()
        kept = {r.spell for r in ns.UI.view.values()}
        gone = [r for r in all_view if r.spell not in kept]
        expect(len(gone) == ns.UI.salesHidden and all(r.where == "ah" for r in gone),
               f"{mode} {reg}: the sales filter hid {len(gone)} ({ns.UI.salesHidden} counted), vendor sales among them")
        expect(all(ns.UI.SalesOK(r, 1) for r in ns.UI.view.values()), f"{mode} {reg}: a result under 1/day shown")
        out[reg] = (len(gone), sum(1 for r in gone if r.sales is None), sum(1 for r in gone if r.sales is not None),
                    len(all_view))
    ns.settings.minBatch = 5
    stub.regionName = "EU"
    ns.Sales.Reset()
    ns.settings.mode = "char"
    return out


def hidden_text(h):
    return "; ".join(f"{reg} {n} of {total} ({nodata} no TSM data, {low} under 1/day)"
                     for reg, (n, nodata, low, total) in h.items())


def check_sales_tsm_empty():
    """TSM installed but with no region data (Desktop App never run): full My character and what-if runs must stay
    cheap (the scale detection is tried once per run, never per item) and use the snapshot; once TSM has data, the
    next run uses it."""
    lua, ns, stub = new_runtime()
    login(lua, stub, skills={line: 300 for line in (171, 164, 333, 202, 165, 197, 185, 129, 186)},
          known=list(ns.Recipes.keys()))
    listings = []
    for i in ns.Items.keys():
        price = 100 + (i * 7919) % 50000
        listings += [(i, 5, price * 5), (i, 1, price + 10)]
    set_auctions(lua, stub, listings)
    scan(lua, stub)
    lua.execute("""
      TSM_STUB = { calls = 0, live = {} }
      TSM_API = { GetCustomPriceValue = function(key, s)
        TSM_STUB.calls = TSM_STUB.calls + 1
        local e = TSM_STUB.live[tonumber(s:match("^i:(%d+)$"))]
        if not e then return nil end
        return key == "DBRegionSoldPerDay" and e[1] or e[2]
      end }
    """)
    tsm = lua.globals().TSM_STUB
    eu = ns.SalesData.regions.eu
    for region in ("EU", "KR"):
        stub.regionName = region
        ns.Sales.Reset()
        tsm.calls = 0
        res, _ = ns.Planner.Run()
        res = list(res.values())
        wres, _ = ns.Planner.Run(ltable(lua, {"whatIf": WI_DEFAULT}))
        wres = list(wres.values())
        expect(tsm.calls < 5000, f"TSM with no data ({region}): {tsm.calls} TSM_API calls in a full run and a what-if run")
        srcs = {r.sales.src for r in res + wres if r.sales is not None}
        expect(srcs == ({"snapshot"} if region == "EU" else set()),
               f"TSM with no data ({region}): sales sources {srcs}")
    # TSM gets its data later: the next run picks it up.
    stub.regionName = "EU"
    ns.Sales.Reset()
    ns.Planner.Run()
    for i, v in eu["items"].items():
        tsm.live[i] = lua.table_from([v[1] * 2, v[2]])
    tsm.calls = 0
    res, _ = ns.Planner.Run()
    live = [r for r in res.values() if r.sales is not None]
    expect(live and all(r.sales.src == "tsm" for r in live), "the run after TSM loads its data must use it")
    expect(tsm.calls < 10000, f"{tsm.calls} TSM_API calls in a run with TSM data")
    errs = list(ns.errors.values())
    expect(not errs, f"errors with TSM and no data: {errs[:3]}")
    return tsm.calls


def check_sales():
    """TSM sold per day: the bundled snapshot by region, the TSM addon's live values and their scale, the filter."""
    lua, ns, stub = new_runtime()
    g = lua.globals()
    login(lua, stub)
    S = ns.Sales
    eu, us = ns.SalesData.regions.eu, ns.SalesData.regions.us
    both = sorted(i for i in eu["items"].keys() if us["items"][i] is not None and eu["items"][i][1] >= 1
                  and us["items"][i][1] != eu["items"][i][1])
    item = both[0]
    # Snapshot, by region name and by region number.
    key, name = S.Region()
    expect((key, name) == ("eu", "EU"), f"Sales.Region() with GetCurrentRegionName EU = {key}, {name}")
    e = S.Get(item)
    expect(e and e.src == "snapshot" and e.perDay == eu["items"][item][1] and e.rate == eu["items"][item][2]
           and e.updated == eu.updated, f"EU snapshot Sales.Get({item})")
    for reg_name, reg_num, want in (("US", 3, "us"), (None, 1, "us"), (None, 3, "eu"), ("", 3, "eu")):
        stub.regionName, stub.region = reg_name, reg_num
        S.Reset()
        expect(S.Region()[0] == want, f"region name {reg_name!r} number {reg_num} → {S.Region()}, want {want}")
    stub.regionName, stub.region = "US", 1
    S.Reset()
    e = S.Get(item)
    expect(e and e.src == "snapshot" and e.perDay == us["items"][item][1], f"US snapshot Sales.Get({item})")
    expect(S.Get(2) is None and S.Get(None) is None, "Sales.Get of an item with no data")
    for reg_name, reg_num in (("KR", 2), (None, 2), (None, None)):
        stub.regionName, stub.region = reg_name, reg_num
        S.Reset()
        expect(S.Region()[0] is None and S.Get(item) is None, f"region {reg_name!r}/{reg_num} must have no snapshot")
    n0 = len(stub.prints)
    slash(lua, "status")
    out = "\n".join(prints(stub, n0))
    expect("region unknown" in out and "no TSM snapshot" in out,
           f"/crafter status with an unknown region: {out}")
    del g["GetCurrentRegionName"], g["GetCurrentRegion"]
    S.Reset()
    expect(S.Region()[0] is None and S.Get(item) is None, "a client without the region functions must have no snapshot")
    lua.execute("function GetCurrentRegionName() return STUB.regionName end "
                "function GetCurrentRegion() return STUB.region end")

    # The TSM addon: live values, scaled x1000 (sold/day) and x100 (sale rate) or raw.
    stub.regionName, stub.region = "EU", 3
    lua.execute("""
      TSM_STUB = { perDay = 1000, rate = 100, live = {}, calls = 0 }
      TSM_API = { GetCustomPriceValue = function(key, s)
        TSM_STUB.calls = TSM_STUB.calls + 1
        if TSM_STUB.fail then error("TSM is broken") end
        local id = tonumber(s:match("^i:(%d+)$"))
        local e = TSM_STUB.live[id]
        if not e then return nil end
        if key == "DBRegionSoldPerDay" then return e[1] * TSM_STUB.perDay end
        if key == "DBRegionSaleRate" then return e[2] * TSM_STUB.rate end
      end }
    """)
    tsm = g.TSM_STUB

    def feed(scale_d, scale_r, factor=1.1, region=eu):
        tsm.perDay, tsm.rate = scale_d, scale_r
        for i, v in region["items"].items():
            tsm.live[i] = lua.table_from([v[1] * factor, min(v[2] * factor, 1)])

    S.Reset()
    a = S.Get(item)
    expect(a and a.src == "snapshot", "TSM loaded without values must fall back to the snapshot")
    feed(1000, 100)
    b = S.Get(item)
    expect(b and b.src == "snapshot", "a failed scale detection must not be retried before the next run")
    S.NewRun()
    b = S.Get(item)
    expect(b and b.src == "tsm" and abs(b.perDay - eu["items"][item][1] * 1.1) < 1e-6
           and abs(b.rate - min(eu["items"][item][2] * 1.1, 1)) < 1e-6,
           f"TSM live x1000/x100 not read back (got {b and (b.src, b.perDay, b.rate)}): an item read before TSM had "
           f"values must not stay cached")
    n0 = len(stub.prints)
    slash(lua, "status")
    out = "\n".join(prints(stub, n0))
    expect("scale 1000 (sale rate 100)" in out and "compared with the snapshot" in out and "EU" in out,
           f"/crafter status with TSM live: {out}")
    tsm.live[item] = None
    S.Reset()
    feed(1000, 100)
    tsm.live[item] = None
    c = S.Get(item)
    expect(c and c.src == "snapshot", "an item TSM has no value for must fall back to the snapshot")
    S.Reset()
    feed(1, 1)
    d = S.Get(item)
    expect(d and d.src == "tsm" and abs(d.perDay - eu["items"][item][1] * 1.1) < 1e-6, "TSM live raw values")
    S.Reset()
    tsm.fail = True
    e = S.Get(item)
    expect(e and e.src == "snapshot", "a TSM_API that errors must fall back to the snapshot")
    tsm.fail = False
    # No snapshot for the region (KR): the scale comes from the sale rate alone.
    stub.regionName = "KR"
    S.Reset()
    feed(1000, 1000)
    f = S.Get(item)
    expect(f and f.src == "tsm" and abs(f.perDay - eu["items"][item][1] * 1.1) < 1e-6,
           f"TSM live with no snapshot (KR, x1000): {f and (f.src, f.perDay)}")
    n0 = len(stub.prints)
    slash(lua, "status")
    out = "\n".join(prints(stub, n0))
    expect("scale 1000" in out and "from the sale rate" in out and "no TSM snapshot" in out,
           f"/crafter status with TSM and no snapshot: {out}")
    lua.execute("TSM_API = nil")
    stub.regionName = "EU"
    S.Reset()
    check_sales_tsm_empty()

    # Texts and the filter rule.
    expect([S.Format(x) for x in (None, 0.25, 3.44, 12.6)] == ["—", "0.25", "3.4", "13"], "Sales.Format")
    expect(S.DetailText(None) == "No TSM sales data for this item", "detail text without data")
    t = S.DetailText(S.Get(item))
    expect(t.startswith("Sells ~") and "/day in EU (TSM snapshot " + eu.updated[:10] + ")" in t and "sale rate" in t,
           f"detail text {t!r}")
    r = lambda where, sales: ltable(lua, {"where": where, "sales": sales})
    ok = ns.UI.SalesOK
    expect(ok(r("vendor", None), 1) and ok(r("vendor", {"perDay": 0.1}), 5), "vendor sales must never be hidden")
    expect(not ok(r("ah", None), 1) and not ok(r("ah", {"perDay": 0.5}), 1) and ok(r("ah", {"perDay": 1}), 1),
           "AH sales under the minimum or with no data must be hidden")
    expect(ok(r("ah", None), 0) and ok(r("ah", None), None), "filter 0 must hide nothing")

    # In the window: a result with no TSM data shows "—", and filter 0 shows exactly what the filter ignores.
    tailoring_world(lua, stub)
    scan(lua, stub)
    expect(ns.settings.minSoldPerDay == 1, "Min sold/day must default to 1")
    slash(lua, "")
    frame = g.ForeverCrafterFrame
    ns.settings.minSoldPerDay = 0
    ns.UI.ApplyFilter()
    view0 = [x.spell for x in ns.UI.view.values()]
    expect(ns.UI.salesHidden == 0 and view0, "filter 0 hides results")
    labels = [h.col.label for h in frame.headers.values() if h.col]
    expect(labels == ["S", "Recipe", "Profit", "Vend. profit", "%", "Sell", "Listed", "Sold/d", "Batch", "Batch profit",
                     "Time", "AH g/h", "Vend g/h"],
           f"My character columns {labels}")
    ns.UI.Refresh()
    cells = [f.cells[8].__text for f in stub.frames.values() if f.cells is not None and f.result is not None]
    expect(cells and all(c == S.Format(x.sales and x.sales.perDay) for c, x in
                         zip(cells, ns.UI.view.values())), f"Sold/d cells {cells}")
    frame.minSold.SetText(frame.minSold, "2.5")
    frame.minSold.__scripts.OnEnterPressed(frame.minSold)
    expect(ns.settings.minSoldPerDay == 2.5 and frame.minSold.__text == "2.5", "Min sold/day box")
    frame.minSold.SetText(frame.minSold, "-1")
    frame.minSold.__scripts.OnEnterPressed(frame.minSold)
    expect(ns.settings.minSoldPerDay == 2.5, "Min sold/day box must reject negatives")
    frame.minSold.SetText(frame.minSold, "1")
    frame.minSold.__scripts.OnEnterPressed(frame.minSold)
    expect(frame.minSold.__text == "1" and "Sold/day: TSM EU snapshot" in frame.status.__text,
           f"status line {frame.status.__text!r}")
    rows = [x for x in stub.frames.values() if x.result is not None]
    if rows:
        rows[0].Click(rows[0])
        expect("TSM" in frame.detail.__text, "detail pane has no TSM sales line")
    errs = list(ns.errors.values())
    expect(not errs, f"errors in the sales checks: {errs[:3]}")


R_KNOWN_EXCL, R_LISTED_EXCL = 7636, 8778  # Tailoring recipes on no Wowhead Forever list (excluded_recipes.txt)
SOURCE_TEXT = ("|cFFFFD200Trainer: |rAny Tailoring trainer|n|cFFFFD200Cost: |r50"
               "|TInterface\\MoneyFrame\\UI-SilverIcon:0:0:2:0|t")


HORDE_REP = 2587
W_FROST, W_INVIS, W_SHOT = 264056, 264057, 264037       # Expert, Expert, Journeyman (Solid Shot x200)
Q_FROST, Q_INVIS = 94256, 94257
C_ORE, C_INGOTS, C_EMPTY = 248683, 248703, 248549       # Apprentice white (5 favor) / green (10), unidentified
S_INGOTS, RECEIPT = 248770, 262902                      # Sealed Apprentice Crate (green), Forged Delivery Receipt
FRIENDLY_AT = {"reaction": 5, "currentStanding": 3500, "currentReactionThreshold": 3000, "nextReactionThreshold": 9000}


def rep_world(standing=FRIENDLY_AT, goal=250, favor=None, bags=None, remove=()):
    """A Horde character with a small AH: Frost writ 6000 - 3600 pouch = 2400 for 125 (19.2c/rep), Invisibility writ
    17400 (139.2c/rep); green crate + 20 Copper Bars 900 for 10 favor, white crate + 20 Copper Ore 600 for 5; one
    unidentified crate 100. One listing of each crate, so the plan's second notarised crate runs out."""
    lua, ns, stub = new_runtime(remove=remove)
    stub.faction = "Horde"
    if standing:
        stub.factions[HORDE_REP] = ltable(lua, standing)
    if favor is not None:
        stub.currency[3402] = favor
    for i, n in (bags or {}).items():
        stub.bags[i] = n
    login(lua, stub)
    set_auctions(lua, stub, [(W_FROST, 1, 1000), (6050, 1, 5000), (W_INVIS, 1, 1000), (3823, 1, 20000),
                             (C_INGOTS, 1, 300), (2840, 20, 600), (C_ORE, 1, 200), (2770, 20, 400), (C_EMPTY, 1, 100)])
    scan(lua, stub)
    ns.settings.repGoal = goal
    return lua, ns, stub


def rep_options(ns, standing=True):
    opts, plan, st = ns.Reputation.Run()
    return {o.key: o for o in opts.values()}, plan, st


def plan_steps(plan):
    return [(s.kind, s.writ or s.n, s.cost, s.rep) for s in plan.steps.values()]


def check_reputation():
    lua, ns, stub = rep_world()
    R = ns.Reputation
    o, plan, st = rep_options(ns)
    expect(st and st.reaction == 5 and st.label == "Friendly", f"standing {st and st.reaction}")
    frost, invis, crate = o.get(f"writ:{W_FROST}"), o.get(f"writ:{W_INVIS}"), o.get("crate")
    fg, fw = o.get(f"favor:{C_INGOTS}"), o.get(f"favor:{C_ORE}")
    expect(len(o) == 181, f"{len(o)} options, expected 150 writs + 1 crate + 30 fills")
    expect(frost.cost == 2400 and frost.rep == 125 and frost.per == 2400 / 125 and frost.repSrc == "user",
           f"Frost writ {frost.cost} {frost.rep} {frost.per}")
    expect(invis.cost == 17400 and invis.per == 17400 / 125, f"Invisibility writ {invis.cost}")
    # Receipt = 15 x the cheapest copper per favor (green: 900 / 10) + the cheapest empty crate (100).
    expect(crate.cost == 15 * 90 + 100 and crate.rep == 50 and not crate.gated and crate.empty.id == C_EMPTY,
           f"notarised crate {crate.cost} {crate.rep}")
    expect(fg.favor == 10 and fg.perFavor == 90 and fw.favor == 5 and fw.perFavor == 120, "white vs green favor")
    expect(R.CellText(fg, "rtier") == "Apprentice (g)" and R.CellText(fw, "rtier") == "Apprentice (w)"
           and R.CellText(fg, "rrep") == "10 fav" and R.CellText(fg, "rper").endswith(" /fav"), "fill cells")
    art = o.get("favor:248697")
    expect(art.favor is None and "? fav" in R.CellText(art, "rrep") and art.missing, "Artisan favor is unknown")
    expect(R.CellText(frost, "rrep").startswith("|cffff8040"), "unverified writ rep is not orange")
    shot = o.get(f"writ:{W_SHOT}")
    expect(shot.missing and R.CellText(shot, "rper") == "—", "an unlisted writ is priced")
    # Cheapest per rep first: Frost writ, then the crate (beats the Invisibility writ), then the fill it uses.
    ranked = [x.key for x in sorted(o.values(), key=lambda x: (R.SortValue(x, "rper"), x.key))]
    expect(ranked[:5] == [f"writ:{W_FROST}", "crate", f"favor:{C_INGOTS}", f"favor:{C_ORE}", f"writ:{W_INVIS}"],
           f"cost/rep order {ranked[:5]}")
    # Today plan, goal 250: Frost writ, then a crate (the green crate is used up: green 10 + white 5 favor, 1600 =
    # 32c/rep, dearer than the option's 29), then the Invisibility writ.
    expect(plan_steps(plan) == [("writ", W_FROST, 2400, 125), ("crate", 1, 1600, 50), ("writ", W_INVIS, 17400, 125)],
           f"plan {plan_steps(plan)}")
    expect(plan.reached and plan.gained == 300 and plan.cash == 6000 + 1600 + 21000 and plan.pouches == 7200
           and plan.favorLeft == 0, f"plan totals {plan.gained} {plan.cash} {plan.pouches} {plan.favorLeft}")
    shop = {(b.id, b.n) for b in plan.shopping.values()}
    expect({(C_INGOTS, 1), (2840, 20), (C_ORE, 1), (2770, 20), (C_EMPTY, 1), (W_FROST, 1), (6050, 1)} <= shop,
           f"shopping list {sorted(shop)}")
    expect(plan.inPlan[f"favor:{C_INGOTS}"] == 1 and plan.inPlan.crate == 1, "inPlan counts")
    expect(R.CellText(crate, "rtoday", plan).endswith("plan|r"), "plan marker")
    # Goal 0 = up to the next standing; not enough on this AH.
    ns.settings.repGoal = 0
    _, plan, _ = rep_options(ns)
    expect(plan.goal == 5500 and not plan.reached and plan.gained == 300, f"goal to the next standing {plan.goal}")
    # Done today: the Frost writ is skipped.
    stub.questsDone[Q_FROST] = True
    ns.settings.repGoal = 250
    o, plan, _ = rep_options(ns)
    expect(o[f"writ:{W_FROST}"].done and R.CellText(o[f"writ:{W_FROST}"], "rtoday") == "|cff808080done|r"
           and plan_steps(plan)[0][0] == "crate" and plan.inPlan[f"writ:{W_FROST}"] is None, "done today")
    stub.questsDone[Q_FROST] = None
    # Favor held is spent first (cost 0): the crate costs only the empty one, so it comes first.
    stub.currency[3402] = 15
    _, plan, _ = rep_options(ns)
    expect(plan.favorHeld == 15 and plan_steps(plan)[0] == ("crate", 1, 100, 50), f"held favor {plan_steps(plan)}")
    stub.currency[3402] = None

    # Neutral, 100 short of Friendly: crates are greyed out, the plan unlocks them after 100 rep.
    neutral = {"reaction": 4, "currentStanding": 2900, "currentReactionThreshold": 0, "nextReactionThreshold": 3000}
    stub.factions[HORDE_REP] = ltable(lua, neutral)
    o, plan, _ = rep_options(ns)
    expect(o["crate"].gated and R.CellText(o["crate"], "rtoday") == "|cff808080needs Friendly|r"
           and o[f"favor:{C_INGOTS}"].gated, "crates not gated below Friendly")
    expect(plan.gatedUntil == 100 and [s[0] for s in plan_steps(plan)] == ["writ", "crate", "writ"],
           f"Neutral plan {plan.gatedUntil} {plan_steps(plan)}")
    expect("Crates only after 100 reputation" in R.DetailText(None, plan, R.Standing()), "gate line in the plan")
    stub.factions[HORDE_REP] = ltable(lua, dict(neutral, reaction=3))
    _, plan, _ = rep_options(ns)
    expect(plan.gatedUntil is False and [s[0] for s in plan_steps(plan)] == ["writ", "writ"], "Unfriendly: writs only")

    # Window: /crafter rep, sort by a header, Rep goal box, the detail pane, back to crafts.
    stub.factions[HORDE_REP] = ltable(lua, FRIENDLY_AT)
    ns.settings.repGoal = 0
    slash(lua, "rep")
    frame = lua.globals().ForeverCrafterFrame
    UI = ns.UI
    expect(frame.__shown and ns.settings.tab == "rep" and len(UI.view) == 181, "/crafter rep does not list options")
    expect(UI.view[1].key == f"writ:{W_FROST}", f"rep tab sorts {UI.view[1].key} first")
    expect("Durotar Supply and Logistics: Friendly 500/6000" in frame.status.__text, f"status {frame.status.__text!r}")
    heads = {h.col.key: h for h in frame.headers.values() if h.col}
    expect(set(heads) == {c.key for c in R.COLUMNS.values()}, "rep headers")
    heads["rtier"].Click(heads["rtier"])
    expect(ns.settings.repSort == "rtier" and ns.settings.repSortDesc and UI.view[1].tier == 4, "tier sort")
    heads["rper"].Click(heads["rper"])
    frame.repGoal.SetText(frame.repGoal, "250")
    frame.repGoal.__scripts.OnEnterPressed(frame.repGoal)
    expect(ns.settings.repGoal == 250 and UI.repPlan.goal == 250, "Rep goal box")
    rows = [f for f in stub.frames.values() if f.result is not None and f.__shown]
    rows[0].Click(rows[0])
    d = frame.detail.__text
    expect("Today's plan" in d and "Shopping list" in d and "Coin Pouch" in d, "rep detail pane")
    frame.repTab.Click(frame.repTab)
    expect(ns.settings.tab == "craft" and ns.settings.mode == "char", "Back to crafts")

    # Learning (time() moves on between turn-ins so they are not matched with each other's gains).
    stub.fire("QUEST_TURNED_IN", Q_FROST, 0, 0)
    stub.factions[HORDE_REP] = ltable(lua, dict(FRIENDLY_AT, currentStanding=3630))
    stub.fire("UPDATE_FACTION")
    stub.now = stub.now + 10
    stub.bags[S_INGOTS] = 2
    stub.fire("BAG_UPDATE_DELAYED")
    stub.bags[S_INGOTS] = 1
    stub.fire("BAG_UPDATE_DELAYED")
    stub.fire("CURRENCY_DISPLAY_UPDATE", 3402, 12, 12)
    stub.now = stub.now + 10
    stub.bags[RECEIPT] = 1
    stub.fire("BAG_UPDATE_DELAYED")
    stub.bags[RECEIPT] = 0
    stub.fire("BAG_UPDATE_DELAYED")
    stub.factions[HORDE_REP] = ltable(lua, dict(FRIENDLY_AT, currentStanding=3690))
    stub.fire("FACTION_STANDING_CHANGED", HORDE_REP)
    stub.now = stub.now + 10
    stub.fire("QUEST_TURNED_IN", Q_INVIS, 0, 0)          # its rep comes too late to match
    stub.now = stub.now + 10
    stub.factions[HORDE_REP] = ltable(lua, dict(FRIENDLY_AT, currentStanding=3815))
    stub.fire("UPDATE_FACTION")
    stub.fire("QUEST_TURNED_IN", 12345, 0, 0)            # not a writ
    stub.factions[HORDE_REP] = ltable(lua, dict(FRIENDLY_AT, currentStanding=3900))
    stub.fire("UPDATE_FACTION")
    learned = ns.db.rep.learned
    expect(learned.quest[Q_FROST] == 130 and learned.quest[Q_INVIS] is None and learned.quest[12345] is None,
           f"learned writ rep {dict(learned.quest.items())}")
    expect(learned.favor[S_INGOTS] == 12 and learned.crateRep == 60 and learned.sealedRep[S_INGOTS] is None,
           f"learned favor {dict(learned.favor.items())} crate {learned.crateRep}")
    o, _, _ = rep_options(ns)
    expect(o[f"writ:{W_FROST}"].rep == 130 and o[f"writ:{W_FROST}"].repSrc == "learned"
           and o[f"favor:{C_INGOTS}"].favor == 12 and o["crate"].rep == 60
           and not R.CellText(o[f"writ:{W_FROST}"], "rrep").startswith("|cffff8040"), "learned amounts not used")
    # Kept across sessions and /crafter reset; /crafter rep forget clears them.
    slash(lua, "reset")
    lua2, ns2, stub2 = new_runtime(saved=stub.savedVariables("ForeverCrafterDB"))
    login(lua2, stub2)
    expect(ns2.db.rep.learned.quest[Q_FROST] == 130 and ns2.settings.repGoal == 250, "learned rep not saved")
    slash(lua2, "rep forget")
    expect(ns2.db.rep.learned.quest[Q_FROST] is None and ns2.db.rep.learned.crateRep is None, "rep forget")
    errs = list(ns.errors.values()) + list(ns2.errors.values())
    expect(not errs, f"errors in the reputation checks: {errs[:3]}")

    # Without the reputation, currency and quest APIs: no errors, writs priced, the plan asks for a Rep goal.
    lua, ns, stub = rep_world(standing=None, goal=0, remove=("C_Reputation", "C_CurrencyInfo", "C_QuestLog"))
    o, plan, st = rep_options(ns)
    expect(st is None and not o["crate"].gated and o[f"writ:{W_FROST}"].cost == 2400, "options without the APIs")
    expect(plan.goal is None and "set a Rep goal" in plan.message, f"plan message {plan.message!r}")
    ns.settings.repGoal = 250
    _, plan, _ = rep_options(ns)
    expect(plan.reached and plan.ungated, "plan with a Rep goal and no standing")
    slash(lua, "rep")
    for ev, args in (("UPDATE_FACTION", ()), ("CURRENCY_DISPLAY_UPDATE", (3402, 5, 5)),
                     ("QUEST_TURNED_IN", (Q_FROST, 0, 0)), ("BAG_UPDATE_DELAYED", ())):
        stub.fire(ev, *args)
    expect("standing unknown" in lua.globals().ForeverCrafterFrame.status.__text, "status without the APIs")
    expect(not list(ns.errors.values()), f"errors without the reputation APIs: {list(ns.errors.values())[:3]}")


def rep_summary():
    """Full-style snapshot: every writ, item, crate and bundle listed at a pseudo-random price (5-stacks plus a
    single). → summary lines: the top options and a today plan from Friendly 500/6000."""
    lua, ns, stub = new_runtime()
    stub.faction = "Horde"
    stub.factions[HORDE_REP] = ltable(lua, FRIENDLY_AT)
    login(lua, stub)
    ids = set(ns.RepWrits.keys()) | set(ns.RepCrates.keys()) | {C_EMPTY}
    ids |= {w.item for w in ns.RepWrits.values()}
    ids |= {b[1] for c in ns.RepCrates.values() for b in c.bundles.values()}
    listings = []
    for i in sorted(ids):
        p = 100 + (i * 7919) % 50000
        listings += [(i, 5, p * 5), (i, 1, p + 10)]
    set_auctions(lua, stub, listings)
    scan(lua, stub)
    o, plan, _ = rep_options(ns)
    R, U = ns.Reputation, ns.Util
    strip = lambda t: re.sub(r"\|c\w{8}|\|r", "", t)
    top = sorted((x for x in o.values() if not x.gated and not x.missing), key=lambda x: (R.SortValue(x, "rper"), x.key))
    out = [f"reputation (test snapshot, {len(o)} options, Friendly 500/6000): top by cost/rep"]
    for x in top[:6]:
        out.append(f"  {strip(R.CellText(x, 'rname'))}: {strip(R.CellText(x, 'rcost'))} for "
                   f"{strip(R.CellText(x, 'rrep'))} = {strip(R.CellText(x, 'rper'))}")
    kinds = {}
    for s in plan.steps.values():
        kinds[s.kind] = kinds.get(s.kind, 0) + (s.n or 1)
    out.append(f"  today plan: +{plan.gained} of {plan.goal} rep for {strip(U.Money(plan.cash))} "
               f"(pouches back {strip(U.Money(plan.pouches or 0))}), {len(plan.steps)} steps: "
               f"{kinds.get('writ', 0)} writs, {kinds.get('crate', 0)} notarised crate(s)")
    expect(plan.reached and not list(ns.errors.values()), "full-style reputation plan")
    return out


def check_dump():
    """/crafter dump in the fake client -> SavedVariables text -> gen_data.py client-dump merge -> build."""
    import tempfile
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import gen_data
    lua, ns, stub = new_runtime()
    login(lua, stub, skills={TAILORING: 30})
    missing = sorted(i for i, e in ns.Items.items() if e.missing)
    got_item, never = missing[0], missing[1]
    stub["items"][got_item] = lua.table_from({"name": "Client Item", "quality": 2, "sell": 77})
    open_ts(lua, stub, TAILORING, 30, {
        R_BOLT: (True, 0, {"name": "Bolt of Linen Cloth", "out": [BOLT, 1, 1], "reagents": [[LINEN, 3]]}),
        R_VEST: (True, 1, None),
        R_SHIRT: (False, None, None, SOURCE_TEXT),
        R_KNOWN_EXCL: (True, 1, None),
        R_LISTED_EXCL: (False, None, None),
    })
    acq = ns.Planner.Acquire(ns.Recipes[R_SHIRT], R_SHIRT).text
    expect(acq.startswith("Game: ") and "Any Tailoring trainer" in acq,
           f"Acquire does not show the game's source text first: {acq!r}")
    n0 = len(stub.prints)
    slash(lua, "dump")
    stub.runTimers(30)
    out = " / ".join(prints(stub, n0))
    expect("5 recipes (2 unlearned, 1 with the game's source text)" in out and "item data for" in out,
           f"/crafter dump output: {out}")
    expect(stub.ts.showUnlearned is False, "/crafter dump did not put the unlearned filter back")
    d = lua.globals().ForeverCrafterDB.dump
    expect(d.lines[TAILORING].complete and d.lines[TAILORING].recipes[R_SHIRT].s == SOURCE_TEXT,
           "dump misses the unlearned recipe's source text")
    expect(d["items"][got_item] and d["items"][got_item].n == "Client Item" and d["items"][never] is None,
           "dump item data wrong")
    expect(d.noItem[never] and d.noItem[got_item] is None, "dump does not record the items the game gave no info for")
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "ForeverCrafter.lua")
        with open(path, "w", encoding="utf-8") as f:
            f.write(stub.savedVariables("ForeverCrafterDB"))
        store = {"lines": {}, "items": {}}
        expect(gen_data.merge_dump(store, gen_data.read_dump(path)) == (1, 1), "client-dump merge counts")
    rec = store["lines"][str(TAILORING)]["recipes"]
    expect(sorted(rec) == sorted(str(x) for x in (R_BOLT, R_VEST, R_SHIRT, R_KNOWN_EXCL, R_LISTED_EXCL))
           and all(set(e) <= {"name", "out", "reagents", "text"} for e in rec.values()),
           f"merged recipes {rec}")
    expect(str(never) in store.get("noItem", {}) and str(got_item) not in store["noItem"],
           f"merged noItem {store.get('noItem')}")
    expect(sorted(store.get("known", {})) == sorted(str(x) for x in (R_BOLT, R_VEST, R_KNOWN_EXCL)),
           f"merged known recipes {store.get('known')}")
    manifest, db, wh, _ = gen_data.load_research()
    files, report = gen_data.build(manifest, db, wh, store)
    recipes = files["Data/Recipes.lua"]
    shirt = re.search(r"\n  \[%d\]=\{[^\n]*" % R_SHIRT, recipes)
    expect(shirt and 'learnText="Trainer: Any Tailoring trainer; Cost: 50s"' in shirt.group(0)
           and "client" in shirt.group(0), f"built Shirt: {shirt and shirt.group(0)}")
    bolt = re.search(r"\n  \[%d\]=\{[^\n]*" % R_BOLT, recipes)
    expect(bolt and "reagents={{%d,3}}" % LINEN in bolt.group(0), "client reagents do not replace DB2's")
    expect(not re.search(r"\n  \[%d\]=" % R_BOOTS, recipes) and str(R_BOOTS) in
           files["../research/excluded_recipes.txt"], "a recipe missing from the game's full list is not left out")
    known = re.search(r"\n  \[%d\]=\{[^\n]*" % R_KNOWN_EXCL, recipes)
    expect(known and 'known="' in known.group(0) and 'src="db2+client"' in known.group(0),
           f"a left-out recipe a character knows is not brought in: {known and known.group(0)}")
    expect(not re.search(r"\n  \[%d\]=" % R_LISTED_EXCL, recipes),
           "a recipe the game merely lists (unlearned, on no Wowhead list) was brought in")
    expect(re.search(r"\n  \[%d\]=\{name=\"Client Item\"[^\n]*src=\"[^\"]*client" % got_item,
                     files["Data/Items.lua"]), "client item info not used")
    expect(any("client reagents differ %d" % R_BOLT in x for x in report), "client reagent difference not reported")


def check_zip():
    import tempfile
    import zipfile
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(build_zip(tmp)) as z:
            names = z.namelist()
    tops = {n.split("/")[0] for n in names}
    expect(tops == {NAME}, f"zip: top-level folders {sorted(tops)}")
    expect(f"{NAME}/{NAME}.toc" in names, "zip: TOC missing")
    expect(f"{NAME}/LICENSE" in names, "zip: LICENSE missing")
    _, files = toc()
    for rel in files:
        expect(f"{NAME}/{rel}" in names, f"zip: {rel} missing")
    # A release zip carries the release version in its .toc; the rest is unchanged.
    with tempfile.TemporaryDirectory() as tmp:
        path = build_zip(tmp, release="0.1.4")
        with zipfile.ZipFile(path) as z:
            zipped = z.read(f"{NAME}/{NAME}.toc").decode("utf-8")
            names2 = z.namelist()
    want = read(os.path.join(ADDON, NAME + ".toc")).replace(f"## Version: {version()}", "## Version: 0.1.4")
    expect(os.path.basename(path) == f"{NAME}-v0.1.4.zip" and zipped == want and names2 == names,
           f"release zip: {os.path.basename(path)}")


def check_release_version():
    """tools/release_version.py: the vX.Y.Z of the next release (.github/workflows/release.yml)."""
    from release_version import next_version
    old = ["v0.1.0-dc1a6d3", "v0.1.0-f82da0b"]
    cases = [
        ("0.1.0", [], [], "0.1.1"),                                # first release: bump the .toc's patch
        ("0.1.0", old, [], "0.1.1"),                               # old v<version>-<commit> tags are ignored
        ("0.1.0", ["v0.1.0-abc", "v0.1.3"], [], "0.1.4"),          # bump the newest tag
        ("0.1.0", ["v0.1.10", "v0.1.9", "v0.1.2"], [], "0.1.11"),  # numeric, not string, order
        ("0.2.0", ["v0.1.3", "v0.1.4"], [], "0.2.0"),              # manual bump in the .toc: used as is
        ("0.1.4", ["v0.1.4"], [], "0.1.5"),                        # .toc equal to the newest tag: bump
        ("0.1.0", ["v0.1.3", "v0.1.4"], ["v0.1.4"], None),         # HEAD already released: skip
        ("0.1.0", old, ["v0.1.0-f82da0b"], "0.1.1"),               # an old-style tag on HEAD is no release
    ]
    for toc_v, tags, head, want in cases:
        got = next_version(toc_v, tags, head)
        expect(got == want, f"next_version({toc_v!r}, {tags}, {head}) = {got!r}, want {want!r}")
    try:
        next_version("0.1", [])
        expect(False, "a .toc version that is not X.Y.Z must fail")
    except ValueError:
        pass


def main():
    check_toc()
    check_release_version()
    check_policy()
    check_gen_data()
    lua, ns, _ = new_runtime()
    counts = check_data(ns)
    summary = []
    if not problems:
        check_core_flow()
        check_solver_shapes()
        check_random_output()
        summary.append(f"vendor prices: {check_vendor_costs()} unlimited entries match the Wowhead sold-by cost")
        check_vendor_shuffles()
        check_crafting_time()
        check_fast_path()
        check_fast_batch_path()
        check_cheap_batch()
        check_merchant()
        check_sniper()
        check_sniper_target()
        check_sniper_quick()
        check_cooldowns()
        check_shelves()
        check_farm()
        check_farm_guide()
        check_filter_row()
        check_missing_apis()
        check_dump()
        n, evaluated, took, hidden, shuffles, times, batches, fasts = check_full_run()
        summary.append(f"full run: {evaluated} recipes evaluated, {n} profitable, {took:.2f} s")
        summary.append("  Min sold/day 1 hides (My character): " + hidden_text(hidden))
        summary.append("  vendor shuffles (My character): " + shuffle_text(shuffles))
        summary += time_text(ns, times, "My character")
        summary += batch_text(ns, batches, "My character")
        summary += fast_text(fasts, "My character")
        check_what_if()
        line, _, hidden, shuffles, times, batches, fasts = check_what_if_full()
        summary.append(line)
        summary.append("  Min sold/day 1 hides (What-if): " + hidden_text(hidden))
        summary.append("  vendor shuffles (What-if): " + shuffle_text(shuffles))
        summary += time_text(ns, times, "What-if")
        summary += batch_text(ns, batches, "What-if")
        summary += fast_text(fasts, "What-if")
        summary += check_batch_depth()
        check_sales()
        check_reputation()
        summary += rep_summary()
        summary += farm_summary()
        check_zip()
    for p in problems:
        print("FAIL", p)
    if problems:
        print(f"\n{len(problems)} problem(s)")
        sys.exit(1)
    print("data: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    for s in summary:
        print(s)
    print("all checks passed")


if __name__ == "__main__":
    main()
