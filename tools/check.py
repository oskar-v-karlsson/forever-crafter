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


def build_zip(dist=None):
    """dist/ForeverCrafter-v<version>.zip with ForeverCrafter/ at the top (unzip straight into AddOns)."""
    import zipfile
    dist = dist or os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    path = os.path.join(dist, f"{NAME}-v{version()}.zip")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirs, files in os.walk(ADDON):
            dirs.sort()
            for fn in sorted(files):
                if fn.startswith("."):
                    continue
                full = os.path.join(dirpath, fn)
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
    expect({"db2", "wh_list", "wh_tt", "wh_item", "ui", "in-game", "client", "tsm"} <= keys,
           f"SOURCES.md sources table misses keys (has {sorted(keys)})")
    expect(ns.DATA_BUILD in read(os.path.join(ROOT, "SOURCES.md")), "SOURCES.md does not name the pinned DB2 build")
    date = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    counts = {}
    for table in ("SkillLines", "Recipes", "Items", "Vendor"):
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
    return counts


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

def new_runtime(remove=(), bad_events=()):
    """A fresh fake client with the addon loaded and ADDON_LOADED fired (not logged in). remove: global API tables
    or functions to delete before loading (a client without them). bad_events: events RegisterEvent rejects."""
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


def open_ts(lua, stub, line, rank, recipes, show_unlearned=False):
    """recipes: {spell: (learned, difficulty, schematic or None[, GetRecipeSourceText])}"""
    t = {"line": line, "rank": rank, "max": 300, "showUnlearned": show_unlearned, "recipes": {}}
    for spell, (learned, diff, schem, *source) in recipes.items():
        t["recipes"][spell] = {"learned": learned, "difficulty": diff, "schematic": schem,
                               "source": source[0] if source else None}
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
    total, deep = ns.Pricing.AHBuy(LINEN, 22)
    expect(total == 230 and not deep, f"AH ladder: 22 linen cost {total}, want 230")
    expect(ns.Pricing.AHBuy(LINEN, 26) is None, "AH ladder sells more than is listed")

    res, stats = results(ns)
    vest = res.get(R_VEST)
    if expect(vest, "Brown Linen Vest (known, AH 1g) not profitable"):
        # Bolt crafted from 2 linen (20c) beats the AH bolt (200c); thread from the vendor list (10c, estimate).
        expect(vest.cost == 30, f"vest cost {vest.cost}, want 30 (bolt crafted 20c + thread 10c)")
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
    expect(vest and vest.cost == 32 and not vest.est, "merchant price did not replace the estimate")

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
    expect(shirt and shirt.known and shirt.cost == 20 and shirt.runtime, "window schematic did not override reagents")
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
        frame.headers[1].Click(frame.headers[1])
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
    errs = list(ns.errors.values())
    expect(not errs, f"errors without the APIs: {errs[:3]}")


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
    return n, stats.evaluated, took, hidden


MINING, BLACKSMITHING, ENGINEERING, ALCHEMY, COOKING = 186, 164, 202, 171, 185
WI_DEFAULT = {"cap": 150, "overrides": {}, "minConf": 4, "maxPrimaries": 2}


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
    expect(labels == ["Recipe", "Profit", "%", "Profs", "Conf", "Sell", "Sold/d"], f"what-if columns {labels}")
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
    return (f"what-if run (cap 150, max 2 primaries): {st.sets} sets, {st.evaluated} recipes evaluated, "
            f"{len(profit)} profitable, {took:.2f} s in one go (any number of primaries: {out[0][2]:.2f} s), "
            f"slowest frame async {max(frames) * 1000:.0f} ms"), top, hidden


def sales_hidden(lua, ns, stub, run, mode):
    """Profitable results the default Min sold/day filter (1) hides, with the test snapshot's region set to EU, then
    US. run() → the Planner's results. → {region: (hidden, no data, under 1, shown at filter 0)}"""
    out = {}
    for reg in ("EU", "US"):
        stub.regionName = reg
        ns.Sales.Reset()
        ns.UI.results, ns.UI.stats = run()
        ns.settings.mode, ns.settings.profession = mode, 0
        ns.settings.minSoldPerDay = 0
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
    stub.regionName = "EU"
    ns.Sales.Reset()
    ns.settings.mode = "char"
    return out


def hidden_text(h):
    return "; ".join(f"{reg} {n} of {total} ({nodata} no TSM data, {low} under 1/day)"
                     for reg, (n, nodata, low, total) in h.items())


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
    expect(labels == ["Recipe", "Profit", "%", "Sell", "Listed", "Sold/d"], f"My character columns {labels}")
    ns.UI.Refresh()
    cells = [f.cells[6].__text for f in stub.frames.values() if f.cells is not None and f.result is not None]
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


def main():
    check_toc()
    check_policy()
    check_gen_data()
    lua, ns, _ = new_runtime()
    counts = check_data(ns)
    summary = []
    if not problems:
        check_core_flow()
        check_solver_shapes()
        check_missing_apis()
        check_dump()
        n, evaluated, took, hidden = check_full_run()
        summary.append(f"full run: {evaluated} recipes evaluated, {n} profitable, {took:.2f} s")
        summary.append("  Min sold/day 1 hides (My character): " + hidden_text(hidden))
        check_what_if()
        line, _, hidden = check_what_if_full()
        summary.append(line)
        summary.append("  Min sold/day 1 hides (What-if): " + hidden_text(hidden))
        check_sales()
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
