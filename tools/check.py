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
   over every recipe.
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
    expect({"db2", "wh_list", "wh_tt", "wh_item", "ui", "in-game", "client"} <= keys,
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
    return n, stats.evaluated, took


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
        n, evaluated, took = check_full_run()
        summary.append(f"full run: {evaluated} recipes evaluated, {n} profitable, {took:.2f} s")
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
