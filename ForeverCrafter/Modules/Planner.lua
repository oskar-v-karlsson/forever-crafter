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
PL.BATCH_CAP = 200     -- the cheap batch search stops here
PL.BATCH_KEEP = 0.75   -- a craft is in the cheap batch while its own profit is at least this share of the first's
PL.FAST_ROUNDS = 6     -- Dinkelbach rounds for the best-g/h path
PL.FAST_PATHS = true   -- false: no best-g/h paths (the checks compare the most-gold fields with and without)
PL.FAST_PER_FRAME = 40 -- what-if: best-g/h paths solved per frame

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
    known = r and r.known, cast = r and r.cast, runtime = true,
  }
end

-- Cast time of one craft in ms: the game's C_Spell.GetSpellInfo castTime read at the profession window, else the
-- DB2 (SpellMisc -> SpellCastTimes.Base). → ms or nil (unknown), "game" | "db2"
function PL.CastMs(spell, r)
  local c = ns.char and ns.char.casts and ns.char.casts[spell]
  if c and c > 0 then return c, "game" end
  r = r or PL.Recipe(spell)
  if r and r.cast then return r.cast, "db2" end
  return nil
end

-- Time to craft a chain: crafts x cast time summed over every craft node (the root and each crafted step; bought
-- items take no time). → seconds, casts, unknown (a craft has no cast time; the seconds are then a lower bound)
function PL.ChainTime(node)
  local ms, casts, unknown = 0, 0, false
  local function walk(n)
    if n.src ~= "craft" then return end
    local c = PL.CastMs(n.spell)
    casts = casts + n.crafts
    if c then ms = ms + c * n.crafts else unknown = true end
    for _, k in ipairs(n.children or {}) do walk(k) end
  end
  walk(node)
  return ms / 1000, casts, unknown
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
-- Each node is chosen by its score = copper cost + lambda x crafting seconds of its subtree (buying takes 0 s; a
-- recipe with no cast time counts as 0 s). lambda nil or 0: the cheapest in copper (the most-gold path). A positive
-- lambda (copper per second) trades copper for time: the best-g/h path (see fastPath). sec: the subtree's seconds.
local function newSolver(usable, producers, lambda)
  lambda = lambda or 0
  local memo = {}
  local cost
  cost = function(id, qty, depth, visiting)
    local key = id * 1000000 + qty
    local m = memo[key]
    -- A cached chain is reused only if it still fits under the depth limit from here (h = crafts in its height).
    if m == false or (m and depth + m.h <= PL.MAX_DEPTH) then return m or nil, false end
    local best
    local ah, est, top = ns.Pricing.AHBuy(id, qty)
    -- deep: more than the snapshot's price steps (the cost is a lower bound)
    if ah then
      best = { id = id, qty = qty, cost = ah, src = "ah", est = est, h = 0, top = top, deep = est or nil, sec = 0,
        score = ah }
    end
    local unit, label, limited = ns.Pricing.VendorUnit(id)
    if unit then
      local c = math.ceil(unit * qty)
      if not best or c < best.score then
        best = { id = id, qty = qty, cost = c, src = "vendor", est = label == "estimate", limited = limited, h = 0,
          sec = 0, score = c }
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
          local total, kids, ok, est, h, var, deep = 0, {}, true, PL.CountUnknown(r), 0, hi > lo, nil
          local sec = crafts * (PL.CastMs(spell, r) or 0) / 1000
          local score = lambda * sec
          for _, rg in ipairs(r.reagents) do
            local c, inc = cost(rg[1], rg[2] * crafts, depth + 1, visiting)
            if inc then incomplete = true end
            if not c then
              ok = false
              break
            end
            total = total + c.cost
            score = score + c.score
            sec = sec + c.sec
            if c.est then est = true end
            if c.var then var = true end
            if c.deep then deep = true end
            if c.h > h then h = c.h end
            table.insert(kids, c)
          end
          if ok and (not best or score < best.score) then
            best = { id = id, qty = qty, cost = total, src = "craft", spell = spell, crafts = crafts, children = kids,
              est = est, h = h + 1, var = var or nil, outMin = hi > lo and lo or nil, outMax = hi > lo and hi or nil,
              deep = deep, sec = sec, score = score }
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

-- The reagents of k crafts of a recipe, each priced by the solver for the whole quantity (AH price steps, vendor,
-- crafting). → { cost, kids, est, var, deep, h } or nil (cannot be bought or made)
local function solveCrafts(r, k, cost)
  local outID = r.out[1]
  local s = { cost = 0, kids = {}, est = false, var = false, h = 0, sec = 0 }
  for _, rg in ipairs(r.reagents) do
    local c = cost(rg[1], rg[2] * k, 0, { [outID] = true })
    if not c then return nil end
    s.cost = s.cost + c.cost
    s.sec = s.sec + c.sec
    if c.est then s.est = true end
    if c.var then s.var = true end
    if c.deep then s.deep = true end
    if c.h > s.h then s.h = c.h end
    table.insert(s.kids, c)
  end
  return s
