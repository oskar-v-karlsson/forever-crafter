// tools/wowhead_dump.js: dumps the list view of a Wowhead Forever list page to a JSON download.
//
// www.wowhead.com/forever pages return HTTP 403 to scripts, so this runs in a normal browser:
// open a list page (e.g. https://www.wowhead.com/forever/spells/professions/alchemy or
// https://www.wowhead.com/forever/items/recipes/alchemy), paste this into the developer console and press Enter.
// The browser downloads wh_<path>.json. Put the downloads in one folder and run
//   python3 tools/gen_data.py wowhead <folder>
// to trim them into research/wowhead/, then `make data` to regenerate ForeverCrafter/Data.
// Wowhead shows at most 1000 rows per list; gen_data.py records pages that hit the cap ("capped").
(() => {
  const lvName = Object.keys(g_listviews)[0];
  const lv = g_listviews[lvName];
  const label = {};
  const keep = ['id', 'name', 'skill', 'learnedat', 'colors', 'creates', 'reagents', 'source', 'trainingcost',
    'nskillup', 'cat', 'classs', 'subclass', 'quality', 'reqskill', 'reqskillrank', 'buyprice', 'sellprice', 'cost',
    'sourcemore', 'teaches', 'spellid', 'spells'];
  const data = lv.data.map(r => {
    for (const c of (r.source || [])) label[c] = WH.Wow.getSourceName(c);
    return Object.fromEntries(keep.filter(k => r[k] !== undefined).map(k => [k, r[k]]));
  });
  const out = { url: location.href, title: document.title, fetched: new Date().toISOString(), listview: lvName,
    count: data.length, sourceLabels: label, data };
  const slug = location.pathname.split('/').filter(Boolean).slice(1).join('_');
  const b = new Blob([JSON.stringify(out)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = 'wh_' + slug + '.json';
  document.body.appendChild(a);
  a.click();
  return slug + ' ' + data.length + ' ' + JSON.stringify(label);
})();
