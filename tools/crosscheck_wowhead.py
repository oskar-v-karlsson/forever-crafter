#!/usr/bin/env python3
"""tools/crosscheck_wowhead.py: cross-checks a sample of the generated recipes against Wowhead Forever tooltips.

For each sampled recipe it fetches https://nether.wowhead.com/forever/tooltip/spell/<id> (scriptable, unlike the
www.wowhead.com/forever pages) and compares with ForeverCrafter/Data:
  - reagents and counts (DB2 SpellReagents),
  - the created item (DB2 SpellEffect "Create Item"),
  - the created item's vendor sell price (DB2 ItemSparse.SellPrice).
Writes research/crosscheck_<date>.txt and exits 1 on a name, reagent or created-item mismatch. Sell price
differences are listed but do not fail: DB2 ItemSparse.SellPrice and the tooltips disagree for some items.

Usage: python3 tools/crosscheck_wowhead.py [N]     (N = sample size, default 40; network)
"""
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "ForeverCrafter", "Data")
URL = "https://nether.wowhead.com/forever/tooltip/spell/{}"
ALWAYS = [3170, 2963, 2385, 3275, 1244431]  # spot checks named in SOURCES.md


def load_data():
    recipes, sells, missing = {}, {}, set()
    for m in re.finditer(r"^  \[(\d+)\]=\{name=\"((?:[^\"\\]|\\.)*)\",skill=\d+,.*?out=\{(\d+),(\d+),(\d+)\},"
                         r"reagents=\{(.*?)\},how=", open(os.path.join(DATA, "Recipes.lua"), encoding="utf-8").read(),
                         re.M):
        reagents = sorted((int(a), int(b)) for a, b in re.findall(r"\{(\d+),(\d+)\}", m.group(6)))
        recipes[int(m.group(1))] = {"name": m.group(2), "out": int(m.group(3)), "reagents": reagents}
    for line in open(os.path.join(DATA, "Items.lua"), encoding="utf-8"):
        m = re.match(r"^  \[(\d+)\]=\{.*?,sell=(\d+),", line)
        if m:
            sells[int(m.group(1))] = int(m.group(2))
        m = re.match(r"^  \[(\d+)\]=\{name=\"\",missing=true", line)
        if m:
            missing.add(int(m.group(1)))
    return recipes, sells, missing


def fetch(spell):
    req = urllib.request.Request(URL.format(spell), headers={"User-Agent": "ForeverCrafter crosscheck"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def parse(tooltip):
    """→ (reagents [(id, n)], created item id or None, sell price copper or None)"""
    reagents, created, sell = [], None, None
    m = re.search(r"Reagents:<br\s*/?>\s*<div class=\"indent[^\"]*\">(.*?)</div>", tooltip, re.S)
    if m:
        # Counts follow the link: "</a>&nbsp;(2)".
        counts = re.findall(r"/forever/item=(\d+)[^>]*>[^<]*</a>(?:&nbsp;\((\d+)\))?", m.group(1))
        reagents = [(int(i), int(n) if n else 1) for i, n in counts]
        rest = tooltip[m.end():]
        cm = re.search(r"<span class=\"q\d\"><a href=\"/forever/item=(\d+)", rest)
        if cm:
            created = int(cm.group(1))
        sm = re.search(r"whtt-sellprice\">(.*?)</div>", rest, re.S)
        if sm:
            sell = 0
            for unit, v in re.findall(r"money(gold|silver|copper)\">([\d,]+)<", sm.group(1)):
                sell += int(v.replace(",", "")) * {"gold": 10000, "silver": 100, "copper": 1}[unit]
    return sorted(reagents), created, sell


def main(argv):
    n = int(argv[0]) if argv else 40
    recipes, sells, missing = load_data()
    ids = sorted(recipes)
    step = max(1, len(ids) // n)
    sample = sorted(set([i for i in ALWAYS if i in recipes] + ids[::step][:n]))
    today = datetime.date.today().isoformat()
    lines = [f"Wowhead Forever tooltip cross-check, {today}",
             f"source: {URL.format('<id>')}",
             f"sample: {len(sample)} of {len(recipes)} recipes (every {step}th by spell ID plus {ALWAYS})", ""]
    bad = sell_diff = 0
    for spell in sample:
        r = recipes[spell]
        try:
            d = fetch(spell)
        except Exception as e:  # noqa: BLE001
            lines.append(f"{spell} {r['name']}: FETCH ERROR {e}")
            bad += 1
            continue
        reagents, created, sell = parse(d.get("tooltip", ""))
        issues, soft = [], []
        if html.unescape(d.get("name", "")) != r["name"].replace('\\"', '"'):
            issues.append(f"name {d.get('name')!r}")
        extra = [x for x in r["reagents"] if x not in reagents]
        if extra and all(i in missing for i, _ in extra) and [x for x in r["reagents"] if x not in extra] == reagents:
            # Wowhead leaves out reagents that have no item; so does the game. The addon can never price them, so the
            # recipe never shows as a result.
            soft.append(f"Wowhead omits reagent(s) {extra} with no ItemSparse row")
        elif reagents != r["reagents"]:
            issues.append(f"reagents wowhead {reagents} data {r['reagents']}")
        if created is not None and created != r["out"]:
            issues.append(f"creates wowhead {created} data {r['out']}")
        if sell is not None and sells.get(r["out"], 0) != sell:
            soft.append(f"sell price wowhead {sell} data {sells.get(r['out'], 0)}")
            sell_diff += 1
        if issues:
            bad += 1
            status = "MISMATCH " + "; ".join(issues + soft)
        else:
            status = "OK" + (" (" + "; ".join(soft) + ")" if soft else "")
        lines.append(f"{spell} {r['name']}: {status}  (reagents {len(reagents)}, creates {created}, sell {sell})")
        time.sleep(0.4)
    lines += ["", f"{len(sample) - bad} OK, {bad} mismatch(es) in name, reagents or created item",
              f"{sell_diff} sell price difference(s) (DB2 ItemSparse.SellPrice vs the tooltip; the addon prefers the "
              "client's price and marks DB2-only vendor values as estimates)"]
    out = os.path.join(ROOT, "research", f"crosscheck_{today}.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines[-4:]))
    print("wrote", os.path.relpath(out, ROOT))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