end

-- Cheap batch: the most crafts k (up to BATCH_CAP) for which every craft's own profit, worth - (cost(k) - cost(k-1)),
-- is at least BATCH_KEEP of the first craft's. The extra cost of each craft is taken to never fall, so k is found by
-- doubling and a binary search. at(k) is the cached solveCrafts. → k, capped (k is a lower bound: the search cap,
-- or the next craft needs more than the snapshot's price steps)
local function cheapBatch(worth, at)
  local first = worth - at(1).cost
  if first <= 0 then return nil end
  local need = PL.BATCH_KEEP * first
  local status = {}
  local function check(k)
    if status[k] == nil then
      local s, prev = at(k), at(k - 1)
      if not s or not prev then
        status[k] = "fail"
      elseif s.deep then
        status[k] = "deep"
      else
        status[k] = worth - (s.cost - prev.cost) >= need and "ok" or "fail"
      end
    end
    return status[k]
  end
  if at(1).deep then return 1, true end
  local lo, hi = 1, 2
  while hi <= PL.BATCH_CAP and check(hi) == "ok" do
    lo, hi = hi, hi * 2
  end
  if hi > PL.BATCH_CAP then
    if check(PL.BATCH_CAP) == "ok" then return PL.BATCH_CAP, true end
    hi = PL.BATCH_CAP
  end
  while hi - lo > 1 do
    local mid = math.floor((lo + hi) / 2)
    if check(mid) == "ok" then lo = mid else hi = mid end
  end
  -- The binary search checks single crafts; make sure the batch as a whole keeps the share too.
  while lo > 1 and lo * worth - at(lo).cost < need * lo do lo = lo - 1 end
  return lo, check(lo + 1) == "deep"
end

-- Average cost per craft of a batch of k. Leftovers of a step that makes several items are not counted as a saving,
-- so the average is never below the first craft's cost (with deep enough supply, batch = first craft).
local function batchCost(at, k)
  local c1 = at(1).cost
  return math.max(c1, math.ceil(at(k).cost / k))
end

-- A batch's chain tree, for its shopping list.
local function batchTree(spell, outID, n, k, s)
  return { id = outID, qty = n * k, cost = s.cost, src = "craft", spell = spell, crafts = k, children = s.kids,
    h = s.h + 1 }
end

-- Best-g/h path ---------------------------------------------------------------------------------------------------
-- The most-gold path (above) picks the cheapest copper at every node. Buying an intermediate instead of crafting it
-- can cost a little more but save a long cast, so the path with the most gold per hour can differ. It is found by
-- Dinkelbach's method: with lambda = a g/h (copper per second), solve for the least copper + lambda x seconds, take
-- that path's real profit / time as the next lambda, and repeat until the path stops changing. The AH and the vendor
-- sale each get their own (worth differs).

-- How each item of a chain is got, as text (for "did the path change").
local function pathSig(node, out)
  table.insert(out, node.id .. node.src .. (node.spell or ""))
  if node.src == "craft" then
    for _, c in ipairs(node.children) do pathSig(c, out) end
  end
  return out
end
local function kidsSig(kids)
  local out = {}
  for _, c in ipairs(kids) do pathSig(c, out) end
  return table.concat(out, ",")
end

function PL.PathSig(tree) return kidsSig(tree.children) end

-- A chain with no crafted step below the root has nothing to trade: lambda only makes crafting dearer.
local function hasCraftedStep(tree)
  for _, c in ipairs(tree.children) do
    if c.src == "craft" then return true end
  end
  return false
end

-- The best-g/h path for one sale: worth = copper per craft, goldPerHour = the most-gold path's g/h (batch average).
-- The rounds work on the first craft; the found path then gets its own cheap batch (cheapBatch on the same lambda
-- solver, so each batch size takes the best-g/h choice at that quantity) and its g/h is the batch-average profit over
-- the first craft's time, as for the most-gold path. → { tree, cost1, profit1, cost, profit, time, casts, batch,
-- batchCapped, batchProfit, batchTree, perHour, est, rounds } or nil when it is the most-gold path (or not better)
local function fastPath(res, r, kit, worth, goldPerHour)
  if not goldPerHour or goldPerHour <= 0 then return nil end
  local rootSec = (PL.CastMs(res.spell, r) or 0) / 1000
  local goldSig = kidsSig(res.tree.children)
  local lambda, sig, solver, one, rounds = goldPerHour / 3600, goldSig, nil, nil, 0
  for _ = 1, PL.FAST_ROUNDS do
    rounds = rounds + 1
    local c = newSolver(kit.usable, kit.producers, lambda)
    local s = solveCrafts(r, 1, c)
    if not s then break end
    local sg = kidsSig(s.kids)
    if sg == sig then break end
    local t = rootSec + s.sec
    if t <= 0 then break end
    sig, solver, one = sg, c, s
    local nl = (worth - s.cost) / t
    if nl <= lambda then break end
    lambda = nl
  end
  if not one or sig == goldSig then return nil end
  local lo, hi = PL.OutRange(r)
  local tree = { id = res.out, qty = res.n, cost = one.cost, src = "craft", spell = res.spell, crafts = 1,
    children = one.kids, h = one.h + 1, var = res.tree.var, outMin = res.tree.outMin, outMax = res.tree.outMax }
  local time, casts, unknown = PL.ChainTime(tree)
  if unknown or time <= 0 then return nil end
  local solved = { [1] = one }
  local function at(k)
    if k < 1 then return nil end
    local s = solved[k]
    if s == nil then
      s = solveCrafts(r, k, solver) or false
      solved[k] = s
    end
    return s or nil
  end
  local batch, capped = cheapBatch(worth, at)
  if not batch then return nil end
  local cost = batchCost(at, batch)
  local perHour = (worth - cost) / time * 3600
  if perHour <= goldPerHour then return nil end
  return {
    tree = tree, cost1 = one.cost, profit1 = worth - one.cost, cost = cost, profit = worth - cost, time = time,
    casts = casts, batch = batch, batchCapped = capped,
    batchProfit = batch * worth - math.max(batch * one.cost, at(batch).cost),
    batchTree = batchTree(res.spell, res.out, res.n, batch, at(batch)), perHour = perHour,
    est = one.est or PL.CountUnknown(r) or nil, rounds = rounds, outMin = hi > lo and lo or nil,
  }
