"""Durotar Supply and Logistics data for ForeverCrafter (Data/Reputation.lua), used by tools/gen_data.py.

Sources (see SOURCES.md):
  db2   wago.tools DB2 CSV export, product "wowf", build REP_BUILD: ItemSparse, Faction, CurrencyTypes
  wh_tt Wowhead Forever tooltips (nether.wowhead.com/forever/tooltip/item/<id> and /quest/<id>): which item and
        how many each Craftsman's Writ quest wants, the fill bundles of each Waylaid Crate, the receipt's +50
  user  amounts the user gave from third-party guides (research/rep/amounts.json), verified=false

  python3 tools/gen_data.py rep-import DIR   filter DIR/{ItemSparse,Faction,CurrencyTypes}.csv (full wago.tools
                                             downloads) and copy DIR/{writs,crates}.json into research/rep/
"""
import csv
import hashlib
import io
import json
import os
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REP_DIR = os.path.join(ROOT, "research", "rep")
REP_BUILD = "1.60.1.70938"
REP_VERIFIED = "2026-11-16"
DB2_URL = "https://wago.tools/db2/{table}/csv?build={build}"
TT_URL = "https://nether.wowhead.com/forever/tooltip/{kind}/{id}"

FACTIONS = {"Horde": 2587, "Alliance": 2586}   # Durotar Supply and Logistics / Azeroth Commerce Authority
CURRENCY = 3402                                  # Merchant's Favor
EMPTY_CRATE = 248549                             # Waylaid Crate (unidentified, "Read the label")
RECEIPT = 262902                                 # Forged Delivery Receipt
SEALED = range(248765, 248780)                   # Sealed <Tier> Crate, 3 qualities x 5 tiers (BoP)
WRITS = range(264011, 264161)                    # Craftsman's Writ: <item>
TIERS = ["Apprentice", "Journeyman", "Expert", "Artisan", "Elite"]
REP_TABLES = {
    "ItemSparse": ["ID", "Display_lang", "OverallQualityID", "SellPrice", "BuyPrice", "VendorStackCount",
                   "Stackable", "Bonding", "StartQuestID"],
    "Faction": ["ID", "Name_lang"],
    "CurrencyTypes": ["ID", "Name_lang"],
}
BUNDLE = re.compile(r"\|- (\d+) ([^|]+?)(?= Crafting Reagent|\|)")
COUNT_IN_NAME = re.compile(r"^(.*) x (\d+)$")   # "Crafted Solid Shot x 200": the tooltip puts the count in the name


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def read_csv_bytes(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8"))))


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


def crate_bundles(text):
    return [(int(n), name.strip()) for n, name in BUNDLE.findall(text + "|")]


def writ_item(entry):
    """(name, count, candidate ids) of the one item a writ quest wants."""
    it = entry["items"][0]
    name, count = it["name"], it["count"]
    m = COUNT_IN_NAME.match(name)
    if m and not it["ids"]:
        name, count = m.group(1), int(m.group(2))
    return name, count, it["ids"]


def needed_names(writs, crates):
    names = set()
    for w in writs:
        names.add(writ_item(w)[0])
    for _, (_, text) in crates.items():
        for _, name in crate_bundles(text):
            names.add(name)
    return names


def cmd_rep_import(args):
    if not args:
        print("usage: gen_data.py rep-import DIR")
        return 2
    src = args[0]
    os.makedirs(REP_DIR, exist_ok=True)
    writs = json.load(open(os.path.join(src, "writs.json")))
    crates = json.load(open(os.path.join(src, "crates.json")))
    names = needed_names(writs, crates)
    ids = {str(i) for i in list(WRITS) + list(SEALED) + [EMPTY_CRATE, RECEIPT]} | set(crates)
    manifest = {"product": "wowf", "build": REP_BUILD, "fetched": REP_VERIFIED, "tables": {}, "tooltips": {}}
    for t, cols in REP_TABLES.items():
        raw = open(os.path.join(src, t + ".csv"), "rb").read()
        rows = read_csv_bytes(raw)
        if t == "ItemSparse":
            keep = [r for r in rows if r["ID"] in ids or r["Display_lang"] in names]
        elif t == "Faction":
            keep = [r for r in rows if int(r["ID"]) in FACTIONS.values()]
        else:
            keep = [r for r in rows if int(r["ID"]) == CURRENCY]
        keep.sort(key=lambda r: int(r["ID"]))
        data = write_csv(os.path.join(REP_DIR, t + ".csv"), cols, keep)
        manifest["tables"][t] = {"url": DB2_URL.format(table=t, build=REP_BUILD), "full_sha256": sha256(raw),
                                 "full_rows": len(rows), "snapshot_sha256": sha256(data),
                                 "snapshot_rows": len(keep), "columns": cols}
        print("%-14s %6d of %6d rows" % (t, len(keep), len(rows)))
    for n, what in (("writs.json", "Craftsman's Writ items 264011-264160: " + TT_URL.format(kind="item", id="<writ>")
                     + " and the quest it starts, " + TT_URL.format(kind="quest", id="<quest>")),
                    ("crates.json", "Waylaid Crate items, the receipt and 275642: "
                     + TT_URL.format(kind="item", id="<id>") + " as [name, tooltip text]")):
        shutil.copy(os.path.join(src, n), os.path.join(REP_DIR, n))
        data = open(os.path.join(REP_DIR, n), "rb").read()
        manifest["tooltips"][n] = {"source": what, "sha256": sha256(data), "fetched": REP_VERIFIED}
    with open(os.path.join(REP_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return 0


def verify_rep_manifest():
    bad = []
    path = os.path.join(REP_DIR, "manifest.json")
    if not os.path.exists(path):
        return ["research/rep/manifest.json is missing"]
    m = json.load(open(path))
    for t, e in m["tables"].items():
        if sha256(open(os.path.join(REP_DIR, t + ".csv"), "rb").read()) != e["snapshot_sha256"]:
            bad.append("research/rep/%s.csv does not match manifest checksum" % t)
    for n, e in m["tooltips"].items():
        if sha256(open(os.path.join(REP_DIR, n), "rb").read()) != e["sha256"]:
            bad.append("research/rep/%s does not match manifest checksum" % n)
    return bad


def lstr(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def lnum(v):
    return "nil" if v is None else str(v)


def build_rep(recipe_items):
    """Data/Reputation.lua text and report lines. recipe_items: the item IDs of Data/Items.lua."""
    rd = lambda n: open(os.path.join(REP_DIR, n), encoding="utf-8")
    sparse = {int(r["ID"]): r for r in csv.DictReader(rd("ItemSparse.csv"))}
    factions = {int(r["ID"]): r["Name_lang"] for r in csv.DictReader(rd("Faction.csv"))}
    currency = {int(r["ID"]): r["Name_lang"] for r in csv.DictReader(rd("CurrencyTypes.csv"))}
    writs = json.load(rd("writs.json"))
    crates = json.load(rd("crates.json"))
    amounts = json.load(rd("amounts.json"))
    by_name = {}
    for i, r in sparse.items():
        by_name.setdefault(r["Display_lang"], []).append(i)
    report = []

    def resolve(name, ids=None):
        """Item ID by name: a recipe item (Data/Items.lua) first, else the lowest (classic) ID."""
        cands = sorted(set(ids or []) | set(by_name.get(name, [])))
        if not cands:
            raise SystemExit("rep: no ItemSparse row named %r" % name)
        known = [i for i in cands if i in recipe_items]
        pick = (known or cands)[0]
        if len(cands) > 1:
            report.append("rep: %r matches %s, using %d" % (name, cands, pick))
        return pick

    used = set()
    wl = []
    tiers = {t: i + 1 for i, t in enumerate(TIERS)}
    for w in sorted(writs, key=lambda x: x["writ"]):
        row = sparse[w["writ"]]
        assert row["Display_lang"] == "Craftsman's Writ: " + w["name"], w
        assert int(row["StartQuestID"]) == w["quest"], w
        assert row["Bonding"] == "0", w
        assert len(w["items"]) == 1, w
        name, count, ids = writ_item(w)
        item = resolve(name, ids)
        used.add(item)
        wl.append("  [%d]={quest=%d,tier=%d,item=%d,n=%d,src=\"db2+wh_tt\",verified=\"%s\"}, -- %s" % (
            w["writ"], w["quest"], tiers[w["tier"]], item, count, REP_VERIFIED, w["name"]))
    cl, crate_ids = [], set()
    for k in sorted(crates, key=int):
        cid = int(k)
        name, text = crates[k]
        m = re.match(r"^Waylaid Crate: (?:(Earthly|Flowering) )?(\w+) (\w+)$", name)
        if not m:
            continue
        row = sparse[cid]
        assert row["Display_lang"] == name and row["Bonding"] == "0", name
        kind = (m.group(1) + " " if m.group(1) else "") + m.group(3)
        crate_ids.add(cid)
        bundles = []
        for n, bname in crate_bundles(text):
            i = resolve(bname)
            used.add(i)
            bundles.append("{%d,%d}" % (i, n))
        assert bundles, name
        cl.append("  [%d]={tier=%d,kind=%s,q=%d,bundles={%s},src=\"db2+wh_tt\",verified=\"%s\"}, -- %s" % (
            cid, tiers[m.group(2)], lstr(kind), int(row["OverallQualityID"]), ",".join(bundles), REP_VERIFIED, name))
    sl = []
    for i in SEALED:
        row = sparse[i]
        m = re.match(r"^Sealed (\w+) Crate$", row["Display_lang"])
        sl.append("  [%d]={tier=%d,q=%d,src=\"db2\",verified=\"%s\"}, -- %s" % (
            i, tiers[m.group(1)], int(row["OverallQualityID"]), REP_VERIFIED, row["Display_lang"]))
    assert "+50 reputation" in crates[str(RECEIPT)][1]
    own = set(WRITS) | set(SEALED) | {EMPTY_CRATE, RECEIPT} | crate_ids
    il = []
    for i in sorted((own | used) - set(recipe_items)):
        r = sparse.get(i)
        if not r:
            continue
        il.append("  [%d]={name=%s,q=%s,sell=%s,buy=%s,vstack=%s,stack=%s,bop=%s,src=\"db2\",verified=\"%s\"}," % (
            i, lstr(r["Display_lang"]), r["OverallQualityID"], r["SellPrice"], r["BuyPrice"], r["VendorStackCount"],
            r["Stackable"], "true" if r["Bonding"] == "1" else "false", REP_VERIFIED))

    def amount(key, body):
        a = amounts[key]
        ver = "false" if a["verified"] is False else '"%s"' % a["verified"]
        return "  %s={%s,src=\"%s\",verified=%s}, -- %s" % (key, body, a["src"], ver, a["note"])

    tier_map = lambda d: ",".join("[%d]=%d" % (tiers[t], v) for t, v in d.items() if v is not None)
    favor = ",".join("[%d]={%s,%s}" % (tiers[t], lnum(v.get("white")), lnum(v.get("green")))
                     for t, v in amounts["favor"]["value"].items())
    ver = REP_VERIFIED
    out = ["-- GENERATED by tools/gen_data.py (tools/gen_rep.py) -- do not edit by hand.",
           "-- Sources: db2 = wago.tools DB2 export, product wowf, build %s (research/rep/manifest.json)" % REP_BUILD,
           "--          wh_tt = Wowhead Forever tooltips (research/rep/writs.json, crates.json)",
           "--          user = amounts from the user and third-party guides, not verified (research/rep/amounts.json)",
           "-- See SOURCES.md. Licence: GPL-2.0-or-later.",
           "local _, ns = ...", "",
           "ns.Rep = {",
           "  build = \"%s\"," % REP_BUILD,
           "  tiers = {%s}," % ",".join(lstr(t) for t in TIERS),
           "  factions = {Horde={id=%d,name=%s},Alliance={id=%d,name=%s},src=\"db2\",verified=\"%s\"}," % (
               FACTIONS["Horde"], lstr(factions[FACTIONS["Horde"]]), FACTIONS["Alliance"],
               lstr(factions[FACTIONS["Alliance"]]), ver),
           "  currency = {id=%d,name=%s,src=\"db2\",verified=\"%s\"}," % (CURRENCY, lstr(currency[CURRENCY]), ver),
           "  emptyCrate = %d, -- %s" % (EMPTY_CRATE, sparse[EMPTY_CRATE]["Display_lang"]),
           "  receipt = %d, -- %s" % (RECEIPT, sparse[RECEIPT]["Display_lang"]),
           "}", "",
           "-- [writ item] = { quest = the quest it starts (ItemSparse StartQuestID), tier = 2 Journeyman .. 4 Artisan,",
           "--   item, n = what the quest wants (the quest tooltip) }",
           "ns.RepWrits = {"] + wl + ["}", "",
           "-- [identified crate] = { tier = 1 Apprentice .. 4 Artisan, kind, q = ItemSparse quality (1 = white: raw",
           "--   materials, 2 = green: processed), bundles = the fill bundles {item, n} of the crate's tooltip }",
           "ns.RepCrates = {"] + cl + ["}", "",
           "-- [sealed crate] = { tier = 1 Apprentice .. 5 Elite, q = ItemSparse quality }: what a filled crate becomes (BoP)",
           "ns.RepSealed = {"] + sl + ["}", "",
           "-- Writs, crates and the items they want that Data/Items.lua does not have: ItemSparse name, quality, prices",
           "ns.RepItems = {"] + il + ["}", "",
           "-- Amounts. Values the game shows replace these (Modules/Reputation.lua learns them on turn-in).",
           "ns.RepAmounts = {",
           amount("writRep", tier_map(amounts["writRep"]["value"])),
           amount("pouch", tier_map(amounts["pouch"]["value"])),
           amount("favor", favor),
           amount("receiptFavor", "value=%d" % amounts["receiptFavor"]["value"]),
           amount("crateRep", "value=%d" % amounts["crateRep"]["value"]),
           "}"]
    report.append("rep: %d writs, %d crates, %d sealed crates, %d extra items" % (len(wl), len(cl), len(sl), len(il)))
    return "\n".join(out) + "\n", report
