-- Modules/FarmGuide.lua: the built-in farms (Data/Farms.lua) in the Farm tab, with an estimated gold per hour.
-- EV per kill or node = sum of chance x average stack x item value over the Wowhead Forever loot tables, the items
-- valued like the session tracker (Farm.Value: shelf / AH min less the cut, or the vendor price; grey and bound items
-- at the vendor price). Skinning counts only with Skinning, pickpocketing only for a Rogue. g/h = (EV + coin per
-- kill) x kills (or nodes) per hour. Coin, the rate and the mob mix are learned from your own Farm sessions in the
-- farm's zone; until then the rate is assumed and coin is 0 (Wowhead has no coin data).
-- Counting: the combat log is not readable by addons on Forever (C_CombatLog.GetCurrentEventInfo is SecureOnly), so a
-- kill is UNIT_DIED for your (not tap-denied) target, or a corpse you loot (GetLootSourceInfo); a node is a loot
-- window from a farm's object (GetLootSourceInfo), else one holding that node's herbs or ore. Each GUID counts once.
local _, ns = ...
local G = {}
ns.FarmGuide = G
local Util = ns.Util

local GREY, ORANGE, CYAN = "|cff808080", "|cffff8040", "|cff40e0ff"
G.MIN_LEARN = 10        -- kills or nodes before learned figures replace the assumed ones
local MONEY_FOR = 60    -- seconds after a farm kill or loot window in which looted money is that farm's
local DEMAND_TOP = 3    -- items checked against the realm's demand
local LISTS = { "drops", "skinning", "pickpocketing", "herbalism", "mining" }
local PART = { drops = "loot", skinning = "skinning", pickpocketing = "pickpocket", herbalism = "gather",
  mining = "gather" }
local NEED = { skinning = 393, herbalism = 182, mining = 186 }
local SKILL_NAME = { [182] = "Herbalism", [186] = "Mining", [393] = "Skinning" }
local BOUND = { [1] = true, [4] = true }   -- Enum.ItemBind: on acquire, quest

local defsByKey
local function defs()
  if not defsByKey then
    defsByKey = {}
    for _, d in ipairs(ns.FarmDefs or {}) do defsByKey[d.key] = d end
  end
  return defsByKey
end
G.Def = function(key) return defs()[key] end

-- The client's zone name for a farm (C_Map.GetAreaInfo of its AreaTable ID), else the Wowhead Forever name.
local zoneNames = {}
function G.ZoneName(def)
  local z = zoneNames[def.zone]
  if z then return z end
  local ok, name = ns.Call("C_Map.GetAreaInfo", def.zone)
  z = ok and type(name) == "string" and name ~= "" and name or def.zoneName
  zoneNames[def.zone] = z
  return z
end

local function secret(v)
  local f = rawget(_G, "issecretvalue")
  return f ~= nil and f(v) == true
end

-- "Creature-0-1-2-3-<npc>-<spawn>" → "npc", id; "GameObject-…-<object>-…" → "object", id; else nil
function G.ParseGUID(guid)
  if type(guid) ~= "string" or secret(guid) then return nil end
  local kind, id = guid:match("^(%a+)%-%d+%-%d+%-%d+%-%d+%-(%d+)%-")
  if kind == "Creature" or kind == "Vehicle" then return "npc", tonumber(id) end
  if kind == "GameObject" then return "object", tonumber(id) end
  return nil
end

-- Learned data -------------------------------------------------------------------------------------------------------

local function learnStore()
  ns.char.farmGuide = ns.char.farmGuide or {}
  ns.char.farmGuide.farms = ns.char.farmGuide.farms or {}
  return ns.char.farmGuide.farms
end

function G.Learned(key)
  return ns.char and learnStore()[key] or nil
end

-- This session's count for a farm (not learned until Stop).
local function sessionCount(key)
  local cur = ns.Farm.Current()
  local t = cur and cur.guide and cur.guide[key]
  return t and t.n or 0