end

-- Best-g/h paths of a result for the AH sale (fastAH) and the vendor sale (fastVendor); nil = the most-gold path.
-- kit = { usable, producers } of the run that made the result.
local function addFast(res, r, kit)
  if not PL.FAST_PATHS or not hasCraftedStep(res.tree) then return end
  local v = res.sell
  if v.ah and res.ahPerHour then
    res.fastAH = fastPath(res, r, kit, math.floor(v.ah * res.n), res.ahPerHour)
  end
  if v.vendor and res.vendorPerHour then
    res.fastVendor = fastPath(res, r, kit, math.floor(v.vendor * res.n), res.vendorPerHour)
  end
end

-- The g/h shown and sorted on: the best-g/h path's when it beats the most-gold path's. → g/h or nil, fast path or nil
function PL.AHPerHour(r)
  if r.fastAH then return r.fastAH.perHour, r.fastAH end
  return r.ahPerHour, nil
end
function PL.VendorPerHour(r)
  if r.fastVendor then return r.fastVendor.perHour, r.fastVendor end
  return r.vendorPerHour, nil
end

-- What the best-g/h path does differently: per item of its chain got another way than in the most-gold chain.
-- → { { id, gold = node, fast = node }, ... } in chain order
function PL.PathChanges(gold, fast)
  local how = {}
  local function index(node)
    if not how[node.id] then how[node.id] = node end
    if node.src == "craft" then
      for _, c in ipairs(node.children) do index(c) end
    end
  end
  for _, c in ipairs(gold.children) do index(c) end
  local out, seen = {}, {}
  local function walk(node)
    local g = how[node.id]
    if g and not seen[node.id] and (g.src ~= node.src or g.spell ~= node.spell) then
      seen[node.id] = true
      table.insert(out, { id = node.id, gold = g, fast = node })
    end
    if node.src == "craft" then
      for _, c in ipairs(node.children) do walk(c) end
    end
  end
  for _, c in ipairs(fast.children) do walk(c) end
  return out
end

