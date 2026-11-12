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
    runtime = true,
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
  local rank = ns.Professions.Rank(Util.ParentLine(r.skill))
  if not rank or not r.trivLo or not r.trivHi then return "unknown" end
  if rank >= r.trivHi then return "grey" end
  if rank >= math.floor((r.trivLo + r.trivHi) / 2) then return "green" end
  if rank >= r.trivLo then return "yellow" end
  return "orange"
end

-- Created items per craft. DB2 and Wowhead give 0 for a few recipes (e.g. Lesser Wizard Oil 25126); a craft makes
-- at least one, so 0 counts as 1 and the result is marked as an estimate until the profession window gives the count.
function PL.CountUnknown(r)
  return (r.out[2] or 1) < 1
end

local function avgOut(r)
  local lo = math.max(r.out[2] or 1, 1)
  local hi = math.max(r.out[3] or lo, lo)
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
          local crafts = math.ceil(qty / avgOut(r))
          local total, kids, ok, est, h = 0, {}, true, PL.CountUnknown(r), 0
          for _, rg in ipairs(r.reagents) do
            local c, inc = cost(rg[1], rg[2] * crafts, depth + 1, visiting)
            if inc then incomplete = true end
            if not c then
              ok = false
              break
            end
            total = total + c.cost
            if c.est then est = true end
            if c.h > h then h = c.h end
            table.insert(kids, c)
          end
          if ok and (not best or total < best.cost) then
            best = { id = id, qty = qty, cost = total, src = "craft", spell = spell, crafts = crafts, children = kids,
              est = est, h = h + 1 }
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
        .. "automatically - check your trainer)")
    else
      table.insert(parts, "source unknown (check Wowhead Forever or your trainer)")
    end
  end
  return { cost = cost, text = table.concat(parts, "; ") }
end

-- Evaluates every recipe. → results (sorted by profit), stats
function PL.Run()
  local results, stats = {}, { noPrice = 0, noValue = 0, evaluated = 0, hidden = 0 }
  if not ns.char then return results, stats end
  local spells = allSpells()
  local producers = {}
  for _, spell in ipairs(spells) do
    local r = PL.Recipe(spell)
    if r and r.out then
      producers[r.out[1]] = producers[r.out[1]] or {}
      table.insert(producers[r.out[1]], spell)
    end
  end
  for _, list in pairs(producers) do table.sort(list) end
  local cost = newSolver(knownUsable, producers)

  for _, spell in ipairs(spells) do
    local r = PL.Recipe(spell)
    if r and r.out and r.skill then
      local line = Util.ParentLine(r.skill)
      local known = ns.Professions.IsKnown(spell, line)
      local learnable = not known and PL.Learnable(spell, r)
      if not known and ns.Professions.IsHidden(spell, line) then stats.hidden = stats.hidden + 1 end
      if known or learnable then
        stats.evaluated = stats.evaluated + 1
        local outID = r.out[1]
        local value = ns.Pricing.SellValue(outID)
        if not value then
          stats.noValue = stats.noValue + 1
        else
          local total, kids, ok, est, h = 0, {}, true, false, 0
          for _, rg in ipairs(r.reagents) do
            local c = cost(rg[1], rg[2], 0, { [outID] = true })
            if not c then
              ok = false
              break
            end
            total = total + c.cost
            if c.est then est = true end
            if c.h > h then h = c.h end
            table.insert(kids, c)
          end
          if not ok then
            stats.noPrice = stats.noPrice + 1
          else
            local n = avgOut(r)
            local worth = math.floor(value.unit * n)
            local res = {
              spell = spell, name = r.name or Util.ItemName(outID), line = line, out = outID, n = n,
              cost = total, value = worth, profit = worth - total,
              pct = total > 0 and (worth - total) / total or nil,
              where = value.where, sell = value, known = known, learnable = learnable,
              color = PL.Color(spell, r),
              est = est or PL.CountUnknown(r) or (value.where == "vendor" and value.vendorEst) or false,
              runtime = r.runtime,
              tree = { id = outID, qty = n, cost = total, src = "craft", spell = spell, crafts = 1, children = kids,
                h = h + 1 },
            }
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
  end
  table.sort(results, function(a, b)
    if a.profit ~= b.profit then return a.profit > b.profit end
    return a.spell < b.spell
  end)
  return results, stats
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
