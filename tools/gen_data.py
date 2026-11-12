#!/usr/bin/env python3
"""Build ForeverCrafter/Data/*.lua from pinned WoW: Forever sources.

Sources (see SOURCES.md):
  db2     wago.tools DB2 CSV export, product "wowf", build BUILD below
  wh_list Wowhead Forever list views (www.wowhead.com/forever/...), dumped in a
          browser with tools/wowhead_dump.js (the site blocks scripts)
  wh_item Wowhead Forever item/spell pages, read in a browser with tools/wowhead_crawl.js
  wh_tt   Wowhead Forever tooltips (nether.wowhead.com/forever/tooltip/..., scriptable)
  client  the game client's own answers, saved in game by /crafter dump (research/client/)

Usage:
  python3 tools/gen_data.py fetch [--from DIR]   download the pinned DB2 CSVs and
                                                 write filtered snapshots + manifest
                                                 to research/db2/
  python3 tools/gen_data.py wowhead DIR          trim raw browser dumps from DIR
                                                 into research/wowhead/
  python3 tools/gen_data.py wowhead-pages DIR    trim tools/wowhead_crawl.js page
                                                 downloads from DIR into research/wowhead/
  python3 tools/gen_data.py wowhead-sourcemore F trim FCsourcemore()'s wh_sourcemore.json
                                                 into research/wowhead/ (+ zones.json)
  python3 tools/gen_data.py wowhead-tooltips     fetch the tooltips of the items with no
                                                 ItemSparse row (network)
  python3 tools/gen_data.py client-dump FILE...  merge /crafter dump data from SavedVariables
                                                 files (ForeverCrafter.lua) into research/client/
  python3 tools/gen_data.py [build]              generate Data/*.lua from research/
  python3 tools/gen_data.py verify               exit 1 if Data/*.lua differs from
                                                 what research/ would generate

The default mode is offline and deterministic: it only reads research/.
"""
import csv
import hashlib
import io
import json
import os
import re
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "ForeverCrafter")
RESEARCH = os.path.join(ROOT, "research")
DB2_DIR = os.path.join(RESEARCH, "db2")
WH_DIR = os.path.join(RESEARCH, "wowhead")
CLIENT_FILE = os.path.join(RESEARCH, "client", "dump.json")

PRODUCT = "wowf"
BUILD = "1.60.1.70888"
DB2_URL = "https://wago.tools/db2/{table}/csv?build={build}"
DB2_VERIFIED = "2026-11-12"
WH_VERIFIED = "2026-11-12"
PAGES_VERIFIED = "2026-11-12"

# Primary profession and secondary skill lines in the Forever SkillLine table.
PROFESSIONS = [171, 164, 333, 202, 165, 197, 185, 129, 186]
CREATE_ITEM = 24          # SpellEffect.Effect
RECIPE_CLASS = 9          # Item.ClassID for recipe items
WH_TRAINER = 6            # Wowhead source code "Trainer"
WH_VENDOR = 5             # Wowhead source code "Vendor"
UNLEARNABLE = 9999        # Wowhead learnedat for things no trainer teaches
MAX_UNLIMITED_QUALITY = 1 # Common

TABLES = {
    "SkillLine": ["ID", "DisplayName_lang", "ParentSkillLineID", "CategoryID"],
    "SkillLineAbility": ["ID", "SkillLine", "Spell", "MinSkillLineRank", "AcquireMethod",
                         "TrivialSkillLineRankLow", "TrivialSkillLineRankHigh", "NumSkillUps"],
    "SpellName": ["ID", "Name_lang"],
    "SpellEffect": ["ID", "SpellID", "DifficultyID", "EffectIndex", "Effect", "EffectItemType",
                    "EffectBasePointsF"],
    "SpellReagents": ["ID", "SpellID"] + ["Reagent_%d" % i for i in range(8)]
                     + ["ReagentCount_%d" % i for i in range(8)],
    "Item": ["ID", "ClassID", "SubclassID"],
    "ItemXItemEffect": ["ID", "ItemEffectID", "ItemID"],
    "ItemEffect": ["ID", "SpellID", "TriggerType"],
    "ItemSparse": ["ID", "Display_lang", "OverallQualityID", "SellPrice", "BuyPrice",
                   "VendorStackCount", "Stackable", "RequiredSkill", "RequiredSkillRank", "Bonding"],
}


# ---------------------------------------------------------------- helpers

def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, cols, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(cols)
    for r in rows:
        w.writerow([r[c] for c in cols])
    data = buf.getvalue().encode("utf-8")
    with open(path, "wb") as f:
        f.write(data)
    return data


def num(v):
    f = float(v or 0)
    return int(f) if f == int(f) else f


# ---------------------------------------------------------------- fetch