end

-- Kills or nodes per hour: → rate, "you" | "learned" | "assumed"
function G.Rate(def)
  if def.kind == "node" then
    local n = tonumber(ns.settings.farmRates and ns.settings.farmRates[def.key])
    if n and n > 0 then return n, "you" end
  end
  local L = G.Learned(def.key)
  if L and L.n >= G.MIN_LEARN and (L.secs or 0) > 0 then return L.n * 3600 / L.secs, "learned" end
  return def.rate.n, "assumed"
end

-- The share of each mob or node: equal, or your learned mix.
local function weights(def, L)
  local w = {}
  if L and L.n >= G.MIN_LEARN and L.mix then
    local sum = 0
    for _, p in ipairs(def.pages) do sum = sum + (L.mix[p] or 0) end
    if sum > 0 then
      for _, p in ipairs(def.pages) do w[p] = (L.mix[p] or 0) / sum end
      return w, true
    end
  end
  for _, p in ipairs(def.pages) do w[p] = 1 / #def.pages end
  return w, false
end

-- Valuation ---------------------------------------------------------------------------------------------------------

-- What one looted item is worth: grey and bound items at the vendor price, else Farm.Value. → copper, how
function G.Value(id)
  local c = Util.ClientInfo(id)
  local d = Util.ItemData(id)
  local q = (c and c.q) or (d and d.q)
  local bound
  if c then bound = BOUND[c.bind] else bound = d and d.bop end
  if q == 0 or bound then
    local s = Util.SellPrice(id)
    if s and s > 0 then return s, "vendor" end
    return 0, nil
  end
  return ns.Farm.Value(id)
end

local function rogue()
  local ok, _, file = ns.Call("UnitClass", "player")
  return ok and file == "ROGUE"
end

local function hasSkill(line)
  local g = ns.char and ns.char.gather
  return g ~= nil and (g[line] or 0) > 0
end

-- Evaluation --------------------------------------------------------------------------------------------------------

-- One farm: → row { spell = key, def, ev, parts = { loot, skinning, pickpocket, gather }, skipped = { part = ev },
-- coin, rate, rateSrc, gph, items = { {id, part, chance, qty, each, how, ev, counted} }, top, demand, over, need }
function G.Eval(def, cache)
  cache = cache or {}
  local L = G.Learned(def.key)
  local w, learnedMix = weights(def, L)
  local isRogue = rogue()
  local parts, skipped, items, byKey = { loot = 0, skinning = 0, pickpocket = 0, gather = 0 }, {}, {}, {}
  local need
  for _, pkey in ipairs(def.pages) do
    local page = ns.FarmPages[pkey]
    local wp = w[pkey] or 0
    for _, lname in ipairs(LISTS) do
      local rows = page and page[lname]
      if rows and wp > 0 then
        local part = PART[lname]
        local counted = true
        if lname == "pickpocketing" then
          counted = isRogue
        elseif lname == "skinning" then
          counted = hasSkill(NEED.skinning)
        elseif NEED[lname] and ns.char and ns.char.gather and not hasSkill(NEED[lname]) then
          need = SKILL_NAME[NEED[lname]]
        end
        for _, r in ipairs(rows) do
          local id, count, outof, lo, hi = r[1], r[2], r[3], r[4], r[5]
          local v = cache[id]
          if not v then
            local each, how = G.Value(id)
            v = { each or 0, how }
            cache[id] = v
          end
          local chance = wp * count / outof
          local qty = chance * (lo + hi) / 2
          local ev = qty * v[1]
          local k = id .. ":" .. part
          local o = byKey[k]
          if not o then
            o = { id = id, part = part, chance = 0, qty = 0, each = v[1], how = v[2], ev = 0, counted = counted }
            byKey[k] = o
            table.insert(items, o)
          end
          o.chance, o.qty, o.ev = o.chance + chance, o.qty + qty, o.ev + ev
          if counted then
            parts[part] = parts[part] + ev
          else
            skipped[part] = (skipped[part] or 0) + ev
          end
        end
      end
    end
  end
  table.sort(items, function(a, b)
    if a.ev ~= b.ev then return a.ev > b.ev end
    if a.id ~= b.id then return a.id < b.id end
    return a.part < b.part
  end)
  local ev = parts.loot + parts.skinning + parts.pickpocket + parts.gather
  local coin, coinN = 0, nil
  if L and L.n >= G.MIN_LEARN then coin, coinN = (L.money or 0) / L.n, L.n end
  local rate, rateSrc = G.Rate(def)
  local o = { spell = def.key, def = def, ev = ev, parts = parts, skipped = skipped, coin = coin, coinN = coinN,
    rate = rate, rateSrc = rateSrc, gph = (ev + coin) * rate, items = items, learnedMix = learnedMix, weights = w,
    learned = L, session = sessionCount(def.key), need = need, zone = G.ZoneName(def) }
  for _, it in ipairs(items) do
    if it.counted and it.ev > 0 then
      o.top = it
      break
    end
  end
  -- Demand: an hour's drops of the top AH items against the realm's sales a day (region sold/day x realm share).
  o.demand = {}
  local share = ns.Shelves.Share()
  for _, it in ipairs(items) do
    if #o.demand >= DEMAND_TOP then break end
    if it.counted and it.ev > 0 and it.how ~= "vendor" then
      local sales = ns.Sales.Get(it.id)
      local realm = sales and sales.perDay and sales.perDay * share or nil
      local perHour = it.qty * rate
      local over = realm ~= nil and perHour > realm
      table.insert(o.demand, { id = it.id, perHour = perHour, realmDay = realm, over = over })
      if over then o.over = true end
    end
  end
  return o