-- One recipe's craft: sell value of its output minus the cheapest reagents, as the average of its cheap batch (the
-- first craft's numbers are kept as profit1, cost1). → result, or nil and the reason ("noValue" | "noPrice")
local function evaluate(spell, r, line, cost, kit)
  local outID = r.out[1]
  local value = ns.Pricing.SellValue(outID)
  if not value then return nil, "noValue" end
  local solved = {}
  local function at(k)
    if k < 1 then return nil end
    local s = solved[k]
    if s == nil then
      s = solveCrafts(r, k, cost) or false
      solved[k] = s
    end
    return s or nil
  end
  local one = at(1)
  if not one then return nil, "noPrice" end
  local total, kids, est, h, var = one.cost, one.kids, one.est, one.h, one.var
  local lo, hi = PL.OutRange(r)
  local n = (lo + hi) / 2
  local worth = math.floor(value.unit * n)
  local res = {
    spell = spell, name = r.name or Util.ItemName(outID), line = line, out = outID, n = n,
    cost = total, value = worth, profit = worth - total, cost1 = total, profit1 = worth - total,
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
    res.tree.outMin, res.tree.outMax = lo, hi
  end
  if hi > lo or var then
    res.var = true
    res.tree.var = true
  end
  -- Cheap batch for the best sale, and for a vendor sale (Vendor shuffles); the numbers below are batch averages.
  local vworth = value.vendor and math.floor(value.vendor * n)
  res.batch, res.batchCapped = cheapBatch(worth, at)
  if res.batch then
    res.cost = batchCost(at, res.batch)
    res.profit = worth - res.cost
    res.batchProfit = res.batch * worth - math.max(res.batch * total, at(res.batch).cost)
    res.batchTree = batchTree(spell, outID, n, res.batch, at(res.batch))
    res.pct = res.cost > 0 and res.profit / res.cost or nil
  end
  local vcost = res.cost
  if vworth and vworth - total > 0 then
    if vworth == worth then
      res.vendorBatch, res.vendorBatchCapped = res.batch, res.batchCapped
    else
      res.vendorBatch, res.vendorBatchCapped = cheapBatch(vworth, at)
    end
    vcost = batchCost(at, res.vendorBatch)
    res.vendorBatchProfit = res.vendorBatch * vworth - math.max(res.vendorBatch * total, at(res.vendorBatch).cost)
    res.vendorBatchTree = res.vendorBatch == res.batch and res.batchTree
      or batchTree(spell, outID, n, res.vendorBatch, at(res.vendorBatch))
  end
  if hi > lo then
    res.worst = math.floor(value.unit * lo) - res.cost
    res.best = math.floor(value.unit * hi) - res.cost
  end
  -- Vendor shuffle: the profit when the output goes to a vendor, even if the AH pays more (vendorProfit <= profit).
  if value.vendor then
    res.vendorProfit1 = vworth - total
    res.vendorProfit = vworth - vcost
    res.vendorEst = value.vendorEst or false
    if hi > lo then res.vendorWorst = math.floor(value.vendor * lo) - vcost end
  end
  if value.ah then res.ahProfit = math.floor(value.ah * n) - res.cost end
  -- Crafting time (per craft) and the batch-average profit per hour (nil when the time is 0 or partly unknown).
  res.time, res.casts, res.timeUnknown = PL.ChainTime(res.tree)
  if res.time > 0 and not res.timeUnknown then
    res.ahPerHour = res.ahProfit and res.ahProfit / res.time * 3600
    res.vendorPerHour = res.vendorProfit and res.vendorProfit / res.time * 3600
  end
  if kit then addFast(res, r, kit) end
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
    local usable = function(spell) return allowed[lineOf[spell]] and true or false end
    local kit = { usable = usable, producers = producers }
    local cost = newSolver(usable, producers)
    for _, spell in ipairs(eligible) do
      if allowed[lineOf[spell]] then
        local r = PL.Recipe(spell)
        local res, why = evaluate(spell, r, lineOf[spell], cost)
        if res then
          local b = best[spell]
          if not b or res.profit > b.profit then
            res.kit = kit
            best[spell] = res
          end
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
  -- Best-g/h paths only for the winning set of each recipe, a few per frame.
  local winners = {}
  for spell in pairs(best) do table.insert(winners, spell) end
  table.sort(winners)
  local done = 0
  for _, spell in ipairs(winners) do
    local res = best[spell]
    if res.profit > 0 and hasCraftedStep(res.tree) then
      addFast(res, PL.Recipe(spell), res.kit)
      done = done + 1
      if yield and done % PL.FAST_PER_FRAME == 0 then yield(#sets, #sets) end
    end
    res.kit = nil
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
  local kit = { usable = knownUsable, producers = producersOf(spells) }
  local cost = newSolver(kit.usable, kit.producers)

  for _, spell in ipairs(spells) do
    local r = PL.Recipe(spell)
    if r and r.out and r.skill then
      local line = Util.ParentLine(r.skill)
      local known = ns.Professions.IsKnown(spell, line)
      local learnable = not known and PL.Learnable(spell, r)
      if not known and ns.Professions.IsHidden(spell, line) then stats.hidden = stats.hidden + 1 end
      if known or learnable then
        stats.evaluated = stats.evaluated + 1
        local res, why = evaluate(spell, r, line, cost, kit)
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

-- Leaves of a chain tree, merged per item and source. → { {id, qty, cost, src, est, top (highest AH unit price)}, ... }
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
    if node.top and (not e.top or node.top > e.top) then e.top = node.top end
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
