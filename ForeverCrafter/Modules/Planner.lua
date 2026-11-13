-- Modules/Planner.lua: finds profitable crafts and chains of crafts.
-- cost(item, qty) = cheapest of: buying qty on the AH (ladder walk), a vendor, or crafting it with a known recipe
-- whose reagents are priced the same way (any depth, cycle guard). A recipe's profit = what its output sells for
-- (AH after cut and deposit, or vendor) minus the cost of its reagents. Unlearned recipes the player's skill
-- allows are evaluated too, with what it takes to learn them.
local _, ns = ...
local PL = {}
ns.Planner = PL
local Util = ns.Util

PL.MAX_DEPTH = 8

-- Effective recipe: the trade-skill window's schematic (authoritative) over the static data.
function PL.Recipe(spell)
  local r = ns.Recipes[spell]
  local s = ns.char and ns.char.schematics[spell]
  if not s then return r end
  return {
    name = s.name or (r and r.name), skill = s.skill or (r and r.skill), learn = r and r.learn,
    trivLo = r and r.trivLo, trivHi = r and r.trivHi, out = s.out,
    reagents = (#s.reagents > 0 or not r) and s.reagents or r.reagents,
    how = r and r.how or {}, cost = r and r.cost or 0, items = r and r.items or {}, acquire = r and r.acquire,
    known = r and r.known, runtime = true,
  }
end

local function allSpells()
  local seen, list = {}, {}
  for spell in pairs(ns.Recipes) do
    seen[spell] = true
    table.insert(list, spell)
  end
  for spell in pairs(ns.char and ns.char.schematics or {}) do
    if not seen[spell] then table.insert(list, spell) end
  end
  return list
end

-- Learnable now: not known, the profession window did not hide it, and the skill rank is high enough.
function PL.Learnable(spell, r)
  local line = Util.ParentLine(r.skill)
  local rank = ns.Professions.Rank(line)
  if not rank or not r.learn then return false end
  if ns.Professions.IsHidden(spell, line) then return false end
  return rank >= r.learn
end

-- Skill-up colour: the client's difficulty when the window was read, else the DB2 thresholds.
local DIFFICULTY = { [0] = "orange", [1] = "yellow", [2] = "green", [3] = "grey" }
function PL.Color(spell, r)
  local d = ns.char and ns.char.difficulty[spell]
  if d and DIFFICULTY[d] then return DIFFICULTY[d] end
  return PL.ColorAt(ns.Professions.Rank(Util.ParentLine(r.skill)), r)
end

-- Created items per craft. DB2 and Wowhead give 0 for a few recipes (e.g. Lesser Wizard Oil 25126); a craft makes
-- at least one, so 0 counts as 1 and the result is marked as an estimate until the profession window gives the count.
function PL.CountUnknown(r)
  return (r.out[2] or 1) < 1
end

-- Items per craft as min, max. Some crafts make a random count (Heavy Dynamite 1-5, from SpellEffect.Variance); costs
-- and profit use the average, and the result shows the worst and best case.
function PL.OutRange(r)
  local lo = math.max(r.out[2] or 1, 1)
  return lo, math.max(r.out[3] or lo, lo)
end

local function avgOut(r)
  local lo, hi = PL.OutRange(r)
  return (lo + hi) / 2
end
PL.AvgOut = avgOut

-- One solver run. Memoises cost(item, qty) unless the subtree hit the cycle guard or the depth limit.
local function newSolver(usable, producers)
  local memo = {}
  local cost
  cost = function(id, qty, depth, visiting)
    local key = id * 100000 + qty
    local m = memo[key]
    -- A cached chain is reused only if it still fits under the depth limit from here (h = crafts in its height).
    if m == false or (m and depth + m.h <= PL.MAX_DEPTH) then return m or nil, false end
    local best
    local ah, est = ns.Pricing.AHBuy(id, qty)
    if ah then best = { id = id, qty = qty, cost = ah, src = "ah", est = est, h = 0 } end
    local unit, label, limited = ns.Pricing.VendorUnit(id)
    if unit then
      local c = math.ceil(unit * qty)
      if not best or c < best.cost then
        best = { id = id, qty = qty, cost = c, src = "vendor", est = label == "estimate", limited = limited, h = 0 }
      end
    end
    local incomplete = false
    if visiting[id] or depth >= PL.MAX_DEPTH then
      incomplete = true
    else
      visiting[id] = true
      for _, spell in ipairs(producers[id] or {}) do
        local r = PL.Recipe(spell)
        if usable(spell, r) then
          local lo, hi = PL.OutRange(r)
          local crafts = math.ceil(qty / ((lo + hi) / 2))
          local total, kids, ok, est, h, var = 0, {}, true, PL.CountUnknown(r), 0, hi > lo
          for _, rg in ipairs(r.reagents) do
            local c, inc = cost(rg[1], rg[2] * crafts, depth + 1, visiting)
            if inc then incomplete = true end
            if not c then
              ok = false
              break
            end
            total = total + c.cost
            if c.est then est = true end
            if c.var then var = true end
            if c.h > h then h = c.h end
            table.insert(kids, c)
          end
          if ok and (not best or total < best.cost) then
            best = { id = id, qty = qty, cost = total, src = "craft", spell = spell, crafts = crafts, children = kids,
              est = est, h = h + 1, var = var or nil, outMin = hi > lo and lo or nil, outMax = hi > lo and hi or nil }
          end
        end
      end
      visiting[id] = nil
    end
    if not incomplete then memo[key] = best or false end
    return best, incomplete
  end
  return cost
end

-- Recipes that can be used as a step inside a chain: known and not hidden.
local function knownUsable(spell, r)
  local line = Util.ParentLine(r.skill)
  return ns.Professions.IsKnown(spell, line) and not ns.Professions.IsHidden(spell, line)
end

-- What learning an unlearned recipe takes. → { cost (copper or nil), text }
-- The game's own source text comes first: read from this character's profession window, else from a client dump in
-- the data (learnText).
function PL.Acquire(r, spell)
  local parts, cost = {}, nil
  local game = spell and ns.char and ns.char.sourceText[spell] or r.learnText
  if game then table.insert(parts, "Game: " .. Util.SourceText(game)) end
  local how = {}
  for _, c in ipairs(r.how or {}) do how[c] = true end
  if how[6] then
    cost = r.cost or 0
    table.insert(parts, "Trainer" .. ((r.cost or 0) > 0 and (" " .. Util.Money(r.cost)) or ""))
  end
  for _, item in ipairs(r.items or {}) do
    local p = ns.Scanner.Price(item)
    local unit, label = ns.Pricing.VendorUnit(item)
    local seen = ns.db.vendorSeen[item]
    local v = ns.Vendor[item]
    local options = {}
    if p then
      table.insert(options, "AH " .. Util.Money(p.min))
      if not cost or p.min < cost then cost = p.min end
    end
    if seen then
      table.insert(options, "vendor " .. Util.Money(seen.unit) .. (seen.npc and (" (" .. seen.npc .. ")") or ""))
      if not cost or seen.unit < cost then cost = seen.unit end
    elseif v then
      table.insert(options, "vendor ~" .. Util.Money(v.price) .. (v.limited and " (limited)" or "")
        .. Util.VendorNPC(item))
      if not cost or v.price < cost then cost = v.price end
    elseif unit then
      table.insert(options, "vendor " .. label)
    end
    local d = ns.Items[item]
    local from = Util.FromText(item)
    if #options == 0 then
      table.insert(options, Util.Sources(d and d.how))
    end
    table.insert(parts, Util.ItemText(item) .. ": " .. table.concat(options, ", ") .. (from and (" - " .. from) or ""))
  end
  if #parts == (game and 1 or 0) then
    local rest = {}
    for _, c in ipairs(r.how or {}) do
      if c ~= 6 then table.insert(rest, c) end
    end
    if #rest > 0 then
      table.insert(parts, Util.Sources(rest))
    elseif game then
      -- the game's text says it all
    elseif r.acquire == 1 then
      table.insert(parts, "no source on Wowhead Forever; game data marks it AcquireMethod 1 (may be learned "
        .. "automatically - check your trainer)" .. (r.known and "; a character knew it in a client dump" or ""))
    elseif r.known then
      table.insert(parts, "no source on Wowhead Forever; a character knew it in a client dump (check your trainer)")
    else
      table.insert(parts, "source unknown (check Wowhead Forever or your trainer)")
    end
  end
  return { cost = cost, text = table.concat(parts, "; ") }
end

-- Producers of each item among the given spells: itemID → sorted spell list.
local function producersOf(spells)
  local producers = {}
  for _, spell in ipairs(spells) do
    local r = PL.Recipe(spell)
    if r and r.out then
      producers[r.out[1]] = producers[r.out[1]] or {}
      table.insert(producers[r.out[1]], spell)
    end
  end
  for _, list in pairs(producers) do table.sort(list) end
  return producers
end

-- One recipe's craft: sell value of its output minus the cheapest reagents. → result, or nil and the reason
-- ("noValue" | "noPrice")
local function evaluate(spell, r, line, cost)
  local outID = r.out[1]
  local value = ns.Pricing.SellValue(outID)
  if not value then return nil, "noValue" end
  local total, kids, est, h, var = 0, {}, false, 0, false
  for _, rg in ipairs(r.reagents) do
    local c = cost(rg[1], rg[2], 0, { [outID] = true })
    if not c then return nil, "noPrice" end
    total = total + c.cost
    if c.est then est = true end
    if c.var then var = true end
    if c.h > h then h = c.h end
    table.insert(kids, c)
  end
  local lo, hi = PL.OutRange(r)
  local n = (lo + hi) / 2
  local worth = math.floor(value.unit * n)
  local res = {
    spell = spell, name = r.name or Util.ItemName(outID), line = line, out = outID, n = n,
    cost = total, value = worth, profit = worth - total,
    pct = total > 0 and (worth - total) / total or nil,
    where = value.where, sell = value,
    est = est or PL.CountUnknown(r) or (value.where == "vendor" and value.vendorEst) or false,
    runtime = r.runtime,
    sales = ns.Sales and ns.Sales.Get(outID),
    tree = { id = outID, qty = n, cost = total, src = "craft", spell = spell, crafts = 1, children = kids, h = h + 1 },
  }
  -- Random output count: the worst and best case of one craft (profit itself uses the average). var: this craft or
  -- a step of its chain makes a random count.
  if hi > lo then
    res.outMin, res.outMax = lo, hi
    res.worst = math.floor(value.unit * lo) - total
    res.best = math.floor(value.unit * hi) - total
    res.tree.outMin, res.tree.outMax = lo, hi
  end
  if hi > lo or var then
    res.var = true
    res.tree.var = true
  end
  return res
end

local function byProfit(a, b)
  if a.profit ~= b.profit then return a.profit > b.profit end
  return a.spell < b.spell
end

-- What-if mode ----------------------------------------------------------------------------------------------------
-- A made-up character with every profession at a skill cap: any recipe the cap allows, from any profession, can be a
-- step of a chain. Each recipe gets a confidence that it can really be learned; a chain takes its lowest.

PL.CONF = { "Confirmed", "Trainer/vendor", "Likely", "Drop/quest/other", "Unknown" }
PL.CONF_SHORT = { "known", "trainer", "likely", "drop", "unknown" }
PL.CONF_COLOR = { "ff40ff40", "ffa0e060", "ffffff00", "ffff9040", "ffff4040" }
PL.DEFAULT_CAP = 150
PL.SECONDARY_CAT = 9   -- SkillLine.CategoryID of secondary skills (Cooking, First Aid); 11 = professions

-- How sure it is that a recipe can be learned (see SOURCES.md, "What-if confidence"). → level 1 (surest) .. 5
function PL.Confidence(spell, r)
  if r.known or ns.Professions.IsKnown(spell, Util.ParentLine(r.skill)) then return 1 end
  local other = false
  for _, c in ipairs(r.how or {}) do
    if c == 6 or c == 5 or c == 10 then return 2 end
    other = true
  end
  for _, item in ipairs(r.items or {}) do
    local v = ns.Vendor[item]
    if (v and v.recipe) or (ns.db and ns.db.vendorSeen[item]) then return 2 end
    local d = ns.Items[item]
    if d then
      for _, c in ipairs(d.how or {}) do
        if c == 5 then return 2 end
        other = true
      end
      for _, f in ipairs(d.from or {}) do
        if f[1] == "vendor" then return 2 end
        other = true
      end
    end
  end
  if other then return 4 end
  if r.acquire == 1 then return 3 end
  return 5
end

function PL.IsSecondary(line)
  local d = ns.SkillLines[Util.ParentLine(line)]
  return d ~= nil and d.cat == PL.SECONDARY_CAT
end

-- Professions (parent lines) with recipes in the data: primaries and secondaries, each sorted by name.
function PL.ProfessionLines()
  local primary, secondary, seen = {}, {}, {}
  for _, r in pairs(ns.Recipes) do
    local line = Util.ParentLine(r.skill)
    if not seen[line] then
      seen[line] = true
      table.insert(PL.IsSecondary(line) and secondary or primary, line)
    end
  end
  local function byName(a, b) return Util.LineName(a) < Util.LineName(b) end
  table.sort(primary, byName)
  table.sort(secondary, byName)
  return primary, secondary
end

-- Short profession names for the results list ("Min+BS").
local SHORT = { [129] = "FA", [164] = "BS", [165] = "LW", [171] = "Alch", [185] = "Cook", [186] = "Min",
  [197] = "Tail", [202] = "Eng", [333] = "Ench" }
function PL.ShortName(line)
  line = Util.ParentLine(line)
  return SHORT[line] or Util.LineName(line)
end

-- The what-if settings, filled with defaults. → { cap, overrides = { [line] = rank }, minConf, maxPrimaries }
function PL.WhatIfOptions(w)
  w = w or (ns.settings and ns.settings.whatIf) or {}
  return {
    cap = w.cap or PL.DEFAULT_CAP, overrides = w.overrides or {}, minConf = w.minConf or 4,
    maxPrimaries = w.maxPrimaries or 2,
  }
end

function PL.CapFor(opts, line)
  line = Util.ParentLine(line)
  return opts.overrides[line] or opts.cap
end

function PL.ColorAt(rank, r)
  if not rank or not r.trivLo or not r.trivHi then return "unknown" end
  if rank >= r.trivHi then return "grey" end
  if rank >= math.floor((r.trivLo + r.trivHi) / 2) then return "green" end
  if rank >= r.trivLo then return "yellow" end
  return "orange"
end

-- All k-element subsets of list (k >= #list: the list itself).
local function subsets(list, k)
  if k <= 0 or k >= #list then return { list } end
  local out, cur = {}, {}
  local function rec(i)
    if #cur == k then
      local s = {}
      for j, v in ipairs(cur) do s[j] = v end
      table.insert(out, s)
      return
    end
    for j = i, #list - (k - #cur) + 1 do
      table.insert(cur, list[j])
      rec(j + 1)
      table.remove(cur)
    end
  end
  rec(1)
  return out
end
PL.Subsets = subsets

-- The recipes, professions, confidence and learning cost of a chain. Fills res.steps, profs, conf, confSpell,
-- learnCost, learnUnknown, payback.
local function describeChain(res, confOf)
  local steps, seen, profs, byLine = {}, {}, {}, {}
  local function walk(node)
    if node.src ~= "craft" then return end
    for _, c in ipairs(node.children) do walk(c) end
    if seen[node.spell] then return end
    seen[node.spell] = true
    local r = PL.Recipe(node.spell)
    local line = Util.ParentLine(r.skill)
    local known = ns.Professions.IsKnown(node.spell, line)
    local step = { spell = node.spell, name = r.name, line = line, learn = r.learn, conf = confOf[node.spell],
      known = known }
    if not known then step.acquire = PL.Acquire(r, node.spell) end
    table.insert(steps, step)
    local p = byLine[line]
    if not p then
      p = { line = line, rank = 0, secondary = PL.IsSecondary(line) }
      byLine[line] = p
      table.insert(profs, p)
    end
    if (r.learn or 0) > p.rank then p.rank = r.learn end
  end
  walk(res.tree)
  local conf, confSpell, cost, unknown = 0, nil, 0, 0
  for _, st in ipairs(steps) do
    if st.conf > conf then conf, confSpell = st.conf, st.spell end
    if st.acquire then
      if st.acquire.cost then cost = cost + st.acquire.cost else unknown = unknown + 1 end
    end
  end
  res.steps, res.profs, res.conf, res.confSpell = steps, profs, conf, confSpell
  res.learnCost, res.learnUnknown = cost, unknown
  res.payback = (cost > 0 and res.profit > 0) and math.ceil(cost / res.profit) or nil
  local primaries = 0
  for _, p in ipairs(profs) do
    if not p.secondary then primaries = primaries + 1 end
  end
  res.primaries = primaries
end

-- Number of profession sets a what-if run solves (for the progress text).
function PL.WhatIfSets(opts)
  local primary = PL.ProfessionLines()
  return #subsets(primary, opts.maxPrimaries)
end

-- What-if run as a coroutine body: yields after each profession set (progress i, n). → results, stats
local function runWhatIf(opts, yield)
  opts = PL.WhatIfOptions(opts)
  local results, stats = {}, { noPrice = 0, noValue = 0, evaluated = 0, hidden = 0, whatIf = true, sets = 0,
    byConf = { 0, 0, 0, 0, 0 } }
  if not ns.char then return results, stats end
  -- Usable recipes: learn rank within the cap of their profession, confidence at least minConf, not hidden.
  local eligible, confOf, lineOf = {}, {}, {}
  for _, spell in ipairs(allSpells()) do
    local r = PL.Recipe(spell)
    if r and r.out and r.skill and r.learn then
      local line = Util.ParentLine(r.skill)
      if ns.Professions.IsHidden(spell, line) then
        stats.hidden = stats.hidden + 1
      elseif r.learn <= PL.CapFor(opts, line) then
        local conf = PL.Confidence(spell, r)
        stats.byConf[conf] = stats.byConf[conf] + 1
        if conf <= opts.minConf then
          table.insert(eligible, spell)
          confOf[spell], lineOf[spell] = conf, line
        end
      end
    end
  end
  table.sort(eligible)
  local producers = producersOf(eligible)
  local primary, secondary = PL.ProfessionLines()
  local sets = subsets(primary, opts.maxPrimaries)
  stats.sets = #sets
  local best, outcome = {}, {}
  for i, set in ipairs(sets) do
    local allowed = {}
    for _, line in ipairs(set) do allowed[line] = true end
    for _, line in ipairs(secondary) do allowed[line] = true end
    local cost = newSolver(function(spell) return allowed[lineOf[spell]] and true or false end, producers)
    for _, spell in ipairs(eligible) do
      if allowed[lineOf[spell]] then
        local r = PL.Recipe(spell)
        local res, why = evaluate(spell, r, lineOf[spell], cost)
        if res then
          local b = best[spell]
          if not b or res.profit > b.profit then best[spell] = res end
          outcome[spell] = "ok"
        elseif outcome[spell] ~= "ok" then
          outcome[spell] = why
        end
      end
    end
    if yield then yield(i, #sets) end
  end
  for _, why in pairs(outcome) do
    stats.evaluated = stats.evaluated + 1
    if why ~= "ok" then stats[why] = stats[why] + 1 end
  end
  for spell, res in pairs(best) do
    local r = PL.Recipe(spell)
    describeChain(res, confOf)
    res.whatIf = true
    res.known = ns.Professions.IsKnown(spell, res.line)
    res.learnable = not res.known
    res.color = PL.ColorAt(PL.CapFor(opts, res.line), r)
    table.insert(results, res)
  end
  table.sort(results, byProfit)
  return results, stats
end

-- Evaluates every recipe. opts nil: this character (known recipes, plus unlearned ones its skill allows). opts
-- { whatIf = settings }: a what-if character (see runWhatIf). → results (sorted by profit), stats
function PL.Run(opts)
  if ns.Sales then ns.Sales.NewRun() end
  if opts and opts.whatIf then return runWhatIf(opts.whatIf) end
  local results, stats = {}, { noPrice = 0, noValue = 0, evaluated = 0, hidden = 0 }
  if not ns.char then return results, stats end
  local spells = allSpells()
  local cost = newSolver(knownUsable, producersOf(spells))

  for _, spell in ipairs(spells) do
    local r = PL.Recipe(spell)
    if r and r.out and r.skill then
      local line = Util.ParentLine(r.skill)
      local known = ns.Professions.IsKnown(spell, line)
      local learnable = not known and PL.Learnable(spell, r)
      if not known and ns.Professions.IsHidden(spell, line) then stats.hidden = stats.hidden + 1 end
      if known or learnable then
        stats.evaluated = stats.evaluated + 1
        local res, why = evaluate(spell, r, line, cost)
        if not res then
          stats[why] = stats[why] + 1
        else
          res.known, res.learnable, res.color = known, learnable, PL.Color(spell, r)
          if learnable then
            res.acquire = PL.Acquire(r, spell)
            if res.acquire.cost and res.profit > 0 then
              res.payback = math.ceil(res.acquire.cost / res.profit)
            end
          end
          table.insert(results, res)
        end
      end
    end
  end
  table.sort(results, byProfit)
  return results, stats
end

-- The what-if run spread over frames (one profession set per frame) so a large run does not freeze the game.
-- progress(i, n) after each set; done(results, stats) at the end. Starting a new run cancels the one before.
local runToken = 0
function PL.RunAsync(opts, progress, done)
  if ns.Sales then ns.Sales.NewRun() end
  runToken = runToken + 1
  local token = runToken
  local co = coroutine.create(function()
    return runWhatIf(opts.whatIf, function(i, n) coroutine.yield(i, n) end)
  end)
  local function step()
    if token ~= runToken then return end
    local ok, a, b = coroutine.resume(co)
    if not ok then
      ns.Error("what-if: " .. tostring(a))
      done({}, {})
      return
    end
    if coroutine.status(co) == "dead" then
      done(a, b)
    else
      if progress then progress(a, b) end
      C_Timer.After(0, step)
    end
  end
  step()
end

function PL.CancelAsync()
  runToken = runToken + 1
end

-- Leaves of a chain tree, merged per item and source. → { {id, qty, cost, src, est}, ... }
function PL.ShoppingList(tree)
  local byKey, list = {}, {}
  local function walk(node)
    if node.src == "craft" then
      for _, c in ipairs(node.children) do walk(c) end
      return
    end
    local key = node.id .. node.src
    local e = byKey[key]
    if not e then
      e = { id = node.id, qty = 0, cost = 0, src = node.src, est = node.est, limited = node.limited }
      byKey[key] = e
      table.insert(list, e)
    end
    e.qty = e.qty + node.qty
    e.cost = e.cost + node.cost
  end
  walk(tree)
  table.sort(list, function(a, b) return a.cost > b.cost end)
  return list
end

-- Number of crafting steps in a chain (1 = a single craft).
function PL.Steps(tree)
  if tree.src ~= "craft" then return 0 end
  local n = 1
  for _, c in ipairs(tree.children) do n = n + PL.Steps(c) end
  return n
end