end

function G.List()
  local rows, cache = {}, {}
  for _, def in ipairs(ns.FarmDefs or {}) do table.insert(rows, G.Eval(def, cache)) end
  return rows
end

-- Counting kills and nodes ------------------------------------------------------------------------------------------

local seen, seenFor = {}, nil
local moneyFarm, moneyAt
local index, indexZone

-- The farms of the zone you are in: { npc = { [id] = {def, page} }, object = {...}, items = { [itemID] = {def, page} } }
local function zoneIndex()
  local ok, z = ns.Call("GetRealZoneText")
  z = ok and z or nil
  if index and indexZone == z then return index, z end
  index, indexZone = { npc = {}, object = {}, items = {} }, z
  for _, def in ipairs(ns.FarmDefs or {}) do
    if z and G.ZoneName(def) == z then
      for _, pkey in ipairs(def.pages) do
        local page = ns.FarmPages[pkey]
        if page then
          local hit = { def = def, page = pkey }
          index[page.kind][page.id] = index[page.kind][page.id] or hit
          for _, lname in ipairs({ "herbalism", "mining" }) do
            for _, r in ipairs(page[lname] or {}) do index.items[r[1]] = index.items[r[1]] or hit end
          end
        end
      end
    end
  end
  return index, z
end
-- Forget the cached farm list, zone names and zone index (after the data changes).
function G.Reset() defsByKey, index, indexZone, zoneNames = nil, nil, nil, {} end

-- The running session (paused: nil), with its per-farm tally. A new session forgets the GUIDs already counted.
local function session()
  local cur = ns.Farm.Current()
  if not cur or not cur.since then return nil end
  if seenFor ~= cur.start then seen, seenFor, moneyFarm = {}, cur.start, nil end
  cur.guide = cur.guide or {}
  return cur
end

-- Count one kill or node for a farm. guid = nil: no GUID to dedupe by (one per loot window). → true if counted
local function count(cur, hit, guid, zone)
  if guid then
    if seen[guid] then return false end
    seen[guid] = true
  end
  local t = cur.guide[hit.def.key]
  if not t then
    t = { n = 0, money = 0, mix = {}, zone = zone }
    cur.guide[hit.def.key] = t
  end
  t.n = t.n + 1
  t.mix[hit.page] = (t.mix[hit.page] or 0) + 1
  ns.Fire("DATA_CHANGED")
  return true
