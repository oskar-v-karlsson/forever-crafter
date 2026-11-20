"""Built-in farms for ForeverCrafter (Data/Farms.lua), used by tools/gen_data.py.

Sources (see SOURCES.md):
  wh_npc     Wowhead Forever NPC pages, https://www.wowhead.com/forever/npc=<id>: the drops, skinning and
             pickpocketing list views (research/wowhead/farms_2026-11-21.json)
  wh_object  Wowhead Forever object pages, https://www.wowhead.com/forever/object=<id>: the herbalism and mining
             list views (same file)
  wh_item    the Wowhead Forever zone list (research/wowhead/zones.json): zone names
  wh_tt      Wowhead Forever item tooltips: the sell price of drops with no ItemSparse row (same file)
  db2        wago.tools DB2 export, product "wowf": ItemSparse (build 1.60.1.70938) for the loot's names, quality
             and sell prices, SkillLine (build 1.60.1.70888) for Herbalism, Mining and Skinning
  assumed    kills and nodes per hour until the player's own sessions teach them (verified=false)

  python3 tools/gen_data.py farms-import JSON ITEMSPARSE SKILLLINE
      copy JSON (the Wowhead Forever pages) to research/wowhead/ and filter the full ItemSparse and SkillLine
      downloads to the loot items and the gathering skills into research/farms/
"""
import csv
import hashlib
import io
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FARMS_DIR = os.path.join(ROOT, "research", "farms")
WH_DIR = os.path.join(ROOT, "research", "wowhead")
FARMS_JSON = "farms_2026-11-21.json"
FARMS_VERIFIED = "2026-11-21"
# The zone farms' pages were read on 2026-11-20; the generic (zone-less) node farms were added on 2026-11-21.
ZONE_FARMS_VERIFIED = "2026-11-20"
DB2_URL = "https://wago.tools/db2/{table}/csv?build={build}"
TABLES = {
    "ItemSparse": ("1.60.1.70938", ["ID", "Display_lang", "OverallQualityID", "SellPrice", "Bonding"]),
    "SkillLine": ("1.60.1.70888", ["ID", "DisplayName_lang", "ParentSkillLineID", "CategoryID"]),
}
GATHER = {"herbalism": 182, "mining": 186, "skinning": 393}
LISTS = ("drops", "skinning", "pickpocketing", "herbalism", "mining")
# Assumed rates (not sourced): kills or nodes per hour until the player's sessions measure them.
DEFAULT_RATE = {"kill": 120, "node": 60}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


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


def loot_ids(data):
    return {row[0] for p in data["pages"].values() for rows in p["lists"].values() for row in rows}


