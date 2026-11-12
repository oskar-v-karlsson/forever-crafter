// tools/wowhead_crawl.js: reads Wowhead Forever item and spell pages and keeps their source lists.
//
// www.wowhead.com/forever returns HTTP 403 to scripts, so this runs inside a browser tab that is already on a
// www.wowhead.com/forever page (same-origin fetch, the browser's own cookies). Paste it into the developer console,
// then run for example
//   await FCcrawl({ kind: 'item', ids: [2320, 3371] })
//   await FCcrawl({ kind: 'spell', ids: [2963] })
// Every 100 pages the browser downloads a batch, wh_pages_<kind>_<n>.json. Put the downloads in one folder and run
//   python3 tools/gen_data.py wowhead-pages <folder>
// to trim them into research/wowhead/pages_*.json. The crawl stops at the first page that is not a normal
// Wowhead Forever page (e.g. a bot check); FCstate[kind].left holds the IDs still to read, so nothing is guessed.
// Wowhead's bot check trips after roughly 60-70 pages in a few minutes: use conc 1 and pause 5000 or more, and when
// it trips, solve it in the tab and run FCcrawl again with ids = FCstate[kind].left and first = the next batch number.
// await FCsourcemore() downloads the recipe item lists with their sourcemore column, see below.
(() => {
  const NPC = ['id', 'name', 'location', 'react', 'stock', 'cost', 'stack', 'minlevel', 'maxlevel', 'classification',
    'count', 'outof'];
  const ROW = {
    npc: NPC,
    item: ['id', 'name', 'quality', 'classs', 'subclass', 'source', 'count', 'outof'],
    spell: ['id', 'name', 'skill', 'learnedat', 'cat', 'creates', 'reagents', 'source', 'trainingcost', 'colors'],
    object: ['id', 'name', 'location', 'type', 'count', 'outof'],
    zone: ['id', 'name', 'count', 'outof'],
    quest: ['id', 'name', 'side', 'level', 'reqlevel', 'category', 'category2'],
  };
  // Lists that say nothing about where an item or recipe comes from.
  const SKIP = new Set(['reagent-for', 'see-also', 'comments', 'screenshots', 'guides', 'same-model-as', 'criteria-of',
    'disenchanting', 'milling', 'prospecting', 'objective-of', 'currency-for', 'videos', 'used-by-item']);
  const MAX_ROWS = { 'sold-by': 200, 'taught-by-npc': 25 };   // other lists: the first 10 rows (by Wowhead's order)

  // Wowhead's embedded data is JSON except for a few unquoted keys (e.g. firstseenpatch: 0); quote those.
  function parseArray(t, j) {
    while (t[j] === ' ') j++;
    let depth = 0, inStr = false, k = j, seg = j;
    const parts = [];
    for (; k < t.length; k++) {
      const c = t[k];
      if (inStr) {
        if (c === '\\') k++;
        else if (c === '"') inStr = false;
        continue;
      }
      if (c === '"') inStr = true;
      else if (c === '[' || c === '{') depth++;
      else if (c === ']' || c === '}') {
        depth--;
        if (!depth) break;
      } else if (/[A-Za-z_$]/.test(c) && /[,{ ]/.test(t[k - 1])) {
        let e = k;
        while (/[\w$]/.test(t[e])) e++;
        let f = e;
        while (t[f] === ' ') f++;
        if (t[f] === ':') {
          parts.push(t.slice(seg, k), '"' + t.slice(k, e) + '"');
          seg = e;
        }
        k = e - 1;
      }
    }
    parts.push(t.slice(seg, k + 1));
    return JSON.parse(parts.join(''));
  }

  function listviews(t) {
    const out = {};
    const re = /new Listview\(\{\s*template:\s*'([^']+)',\s*id:\s*'([^']+)'/g;
    let m;
    while ((m = re.exec(t))) {
      const [, tpl, id] = m;
      if (SKIP.has(id)) continue;
      const d = t.indexOf('data:', m.index);
      const next = t.indexOf('new Listview(', m.index + 10);
      if (d < 0 || (next > 0 && d > next)) continue;
      let rows;
      try {
        rows = parseArray(t, d + 5);
      } catch (e) {
        out[id] = { template: tpl, error: String(e) };
        continue;
      }
      const keep = ROW[tpl] || ['id', 'name'];
      const max = MAX_ROWS[id] || 10;
      out[id] = {
        template: tpl, total: rows.length,
        rows: rows.slice(0, max).map(r => Object.fromEntries(keep.filter(k => r[k] !== undefined).map(k => [k, r[k]]))),
      };
    }
    return out;
  }

  function quickFacts(t) {
    const m = t.match(/WH\.markup\.printHtml\(("(?:[^"\\]|\\.)*")\s*,\s*"infobox-contents/);
    return m ? JSON.parse(m[1]) : null;
  }

  // The page's own entry, e.g. WH.Gatherer.addData(3, 16, {"2320": {...}}) for item 2320.
  function ownEntry(t, type, id) {
    const re = new RegExp('WH\\.Gatherer\\.addData\\(' + type + ', \\d+, ', 'g');
    let m;
    while ((m = re.exec(t))) {
      let obj;
      try {
        obj = parseArray(t, m.index + m[0].length);
      } catch (e) {
        continue;
      }
      if (obj[id]) return obj[id];
    }
    return null;
  }

  async function page(kind, id) {
    const url = '/forever/' + kind + '=' + id;
    const r = await fetch(url, { credentials: 'same-origin' });
    const t = await r.text();
    const title = (t.match(/<title>([^<]*)/) || [])[1] || '';
    if (r.status === 404 || /Page Not Found|not found/i.test(title)) return { id, url, status: r.status, notFound: true, title };
    if (r.status !== 200 || !/WoW Forever/.test(title)) throw new Error('blocked at ' + url + ': ' + r.status + ' ' + title);
    const own = ownEntry(t, kind === 'item' ? 3 : 6, id);
    const res = { id, url, title, facts: quickFacts(t), lists: listviews(t) };
    if (own) {
      res.own = {};
      for (const k of ['name_enus', 'quality', 'jsonequip', 'attainable', 'skillcategory']) {
        if (own[k] !== undefined) res.own[k] = own[k];
      }
      if (res.own.jsonequip) {
        const j = res.own.jsonequip;
        res.own.jsonequip = { buyprice: j.buyprice, sellprice: j.sellprice };
      }
    }
    return res;
  }

  window.FCstate = window.FCstate || {};
  window.FCresults = window.FCresults || {};
  function download(name, data) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: 'application/json' }));
    a.download = name + '.json';
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  // The recipe item lists with their sourcemore column (the NPC, quest or zone Wowhead names when an item has one
  // source of a kind) and the zone names, as one download, wh_sourcemore.json, for
  //   python3 tools/gen_data.py wowhead-sourcemore wh_sourcemore.json
  window.FCsourcemore = async function (paths = ['9.1', '9.2', '9.3', '9.4', '9.5', '9.6', '9.7', '9.8']
    .map(s => '/forever/items=' + s)) {
    const get = async url => {
      const r = await fetch(url, { credentials: 'same-origin' });
      const t = await r.text();
      const title = (t.match(/<title>([^<]*)/) || [])[1] || '';
      if (r.status !== 200 || !/WoW Forever/.test(title)) throw new Error('blocked at ' + url + ': ' + r.status + ' ' + title);
      return [t, title];
    };
    const lists = {};
    for (const path of paths) {
      const [t, title] = await get(path);
      const i = t.indexOf('var listviewitems = ');
      if (i < 0) throw new Error('no listviewitems on ' + path);
      lists[path] = {
        title, rows: parseArray(t, i + 'var listviewitems = '.length).map(r => ({
          id: r.id, name: String(r.name).replace(/^[0-7](?=\D)/, ''), source: r.source, sourcemore: r.sourcemore,
        })),
      };
      await new Promise(r => setTimeout(r, 4000));
    }
    const [zt] = await get('/forever/zones');
    const z = zt.indexOf('id="data.page.listPage.listviews">');
    const views = JSON.parse(zt.slice(z + 34, zt.indexOf('</script>', z)));
    const zones = views.find(v => v.id === 'zones').data
      .map(r => ({ id: r.id, name: r.name, category: r.category, territory: r.territory }));
    const out = { fetched: new Date().toISOString(), lists, zones: { url: '/forever/zones', rows: zones } };
    download('wh_sourcemore', out);
    return Object.entries(lists).map(([k, v]) => k + ' ' + v.rows.length).join(', ') + ', zones ' + zones.length;
  };

  window.FCcrawl = async function ({ kind, ids, batch = 100, conc = 3, pause = 250, first = 0 }) {
    const st = window.FCstate[kind] = { done: 0, total: ids.length, posted: first, error: null,
      started: new Date().toISOString() };
    const pending = ids.slice();
    let buf = [];
    const flush = async () => {
      if (!buf.length) return;
      const out = { kind, fetched: new Date().toISOString(), pages: buf };
      buf = [];
      const name = 'wh_pages_' + kind + '_' + String(st.posted).padStart(3, '0');
      window.FCresults[name] = out;
      download(name, out);
      st.posted++;
    };
    const worker = async () => {
      while (pending.length && !st.error) {
        const id = pending.shift();
        try {
          buf.push(await page(kind, id));
        } catch (e) {
          st.error = String(e);
          pending.unshift(id);
          break;
        }
        st.done++;
        if (buf.length >= batch) await flush();
        await new Promise(r => setTimeout(r, pause));
      }
    };
    await Promise.all(Array.from({ length: conc }, worker));
    await flush();
    st.left = pending;
    st.finished = new Date().toISOString();
    return st;
  };
  return 'FCcrawl ready';
})();