end

local function targetGUID()
  local ok, g = ns.Call("UnitGUID", "target")
  if not ok or type(g) ~= "string" or secret(g) then return nil end
  return g
end

function G.OnUnitDied(guid)
  local cur = session()
  if not cur or type(guid) ~= "string" or secret(guid) then return end
  if guid ~= targetGUID() then return end
  local ok, denied = ns.Call("UnitIsTapDenied", "target")
  if ok and denied then return end
  local kind, id = G.ParseGUID(guid)
  if kind ~= "npc" then return end
  local idx, z = zoneIndex()
  local hit = idx.npc[id]
  if not hit then
    moneyFarm = nil
    return
  end
  count(cur, hit, guid, z)
  moneyFarm, moneyAt = hit.def.key, GetTime()
end

function G.OnLootOpened()
  local cur = session()
  if not cur then return end
  local idx, z = zoneIndex()
  local okN, n = ns.Call("GetNumLootItems")
  n = okN and tonumber(n) or 0
  local sources, any = {}, false
  for slot = 1, n do
    local res = { ns.Call("GetLootSourceInfo", slot) }
    if res[1] then
      for i = 2, #res, 2 do
        local g = res[i]
        if type(g) == "string" and not secret(g) then
          sources[g], any = true, true
        end
      end
    end
  end
  local tg = targetGUID()
  local okD, dead = ns.Call("UnitIsDead", "target")
  local targetDead = okD and dead == true
  local farm
  if any then
    for g in pairs(sources) do
      local kind, id = G.ParseGUID(g)
      local hit = kind and idx[kind][id]
      if hit then
        farm = hit.def.key
        -- Pickpocketing opens the living target's loot: its money is the farm's, but it is not a kill.
        if not (kind == "npc" and g == tg and not targetDead) then count(cur, hit, g, z) end
      end
    end
  elseif tg and targetDead then
    local kind, id = G.ParseGUID(tg)
    local hit = kind == "npc" and idx.npc[id]
    if hit then
      farm = hit.def.key
      count(cur, hit, tg, z)
    end
  else
    for slot = 1, n do
      local ok, link = ns.Call("GetLootSlotLink", slot)
      local item = ok and type(link) == "string" and tonumber(link:match("item:(%d+)"))
      local hit = item and idx.items[item]
      if hit then
        farm = hit.def.key
        count(cur, hit, nil, z)
        break
      end
    end
  end
  moneyFarm, moneyAt = farm, GetTime()
end

