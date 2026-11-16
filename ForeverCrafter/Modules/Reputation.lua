-- Modules/Reputation.lua: the cheapest way to gain reputation with Durotar Supply and Logistics (Horde; the Alliance
-- has the Azeroth Commerce Authority) by buying everything from the AH or a vendor (no crafting).
-- Two ways: a Craftsman's Writ (the writ plus the item its quest wants, once per writ per day; its Coin Pouch is
-- taken off the cost) and, from Friendly, a notarised crate (an empty Waylaid Crate plus a Forged Delivery Receipt,
-- which costs Merchant's Favor, earned by filling and handing in identified Waylaid Crates).
-- The amounts in Data/Reputation.lua are partly unverified (src "user"); what the game really gives on a turn-in
-- is learned here (account-wide) and replaces them.
local _, ns = ...
local R = {}
ns.Reputation = R
local Util, P = ns.Util, ns.Pricing

R.FRIENDLY = 5        -- FactionData.reaction is a luaIndex: 4 = Neutral, 5 = Friendly (FACTION_STANDING_LABEL5)
R.MAX_STEPS = 500     -- the today plan stops after this many steps
R.WINDOW = 3          -- seconds between a turn-in and the reputation or favor change it caused

local function learned()
  return ns.db.rep.learned
end

-- Faction ------------------------------------------------------------------------------------------------------------

-- → faction ID, name
function R.Faction()
  local f = ns.Rep.factions
  local side = UnitFactionGroup and UnitFactionGroup("player")
  local e = side == "Alliance" and f.Alliance or f.Horde
  return e.id, e.name
end

-- → { reaction, cur, min, next, label } from C_Reputation.GetFactionDataByID, or nil (API missing, or the
-- character has not met the faction)
function R.Standing()
  local ok, d = ns.Call("C_Reputation.GetFactionDataByID", (R.Faction()))
  if not ok or type(d) ~= "table" or not d.reaction or not d.currentStanding then return nil end
  return { reaction = d.reaction, cur = d.currentStanding, min = d.currentReactionThreshold,
           next = d.nextReactionThreshold, label = R.StandingLabel(d.reaction) }
end

function R.StandingLabel(reaction)
  return _G["FACTION_STANDING_LABEL" .. tostring(reaction)] or ("standing " .. tostring(reaction))
end

-- Merchant's Favor the character has. → n or nil
function R.FavorHeld()
  local ok, info = ns.Call("C_CurrencyInfo.GetCurrencyInfo", ns.Rep.currency.id)
  if ok and type(info) == "table" then return info.quantity end
  return nil
end

function R.DoneToday(quest)
  local ok, done = ns.Call("C_QuestLog.IsQuestFlaggedCompleted", quest)
  return ok and done == true
end

-- Amounts: learned in game, else Data/Reputation.lua -------------------------------------------------------------

function R.SealedID(tier, q)
  for id, s in pairs(ns.RepSealed) do
    if s.tier == tier and s.q == q then return id end
  end
end

-- → rep, "learned"|"user"
function R.WritRep(w)
  local l = learned().quest[w.quest]
  if l then return l, "learned" end
  local a = ns.RepAmounts.writRep
  return a[w.tier], a.src
end

-- Merchant's Favor for handing in one filled crate. → n, "learned"|"user"  or nil (unknown, e.g. Artisan)
function R.Favor(c)
  local l = learned().favor[R.SealedID(c.tier, c.q)]
  if l then return l, "learned" end
  local f = ns.RepAmounts.favor[c.tier]
  local v = f and f[c.q == 1 and 1 or 2]
  if v then return v, ns.RepAmounts.favor.src end
  return nil
end

-- Reputation a filled crate's hand-in gives itself (only once seen in game). → n or nil
function R.SealedRep(c)
  return learned().sealedRep[R.SealedID(c.tier, c.q)]
end

function R.CrateRep()
  local l = learned().crateRep
  if l then return l, "learned" end
  return ns.RepAmounts.crateRep.value, ns.RepAmounts.crateRep.src
end

function R.ReceiptFavor()
  return ns.RepAmounts.receiptFavor.value
end

function R.Pouch(tier)
  return ns.RepAmounts.pouch[tier] or 0
end

function R.TierName(tier)
  return ns.Rep.tiers[tier] or "?"
end

-- Buying -------------------------------------------------------------------------------------------------------------

-- n more of an item when `used` of it are already bought from the AH: the cheaper of the AH price steps and a
-- vendor. → { id, n, cost, src = "ah"|"vendor", est, limited }  or nil
function R.Buy(id, n, used)
  local u = used and used[id] or 0
  local ah, est
  local total, e = P.AHBuy(id, u + n)
  if total then ah, est = total - (u > 0 and P.AHBuy(id, u) or 0), e end
  local unit, label, limited = P.VendorUnit(id)
  if unit then
    local v = math.ceil(unit * n)
    if not ah or v < ah then
      return { id = id, n = n, cost = v, src = "vendor", est = label == "estimate", limited = limited }
    end
  end
  if ah then return { id = id, n = n, cost = ah, src = "ah", est = est } end
  return nil
end

local function commit(used, buys, list)
  for _, b in ipairs(buys) do
    if b.src == "ah" then used[b.id] = (used[b.id] or 0) + b.n end
    if list then table.insert(list, b) end
  end
end

local function copy(t)
  local out = {}
  for k, v in pairs(t) do out[k] = v end
  return out
end

-- A writ and the item its quest wants, less the Coin Pouch. → net cost, buys  or nil, why
local function writCost(writ, w, used)
  local wb = R.Buy(writ, 1, used)
  if not wb then return nil, "writ not on the AH" end
  local u = used
  if wb.src == "ah" and w.item == writ then u = copy(used); u[writ] = (u[writ] or 0) + 1 end
  local ib = R.Buy(w.item, w.n, u)
  if not ib then return nil, "item not on the AH" end
  return wb.cost + ib.cost - R.Pouch(w.tier), { wb, ib }
end

-- An identified crate and its cheapest fill bundle. → cost, buys  or nil, why
local function filledCost(id, c, used)
  local cb = R.Buy(id, 1, used)
  if not cb then return nil, "crate not on the AH" end
  local best
  for _, b in ipairs(c.bundles) do
    local bb = R.Buy(b[1], b[2], used)
    if bb and (not best or bb.cost < best.cost) then best = bb end
  end
  if not best then return nil, "no fill bundle on the AH" end
  return cb.cost + best.cost, { cb, best }
end

local function sortedCrates()
  local ids = {}
  for id in pairs(ns.RepCrates) do table.insert(ids, id) end
  table.sort(ids)
  return ids
end

-- The cheapest Merchant's Favor: the filled crate with the least copper per favor. → { id, per, cost, favor, buys }
function R.CheapestFavor(used)
  local best
  for _, id in ipairs(sortedCrates()) do
    local c = ns.RepCrates[id]
    local f = R.Favor(c)
    if f and f > 0 then
      local cost, buys = filledCost(id, c, used)
      if cost and (not best or cost / f < best.per) then
        best = { id = id, per = cost / f, cost = cost, favor = f, buys = buys }
      end
    end
  end
  return best
end

-- An empty crate for a receipt: the unidentified Waylaid Crate or any identified one. → buy or nil
function R.EmptyCrate(used)
  local best = R.Buy(ns.Rep.emptyCrate, 1, used)
  for _, id in ipairs(sortedCrates()) do
    local b = R.Buy(id, 1, used)
    if b and (not best or b.cost < best.cost) then best = b end
  end
  return best
end

-- Options --------------------------------------------------------------------------------------------------------

local function fromText(b)
  if not b then return "—" end
  return (b.src == "ah" and "AH" or "vendor") .. (b.est and " ~" or "") .. (b.limited and " (limited)" or "")
end

-- Every way to gain reputation (or favor), each priced on its own. → list of options
-- option = { key, kind = "writ"|"crate"|"favor", name, tier, cost, rep, per = copper per rep, favor, perFavor,
--   buys, est, done, gated, missing = why it cannot be bought, from }
function R.Options(standing)
  local out = {}
  local gated = standing ~= nil and standing.reaction < R.FRIENDLY
  for writ, w in pairs(ns.RepWrits) do
    local rep, repSrc = R.WritRep(w)
    local o = { key = "writ:" .. writ, kind = "writ", writ = writ, w = w, tier = w.tier, rep = rep, repSrc = repSrc,
                name = "Writ: " .. Util.ItemName(w.item) .. (w.n > 1 and (" x" .. w.n) or ""),
                done = R.DoneToday(w.quest) }
    local cost, buys = writCost(writ, w, {})
    if cost then
      o.cost, o.buys, o.per = cost, buys, cost / rep
      o.est = buys[1].est or buys[2].est
      o.from = fromText(buys[2])
    else
      o.missing, o.from = buys, "—"
    end
    table.insert(out, o)
  end
  local favor = R.CheapestFavor({})
  local crateRep, crateSrc = R.CrateRep()
  local empty = R.EmptyCrate({})
  local n = R.ReceiptFavor()
  local o = { key = "crate", kind = "crate", name = "Notarised Waylaid Crate", rep = crateRep, repSrc = crateSrc,
              gated = gated }
  if favor and empty then
    o.cost = math.ceil(n * favor.per) + empty.cost
    o.per, o.est = o.cost / crateRep, empty.est or favor.buys[1].est or favor.buys[2].est
    o.buys, o.favorFrom, o.empty = favor.buys, favor, empty
    o.from = "fill " .. ns.RepCrates[favor.id].kind
  else
    o.missing = not empty and "no empty crate on the AH" or "no favor price (no crate and bundle on the AH)"
    o.from = "—"
  end
  table.insert(out, o)
  for _, id in ipairs(sortedCrates()) do
    local c = ns.RepCrates[id]
    local f, fSrc = R.Favor(c)
    local fo = { key = "favor:" .. id, kind = "favor", crate = id, c = c, tier = c.tier, favor = f, favorSrc = fSrc,
                 name = "Fill: " .. R.TierName(c.tier) .. " " .. c.kind, gated = gated, rep = R.SealedRep(c) }
    local cost, buys = filledCost(id, c, {})
    if cost then
      fo.cost, fo.buys, fo.est = cost, buys, buys[1].est or buys[2].est
      if f and f > 0 then fo.perFavor = cost / f end
      if fo.rep and fo.rep > 0 then fo.per = cost / fo.rep end
      -- Sorted as a notarised crate with this crate's favor would be.
      if fo.perFavor and empty then fo.eqPer = (fo.perFavor * n + empty.cost) / crateRep end
      fo.from = Util.ItemName(buys[2].id) .. " x" .. buys[2].n .. " " .. fromText(buys[2])
    else
      fo.missing, fo.from = buys, "—"
    end
    table.insert(out, fo)
  end
  for _, x in ipairs(out) do x.spell = x.key end
  return out
end

-- Today plan ------------------------------------------------------------------------------------------------------

-- How much reputation to plan for: the Rep goal setting, else up to the next standing. → n or nil, message
function R.Goal(standing)
  local g = ns.settings.repGoal or 0
  if g > 0 then return g end
  if not standing then return nil, "standing unknown (Reputation API missing or faction not met): set a Rep goal" end
  if not standing.next or standing.next <= standing.cur then return nil, "at the highest standing" end
  return standing.next - standing.cur
end

local function favorTake(bank, need)
  local value = 0
  while need > 0 and bank[1] do
    local b = bank[1]
    local take = math.min(need, b.n)
    value = value + take * b.per
    b.n, need = b.n - take, need - take
    if b.n <= 0 then table.remove(bank, 1) end
  end
  return value
end

-- One notarised crate on top of `used` and the favor bank (FIFO of { per, n }): buy filled crates until the bank
-- holds a receipt's worth, spend it, add an empty crate. Nothing is changed in place.
-- → { cost = copper value used up (receipt favor + empty crate), cash, rep, buys, used, bank, fills }  or nil
local function crateStep(used, bank)
  local u, q = copy(used), {}
  for i, b in ipairs(bank) do q[i] = { per = b.per, n = b.n } end
  local need, have = R.ReceiptFavor(), 0
  for _, b in ipairs(q) do have = have + b.n end
  local buys, cash, rep, fills = {}, 0, R.CrateRep(), {}
  while have < need do
    local f = R.CheapestFavor(u)
    if not f then return nil end
    commit(u, f.buys, buys)
    table.insert(q, { per = f.per, n = f.favor })
    have, cash = have + f.favor, cash + f.cost
    rep = rep + (R.SealedRep(ns.RepCrates[f.id]) or 0)
    fills[f.id] = (fills[f.id] or 0) + 1
  end
  local value = favorTake(q, need)
  local e = R.EmptyCrate(u)
  if not e then return nil end
  commit(u, { e }, buys)
  return { cost = value + e.cost, cash = cash + e.cost, rep = rep, buys = buys, used = u, bank = q, fills = fills }
end

-- Greedy: each step takes the cheapest copper per reputation of the writs not yet done today and the next
-- notarised crate, each priced after everything the plan already bought (the AH price steps rise).
-- → { goal, gained, cash, steps = { {kind, writ|n, cost, rep} }, shopping = { {id, n, cost, src, est} },
--     inPlan = { [option key] = count }, crates, favorLeft, favorLeftValue, message, reached, gatedUntil }
function R.Plan(standing)
  local goal, msg = R.Goal(standing)
  local plan = { goal = goal, gained = 0, cash = 0, steps = {}, shopping = {}, inPlan = {}, crates = 0,
                 message = msg }
  if not goal then return plan end
  -- Crates need Friendly: below it they unlock once the plan has gained up to the next standing (from Neutral).
  local unlock = 0
  if standing and standing.reaction < R.FRIENDLY then
    unlock = (standing.reaction == R.FRIENDLY - 1 and standing.next and standing.next > standing.cur)
      and (standing.next - standing.cur) or nil
  end
  if unlock == nil then
    plan.gatedUntil = false
  elseif unlock > 0 then
    plan.gatedUntil = unlock
  end
  plan.ungated = standing == nil
  local used, bank, buys = {}, {}, {}
  local held = R.FavorHeld()
  if held and held > 0 then bank[1] = { per = 0, n = held } end
  plan.favorHeld = held
  local left = {}
  for writ, w in pairs(ns.RepWrits) do
    if not R.DoneToday(w.quest) then left[writ] = w end
  end
  local cache, crate = {}, nil
  local crateItems = { [ns.Rep.emptyCrate] = true }
  for id, c in pairs(ns.RepCrates) do
    crateItems[id] = true
    for _, b in ipairs(c.bundles) do crateItems[b[1]] = true end
  end
  while plan.gained < goal and #plan.steps < R.MAX_STEPS do
    local best
    for writ, w in pairs(left) do
      local e = cache[writ]
      if e == nil then
        local cost, b = writCost(writ, w, used)
        e = cost and { cost = cost, buys = b, rep = (R.WritRep(w)) } or false
        cache[writ] = e
      end
      if e then
        local per = e.cost / e.rep
        if not best or per < best.per or (per == best.per and writ < best.writ) then
          best = { kind = "writ", writ = writ, per = per, e = e }
        end
      end
    end
    if unlock and plan.gained >= unlock then
      if crate == nil then crate = crateStep(used, bank) or false end
      if crate and (not best or crate.cost / crate.rep < best.per) then
        best = { kind = "crate", per = crate.cost / crate.rep, e = crate }
      end
    end
    if not best then break end
    local touched = {}
    if best.kind == "writ" then
      local e = best.e
      commit(used, e.buys, buys)
      for _, b in ipairs(e.buys) do touched[b.id] = true end
      left[best.writ], cache[best.writ] = nil, nil
      plan.cash = plan.cash + e.cost + R.Pouch(ns.RepWrits[best.writ].tier)
      plan.pouches = (plan.pouches or 0) + R.Pouch(ns.RepWrits[best.writ].tier)
      plan.gained = plan.gained + e.rep
      table.insert(plan.steps, { kind = "writ", writ = best.writ, cost = e.cost, rep = e.rep })
      plan.inPlan["writ:" .. best.writ] = 1
    else
      local e = best.e
      for _, b in ipairs(e.buys) do touched[b.id] = true end
      for _, b in ipairs(e.buys) do table.insert(buys, b) end
      used, bank = e.used, e.bank
      plan.cash = plan.cash + e.cash
      plan.gained = plan.gained + e.rep
      plan.crates = plan.crates + 1
      plan.inPlan.crate = plan.crates
      for id, k in pairs(e.fills) do plan.inPlan["favor:" .. id] = (plan.inPlan["favor:" .. id] or 0) + k end
      local last = plan.steps[#plan.steps]
      if last and last.kind == "crate" then
        last.n, last.cost, last.rep = last.n + 1, last.cost + e.cost, last.rep + e.rep
      else
        table.insert(plan.steps, { kind = "crate", n = 1, cost = e.cost, rep = e.rep })
      end
      crate = nil
    end
    for writ, w in pairs(left) do
      if cache[writ] ~= nil and (touched[writ] or touched[w.item]) then cache[writ] = nil end
    end
    if crate then
      for id in pairs(touched) do
        if crateItems[id] then crate = nil break end
      end
    end
  end
  plan.reached = plan.gained >= goal
  local favorLeft, favorValue = 0, 0
  for _, b in ipairs(bank) do favorLeft, favorValue = favorLeft + b.n, favorValue + b.n * b.per end
  plan.favorLeft, plan.favorLeftValue = favorLeft, favorValue
  local byId, order = {}, {}
  for _, b in ipairs(buys) do
    local k = b.id .. ":" .. b.src
    local s = byId[k]
    if not s then
      s = { id = b.id, n = 0, cost = 0, src = b.src }
      byId[k] = s
      table.insert(order, s)
    end
    s.n, s.cost, s.est = s.n + b.n, s.cost + b.cost, s.est or b.est
  end
  table.sort(order, function(a, b) return a.cost > b.cost end)
  plan.shopping = order
  return plan
end

-- Run: options and the today plan. → options, plan, standing
function R.Run()
  local standing = R.Standing()
  local options, plan = R.Options(standing), R.Plan(standing)
  R.lastPlan, R.lastOptions, R.lastStanding = plan, options, standing
  return options, plan, standing
end

-- Display ----------------------------------------------------------------------------------------------------------

R.COLUMNS = {
  { key = "rname", label = "Option", width = 236 },
  { key = "rtier", label = "Tier", width = 70 },
  { key = "rcost", label = "Cost", width = 88,
    hint = "AH and vendor prices only (no crafting). Writs: the writ plus the item, less the Coin Pouch's average "
      .. "(unverified); below 0 = it earns gold. ~ = estimated price." },
  { key = "rrep", label = "Gives", width = 70,
    hint = "Reputation per turn-in (white: from game data or learned; orange: unverified, from guides), or "
      .. "Merchant's Favor for a filled crate. The addon learns the real amounts when you turn in." },
  { key = "rper", label = "Cost/rep", width = 84,
    hint = "Copper per reputation point. Filled crates: copper per Merchant's Favor (/fav); they sort as the "
      .. "notarised crate they would pay for." },
  { key = "rfrom", label = "Buy", width = 150 },
  { key = "rtoday", label = "Today", width = 90,
    hint = "plan = in today's plan (xN times); done = turned in today (once per writ per day); needs Friendly = "
      .. "crates are not recommended below Friendly." },
}

function R.SortValue(o, key)
  if key == "rname" then return o.name end
  if key == "rtier" then return o.tier or 0 end
  if key == "rcost" then return o.cost or math.huge end
  if key == "rrep" then return o.rep or 0 end
  if key == "rfrom" then return o.from or "" end
  if key == "rtoday" then
    if o.done then return 1 end
    if o.gated then return 2 end
    return -(R.lastPlan and R.lastPlan.inPlan[o.key] or 0)
  end
  if o.missing then return math.huge end
  return o.per or o.eqPer or math.huge
end

local GREY, ORANGE, GREEN = "|cff808080", "|cffff8040", "|cff40ff40"

function R.CellText(o, key, plan)
  local dim = (o.done or o.gated or o.missing) and GREY or nil
  local function d(s) return dim and (dim .. s .. "|r") or s end
  if key == "rname" then
    if o.kind ~= "writ" then return d(o.name) end
    local text = Util.ItemText(o.w.item):gsub("^(|c%x%x%x%x%x%x%x%x)", "%1Writ: ")
    return d(text .. (o.w.n > 1 and (" x" .. o.w.n) or ""))
  elseif key == "rtier" then
    if not o.tier then return "—" end
    local t = R.TierName(o.tier)
    if o.kind == "favor" then t = t .. (o.c.q == 1 and " (w)" or " (g)") end
    return d(t)
  elseif key == "rcost" then
    if not o.cost then return "—" end
    return d(Util.Money(o.cost) .. (o.est and " ~" or ""))
  elseif key == "rrep" then
    if o.kind == "favor" then
      local s = o.favor and (o.favor .. " fav") or "? fav"
      if o.rep then s = s .. ", " .. o.rep end
      return d(s)
    end
    local s = tostring(o.rep)
    return o.repSrc == "user" and (ORANGE .. s .. "|r") or d(s)
  elseif key == "rper" then
    if o.kind == "favor" then
      return o.perFavor and d(Util.Money(o.perFavor) .. " /fav") or "—"
    end
    return o.per and d(Util.Money(o.per)) or "—"
  elseif key == "rfrom" then
    return d(o.missing or o.from or "—")
  elseif key == "rtoday" then
    if o.done then return GREY .. "done|r" end
    if o.gated then return GREY .. "needs Friendly|r" end
    local k = plan and plan.inPlan[o.key]
    if k then return GREEN .. "plan" .. (k > 1 and (" x" .. k) or "") .. "|r" end
    return ""
  end
  return ""
end

local function buyLine(b)
  return string.format("%dx %s  %s (%s%s)", b.n, Util.ItemText(b.id), Util.Money(b.cost),
    b.src == "ah" and "AH" or "vendor", b.est and " ~" or "")
end

function R.OptionLines(o, out)
  table.insert(out, "|cffffd100" .. o.name .. "|r")
  if o.kind == "writ" then
    table.insert(out, string.format("%s writ; its quest (%d) wants %dx %s. Once per writ per day.",
      R.TierName(o.tier), o.w.quest, o.w.n, Util.ItemText(o.w.item)))
  elseif o.kind == "crate" then
    table.insert(out, string.format("An empty Waylaid Crate plus a Forged Delivery Receipt (%d Merchant's Favor) "
      .. "for %d reputation. Friendly and above.", R.ReceiptFavor(), o.rep))
    if o.favorFrom then
      local c = ns.RepCrates[o.favorFrom.id]
      table.insert(out, string.format("Favor from: %s %s at %s per favor (%d favor per crate)",
        R.TierName(c.tier), c.kind, Util.Money(o.favorFrom.per), o.favorFrom.favor))
    end
    if o.empty then table.insert(out, "Empty crate: " .. buyLine(o.empty)) end
  else
    table.insert(out, string.format("Buy %s, fill it with one bundle, hand in the Sealed %s Crate for %s Merchant's Favor%s.",
      Util.ItemText(o.crate), R.TierName(o.tier), o.favor and tostring(o.favor) or "?",
      o.favorSrc == "user" and " (unverified)" or ""))
    local list = {}
    for _, b in ipairs(o.c.bundles) do table.insert(list, b[2] .. " " .. Util.ItemName(b[1])) end
    table.insert(out, "Bundles: " .. table.concat(list, ", "))
  end
  if o.missing then
    table.insert(out, GREY .. "Cannot be priced: " .. o.missing .. "|r")
  else
    for _, b in ipairs(o.buys or {}) do
      if o.kind ~= "crate" then table.insert(out, "  " .. buyLine(b)) end
    end
    if o.kind == "writ" then
      table.insert(out, string.format("  Coin Pouch about -%s (unverified average)", Util.Money(R.Pouch(o.tier))))
    end
    if o.per then
      table.insert(out, string.format("Net %s for %d reputation%s = %s per point", Util.Money(o.cost), o.rep,
        o.repSrc == "user" and " (unverified)" or (o.repSrc == "learned" and " (learned)" or ""), Util.Money(o.per)))
    end
  end
  if o.done then table.insert(out, GREY .. "Turned in today.|r") end
  if o.gated then table.insert(out, ORANGE .. "Needs Friendly with the faction.|r") end
end

function R.PlanLines(plan, standing, out)
  table.insert(out, "|cffffd100Today's plan|r")
  if not plan.goal then
    table.insert(out, plan.message or "nothing to plan")
    return
  end
  local goalText = (ns.settings.repGoal or 0) > 0 and "your Rep goal" or
    (standing and ("the next standing after " .. standing.label) or "the goal")
  table.insert(out, string.format("%d of %d reputation (%s)%s", plan.gained, plan.goal, goalText,
    plan.reached and "" or (ORANGE .. " - not enough to buy|r")))
  table.insert(out, string.format("Spend %s; Coin Pouches give back about %s", Util.Money(plan.cash),
    Util.Money(plan.pouches or 0)))
  if plan.gatedUntil then
    table.insert(out, string.format("Crates only after %d reputation (Friendly).", plan.gatedUntil))
  elseif plan.gatedUntil == false then
    table.insert(out, "Crates need Friendly: writs only.")
  end
  if plan.ungated then table.insert(out, ORANGE .. "Standing unknown: crates need Friendly.|r") end
  if plan.favorHeld and plan.favorHeld > 0 then
    table.insert(out, string.format("Uses the %d Merchant's Favor you have first.", plan.favorHeld))
  end
  for i, s in ipairs(plan.steps) do
    if s.kind == "writ" then
      local w = ns.RepWrits[s.writ]
      table.insert(out, string.format("%d. Writ: %s%s  %s for %d (%s/rep)", i, Util.ItemText(w.item),
        w.n > 1 and (" x" .. w.n) or "", Util.Money(s.cost), s.rep, Util.Money(s.cost / s.rep)))
    else
      table.insert(out, string.format("%d. Notarised crate x%d  %s for %d (%s/rep)", i, s.n, Util.Money(s.cost),
        s.rep, Util.Money(s.cost / s.rep)))
    end
  end
  if plan.favorLeft and plan.favorLeft > 0 then
    table.insert(out, string.format("Merchant's Favor left over: %d (cost %s)", plan.favorLeft,
      Util.Money(plan.favorLeftValue)))
  end
  if #plan.shopping > 0 then
    table.insert(out, "")
    table.insert(out, "|cffffd100Shopping list|r")
    for _, b in ipairs(plan.shopping) do table.insert(out, "  " .. buyLine(b)) end
  end
end

function R.DetailText(o, plan, standing)
  local out = {}
  if o then
    R.OptionLines(o, out)
    table.insert(out, "")
  end
  R.PlanLines(plan, standing, out)
  table.insert(out, "")
  table.insert(out, GREY .. "Orange amounts are unverified (from guides); the addon learns the real ones when you "
    .. "turn in. ~ = estimated price.|r")
  return table.concat(out, "\n")
end

function R.StatusText(plan, standing, n)
  local _, name = R.Faction()
  local parts = {}
  if standing then
    table.insert(parts, string.format("%s: %s %d/%d", name, standing.label, standing.cur - (standing.min or 0),
      (standing.next or standing.cur) - (standing.min or 0)))
  else
    table.insert(parts, name .. ": standing unknown")
  end
  local held = R.FavorHeld()
  if held then table.insert(parts, ns.Rep.currency.name .. " " .. held) end
  local _, t = ns.Scanner.Prices()
  table.insert(parts, "Snapshot: " .. Util.Age(t))
  if plan.goal then
    table.insert(parts, string.format("plan: +%d rep for %s", plan.gained, Util.Money(plan.cash)))
  end
  table.insert(parts, n .. " options")
  if not t then table.insert(parts, "|cffff8040open the AH and press Scan|r") end
  return table.concat(parts, "  |  ")
end

R.FOOTER = "Cost/rep = copper per reputation point; orange = unverified amount; ~ = estimate; plan = in today's plan"

-- Learning -----------------------------------------------------------------------------------------------------------
-- A turn-in is matched with the reputation or favor change that follows (or comes just before) it.
local causes, gains = {}, {}
local lastStanding, lastFavor
local bagCount = {}

local function now()
  return time()
end

local function learn(c, g)
  local l = learned()
  local what
  if c.kind == "quest" and g.kind == "rep" then
    l.quest[c.quest], what = g.n, string.format("writ quest %d gives %d reputation", c.quest, g.n)
  elseif c.kind == "sealed" and g.kind == "favor" then
    l.favor[c.id], what = g.n, string.format("%s gives %d Merchant's Favor", Util.ItemName(c.id), g.n)
  elseif c.kind == "sealed" and g.kind == "rep" then
    l.sealedRep[c.id], what = g.n, string.format("%s gives %d reputation", Util.ItemName(c.id), g.n)
  elseif c.kind == "receipt" and g.kind == "rep" then
    l.crateRep, what = g.n, string.format("a notarised crate gives %d reputation", g.n)
  else
    return false
  end
  ns.Debug("reputation: learned " .. what)
  return true
end

local function match()
  local t = now()
  for _, list in ipairs({ causes, gains }) do
    for i = #list, 1, -1 do
      if t - list[i].t > R.WINDOW then table.remove(list, i) end
    end
  end
  local changed = false
  for _, c in ipairs(causes) do
    for _, g in ipairs(gains) do
      if not g.done and not c[g.kind] and math.abs(g.t - c.t) <= R.WINDOW and learn(c, g) then
        g.done, c[g.kind], changed = true, true, true
      end
    end
  end
  if changed then ns.Fire("DATA_CHANGED") end
end

local function readStanding()
  local s = R.Standing()
  if not s then return end
  if lastStanding and s.cur > lastStanding then
    table.insert(gains, { kind = "rep", n = s.cur - lastStanding, t = now() })
  end
  lastStanding = s.cur
  match()
end

local questWrits
local function isWritQuest(q)
  if not questWrits then
    questWrits = {}
    for _, w in pairs(ns.RepWrits) do questWrits[w.quest] = true end
  end
  return questWrits[q]
end

local function countBags()
  local out = {}
  for id in pairs(ns.RepSealed) do
    local ok, n = ns.Call("C_Item.GetItemCount", id)
    out[id] = ok and tonumber(n) or nil
  end
  local ok, n = ns.Call("C_Item.GetItemCount", ns.Rep.receipt)
  out[ns.Rep.receipt] = ok and tonumber(n) or nil
  return out
end

local function readBags()
  local cur = countBags()
  for id, n in pairs(cur) do
    local was = bagCount[id]
    if was and n == was - 1 then
      table.insert(causes, { kind = id == ns.Rep.receipt and "receipt" or "sealed", id = id, t = now() })
    end
  end
  bagCount = cur
  match()
end

function R.ResetLearning()
  causes, gains = {}, {}
end

ns.OnLogin(function()
  local s = R.Standing()
  lastStanding = s and s.cur or nil
  lastFavor = R.FavorHeld()
  bagCount = countBags()
end)
ns.On("UPDATE_FACTION", readStanding)
ns.On("FACTION_STANDING_CHANGED", function(faction)
  if faction == nil or faction == (R.Faction()) then readStanding() end
end)
ns.On("CURRENCY_DISPLAY_UPDATE", function(currency, quantity, change)
  if currency ~= ns.Rep.currency.id then return end
  if change == nil and quantity and lastFavor then change = quantity - lastFavor end
  if quantity then lastFavor = quantity end
  if change and change > 0 then
    table.insert(gains, { kind = "favor", n = change, t = now() })
    match()
  end
end)
ns.On("QUEST_TURNED_IN", function(quest)
  if not isWritQuest(quest) then return end
  table.insert(causes, { kind = "quest", quest = quest, t = now() })
  match()
end)
ns.On("BAG_UPDATE_DELAYED", readBags)

ns.Command("rep", function(arg)
  if arg == "forget" then
    ns.db.rep.learned = { quest = {}, favor = {}, sealedRep = {} }
    R.ResetLearning()
    ns.Print("learned reputation and favor amounts cleared")
    ns.Fire("DATA_CHANGED")
    return
  end
  ns.UI.Show()
  ns.UI.SetMode("rep")
end)
