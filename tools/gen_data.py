#!/usr/bin/env python3
"""Build ForeverCrafter/Data/*.lua from pinned WoW: Forever sources.

Sources (see SOURCES.md):
  db2     wago.tools DB2 CSV export, product "wowf", build BUILD below
  wh_list Wowhead Forever list views (www.wowhead.com/forever/...), dumped in a
          browser with tools/wowhead_dump.js (the site blocks scripts)

Usage:
  python3 tools/gen_data.py fetch [--from DIR]   download the pinned DB2 CSVs and
                                                 write filtered snapshots + manifest
                                                 to research/db2/
  python3 tools/gen_data.py wowhead DIR          trim raw browser dumps from DIR
                                                 into research/wowhead/
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
import shutil
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON = os.path.join(ROOT, "ForeverCrafter")
RESEARCH = os.path.join(ROOT, "research")
DB2_DIR = os.path.join(RESEARCH, "db2")
WH_DIR = os.path.join(RESEARCH, "wowhead")

PRODUCT = "wowf"
BUILD = "1.60.1.70888"
DB2_URL = "https://wago.tools/db2/{table}/csv?build={build}"
DB2_VERIFIED = "2026-11-12"
WH_VERIFIED = "2026-11-12"

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


# ---------------------------------------------------------------- build

def load_research():
    with open(os.path.join(DB2_DIR, "manifest.json")) as f:
        manifest = json.load(f)
    db = {t: read_csv(os.path.join(DB2_DIR, t + ".csv")) for t in TABLES}
    wh = {}
    for n in ("professions", "recipe_items", "item_sources"):
        with open(os.path.join(WH_DIR, n + ".json")) as f:
            wh[n] = json.load(f)
    return manifest, db, wh


def build(manifest, db, wh):
    """Return (files dict name->text, report lines)."""
    report = []
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
        if not w:
            excluded.append((int(sp), int(a["SkillLine"]), spell_name.get(sp, "?")))
            continue
        if w.get("learnedat") == UNLEARNABLE:
            excluded.append((int(sp), int(a["SkillLine"]), spell_name.get(sp, "?") + " (learnedat 9999)"))
            continue
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
        recipes[sp] = {
            "name": spell_name.get(sp, w["name"]),
            "skill": int(a["SkillLine"]),
            "trivLo": int(a["TrivialSkillLineRankLow"]),
            "trivHi": int(a["TrivialSkillLineRankHigh"]),
            "acquire": int(a["AcquireMethod"]),
            "out": [out_id, out_min, out_max],
            "reagents": rg,
            "how": sorted(w.get("source", [])),
            "cost": int(w.get("trainingcost", 0) or 0),
            "whLearn": int(w.get("learnedat", 0) or 0),
            "items": [],
        }

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

    report.append("recipes kept %d, excluded %d, items %d, vendor %d (unlimited %d)" % (
        len(recipes), len(excluded), len(items), len(vendor),
        sum(1 for v in vendor.values() if not v["limited"])))
    no_src = sum(1 for r in recipes.values() if not r["how"])
    report.append("recipes without a Wowhead source: %d" % no_src)
    no_item_src = sorted(i for i in reagent_ids if "how" not in items.get(i, {}))
    report.append("reagents without Wowhead source data: %d %s" % (len(no_item_src), no_item_src))

    prof = {}
    for r in db["SkillLine"]:
        prof[int(r["ID"])] = (r["DisplayName_lang"], int(r["ParentSkillLineID"]))

    # Pages to read one by one on Wowhead Forever (tools/wowhead_crawl.js): what the list views leave open.
    no_how = {i for i, e in items.items() if "how" not in e}
    targets = {
        "note": "IDs for tools/wowhead_crawl.js, generated by tools/gen_data.py from the db2 and wh_list data",
        "items": sorted(set(vendor) | recipe_item_ids | no_how | set(missing)),
        "spells": sorted({int(sp) for sp, r in recipes.items() if not r["how"]} | {e[0] for e in excluded}),
    }

    files = {
        "Data/Recipes.lua": lua_recipes(recipes, prof),
        "Data/Items.lua": lua_items(items),
        "Data/Vendor.lua": lua_vendor(vendor, items),
    }
    excl = ["# ForeverCrafter: DB2 create-item recipes left out of Data/Recipes.lua",
            "# Reason: absent from every Wowhead Forever profession list (likely unobtainable),",
            "# or Wowhead learnedat 9999. A recipe the player knows still comes in at runtime",
            "# through C_TradeSkillUI. Columns: spellID, skillLine, name",
            "# db2 build %s, Wowhead lists fetched %s" % (BUILD, wh["professions"]["fetched"][:10])]
    excl += ["%d\t%d\t%s" % e for e in sorted(excluded)]
    files["../research/excluded_recipes.txt"] = "\n".join(excl) + "\n"
    files["../research/wowhead/page_targets.json"] = json.dumps(targets, separators=(",", ":")) + "\n"
    return files, report


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
           "-- skillLine = { name, parent } (parent 0 = the profession itself)",
           "ns.SkillLines = {"]
    for k in sorted(prof):
        out.append("  [%d]={name=%s,parent=%d,src=\"db2\",verified=\"%s\"}," % (
            k, lstr(prof[k][0]), prof[k][1], DB2_VERIFIED))
    out += ["}", "",
            "-- [spellID] = { name, skill = skill line, learn = rank needed to learn,",
            "--   trivLo/trivHi = yellow/grey skill-up thresholds, out = {itemID, min, max},",
            "--   reagents = {{itemID, count}}, how = Wowhead source codes (6 trainer, 5 vendor,",
            "--   2 drop, 4 quest, ...), cost = trainer cost (copper), items = recipe item IDs,",
            "--   acquire = SkillLineAbility.AcquireMethod }",
            "ns.Recipes = {"]
    for sp in sorted(recipes, key=int):
        r = recipes[sp]
        out.append(
            "  [%s]={name=%s,skill=%d,learn=%d,trivLo=%d,trivHi=%d,out=%s,reagents=%s,how=%s,"
            "cost=%d,items=%s,acquire=%d,src=\"db2+wh_list\",verified=\"%s\"}," % (
                sp, lstr(r["name"]), r["skill"], r["learn"], r["trivLo"], r["trivHi"],
                llist(r["out"]), llist(r["reagents"]), llist(r["how"]), r["cost"],
                llist(r["items"]), r["acquire"], DB2_VERIFIED))
    out.append("}")
    return "\n".join(out) + "\n"


def lua_items(items):
    out = [HEADER,
           "-- [itemID] = { name, q = quality, sell = vendor sell price, buy = DB2 BuyPrice,",
           "--   vstack = DB2 VendorStackCount, stack = max stack, bop, how = Wowhead source",
           "--   codes, reqSkill/reqRank = skill needed to use a recipe item } (copper)",
           "-- missing = the Item table has the ID but this ItemSparse export has no row;",
           "--   name from Wowhead when listed, prices only from GetItemInfo in game.",
           "ns.Items = {"]
    for i in sorted(items):
        e = items[i]
        if e.get("missing"):
            extra = ",how=%s" % llist(e["how"]) if "how" in e else ""
            out.append("  [%d]={name=%s,missing=true%s,src=\"%s\",verified=\"%s\"}," % (
                i, lstr(e["name"]), extra, "db2+wh_list" if "how" in e else "db2", DB2_VERIFIED))
            continue
        extra = ""
        if "reqRank" in e:
            extra += ",reqSkill=%d,reqRank=%d" % (e["reqSkill"], e["reqRank"])
        if "how" in e:
            extra += ",how=%s" % llist(e["how"])
        src = "db2+wh_list" if "how" in e else "db2"
        out.append("  [%d]={name=%s,q=%d,sell=%d,buy=%d,vstack=%d,stack=%d,bop=%s%s,src=\"%s\",verified=\"%s\"}," % (
            i, lstr(e["name"]), e["q"], e["sell"], e["buy"], e["vstack"], e["stack"],
            llist(e["bop"]), extra, src, DB2_VERIFIED))
    out.append("}")
    return "\n".join(out) + "\n"


def lua_vendor(vendor, items):
    out = [HEADER,
           "-- Items Wowhead Forever lists with the source \"Vendor\" (wh_list) and a DB2",
           "-- BuyPrice > 0. price = DB2 BuyPrice for VendorStackCount (vstack) items -- the",
           "-- per-bundle reading is an ASSUMPTION until checked at a merchant (SOURCES.md).",
           "-- limited = Wowhead also lists other sources (drop, gathered, ...), so the vendor",
           "-- may be limited-stock or rare; the planner only uses it after an in-game merchant",
           "-- capture. recipe = a recipe item. Which NPC sells it needs a browser/in-game check.",
           "ns.Vendor = {"]
    for i in sorted(vendor):
        v = vendor[i]
        out.append("  [%d]={price=%d,vstack=%d,limited=%s,recipe=%s,src=\"db2+wh_list\",verified=\"%s\"}, -- %s" % (
            i, v["price"], v["vstack"], llist(v["limited"]), llist(v["recipe"]), DB2_VERIFIED,
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
    manifest, db, wh = load_research()
    bad = verify_manifest(manifest)
    files, report = build(manifest, db, wh)
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