def cmd_fetch(args):
    src_dir = None
    if args[:1] == ["--from"]:
        src_dir = args[1]
    cache = os.path.join(ROOT, ".cache", "db2", BUILD)
    os.makedirs(cache, exist_ok=True)
    raw = {}
    for t in TABLES:
        path = os.path.join(cache, t + ".csv")
        if not os.path.exists(path):
            if src_dir:
                shutil.copy(os.path.join(src_dir, t + ".csv"), path)
            else:
                url = DB2_URL.format(table=t, build=BUILD)
                print("download", url)
                req = urllib.request.Request(url, headers={"User-Agent": "forever-crafter gen_data"})
                with urllib.request.urlopen(req) as r, open(path, "wb") as f:
                    f.write(r.read())
        with open(path, "rb") as f:
            raw[t] = f.read()
    rows = {t: list(csv.DictReader(io.StringIO(raw[t].decode("utf-8")))) for t in TABLES}

    lines = {str(p) for p in PROFESSIONS}
    skill_lines = [r for r in rows["SkillLine"] if r["ID"] in lines or r["ParentSkillLineID"] in lines]
    sla = [r for r in rows["SkillLineAbility"] if r["SkillLine"] in lines]
    spells = {r["Spell"] for r in sla}
    effects = [r for r in rows["SpellEffect"] if r["SpellID"] in spells and r["Effect"] == str(CREATE_ITEM)]
    reagents = [r for r in rows["SpellReagents"] if r["SpellID"] in spells]
    names = [r for r in rows["SpellName"] if r["ID"] in spells]

    recipe_items = {r["ID"] for r in rows["Item"] if r["ClassID"] == str(RECIPE_CLASS)}
    item_effects = {r["ID"]: r for r in rows["ItemEffect"]}
    teaching = {r["ItemID"] for r in rows["ItemXItemEffect"] if r["ItemID"] in recipe_items
                and item_effects.get(r["ItemEffectID"], {}).get("SpellID") in spells}
    ixe = [r for r in rows["ItemXItemEffect"] if r["ItemID"] in teaching]
    ie = [item_effects[i] for i in {r["ItemEffectID"] for r in ixe} if i in item_effects]

    items = set(teaching)
    for r in effects:
        items.add(r["EffectItemType"])
    for r in reagents:
        for i in range(8):
            if r["Reagent_%d" % i] not in ("", "0"):
                items.add(r["Reagent_%d" % i])
    item_rows = [r for r in rows["Item"] if r["ID"] in items]
    sparse = [r for r in rows["ItemSparse"] if r["ID"] in items]

    filtered = {
        "SkillLine": skill_lines, "SkillLineAbility": sla, "SpellName": names,
        "SpellEffect": effects, "SpellReagents": reagents, "Item": item_rows,
        "ItemXItemEffect": ixe, "ItemEffect": ie, "ItemSparse": sparse,
    }
    os.makedirs(DB2_DIR, exist_ok=True)
    manifest = {"product": PRODUCT, "build": BUILD, "fetched": DB2_VERIFIED, "tables": {}}
    for t, cols in TABLES.items():
        out = sorted(filtered[t], key=lambda r: int(r["ID"]))
        data = write_csv(os.path.join(DB2_DIR, t + ".csv"), cols, out)
        manifest["tables"][t] = {
            "url": DB2_URL.format(table=t, build=BUILD),
            "full_sha256": sha256(raw[t]), "full_rows": len(rows[t]),
            "snapshot_sha256": sha256(data), "snapshot_rows": len(out),
            "columns": cols,
        }
        print("%-18s %6d of %6d rows" % (t, len(out), len(rows[t])))
    with open(os.path.join(DB2_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")


# ---------------------------------------------------------------- wowhead

def cmd_wowhead(args):
    src = args[0]
    os.makedirs(WH_DIR, exist_ok=True)
    keep = {
        "professions": ["id", "name", "skill", "learnedat", "colors", "creates", "reagents",
                        "source", "trainingcost"],
        "recipe_items": ["id", "name", "quality", "skill", "source", "forever"],
        "item_sources": ["id", "name", "source"],
    }
    for name, fields in keep.items():
        with open(os.path.join(src, name + ".json")) as f:
            d = json.load(f)
        pages, merged = [], {}
        for path in sorted(d["pages"]):
            p = d["pages"][path]
            pages.append({"path": path, "url": p["url"], "rows": len(p["data"]),
                          "capped": len(p["data"]) >= 1000})
            for r in p["data"]:
                merged[r["id"]] = {k: r[k] for k in fields if k in r}
        out = {"fetched": d["fetched"], "sourceLabels": d["sourceLabels"], "pages": pages,
               "rows": [merged[k] for k in sorted(merged)]}
        with open(os.path.join(WH_DIR, name + ".json"), "w") as f:
            json.dump(out, f, indent=0, sort_keys=True)
            f.write("\n")
        print("%-14s %5d rows from %d pages" % (name, len(merged), len(pages)))


SOURCEMORE_FIELDS = ("t", "ti", "n", "z")


def cmd_wowhead_sourcemore(args):
    """Recipe item list views re-dumped with their sourcemore column, plus /forever/zones."""
    with open(args[0]) as f:
        d = json.load(f)
    rows = {}
    for path in sorted(d["lists"]):
        for r in d["lists"][path]["rows"]:
            sm = [{k: s[k] for k in SOURCEMORE_FIELDS if k in s} for s in r.get("sourcemore") or []]
            if sm:
                rows[r["id"]] = {"id": r["id"], "name": r["name"], "source": r.get("source") or [],
                                 "sourcemore": sm}
    out = {"fetched": d["fetched"], "url": "https://www.wowhead.com/forever/items=9.<subclass>",
           "pages": sorted(d["lists"]), "rows": [rows[k] for k in sorted(rows)]}
    with open(os.path.join(WH_DIR, "recipe_item_sourcemore.json"), "w") as f:
        f.write(json.dumps({k: v for k, v in out.items() if k != "rows"}, sort_keys=True)[:-1] + ',"rows":[\n')
        f.write(",\n".join(json.dumps(r, separators=(",", ":"), sort_keys=True) for r in out["rows"]))
        f.write("\n]}\n")
    zones = {str(z["id"]): z["name"] for z in sorted(d["zones"]["rows"], key=lambda z: z["id"])}
    with open(os.path.join(WH_DIR, "zones.json"), "w") as f:
        json.dump({"fetched": d["fetched"], "url": "https://www.wowhead.com/forever/zones", "zones": zones},
                  f, indent=0, sort_keys=True)
        f.write("\n")
    print("sourcemore %d recipe items, zones %d" % (len(rows), len(zones)))


TOOLTIP_URL = "https://nether.wowhead.com/forever/tooltip/item/%d"   # never add dataEnv: 8 = WotLK data
MONEY = {"moneygold": 10000, "moneysilver": 100, "moneycopper": 1}


def parse_tooltip(d):
    out = {"name": d["name"], "q": d["quality"]}
    m = re.search(r'<div class="whtt-sellprice">(.*?)</div>', d.get("tooltip", ""))
    if m:
        out["sell"] = sum(int(v) * MONEY[c] for c, v in re.findall(r'<span class="(money\w+)">(\d+)</span>', m.group(1)))
    return out


def cmd_wowhead_tooltips(args):
    """Fetch the Wowhead Forever tooltip of every item without an ItemSparse row (page_targets.json)."""
    import time
    import urllib.error
    import urllib.request
    with open(os.path.join(WH_DIR, "page_targets.json")) as f:
        ids = json.load(f)["tooltips"]
    rows = []
    for i in ids:
        req = urllib.request.Request(TOOLTIP_URL % i, headers={"User-Agent": "forever-crafter gen_data.py"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            rows.append({"id": i, "notFound": True})
            continue
        rows.append(dict(id=i, **parse_tooltip(d)))
        time.sleep(0.3)
    head = {"fetched": time.strftime("%Y-%m-%d"), "url": TOOLTIP_URL % 0 + " (<id>)"}
    with open(os.path.join(WH_DIR, "tooltips_items.json"), "w") as f:
        f.write(json.dumps(head, sort_keys=True)[:-1] + ',"items":[\n')
        f.write(",\n".join(json.dumps(r, separators=(",", ":"), sort_keys=True) for r in rows))
        f.write("\n]}\n")
    print("tooltips %d, not on Wowhead Forever %d" % (len(rows), sum(1 for r in rows if r.get("notFound"))))


def lua_value(v):
    """lupa table -> list (keys 1..n) or dict (str keys), recursively."""
    if hasattr(v, "items") and not isinstance(v, (dict, str)):
        d = {k: lua_value(x) for k, x in v.items()}
        if d and all(isinstance(k, int) for k in d) and sorted(d) == list(range(1, len(d) + 1)):
            return [d[k] for k in sorted(d)]
        return {str(k): x for k, x in d.items()}
    return v


def read_dump(path):
    """ForeverCrafterDB.dump from a SavedVariables file, as plain Python data (None when there is none)."""
    try:
        import lupa.lua51 as lupa_mod
    except ImportError:
        import lupa as lupa_mod
    lua = lupa_mod.LuaRuntime()
    lua.execute(open(path, encoding="utf-8").read())
    db = lua.globals().ForeverCrafterDB
    return lua_value(db["dump"]) if db is not None and db["dump"] is not None else None


def utc_date(t):
    import datetime
    return datetime.datetime.fromtimestamp(int(t), datetime.timezone.utc).strftime("%Y-%m-%d")


def merge_dump(store, dump):
    """Merge one /crafter dump into store {lines, items}. A profession's newer listing replaces the older one, unless
    only the older one lists the unlearned recipes too. Only facts about the game are kept: no character name or
    skill. Whether some dumped character knows a recipe is kept, without saying who, in store["known"]
    (spell → latest dump date), as proof that the recipe can be learned in Forever. → (lines merged, items merged)"""
    if not dump or dump.get("v") != 1:
        return 0, 0
    c = dump.get("client") or {}
    client = "%s.%s" % (c.get("version", "?"), c.get("build", "?"))
    n_lines = n_items = 0
    for line, ln in sorted((dump.get("lines") or {}).items()):
        new = {"captured": utc_date(ln["time"]), "time": int(ln["time"]), "client": client,
               "faction": ln.get("faction"), "complete": bool(ln.get("complete")), "recipes": {}}
        for sp, e in sorted((ln.get("recipes") or {}).items(), key=lambda kv: int(kv[0])):
            r = {"name": e.get("n") or ""}
            if e.get("o"):
                r["out"] = [int(x) for x in e["o"]]
            if e.get("r") is not None:
                r["reagents"] = [[int(a), int(b)] for a, b in e["r"]]
            if e.get("s"):
                r["text"] = e["s"]
            if e.get("l"):
                known = store.setdefault("known", {})
                known[str(int(sp))] = max(known.get(str(int(sp)), ""), new["captured"])
            new["recipes"][str(int(sp))] = r
        old = store["lines"].get(str(int(line)))
        if old and (old["time"] > new["time"] or (old["complete"] and not new["complete"])):
            continue
        store["lines"][str(int(line))] = new
        n_lines += 1
    no_item = store.setdefault("noItem", {})
    for i, t in (dump.get("noItem") or {}).items():
        if str(int(i)) not in store["items"]:
            no_item[str(int(i))] = max(no_item.get(str(int(i)), ""), utc_date(t))
    for i, e in sorted((dump.get("items") or {}).items(), key=lambda kv: int(kv[0])):
        no_item.pop(str(int(i)), None)
        old = store["items"].get(str(int(i)))
        if old and old["time"] > int(e.get("time", 0)):
            continue
        store["items"][str(int(i))] = {
            "name": e.get("n"), "q": e.get("q"), "sell": e.get("sell"), "stack": e.get("stack"),
            "class": e.get("class"), "sub": e.get("sub"), "bind": e.get("bind"),
            "captured": utc_date(e.get("time", 0)), "time": int(e.get("time", 0)), "client": client}
        n_items += 1
    return n_lines, n_items


def cmd_client_dump(args):
    if not args:
        sys.exit("usage: gen_data.py client-dump <SavedVariables/ForeverCrafter.lua>...")
    store = json.load(open(CLIENT_FILE)) if os.path.exists(CLIENT_FILE) else {
        "note": "the game client's answers, saved in game by /crafter dump and merged by "
                "tools/gen_data.py client-dump (see SOURCES.md, source client)", "lines": {}, "items": {}}
    for path in args:
        nl, ni = merge_dump(store, read_dump(path))
        print("%s: %d profession listings, %d items merged" % (path, nl, ni))
    os.makedirs(os.path.dirname(CLIENT_FILE), exist_ok=True)
    with open(CLIENT_FILE, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    print("wrote %s; now run python3 tools/gen_data.py" % os.path.relpath(CLIENT_FILE, ROOT))


MONEY_ICON = re.compile(r"\|TInterface\\MoneyFrame\\UI-(Gold|Silver|Copper)Icon[^|]*\|t", re.I)


def clean_source_text(t):
    """GetRecipeSourceText output -> plain one-line text: colour, link and texture codes out, money icons as g/s/c,
    |n line breaks as "; "."""
    t = MONEY_ICON.sub(lambda m: m.group(1)[0].lower(), t)
    t = re.sub(r"\|T[^|]*\|t", "", t)
    t = re.sub(r"\|c[0-9a-fA-F]{8}", "", t).replace("|r", "")
    t = re.sub(r"\|H[^|]*\|h(.*?)\|h", r"\1", t)
    parts = [re.sub(r"\s+", " ", x).strip() for x in t.split("|n")]
    return "; ".join(x for x in parts if x)


PAGE_KEEP_ROWS = 5          # rows kept per list (Wowhead's order) besides sold-by
SOLD_BY_KEEP = 10           # sold-by rows kept per stock kind (unlimited / limited)
NPC_FIELDS = ("id", "name", "location", "react", "stock", "cost", "stack", "count", "outof")
OTHER_FIELDS = ("id", "name", "location", "count", "outof", "learnedat", "skill", "cat", "creates",
                "reagents", "source", "trainingcost", "level", "side")


# Lists that do not say where an item or recipe comes from.
PAGE_SKIP = {"outfits", "shared-cooldown", "can-be-placed-in", "transmog-with", "disenchanted-from"}


def trim_page(p):
    if p.get("notFound"):
        return {"id": p["id"], "notFound": True}
    out = {"id": p["id"]}
    own = p.get("own") or {}
    if "name_enus" in own:
        out["name"] = own["name_enus"]
    if "quality" in own:
        out["q"] = own["quality"]
    je = own.get("jsonequip") or {}
    for k, short in (("sellprice", "sell"), ("buyprice", "buy")):
        if je.get(k) is not None:
            out[short] = je[k]
    facts = p.get("facts") or ""
    m = re.search(r"Training cost: \[money=(\d+)\]", facts)
    if m:
        out["trainingcost"] = int(m.group(1))
    lists = {}
    for lid, lv in sorted((p.get("lists") or {}).items()):
        if "rows" not in lv or lid in PAGE_SKIP:
            continue
        if lid == "sold-by":
            rows = [{k: r[k] for k in NPC_FIELDS if k in r} for r in lv["rows"]]
            unl = [r for r in rows if r.get("stock") == -1]
            lim = [r for r in rows if r.get("stock") != -1]
            lists[lid] = {"total": lv["total"], "read": len(rows), "unlimited": len(unl),
                          "rows": unl[:SOLD_BY_KEEP] + lim[:SOLD_BY_KEEP]}
            continue
        fields = NPC_FIELDS if lv["template"] == "npc" else OTHER_FIELDS
        lists[lid] = {"total": lv["total"],
                      "rows": [{k: r[k] for k in fields if k in r} for r in lv["rows"][:PAGE_KEEP_ROWS]]}
    if lists:
        out["lists"] = lists
    return out


def cmd_wowhead_pages(args):
    """Trim the tools/wowhead_crawl.js downloads (wh_pages_<kind>_NNN.json) in DIR."""
    src = args[0]
    os.makedirs(WH_DIR, exist_ok=True)
    for kind in ("item", "spell"):
        pages, fetched = {}, set()
        for name in sorted(os.listdir(src)):
            if not (name.startswith("wh_pages_%s_" % kind) and name.endswith(".json")):
                continue
            with open(os.path.join(src, name)) as f:
                d = json.load(f)
            fetched.add(d["fetched"][:10])
            for p in d["pages"]:
                pages[p["id"]] = trim_page(p)
        if not pages:
            continue
        head = {"fetched": sorted(fetched), "url": "https://www.wowhead.com/forever/%s=<id>" % kind,
                "tool": "tools/wowhead_crawl.js"}
        # One page per line keeps the diffs readable.
        with open(os.path.join(WH_DIR, "pages_%ss.json" % kind), "w") as f:
            f.write(json.dumps(head, sort_keys=True)[:-1] + ',"pages":[\n')
            f.write(",\n".join(json.dumps(pages[k], separators=(",", ":"), sort_keys=True)
                                for k in sorted(pages)))
            f.write("\n]}\n")
        print("%-6s %5d pages (%d not found)" % (kind, len(pages),
                                                 sum(1 for p in pages.values() if p.get("notFound"))))


# ---------------------------------------------------------------- build

def load_research():
    with open(os.path.join(DB2_DIR, "manifest.json")) as f:
        manifest = json.load(f)
    db = {t: read_csv(os.path.join(DB2_DIR, t + ".csv")) for t in TABLES}
    wh = {}
    for n in ("professions", "recipe_items", "item_sources"):
        with open(os.path.join(WH_DIR, n + ".json")) as f:
            wh[n] = json.load(f)
    for n in ("pages_items", "pages_spells", "zones", "recipe_item_sourcemore", "tooltips_items"):
        path = os.path.join(WH_DIR, n + ".json")
        wh[n] = json.load(open(path)) if os.path.exists(path) else None
    client = json.load(open(CLIENT_FILE)) if os.path.exists(CLIENT_FILE) else None
    return manifest, db, wh, client


def build(manifest, db, wh, client=None):
    """Return (files dict name->text, report lines). client = research/client/dump.json (comes before Wowhead)."""
    report = []
    # The game's own profession listings (complete ones: learned and unlearned) decide which recipes exist.
    cl_lines = {k: v for k, v in ((client or {}).get("lines") or {}).items() if v.get("complete")}
    cl_rec = {sp: (ln, e) for ln in cl_lines.values() for sp, e in ln["recipes"].items()}
    cl_items = (client or {}).get("items") or {}
    cl_known = (client or {}).get("known") or {}
    lines = {str(p) for p in PROFESSIONS}
    sparse = {r["ID"]: r for r in db["ItemSparse"]}
    spell_name = {r["ID"]: r["Name_lang"] for r in db["SpellName"]}
    item_class = {r["ID"]: r["ClassID"] for r in db["Item"]}

    creates = {}
    for r in sorted(db["SpellEffect"], key=lambda r: (int(r["SpellID"]), int(r["DifficultyID"]),
                                                      int(r["EffectIndex"]))):
        if r["DifficultyID"] == "0" and r["SpellID"] not in creates:
            creates[r["SpellID"]] = (int(r["EffectItemType"]), num(r["EffectBasePointsF"]))
    reagents = {}
    for r in db["SpellReagents"]:
        lst = []
        for i in range(8):
            rid, n = r["Reagent_%d" % i], r["ReagentCount_%d" % i]
            if rid not in ("", "0") and int(n) > 0:
                lst.append([int(rid), int(n)])
        reagents[r["SpellID"]] = lst

    wh_rec = {str(r["id"]): r for r in wh["professions"]["rows"]}
    wh_ritem = {str(r["id"]): r for r in wh["recipe_items"]["rows"]}
    wh_src = {str(r["id"]): r for r in wh["item_sources"]["rows"]}
    for k, v in wh_ritem.items():
        wh_src.setdefault(k, v)

    item_effect = {r["ID"]: r for r in db["ItemEffect"]}
    teaches = {}
    for r in db["ItemXItemEffect"]:
        sp = item_effect.get(r["ItemEffectID"], {}).get("SpellID")
        if sp:
            teaches.setdefault(r["ItemID"], set()).add(sp)

    recipes, excluded = {}, []
    for a in sorted(db["SkillLineAbility"], key=lambda r: int(r["ID"])):
        sp = a["Spell"]
        if a["SkillLine"] not in lines or sp not in creates or sp in recipes:
            continue
        w = wh_rec.get(sp)
        cl_ln, cl = cl_rec.get(sp, (None, None))
        # The game's list holds every SkillLineAbility recipe of the line, obtainable or not (client dump
        # 2026-11-12), so being listed proves nothing; a recipe some dumped character knows does exist.
        if a["SkillLine"] in cl_lines and not cl:
            excluded.append((int(sp), int(a["SkillLine"]), spell_name.get(sp, "?") + " (not in the game's list, "
                             "client dump %s)" % cl_lines[a["SkillLine"]]["captured"]))
            continue
        if sp in cl_known:
            pass
        elif not w:
            excluded.append((int(sp), int(a["SkillLine"]), spell_name.get(sp, "?")))
            continue
        elif w.get("learnedat") == UNLEARNABLE:
            excluded.append((int(sp), int(a["SkillLine"]), spell_name.get(sp, "?") + " (learnedat 9999)"))
            continue
        w = w or {}
        out_id, out_n = creates[sp]
        rg = reagents.get(sp, [])
        if w.get("reagents") and sorted(map(list, w["reagents"])) != sorted(rg):
            report.append("reagent mismatch %s %s db2=%s wh=%s" % (sp, w["name"], rg, w["reagents"]))
        out_min = out_max = int(out_n)
        if w.get("creates"):
            c = w["creates"]
            if c[0] != out_id or c[1] != out_n:
                report.append("output mismatch %s db2=%s x%s wh=%s" % (sp, out_id, out_n, c))
            out_max = max(out_max, int(c[2]) if len(c) > 2 else out_max)
        out = [out_id, out_min, out_max]
        if cl and cl.get("out") and cl["out"] != out:
            report.append("client output differs %s db2/wh=%s client=%s (client used)" % (sp, out, cl["out"]))
            out = cl["out"]
        if cl and "reagents" in cl and sorted(cl["reagents"]) != sorted(rg):
            report.append("client reagents differ %s db2=%s client=%s (client used)" % (sp, rg, cl["reagents"]))
            rg = cl["reagents"]
        recipes[sp] = {
            "name": spell_name.get(sp, w.get("name") or (cl or {}).get("name", "?")),
            "skill": int(a["SkillLine"]),
            "trivLo": int(a["TrivialSkillLineRankLow"]),
            "trivHi": int(a["TrivialSkillLineRankHigh"]),
            "acquire": int(a["AcquireMethod"]),
            "out": out,
            "reagents": rg,
            "how": sorted(w.get("source", [])),
            "cost": int(w.get("trainingcost", 0) or 0),
            "whLearn": int(w.get("learnedat", 0) or 0) if w else int(a["MinSkillLineRank"]),
            "items": [],
        }
        if w:
            recipes[sp]["onWh"] = True
        if sp in cl_known:
            recipes[sp]["known"] = cl_known[sp]
        if cl:
            recipes[sp]["client"] = cl_ln["captured"]
            if cl.get("text"):
                recipes[sp]["learnText"] = clean_source_text(cl["text"])
    known_spells = {r["Spell"] for r in db["SkillLineAbility"]}
    db2_recipes = {a["Spell"] for a in db["SkillLineAbility"] if a["SkillLine"] in lines and a["Spell"] in creates}
    not_in_db2 = sorted((int(sp), ln, e) for sp, (ln, e) in cl_rec.items() if sp not in db2_recipes)
    for sp, _, e in not_in_db2:
        report.append("game lists recipe %d %s, not a DB2 create-item recipe%s" % (
            sp, e.get("name", ""), "" if str(sp) in known_spells else " (no SkillLineAbility row)"))

    for item_id in sorted(teaches, key=int):
        if item_class.get(item_id) != str(RECIPE_CLASS):
            continue
        for sp in sorted(teaches[item_id], key=int):
            if sp in recipes:
                recipes[sp]["items"].append(int(item_id))

    for sp, r in recipes.items():
        ranks = [int(sparse[str(i)]["RequiredSkillRank"]) for i in r["items"] if str(i) in sparse]
        if WH_TRAINER in r["how"] or not ranks:
            r["learn"] = r["whLearn"]
        else:
            r["learn"] = min(ranks)

    # Items referenced by the kept recipes.
    item_ids = set()
    for r in recipes.values():
        item_ids.add(r["out"][0])
        item_ids.update(i for i, _ in r["reagents"])
        item_ids.update(r["items"])
    items, missing = {}, []
    for i in sorted(item_ids):
        s = sparse.get(str(i))
        w = wh_src.get(str(i))
        if not s:
            # Present in the Item table but without an ItemSparse row in this export:
            # name from Wowhead if listed, prices come from GetItemInfo at runtime.
            missing.append(i)
            e = {"name": (w or {}).get("name", ""), "missing": True}
            if w is not None:
                e["how"] = sorted(w.get("source", []))
            items[i] = e
            continue
        e = {
            "name": s["Display_lang"], "q": int(s["OverallQualityID"]),
            "sell": int(s["SellPrice"]), "buy": int(s["BuyPrice"]),
            "vstack": max(1, int(s["VendorStackCount"])), "stack": int(s["Stackable"]),
            "bop": int(s["Bonding"]) == 1,
        }
        if int(s["RequiredSkillRank"]) > 0 and item_class.get(str(i)) == str(RECIPE_CLASS):
            e["reqSkill"] = int(s["RequiredSkill"])
            e["reqRank"] = int(s["RequiredSkillRank"])
        if w is not None:
            e["how"] = sorted(w.get("source", []))
        items[i] = e
    if missing:
        report.append("items without an ItemSparse row: %d" % len(missing))

    vendor = {}
    reagent_ids = {i for r in recipes.values() for i, _ in r["reagents"]}
    recipe_item_ids = {i for r in recipes.values() for i in r["items"]}
    for i in sorted(reagent_ids | recipe_item_ids):
        e = items.get(i)
        if not e or e.get("missing") or WH_VENDOR not in e.get("how", []) or e["buy"] <= 0:
            continue
        # Unlimited = Wowhead lists Vendor as the only source and the item is at most
        # Common quality (general-goods style). Anything else may be limited stock or a
        # special vendor and is only used once a merchant capture confirms it.
        limited = e["how"] != [WH_VENDOR] or e["q"] > MAX_UNLIMITED_QUALITY
        vendor[i] = {"price": e["buy"], "vstack": e["vstack"],
                     "limited": limited, "recipe": i in recipe_item_ids}


    prof = {}
    for r in db["SkillLine"]:
        prof[int(r["ID"])] = (r["DisplayName_lang"], int(r["ParentSkillLineID"]), int(r["CategoryID"]))

    # Pages to read one by one on Wowhead Forever (tools/wowhead_crawl.js): what the list views leave open.
    no_how = {i for i, e in items.items() if not e.get("how")}
    targets = {
        "note": "IDs for tools/wowhead_crawl.js, generated by tools/gen_data.py from the db2 and wh_list data",
        "items": sorted(set(vendor) | recipe_item_ids | no_how | set(missing)),
        "spells": sorted({int(sp) for sp, r in recipes.items() if not r["how"] and not r.get("learnText")} |
                         {e[0] for e in excluded}),
        "tooltips": sorted(missing),
    }

    apply_pages(wh, recipes, items, vendor, excluded, reagent_ids, recipe_item_ids, report)
    # The game's GetItemInfo for items with no ItemSparse row comes before Wowhead's page or tooltip.
    by_client = 0
    for i, e in items.items():
        ci = cl_items.get(str(i))
        if e.get("missing") and ci and ci.get("name"):
            e["name"], e["q"], e["sell"] = ci["name"], int(ci["q"] or 0), int(ci["sell"] or 0)
            e["client"] = ci["captured"]
            by_client += 1
    if client:
        report.append("client dump: %d profession listings, items filled by the client %d" % (
            len(cl_lines), by_client))
    zones = {int(k): v for k, v in ((wh.get("zones") or {}).get("zones") or {}).items()}
    sm = {r["id"]: r for r in (wh.get("recipe_item_sourcemore") or {}).get("rows", [])}
    spell_items = {}
    for item_id, sps in teaches.items():
        if item_class.get(item_id) == str(RECIPE_CLASS):
            for sp in sps:
                spell_items.setdefault(int(sp), []).append(int(item_id))

    def recipe_item_text(i):
        name = (sparse[str(i)]["Display_lang"] if str(i) in sparse else
                (items.get(i) or wh_src.get(str(i)) or {}).get("name")) or "(no name in the data)"
        w = wh_ritem.get(str(i))
        if w is None:
            return "%d %s: not on the Wowhead Forever recipe lists" % (i, name)
        how = [source_label(c) for c in sorted(w.get("source") or [])]
        more = [(s["n"] + (" (%s)" % zones[s["z"]] if s.get("z") in zones else "")) if s.get("n")
                else "zone " + zones.get(s.get("z"), "?") for s in (sm.get(i) or {}).get("sourcemore", [])]
        return "%d %s: Wowhead %s%s" % (i, name, ", ".join(how) if how else "lists no source",
                                       ("; " + ", ".join(more)) if more else "")

    for n, e in enumerate(excluded):
        its = sorted(spell_items.get(e[0], []))
        db2 = "db2 recipe item " + " | ".join(recipe_item_text(i) for i in its) if its else "no db2 recipe item"
        excluded[n] = (e[0], e[1], e[2], db2, e[3])
        if any((wh_ritem.get(str(i)) or {}).get("source") for i in its):
            report.append("excluded recipe whose recipe item has a Wowhead source: %d %s" % (e[0], e[2]))

    def sourced(r):
        return r["how"] or r.get("learnText") or any(items.get(i, {}).get("how") or items.get(i, {}).get("from") for i in r["items"])

    open_recipes, known_open = [], []
    for sp in sorted(recipes, key=int):
        r = recipes[sp]
        if sourced(r):
            continue
        its = sorted(r["items"])
        why = ("db2 recipe item " + " | ".join(recipe_item_text(i) for i in its)) if its else "no db2 recipe item"
        row = "%s\t%d\t%s\t%d\t%s" % (sp, r["skill"], r["name"], r["acquire"], why)
        if r.get("known"):
            known_open.append(row + "\tknown in game, client dump " + r["known"])
        else:
            open_recipes.append(row)
    report.append("recipes kept %d, excluded %d, items %d, vendor %d (unlimited %d)" % (
        len(recipes), len(excluded), len(items), len(vendor),
        sum(1 for v in vendor.values() if not v["limited"])))
    no_src = sorted(int(sp) for sp, r in recipes.items() if not r["how"] and not r.get("learnText"))
    report.append("recipes without a source of their own: %d; of those with no recipe item source either: %d" % (
        len(no_src), len(open_recipes)) + ("; known in game (client dump) with no source named: %d" % len(known_open)
                                           if known_open else ""))
    no_item_src = sorted(i for i in reagent_ids if not items.get(i, {}).get("how"))
    report.append("reagents without Wowhead source data: %d %s" % (len(no_item_src), no_item_src))

    files = {
        "Data/Recipes.lua": lua_recipes(recipes, prof),
        "Data/Items.lua": lua_items(items),
        "Data/Vendor.lua": lua_vendor(vendor, items),
    }
    excl = ["# ForeverCrafter: DB2 create-item recipes left out of Data/Recipes.lua",
            "# Reason: absent from every Wowhead Forever profession list (likely unobtainable),",
            "# or Wowhead learnedat 9999. A recipe the player knows still comes in at runtime",
            "# through C_TradeSkillUI. Columns: spellID, skillLine, name, the recipe items that",
            "# teach it in the DB2 (ItemXItemEffect -> ItemEffect.SpellID) with what the Wowhead",
            "# Forever recipe lists say about them, and what the recipe's own Wowhead Forever page",
            "# (www.wowhead.com/forever/spell=<id>) lists as a source",
            "# db2 build %s, Wowhead lists fetched %s" % (BUILD, wh["professions"]["fetched"][:10])]
    excl += ["\t".join(map(str, e)) for e in sorted(excluded)]
    files["../research/excluded_recipes.txt"] = "\n".join(excl) + "\n"

    def uses(i):
        u = []
        for sp in sorted(recipes, key=int):
            r = recipes[sp]
            if r["out"][0] == i:
                u.append("made by " + sp)
            if any(x == i for x, _ in r["reagents"]):
                u.append("reagent of " + sp)
            if i in r["items"]:
                u.append("teaches " + sp)
        return ", ".join(u[:4]) + (" (+%d)" % (len(u) - 4) if len(u) > 4 else "")

    opn = ["# ForeverCrafter: sources still open after the client dump and the Wowhead Forever lists, pages and tooltips",
           "# (see SOURCES.md, \"Open\"). Generated by tools/gen_data.py; check these in game or in a browser.",
           "", "## Recipes with no source: neither the recipe nor its recipe item has one on Wowhead Forever",
           "# spellID, skillLine, name, SkillLineAbility.AcquireMethod (1 = learned with the skill?), recipe items in the DB2"]
    opn += open_recipes
    if known_open:
        opn += ["", "## Recipes a character knows (client dump) but no source names: they exist, how they are learned is open",
                "# spellID, skillLine, name, AcquireMethod, recipe items in the DB2, dump date"]
        opn += known_open
    opn += ["", "## Reagents with no source on Wowhead Forever", "# itemID, name, used by"]
    opn += ["%d\t%s\t%s" % (i, items[i]["name"], uses(i)) for i in no_item_src]
    opn += ["", "## Items with no ItemSparse row and no Wowhead Forever item (tooltip 404)",
            "# itemID, used by (name, quality and prices come from GetItemInfo in game)"]
    no_item = (client or {}).get("noItem") or {}
    opn += ["%d\t%s%s" % (i, uses(i), ("\tthe game gave no item info, client dump " + no_item[str(i)])
                         if str(i) in no_item else "")
            for i in sorted(items) if items[i].get("notOnWh") and not items[i].get("client")]
    opn += ["", "## Vendor items with no NPC named: page not read and no sourcemore NPC (stock unknown)",
            "# itemID, name"]
    opn += ["%d\t%s" % (i, items[i]["name"]) for i in sorted(vendor)
            if not vendor[i].get("page") and not items[i].get("from")]
    if not_in_db2:
        opn += ["", "## Recipes the game lists that are not DB2 create-item recipes (client dump)",
                "# spellID, name, client dump date"]
        opn += ["%d\t%s\t%s" % (sp, e.get("name", ""), ln["captured"]) for sp, ln, e in not_in_db2]
    files["../research/open_sources.txt"] = "\n".join(opn) + "\n"
    files["../research/wowhead/page_targets.json"] = json.dumps(targets, separators=(",", ":")) + "\n"
    return files, report


# Wowhead Forever page lists -> Wowhead source codes (the codes of the list views, see Util.SOURCE_NAMES).
# The pairing is ours: Wowhead's list names say what each list holds, the codes come from its source labels.
# 101/102 have no Wowhead code: "contained in" an object (chest, barrel, ...) or an item (bag, crate, ...).
PAGE_HOW = {
    "sold-by": 5, "dropped-by": 2, "created-by-spell": 1, "reward-from-q": 4, "fished-in": 16,
    "pick-pocketed-from": 21, "skinned-from": 23, "mined-from-object": 19, "gathered-from-object": 17,
    "contained-in-object": 101, "contained-in-item": 102, "taught-by-npc": 6,
}
NPC_SHOWN = 3   # vendors named per item in Data/Vendor.lua


def page_how(page):
    return sorted({PAGE_HOW[k] for k in page.get("lists", {}) if k in PAGE_HOW})


# sourcemore entry -> role. Wowhead does not say which source an entry belongs to; our reading:
# an NPC is the vendor when Vendor is the only source, the dropper when Drop is the only one,
# otherwise just "npc". t: 1 NPC, 2 object, 5 quest, 6 item; no t = a zone only.
def sm_role(s, source):
    t = s.get("t")
    if t == 1:
        return "vendor" if source == [WH_VENDOR] else "drop" if source == [2] else "npc"
    return {2: "object", 5: "quest", 6: "item"}.get(t, "zone")


def npc_side(react):
    a, h = (list(react or []) + [None, None])[:2]
    if a == 1 and h == 1:
        return "both"
    if a == 1:
        return "Alliance"
    if h == 1:
        return "Horde"
    return "hostile"


def apply_pages(wh, recipes, items, vendor, excluded, reagent_ids, recipe_item_ids, report):
    """Fill what the list views leave open from the Wowhead Forever item and spell pages (wh_item)."""
    pi = {p["id"]: p for p in (wh.get("pages_items") or {}).get("pages", [])}
    ps = {p["id"]: p for p in (wh.get("pages_spells") or {}).get("pages", [])}
    zones = {int(k): v for k, v in ((wh.get("zones") or {}).get("zones") or {}).items()}
    unknown_lists = set()
    for p in list(pi.values()) + list(ps.values()):
        for k in p.get("lists", {}):
            if k not in PAGE_HOW and k not in ("teaches-recipe", "recipes", "taught-by-npc", "taught-by-item",
                                               "see-also-recipe"):
                unknown_lists.add(k)
    if unknown_lists:
        report.append("page lists not used: %s" % sorted(unknown_lists))

    # Items: names, quality and prices for the IDs without an ItemSparse row; sources where the lists had none.
    filled = 0
    for i, e in items.items():
        p = pi.get(i)
        if not p or p.get("notFound"):
            continue
        if e.get("missing"):
            if p.get("name"):
                e["name"] = p["name"]
            for k in ("q", "sell", "buy"):
                if k in p:
                    e[k] = p[k]
            e["page"] = True
            filled += 1
        if not e.get("how") and p.get("lists"):
            e["how"] = page_how(p)
            e["page"] = True
    report.append("items filled from Wowhead pages: %d of %d without an ItemSparse row" % (
        filled, sum(1 for e in items.values() if e.get("missing"))))

    # Items without an ItemSparse row and no page read: the item's Wowhead Forever tooltip (wh_tt).
    tt = {r["id"]: r for r in (wh.get("tooltips_items") or {}).get("items", [])}
    by_tt, absent = 0, []
    for i, e in items.items():
        if not e.get("missing") or e.get("page"):
            continue
        t = tt.get(i)
        if not t:
            continue
        if t.get("notFound"):
            e["notOnWh"] = True
            absent.append(i)
            continue
        e["name"], e["q"] = t["name"], t["q"]
        if "sell" in t:
            e["sell"] = t["sell"]
        e["tt"] = True
        by_tt += 1
    report.append("items filled from Wowhead tooltips: %d; not on Wowhead Forever: %d" % (by_tt, len(absent)))

    # Recipe items: the NPC, quest or object Wowhead names in the list view's sourcemore column.
    sm = {r["id"]: r for r in (wh.get("recipe_item_sourcemore") or {}).get("rows", [])}
    for i in recipe_item_ids:
        r, e = sm.get(i), items.get(i)
        if r and e:
            e["from"] = [[sm_role(s, r["source"]), s.get("n", ""), zones.get(s.get("z"), "")]
                         for s in r["sourcemore"]][:NPC_SHOWN]

    # Vendors: who sells each reagent / recipe item, and whether any of them has unlimited stock.
    stack_diff = []
    for i in sorted(reagent_ids | recipe_item_ids):
        p, e = pi.get(i), items.get(i)
        if not p or p.get("notFound") or not e:
            continue
        sb = p.get("lists", {}).get("sold-by")
        if not sb:
            if i in vendor:
                report.append("vendor dropped, the Wowhead page has no sold-by list: %d %s" % (i, e["name"]))
                del vendor[i]
            continue
        rows = sb["rows"]
        unit = min(r["cost"][0][0] / max(1, r.get("stack") or 1) for r in rows if r.get("cost"))
        if not e.get("missing") and e["buy"] > 0:
            price, vstack = e["buy"], e["vstack"]
            stacks = {r.get("stack") or 1 for r in rows}
            if stacks != {vstack}:
                stack_diff.append(i)
        else:
            price, vstack = int(round(unit * (rows[0].get("stack") or 1))), rows[0].get("stack") or 1
        shown = [r for r in rows if r.get("stock") == -1][:NPC_SHOWN] or rows[:NPC_SHOWN]
        vendor[i] = {
            "price": price, "vstack": vstack, "limited": sb["unlimited"] == 0, "recipe": i in recipe_item_ids,
            "npcs": [[r["name"], zones.get((r.get("location") or [0])[0], ""), npc_side(r.get("react"))]
                     for r in shown],
            "nNpc": sb["total"], "page": True,
        }
    if stack_diff:
        report.append("Wowhead sold-by stack differs from DB2 VendorStackCount: %s" % stack_diff)

    # Recipes without a source in the profession lists.
    for sp, r in recipes.items():
        p = ps.get(int(sp))
        if r["how"] or not p or p.get("notFound"):
            continue
        how = page_how(p)
        if how:
            r["how"] = how
            r["page"] = True
            if 6 in how and p.get("trainingcost"):
                r["cost"] = p["trainingcost"]

    # Excluded recipes: what their own page says.
    for n, (sp, line, name) in enumerate(excluded):
        p = ps.get(sp)
        if not p:
            ev = "spell page not read"
        elif p.get("notFound"):
            ev = "spell page not found"
        else:
            how = [source_label(c) for c in page_how(p)]
            tb = [str(r["id"]) for r in p.get("lists", {}).get("taught-by-item", {}).get("rows", [])]
            if tb:
                how.append("taught by item " + ", ".join(tb))
            ev = "spell page: " + (", ".join(how) if how else "no teacher, recipe item or other source")
        excluded[n] = (sp, line, name, ev)


SOURCE_LABELS = {1: "Crafted", 2: "Drop", 4: "Quest", 5: "Vendor", 6: "Trainer", 16: "Fished", 17: "Gathered",
                 19: "Mined", 21: "Pickpocketed", 23: "Skinned", 101: "Container (object)",
                 102: "Container (item)"}


def source_label(c):
    return SOURCE_LABELS.get(c, "source %d" % c)


HEADER = """-- GENERATED by tools/gen_data.py -- do not edit by hand.
-- Sources: db2 = wago.tools DB2 export, product %s, build %s (research/db2/manifest.json)
--          wh_list = Wowhead Forever list views dumped %s (research/wowhead/)
-- See SOURCES.md. Licence: GPL-2.0-or-later.
local _, ns = ...
""" % (PRODUCT, BUILD, WH_VERIFIED)


def lstr(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def llist(v):
    if isinstance(v, list):
        return "{" + ",".join(llist(x) for x in v) + "}"
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def lua_recipes(recipes, prof):
    out = [HEADER, "ns.DATA_BUILD = %s" % lstr(BUILD), "",
           "-- skillLine = { name, parent, cat } (parent 0 = the profession itself; cat = SkillLine.CategoryID:",
           "--   11 profession, 9 secondary skill)",
           "ns.SkillLines = {"]
    for k in sorted(prof):
        out.append("  [%d]={name=%s,parent=%d,cat=%d,src=\"db2\",verified=\"%s\"}," % (
            k, lstr(prof[k][0]), prof[k][1], prof[k][2], DB2_VERIFIED))
    out += ["}", "",
            "-- [spellID] = { name, skill = skill line, learn = rank needed to learn,",
            "--   trivLo/trivHi = yellow/grey skill-up thresholds, out = {itemID, min, max},",
            "--   reagents = {{itemID, count}}, how = Wowhead source codes (6 trainer, 5 vendor,",
            "--   2 drop, 4 quest, ...; from the profession lists, or from the recipe's own page when",
            "--   src has wh_item), cost = trainer cost (copper), items = recipe item IDs,",
            "--   acquire = SkillLineAbility.AcquireMethod, learnText = the game's own \"how to learn\" text",
            "--   (C_TradeSkillUI.GetRecipeSourceText, src client), known = date of the client dump in which a",
            "--   character knew the recipe (src client); src client = the game listed the recipe and its",
            "--   reagents/output come from the game }",
            "ns.Recipes = {"]
    for sp in sorted(recipes, key=int):
        r = recipes[sp]
        src = ["db2"] + (["wh_list"] if r["how"] or r.get("onWh") else []) + (
            ["wh_item"] if r.get("page") else []) + (["client"] if r.get("client") or r.get("known") else [])
        ver = max(PAGES_VERIFIED if r.get("page") else DB2_VERIFIED, r.get("client") or "", r.get("known") or "")
        text = ",learnText=%s" % lstr(r["learnText"]) if r.get("learnText") else ""
        text += ",known=%s" % lstr(r["known"]) if r.get("known") else ""
        out.append(
            "  [%s]={name=%s,skill=%d,learn=%d,trivLo=%d,trivHi=%d,out=%s,reagents=%s,how=%s,"
            "cost=%d,items=%s,acquire=%d%s,src=\"%s\",verified=\"%s\"}," % (
                sp, lstr(r["name"]), r["skill"], r["learn"], r["trivLo"], r["trivHi"],
                llist(r["out"]), llist(r["reagents"]), llist(r["how"]), r["cost"],
                llist(r["items"]), r["acquire"], text, "+".join(src), ver))
    out.append("}")
    return "\n".join(out) + "\n"


def item_src(e):
    parts = ["db2"]
    if "how" in e and not e.get("page"):
        parts.append("wh_list")
    if e.get("page"):
        parts.append("wh_item")
    if e.get("tt"):
        parts.append("wh_tt")
    if e.get("client"):
        parts.append("client")
    return "+".join(parts)


def item_verified(e):
    return max(PAGES_VERIFIED if e.get("page") or e.get("tt") or e.get("from") else DB2_VERIFIED,
               e.get("client") or "")


def lua_from(e):
    if not e.get("from"):
        return ""
    return ",from={%s}" % ",".join("{%s,%s,%s}" % tuple(map(lstr, f)) for f in e["from"])


def lua_items(items):
    out = [HEADER,
           "-- [itemID] = { name, q = quality, sell = vendor sell price, buy = DB2 BuyPrice,",
           "--   vstack = DB2 VendorStackCount, stack = max stack, bop, how = Wowhead source",
           "--   codes, reqSkill/reqRank = skill needed to use a recipe item,",
           "--   from = recipe item sources {role, name, zone} from the Wowhead list view's",
           "--   sourcemore column; role vendor/drop/npc/quest/object/item/zone (see SOURCES.md) } (copper)",
           "-- missing = the Item table has the ID but this ItemSparse export has no row;",
           "--   name, q and sell/buy then come from the item's Wowhead Forever page (src wh_item)",
           "--   or tooltip (src wh_tt, no buy price) when it has one; notOnWh = Wowhead Forever",
           "--   has no such item; src client = name, q and sell from the game's GetItemInfo",
           "--   (/crafter dump), which come before Wowhead's. The live GetItemInfo values win in game.",
           "ns.Items = {"]
    for i in sorted(items):
        e = items[i]
        if e.get("missing"):
            extra = ""
            for k in ("q", "sell", "buy"):
                if k in e:
                    extra += ",%s=%d" % (k, e[k])
            if "how" in e:
                extra += ",how=%s" % llist(e["how"])
            if e.get("notOnWh"):
                extra += ",notOnWh=true"
            extra += lua_from(e)
            out.append("  [%d]={name=%s,missing=true%s,src=\"%s\",verified=\"%s\"}," % (
                i, lstr(e["name"]), extra, item_src(e), item_verified(e)))
            continue
        extra = ""
        if "reqRank" in e:
            extra += ",reqSkill=%d,reqRank=%d" % (e["reqSkill"], e["reqRank"])
        if "how" in e:
            extra += ",how=%s" % llist(e["how"])
        extra += lua_from(e)
        src = item_src(e)
        out.append("  [%d]={name=%s,q=%d,sell=%d,buy=%d,vstack=%d,stack=%d,bop=%s%s,src=\"%s\",verified=\"%s\"}," % (
            i, lstr(e["name"]), e["q"], e["sell"], e["buy"], e["vstack"], e["stack"],
            llist(e["bop"]), extra, src, item_verified(e)))
    out.append("}")
    return "\n".join(out) + "\n"


def lua_vendor(vendor, items):
    out = [HEADER,
           "-- Reagents and recipe items sold by NPCs. price = DB2 BuyPrice for VendorStackCount",
           "-- (vstack) items; the item's Wowhead Forever page (wh_item) lists the same stack size",
           "-- per NPC. src wh_item: from the \"Sold by\" list on that page: limited = no NPC has",
           "-- unlimited stock, npcs = up to %d NPCs {name, zone, side} (unlimited stock first)," % NPC_SHOWN,
           "-- nNpc = how many NPCs sell it. src wh_list (no page read): Wowhead lists the source",
           "-- \"Vendor\" and limited = it also lists other sources or quality > Common. The planner",
           "-- only uses limited vendors after an in-game merchant capture. recipe = recipe item.",
           "ns.Vendor = {"]
    for i in sorted(vendor):
        v = vendor[i]
        extra = ""
        if v.get("page"):
            extra = ",npcs={%s},nNpc=%d" % (",".join("{%s,%s,%s}" % tuple(map(lstr, n)) for n in v["npcs"]),
                                           v["nNpc"])
            src, ver = "db2+wh_item", PAGES_VERIFIED
        else:
            src, ver = "db2+wh_list", DB2_VERIFIED
        out.append("  [%d]={price=%d,vstack=%d,limited=%s,recipe=%s%s,src=\"%s\",verified=\"%s\"}, -- %s" % (
            i, v["price"], v["vstack"], llist(v["limited"]), llist(v["recipe"]), extra, src, ver,
            items[i]["name"]))
    out.append("}")
    return "\n".join(out) + "\n"


def write_files(files):
    for name, text in files.items():
        path = os.path.normpath(os.path.join(ADDON, name))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def verify_manifest(manifest):
    bad = []
    for t, m in manifest["tables"].items():
        with open(os.path.join(DB2_DIR, t + ".csv"), "rb") as f:
            if sha256(f.read()) != m["snapshot_sha256"]:
                bad.append("research/db2/%s.csv does not match manifest checksum" % t)
    return bad


def main(argv):
    mode = argv[0] if argv else "build"
    if mode == "fetch":
        return cmd_fetch(argv[1:])
    if mode == "wowhead":
        return cmd_wowhead(argv[1:])
    if mode == "wowhead-pages":
        return cmd_wowhead_pages(argv[1:])
    if mode == "wowhead-sourcemore":
        return cmd_wowhead_sourcemore(argv[1:])
    if mode == "wowhead-tooltips":
        return cmd_wowhead_tooltips(argv[1:])
    if mode == "client-dump":
        return cmd_client_dump(argv[1:])
    manifest, db, wh, client = load_research()
    bad = verify_manifest(manifest)
    files, report = build(manifest, db, wh, client)
    if mode == "verify":
        for name, text in files.items():
            path = os.path.normpath(os.path.join(ADDON, name))
            cur = open(path, encoding="utf-8").read() if os.path.exists(path) else None
            if cur != text:
                bad.append("%s is stale: run python3 tools/gen_data.py" % os.path.relpath(path, ROOT))
        for b in bad:
            print("FAIL", b)
        return 1 if bad else 0
    if bad:
        for b in bad:
            print("FAIL", b)
        return 1
    write_files(files)
    for line in report:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) or 0)