-- Looted money (from Farm.lua, whenever the session's money grows): the farm of the last kill or loot window.
function G.OnMoney(copper)
  local cur = session()
  if not cur or not moneyFarm or GetTime() - (moneyAt or 0) > MONEY_FOR then return end
  local t = cur.guide[moneyFarm]
  if t then t.money = t.money + copper end
end

-- At Stop: each zone's time goes to that zone's farms by their share of the session's kills and nodes.
function G.OnStop(cur)
  if not cur.guide or not ns.char then return end
  local byZone = {}
  for _, t in pairs(cur.guide) do
    if t.n > 0 and t.zone then byZone[t.zone] = (byZone[t.zone] or 0) + t.n end
  end
  local st = learnStore()
  for key, t in pairs(cur.guide) do
    if t.n > 0 and defs()[key] then
      local L = st[key] or { n = 0, secs = 0, money = 0, mix = {} }
      st[key] = L
      L.n = L.n + t.n
      L.secs = L.secs + (cur.zones[t.zone] or 0) * t.n / byZone[t.zone]
      L.money = L.money + t.money
      L.mix = L.mix or {}
      for p, n in pairs(t.mix) do L.mix[p] = (L.mix[p] or 0) + n end
    end
  end
end

ns.On("UNIT_DIED", function(guid) G.OnUnitDied(guid) end)
ns.On("LOOT_OPENED", function() G.OnLootOpened() end)
ns.On("ZONE_CHANGED_NEW_AREA", function() index = nil end)

-- Item quality and bind type load asynchronously: refresh the open Farms view once a batch is in.
local infoPending = false
ns.On("GET_ITEM_INFO_RECEIVED", function()
  if infoPending or ns.settings.tab ~= "farm" or not ns.Farm.GuideView() or not ns.UI.IsShown() then return end
  infoPending = true
  C_Timer.After(0.5, function()
    infoPending = false
    ns.Fire("DATA_CHANGED")
  end)
end)

-- Panel (the Farm tab's Farms view) ---------------------------------------------------------------------------------

G.COLUMNS = {
  { key = "gname", label = "Farm", width = 200 },
  { key = "gzone", label = "Zone", width = 110 },
  { key = "gev", label = "EV each", width = 80, hint = "Expected value of one kill or node: chance x average stack x "
    .. "what the item is worth (Wowhead Forever loot tables, valued like the session tracker). Skinning counts only "
    .. "with Skinning, pickpocketing only for a Rogue." },
  { key = "grate", label = "Rate", width = 120, hint = "Kills or nodes per hour: learned from your Farm sessions in "
    .. "the zone (after " .. G.MIN_LEARN .. "), else assumed (not sourced). Node farms: set your own with Nodes/h." },
  { key = "ggph", label = "g/h", width = 76, hint = "(EV + coin per kill) x rate. ! = an hour's drops of a top item "
    .. "are more than the realm buys in a day." },
  { key = "gtop", label = "Top drop", width = 210 },
}

local function unit(def) return def.kind == "node" and "node" or "kill" end

local function rateText(o)
  local r = string.format("%d/h", math.floor(o.rate + 0.5))
  if o.rateSrc == "you" then return r .. " yours" end
  if o.rateSrc == "learned" then return CYAN .. r .. " learned|r" end
  local learning = (o.learned and o.learned.n or 0) + o.session
  return r .. GREY .. " assumed" .. (learning > 0 and " (" .. learning .. ")" or "") .. "|r"
end

function G.SortValue(o, key)
  if key == "gname" then return o.def.name end
  if key == "gzone" then return o.zone end
  if key == "gev" then return o.ev end
  if key == "grate" then return o.rate end
  if key == "gtop" then return o.top and Util.ItemName(o.top.id) or "" end
  return o.gph
end

function G.CellText(o, key)
  if key == "gname" then return o.def.name end
  if key == "gzone" then return o.zone end
  if key == "gev" then return o.ev > 0 and Util.Money(math.floor(o.ev + 0.5)) or "—" end
  if key == "grate" then return rateText(o) end
  if key == "ggph" then
    local t = ns.UI.PerHourText(o.gph)
    if o.need then t = GREY .. t .. "|r" end
    return t .. (o.over and ORANGE .. " !|r" or "")
  end
  if key == "gtop" then
    if not o.top then return GREY .. "nothing priced|r" end
    return Util.ItemText(o.top.id) .. GREY .. string.format(" %d%%", math.floor(o.top.ev * 100 / o.ev + 0.5)) .. "|r"
  end
  return ""
end

local HOW = { shelf = "shelf", AH = "AH", vendor = "vendor" }

local function pct(x)
  if x >= 0.1 then return string.format("%d%%", math.floor(x * 100 + 0.5)) end
  if x >= 0.001 then return string.format("%.1f%%", x * 100) end
  return string.format("%.2f%%", x * 100)
end

local function rateLine(o)
  local u = unit(o.def)
  if o.rateSrc == "you" then return string.format("Rate %d %ss/h: set by you (Nodes/h)", o.rate, u) end
  if o.rateSrc == "learned" then
    return string.format("Rate %d %ss/h: learned from %d %ss in %s of your sessions", math.floor(o.rate + 0.5), u,
      o.learned.n, u, ns.UI.TimeText(o.learned.secs))
  end
  local learning = (o.learned and o.learned.n or 0) + o.session
  return string.format("Rate %d %ss/h: assumed, not sourced%s", o.rate, u, learning > 0 and string.format(
    " (learning: %d %ss so far, %d needed)", learning, u, G.MIN_LEARN) or " - farm here with a Farm session to learn it")
end

function G.OptionLines(o, out)
  table.insert(out, o.def.name)
  table.insert(out, string.format("%s per %s + coin %s, x %d/h = %s/h", Util.Money(math.floor(o.ev + 0.5)),
    unit(o.def), Util.Money(math.floor(o.coin + 0.5)), math.floor(o.rate + 0.5), ns.UI.PerHourText(o.gph)))
  table.insert(out, rateLine(o))
  if o.top then table.insert(out, "Top drop: " .. Util.ItemText(o.top.id)) end
  if o.need then table.insert(out, ORANGE .. "Needs " .. o.need .. "|r") end
  if o.over then table.insert(out, ORANGE .. "An hour's drops are more than the realm buys in a day|r") end
end

local LOOT_LINES = 18

function G.DetailText(o)
  local out = {}
  if not o then
    table.insert(out, "Built-in farms: the Wowhead Forever loot tables of " .. #(ns.FarmDefs or {}) .. " farms x "
      .. "today's prices. Click a farm for its loot table, mobs and rate.")
    table.insert(out, "")
    table.insert(out, "Run a Farm session there (Start, farm, Stop) and the addon learns your kills or nodes per hour, "
      .. "coin per kill and mob mix (after " .. G.MIN_LEARN .. "); until then the rate is assumed.")
    return table.concat(out, "\n")
  end
  local u = unit(o.def)
  table.insert(out, "|cffffd100" .. o.def.name .. "|r - " .. o.zone)
  local split = {}
  for _, p in ipairs({ "loot", "skinning", "pickpocket", "gather" }) do
    if o.parts[p] > 0 then table.insert(split, p .. " " .. Util.Money(math.floor(o.parts[p] + 0.5))) end
  end
  table.insert(out, string.format("EV per %s %s: %s", u, Util.Money(math.floor(o.ev + 0.5)),
    #split > 0 and table.concat(split, " + ") or "nothing priced"))
  if o.skipped.skinning then
    table.insert(out, GREY .. "Not counted: skinning " .. Util.Money(math.floor(o.skipped.skinning + 0.5))
      .. " (no Skinning)|r")
  end
  if o.skipped.pickpocket then
    table.insert(out, GREY .. "Not counted: pickpocketing " .. Util.Money(math.floor(o.skipped.pickpocket + 0.5))
      .. " (Rogues only)|r")
  end
  if o.need then table.insert(out, ORANGE .. "You have no " .. o.need .. ": these nodes need it.|r") end
  if o.def.kind == "kill" then
    if o.coinN then
      table.insert(out, string.format("Coin per kill %s: learned from %d kills", Util.Money(math.floor(o.coin + 0.5)),
        o.coinN))
    else
      table.insert(out, "Coin per kill 0: Wowhead has no coin data; your sessions here will learn it")
    end
  end
  table.insert(out, rateLine(o))
  table.insert(out, string.format("g/h = (%s + %s) x %d = %s", Util.Money(math.floor(o.ev + 0.5)),
    Util.Money(math.floor(o.coin + 0.5)), math.floor(o.rate + 0.5), ns.UI.PerHourText(o.gph)))
  if #o.demand > 0 then
    table.insert(out, "")
    table.insert(out, "|cffffd100Realm demand|r (region sold/day x realm share 1/" .. (ns.settings.shelfRealms or 15)
      .. ")")
    for _, d in ipairs(o.demand) do
      local line = string.format("  %s: %.1f/h dropped, realm buys %s/day", Util.ItemText(d.id), d.perHour,
        d.realmDay and string.format("%.1f", d.realmDay) or "? (no TSM data)")
      table.insert(out, d.over and line .. ORANGE .. " - an hour's drops exceed a day's sales|r" or line)
    end
    if o.over then
      table.insert(out, ORANGE .. "Real income is capped by what the realm buys: the g/h above will not hold all day.|r")
    end
  end
  table.insert(out, "")
  table.insert(out, string.format("|cffffd100Loot per %s|r (chance, avg qty, each, priced by, EV)", u))
  local shown, restN, restEV = 0, 0, 0
  for _, it in ipairs(o.items) do
    if shown < LOOT_LINES and it.ev > 0 then
      shown = shown + 1
      local tag = it.part ~= "loot" and it.part ~= "gather" and " (" .. it.part .. ")" or ""
      local line = string.format("  %s%s %s x%.2f %s %s = %s", Util.ItemText(it.id), tag, pct(it.chance),
        it.qty / math.max(it.chance, 1e-12), Util.Money(it.each), HOW[it.how] or "-", Util.Money(math.floor(it.ev
        * 100 + 0.5) / 100))
      table.insert(out, it.counted and line or GREY .. line .. " not counted|r")
    else
      restN = restN + 1
      restEV = restEV + (it.counted and it.ev or 0)
    end
  end
  if restN > 0 then
    table.insert(out, GREY .. string.format("  ... %d more items (unpriced or rarer), together %s", restN,
      Util.Money(math.floor(restEV + 0.5))) .. "|r")
  end
  table.insert(out, "")
  table.insert(out, string.format("|cffffd100%s|r (%s)", o.def.kind == "node" and "Nodes" or "Mobs",
    o.learnedMix and "your learned mix" or "equal mix"))
  for _, pkey in ipairs(o.def.pages) do
    local page = ns.FarmPages[pkey]
    table.insert(out, string.format("  %s %s: %s", page.name, pct(o.weights[pkey] or 0), page.url))
  end
  table.insert(out, "")
  table.insert(out, GREY .. "Loot: Wowhead Forever pages read " .. (ns.FarmInfo and ns.FarmInfo.fetched or "?")
    .. "; values: today's realm prices less the AH cut, or the vendor price (grey and bound items).|r")
  return table.concat(out, "\n")
end

function G.StatusText(n)
  local cur = ns.Farm.Current()
  local counting = ""
  if cur and cur.guide then
    local k = 0
    for _, t in pairs(cur.guide) do k = k + t.n end
    counting = string.format("  |  this session: %d kills or nodes counted", k)
  end
  return string.format("Farms: %d built-in farms, Wowhead Forever loot x today's prices; rates assumed until your "
    .. "sessions teach them%s", n, counting)
end

G.FOOTER = "g/h = (EV + coin) x rate; EV = chance x avg stack x value (shelf / AH less the cut, or vendor); "
  .. "! = beyond the realm's demand"

-- The Nodes/h box: the selected node farm's own rate. → text
function G.RateBoxText(o)
  if not o or not o.def or o.def.kind ~= "node" then return "" end
  local n = ns.settings.farmRates and ns.settings.farmRates[o.def.key]
  return n and tostring(n) or ""
end

-- Sets (or with "" clears) a node farm's nodes per hour. → true if it changed
function G.SetRate(o, text)
  if not o or not o.def or o.def.kind ~= "node" then return false end
  ns.settings.farmRates = ns.settings.farmRates or {}
  local n = tonumber(text)
  if text == "" or text == nil then
    ns.settings.farmRates[o.def.key] = nil
    return true
  end
  if n and n >= 1 and n <= 9999 then
    ns.settings.farmRates[o.def.key] = math.floor(n)
    return true
  end
  return false
end