def cmd_farms_import(args):
    if len(args) != 3:
        print("usage: gen_data.py farms-import FARMS_JSON ITEMSPARSE_CSV SKILLLINE_CSV")
        return 2
    src_json, sparse_csv, skill_csv = args
    os.makedirs(FARMS_DIR, exist_ok=True)
    shutil.copy(src_json, os.path.join(WH_DIR, FARMS_JSON))
    data = json.load(open(os.path.join(WH_DIR, FARMS_JSON), encoding="utf-8"))
    ids = {str(i) for i in loot_ids(data)}
    keep_ids = {"ItemSparse": ids, "SkillLine": {str(v) for v in GATHER.values()}}
    manifest = {"product": "wowf", "fetched": FARMS_VERIFIED, "tables": {}}
    for t, path in (("ItemSparse", sparse_csv), ("SkillLine", skill_csv)):
        build, cols = TABLES[t]
        raw = open(path, "rb").read()
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        keep = sorted((r for r in rows if r["ID"] in keep_ids[t]), key=lambda r: int(r["ID"]))
        out = write_csv(os.path.join(FARMS_DIR, t + ".csv"), cols, keep)
        manifest["tables"][t] = {"build": build, "url": DB2_URL.format(table=t, build=build),
                                 "full_sha256": sha256(raw), "full_rows": len(rows), "snapshot_sha256": sha256(out),
                                 "snapshot_rows": len(keep), "columns": cols}
        print("%-11s %5d of %6d rows" % (t, len(keep), len(rows)))
    raw = open(os.path.join(WH_DIR, FARMS_JSON), "rb").read()
    manifest["wowhead"] = {"file": "research/wowhead/" + FARMS_JSON, "sha256": sha256(raw), "source": data["source"],
                           "fetched": data["fetched"]}
    with open(os.path.join(FARMS_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0


def verify_farms_manifest():
    path = os.path.join(FARMS_DIR, "manifest.json")
    if not os.path.exists(path):
        return ["research/farms/manifest.json is missing"]
    m = json.load(open(path))
    bad = []
    for t, e in m["tables"].items():
        if sha256(open(os.path.join(FARMS_DIR, t + ".csv"), "rb").read()) != e["snapshot_sha256"]:
            bad.append("research/farms/%s.csv does not match manifest checksum" % t)
    if sha256(open(os.path.join(ROOT, m["wowhead"]["file"]), "rb").read()) != m["wowhead"]["sha256"]:
        bad.append("%s does not match research/farms/manifest.json" % m["wowhead"]["file"])
    return bad


def lstr(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def stack(text):
    """Wowhead's stack "min-max". "0-0" (3 rows: no stack data) is read as 1-1."""
    lo, hi = (int(x) for x in text.split("-"))
    if lo == 0 and hi == 0:
        return 1, 1, True
    assert 1 <= lo <= hi, text
    return lo, hi, False


def rows_of(data):
    """{page: {list: [(item, count, outof, lo, hi)]}}, the "0-0" rows, every item with its quality, name, page kind."""
    pages, zero, items = {}, [], {}
    for key, p in data["pages"].items():
        assert key == "%s%d" % (p["type"], p["id"]) and p["type"] in ("npc", "object"), key
        lists = {}
        for lname, rows in p["lists"].items():
            assert lname in LISTS, (key, lname)
            out = []
            for item, name, q, count, outof, st in rows:
                assert 0 < count <= outof, (key, item)
                lo, hi, z = stack(st)
                if z:
                    zero.append((key, item))
                out.append((item, count, outof, lo, hi))
                kind = "wh_" + p["type"]
                prev = items.get(item)
                items[item] = (name, q, "wh_npc" if (prev and prev[2] == "wh_npc") else kind)
            out.sort(key=lambda r: (-r[1] / r[2], r[0]))
            lists[lname] = out
        pages[key] = lists
    return pages, zero, items


def build_farms(known_items):
    """Data/Farms.lua text and report lines. known_items: item IDs that Data/Items.lua or Data/Reputation.lua have."""
    ver = FARMS_VERIFIED
    data = json.load(open(os.path.join(WH_DIR, FARMS_JSON), encoding="utf-8"))
    zones = json.load(open(os.path.join(WH_DIR, "zones.json"), encoding="utf-8"))["zones"]
    rd = lambda n: open(os.path.join(FARMS_DIR, n), encoding="utf-8")
    sparse = {int(r["ID"]): r for r in csv.DictReader(rd("ItemSparse.csv"))}
    skills = {int(r["ID"]): r["DisplayName_lang"] for r in csv.DictReader(rd("SkillLine.csv"))}
    for k, v in GATHER.items():
        assert skills.get(v, "").lower() == k, (k, v, skills.get(v))
    tt = {int(k): v for k, v in data["sellPricesFromTooltip"].items()}
    pages, zero, items = rows_of(data)
    report = []
    fl = []
    used_pages = set()
    page_ver = {}  # a page's date: the zone farms' (2026-11-20) if a zone farm uses it, else the generic farms'
    for f in data["farms"]:
        kind = f["kind"]
        assert kind in DEFAULT_RATE and f["pages"], f
        # Zone-less farms are generic gathering nodes, matched in any zone by the looted object.
        assert f["zone"] is not None or kind == "node", f
        fver = ZONE_FARMS_VERIFIED if f["zone"] is not None else ver
        for p in f["pages"]:
            assert p in pages and p.startswith("npc" if kind == "kill" else "object"), (f["key"], p)
            used_pages.add(p)
            page_ver[p] = min(page_ver.get(p, fver), fver)
        rate = f.get("defaultRate", DEFAULT_RATE[kind])
        if f["zone"] is None:
            where, src = "", "wh_object"
        else:
            where, src = "zone=%d,zoneName=%s," % (f["zone"], lstr(zones[str(f["zone"])])), "%s+wh_item" % (
                "wh_npc" if kind == "kill" else "wh_object")
        fl.append("  {key=%s,name=%s,%skind=%s,pages={%s},rate={n=%d,src=\"assumed\",verified=false},"
                  "src=\"%s\",verified=\"%s\"}," % (
                      lstr(f["key"]), lstr(f["name"]), where, lstr(kind),
                      ",".join(lstr(p) for p in f["pages"]), rate, src, fver))
    assert used_pages == set(pages), set(pages) - used_pages
    item_ver = {}
    for key, lists in pages.items():
        for rows in lists.values():
            for r in rows:
                item_ver[r[0]] = min(item_ver.get(r[0], page_ver[key]), page_ver[key])
    pl = []
    for key in sorted(pages, key=lambda k: (data["pages"][k]["type"], data["pages"][k]["id"])):
        p = data["pages"][key]
        parts = ["kind=%s" % lstr(p["type"]), "id=%d" % p["id"], "name=%s" % lstr(p["name"]), "url=%s" % lstr(p["url"])]
        for lname in LISTS:
            rows = pages[key].get(lname)
            if rows:
                parts.append("%s={%s}" % (lname, ",".join("{%d,%d,%d,%d,%d}" % r for r in rows)))
        parts.append("src=\"wh_%s\",verified=\"%s\"" % (p["type"], page_ver[key]))
        pl.append("  %s={%s}," % (key, ",".join(parts)))
    il = []
    n_db2 = n_tt = 0
    for i in sorted(items):
        name, q, kind = items[i]
        if i in tt and i in sparse:
            assert int(sparse[i]["SellPrice"]) == tt[i]["sell"], (i, sparse[i]["SellPrice"], tt[i])
        if i in known_items:
            continue
        r = sparse.get(i)
        if r:
            n_db2 += 1
            il.append("  [%d]={name=%s,q=%s,sell=%s,bop=%s,src=\"db2\",verified=\"%s\"}," % (
                i, lstr(r["Display_lang"]), r["OverallQualityID"], r["SellPrice"],
                "true" if r["Bonding"] == "1" else "false", item_ver[i]))
        elif i in tt:
            n_tt += 1
            il.append("  [%d]={name=%s,q=%d,sell=%d,missing=true,src=\"%s+wh_tt\",verified=\"%s\"}," % (
                i, lstr(name), q, tt[i]["sell"], kind, item_ver[i]))
        else:
            il.append("  [%d]={name=%s,q=%d,missing=true,src=\"%s\",verified=\"%s\"}," % (
                i, lstr(name), q, kind, item_ver[i]))
    out = ["-- GENERATED by tools/gen_data.py (tools/gen_farms.py) -- do not edit by hand.",
           "-- Sources: wh_npc / wh_object = Wowhead Forever NPC and object pages read on %s" % data["fetched"],
           "--          (research/wowhead/%s), wh_item = the Wowhead Forever zone list (zones.json)," % FARMS_JSON,
           "--          db2 = wago.tools DB2 export, product wowf (research/farms/manifest.json), wh_tt = Wowhead",
           "--          Forever tooltips, assumed = kills or nodes per hour until your own sessions measure them.",
           "-- See SOURCES.md. Licence: GPL-2.0-or-later.",
           "local _, ns = ...", "",
           "ns.FarmInfo = {fetched=%s,skills={herbalism=%d,mining=%d,skinning=%d},src=\"wh_npc+wh_object+db2\","
           "verified=\"%s\"}" % (lstr(data["fetched"]), GATHER["herbalism"], GATHER["mining"], GATHER["skinning"],
                                 ver), "",
           "-- Farms: kind = kill (mobs) | node (herbs, ore); pages = the mobs or nodes (ns.FarmPages); no zone = a generic",
           "--   node farm, counted in any zone;",
           "--   rate = kills or nodes per hour, assumed until learned from your sessions.",
           "ns.FarmDefs = {"] + fl + ["}", "",
           "-- Wowhead Forever pages. Each list (drops, skinning, pickpocketing, herbalism, mining) has rows",
           "--   {item, count, outof, min, max}: chance per kill or node = count / outof; a drop is a stack of min-max",
           "--   (\"0-0\" on Wowhead, %d rows, is read as 1-1).  Avg per kill or node = chance x (min + max) / 2." % len(
               zero),
           "ns.FarmPages = {"] + pl + ["}", "",
           "-- Loot that Data/Items.lua and Data/Reputation.lua do not have: DB2 ItemSparse name, quality, sell price;",
           "--   with no ItemSparse row (missing=true): the Wowhead name and quality, and the tooltip's sell price.",
           "ns.FarmItems = {"] + il + ["}"]
    report.append("farms: %d farms, %d pages, %d loot rows, %d extra items (%d db2, %d tooltip sell, %d no sell), "
                  "%d \"0-0\" stacks read as 1" % (
                      len(fl), len(pl), sum(len(r) for p in pages.values() for r in p.values()), len(il), n_db2, n_tt,
                      len(il) - n_db2 - n_tt, len(zero)))
    return "\n".join(out) + "\n", report
