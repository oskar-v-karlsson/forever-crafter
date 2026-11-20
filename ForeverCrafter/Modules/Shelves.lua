-- Modules/Shelves.lua: the Empty shelves tab. Items that sell steadily in the region (TradeSkillMaster) but that
-- this realm has (almost) none of on the AH: whoever lists first sets the price, with no one to undercut.
-- Candidates: the generated TSM region list (Data/Shelves.lua; TSM_API cannot list items) plus every item of the last
-- snapshot listed at most Max listed times. Values come from TSM_API at runtime: DBMarket (the realm's market value),
-- DBRegionSaleAvg, DBRegionSoldPerDay, DBRegionSaleRate; the realm listings from the last ReplicateItems snapshot.
local _, ns = ...
local S = {}
ns.Shelves = S
local Util = ns.Util

local GREY, ORANGE = "|cff808080", "|cffff8040"
local SUGGEST_DAYS = 2   -- the suggested stack covers this many days of the realm's expected sales

-- Enum.ItemBind (Forever ItemConstantsDocumentation): 1 OnAcquire (BoP), 4 Quest, 7+ account / warband bound.
local function boundBind(bind)
  return bind == 1 or bind == 4 or (bind or 0) >= 7
end
-- Enum.ItemClass: 2 Weapon, 4 Armor (gear: random stats and rolls, so a value is a poor guide), 12 Questitem.
local GEAR = { [2] = true, [4] = true }
local QUEST_CLASS = 12

-- The realm's share of the region's sales. TSM's region data has no listing counts to estimate it from, so it is a
-- setting: 1 / Realms.
function S.Share()
  local n = tonumber(ns.settings.shelfRealms) or 15
  if n < 1 then n = 1 end
  return 1 / n
end

-- Candidate item IDs: the region list (both when the region is unknown) and the snapshot's rarely listed items.
local function candidates(maxListed)
  local ids, seen = {}, {}
  local function add(id)
    if not seen[id] then
      seen[id] = true
      table.insert(ids, id)
    end
  end
  local data = ns.ShelfCandidates
  local key = ns.Sales.Region()
  for k, reg in pairs(data and data.regions or {}) do
    if not key or k == key then
      for _, id in ipairs(reg.items) do add(id) end
    end
  end
  local r = ns.db.realms[ns.RealmKey()]
  if r then
    for id, e in pairs(r.others or {}) do
      if e[2] <= maxListed then add(id) end
    end
    for id, p in pairs(r.items or {}) do
      if p.qty <= maxListed then add(id) end
    end
  end
  table.sort(ids)
  return ids
end

-- What one item is worth to list: → value (copper), "realm" | "region", or nil
local function value(id)
  local v = ns.Sales.Money("DBMarket", id)
  if v then return v, "realm" end
  v = ns.Sales.Money("DBRegionSaleAvg", id)
  if v then return v, "region" end
end

-- The figures of one item. sales = { perDay, rate } (region), listed / qty = the realm's min unit buyout and count.
-- expected = the realm's expected sales a day; supply = days the realm's listings last; score = copper a day.
function S.Score(val, sales, qty, share)
  local expected = sales.perDay * share
  local supply = expected > 0 and qty / expected or math.huge
  local score = val * expected * (sales.rate or 0) / (1 + supply)
  return expected, supply, score
end

-- The price and count to list: the value, never below the vendor sell price; ~2 days of expected realm sales.
function S.Suggest(val, sell, expected)
  local price = math.max(val or 0, sell or 0)
  local stack = math.max(1, math.ceil((expected or 0) * SUGGEST_DAYS - 1e-9))
  return price, stack
end

local function sourceIndex()
  if S.byOutput then return S.byOutput end
  local by = {}
  for spell, r in pairs(ns.Recipes) do
    if r.out then
      by[r.out[1]] = by[r.out[1]] or {}
      table.insert(by[r.out[1]], spell)
    end
  end
  for _, list in pairs(by) do table.sort(list) end
  S.byOutput = by
  return by
end

-- → rows, info = { tsm (TSM_API loaded), snapshot (one with the shelf data), loading, bound, gear, noValue,
-- candidates }
function S.Rows()
  local s = ns.settings
  local maxListed = math.max(0, tonumber(s.shelfMaxListed) or 5)
  local minValue = tonumber(s.shelfMinValue) or 0
  local share = S.Share()
  local info = { tsm = ns.Sales.LiveLoaded(), loading = 0, bound = 0, gear = 0, noValue = 0, candidates = 0 }
  local rows = {}
  local snap = ns.db.realms[ns.RealmKey()]
  info.snapshot = snap ~= nil and snap.others ~= nil
  if not info.tsm or not info.snapshot then
    S.info = info
    return rows, info
  end
  for _, id in ipairs(candidates(maxListed)) do
    local min, qty = ns.Scanner.Listed(id)
    if qty <= maxListed then
      info.candidates = info.candidates + 1
      local val, valSrc = value(id)
      local sales = ns.Sales.Get(id)
      if not val or not sales or not sales.perDay or sales.perDay <= 0 then
        info.noValue = info.noValue + 1
      elseif val >= minValue then
        local c = Util.ClientInfo(id)
        local hide
        if c then
          if boundBind(c.bind) or c.class == QUEST_CLASS then
            hide = "bound"
          elseif GEAR[c.class] and not s.shelfGear then
            hide = "gear"
          end
        end
        if hide then
          info[hide] = info[hide] + 1
        else
          if not c then info.loading = info.loading + 1 end
          local expected, supply, score = S.Score(val, sales, qty, share)
          local sell = c and c.sell or Util.SellPrice(id)
          local price, stack = S.Suggest(val, sell, expected)
          table.insert(rows, { spell = id, id = id, loading = not c, qty = qty, min = min, value = val,
            valueSrc = valSrc, realm = valSrc == "realm" and val or nil,
            regionAvg = ns.Sales.Money("DBRegionSaleAvg", id), perDay = sales.perDay, rate = sales.rate,
            salesSrc = sales.src, expected = expected, supply = supply, score = score, sell = sell,
            price = price, stack = stack, gear = c and GEAR[c.class] or false })
        end
      end
    end
  end
  S.info = info
  return rows, info
end

function S.List()
  return (S.Rows())
end

-- Item names load asynchronously: refresh the open tab once a batch of them is in.
local namePending = false
ns.On("GET_ITEM_INFO_RECEIVED", function()
  if namePending or ns.settings.tab ~= "shelves" or not ns.UI.IsShown() then return end
  namePending = true
  C_Timer.After(0.5, function()
    namePending = false
    ns.Fire("DATA_CHANGED")
  end)
end)

-- Panel (the Empty shelves tab) -------------------------------------------------------------------------------------

S.COLUMNS = {
  { key = "sname", label = "Item", width = 196 },
  { key = "slisted", label = "Listed", width = 46, hint = "How many this realm has on the AH (last snapshot)." },
  { key = "smin", label = "Realm min", width = 74, hint = "The cheapest of those listings, per item." },
  { key = "svalue", label = "Value", width = 74, hint = "TSM's market value on this realm (DBMarket); grey = the "
    .. "region's average sale price instead (the realm has none)." },
  { key = "sregion", label = "Region avg", width = 74, hint = "TSM's average sale price in the region "
    .. "(DBRegionSaleAvg)." },
  { key = "ssold", label = "Sold/d", width = 46, hint = "Sold per day in the whole region (DBRegionSoldPerDay). The "
    .. "realm sees about 1/Realms of it." },
  { key = "srate", label = "Sale %", width = 46, hint = "Share of the region's auctions of it that sell "
    .. "(DBRegionSaleRate)." },
  { key = "ssupply", label = "Supply", width = 56, hint = "Days the realm's listings last at its expected sales: "
    .. "listed / (sold/day x realm share). 0 = an empty shelf." },
  { key = "sscore", label = "Score", width = 64, hint = "Expected copper a day from listing it: value x expected "
    .. "realm sales a day x sale rate / (1 + supply days)." },
}

local function supplyText(d)
  if d == math.huge then return "—" end
  if d < 10 then return string.format("%.1f d", d) end
  return string.format("%d d", math.floor(d + 0.5))
end

function S.SortValue(o, key)
  if key == "sname" then return Util.ItemName(o.id) end
  if key == "slisted" then return o.qty end
  if key == "smin" then return o.min or math.huge end
  if key == "svalue" then return o.value end
  if key == "sregion" then return o.regionAvg or -1 end
  if key == "ssold" then return o.perDay end
  if key == "srate" then return o.rate or -1 end
  if key == "ssupply" then return o.supply end
  return o.score
end

function S.CellText(o, key)
  if key == "sname" then
    if o.loading then return GREY .. "loading item:" .. o.id .. "|r" end
    return (o.gear and (ORANGE .. "[G]|r ") or "") .. Util.ItemText(o.id)
  end
  if key == "slisted" then return o.qty == 0 and "|cff40ff400|r" or tostring(o.qty) end
  if key == "smin" then return o.min and Util.Money(o.min) or "—" end
  if key == "svalue" then
    local m = Util.Money(o.value)
    return o.valueSrc == "realm" and m or (GREY .. m .. "|r")
  end
  if key == "sregion" then return o.regionAvg and Util.Money(o.regionAvg) or "—" end
  if key == "ssold" then return ns.Sales.Format(o.perDay) end
  if key == "srate" then return o.rate and string.format("%d%%", math.floor(o.rate * 100 + 0.5)) or "—" end
  if key == "ssupply" then return supplyText(o.supply) end
  if key == "sscore" then return ns.UI.PerHourText(o.score) .. "/d" end
  return ""
end

-- Where the item comes from, as far as the addon's data knows (recipes, vendors). → lines
local function sourceLines(id)
  local out = {}
  for _, spell in ipairs(sourceIndex()[id] or {}) do
    local r = ns.Recipes[spell]
    table.insert(out, "  Crafted: " .. (r.name or ("spell " .. spell)) .. " (" .. Util.LineName(r.skill) .. ")")
  end
  local v = ns.Vendor and ns.Vendor[id]
  if v then
    local npc = v.npcs and v.npcs[1]
    table.insert(out, string.format("  Vendor: %s%s%s", v.price and v.price > 0 and Util.Money(v.price) or "?",
      npc and (" at " .. npc[1] .. (npc[2] and (", " .. npc[2]) or "")) or "", v.limited and " (limited stock)" or ""))
  end
  return out
end

function S.OptionLines(o, out)
  table.insert(out, o.loading and ("item:" .. o.id) or Util.ItemText(o.id))
  table.insert(out, string.format("Realm: %d listed%s; value %s (%s)", o.qty,
    o.min and (", cheapest " .. Util.Money(o.min)) or "", Util.Money(o.value),
    o.valueSrc == "realm" and "TSM realm market value" or "TSM region sale average: no realm value"))
  table.insert(out, string.format("Region: sells %s/day, sale rate %s; this realm ~%s/day (1/%d of the region)",
    ns.Sales.Format(o.perDay), o.rate and string.format("%d%%", math.floor(o.rate * 100 + 0.5)) or "?",
    ns.Sales.Format(o.expected), math.floor(1 / S.Share() + 0.5)))
  table.insert(out, string.format("Suggested: list %d at %s each%s", o.stack, Util.Money(o.price),
    o.sell and o.price == o.sell and o.sell > 0 and " (the vendor sell price: the value is below it)" or ""))
end

function S.DetailText(o)
  local out = {}
  if not o then
    table.insert(out, "Select a row on the left.")
    table.insert(out, "")
    table.insert(out, "Empty shelves: items that sell steadily in the region but that this realm has (almost) none "
      .. "of on the AH. With no one to undercut you set the price. Score = the copper a day you can expect from "
      .. "listing it. Region numbers overstate this realm's demand: start small.")
    return table.concat(out, "\n")
  end
  S.OptionLines(o, out)
  if o.min and o.min < o.price then
    table.insert(out, string.format("The realm's cheapest listing (%s) is under the suggestion: it may sell first.",
      Util.Money(o.min)))
  end
  table.insert(out, "")
  table.insert(out, "|cffffd100Where to get it|r")
  local src = sourceLines(o.id)
  if #src == 0 then
    table.insert(out, "  No known source in the addon's data (drops and gathering are not in it).")
  else
    for _, l in ipairs(src) do table.insert(out, l) end
  end
  table.insert(out, "")
  table.insert(out, ORANGE .. "Region numbers overstate this realm's demand: list a few, see what sells.|r")
  table.insert(out, GREY .. "TSM: " .. (o.salesSrc == "tsm" and "live" or "snapshot") .. " sales data; realm "
    .. "listings from the last AH snapshot.|r")
  return table.concat(out, "\n")
end

function S.StatusText(n)
  local info = S.info or {}
  local _, t = ns.Scanner.Prices()
  if not info.tsm then
    return ORANGE .. "Empty shelves needs TradeSkillMaster (TSM_API) for values and region sales|r  |  Snapshot: "
      .. Util.Age(t)
  end
  if not info.snapshot then
    return ORANGE .. "Open the AH and press Scan: the snapshot has no realm listings for this tab yet|r"
  end
  local parts = { string.format("Empty shelves: %d items (of %d listed <= %d)", n, info.candidates or 0,
    ns.settings.shelfMaxListed or 5), "realm share 1/" .. math.floor(1 / S.Share() + 0.5),
    "Snapshot: " .. Util.Age(t) }
  local hidden = {}
  if (info.bound or 0) > 0 then table.insert(hidden, info.bound .. " bound/quest") end
  if (info.gear or 0) > 0 then table.insert(hidden, info.gear .. " gear") end
  if (info.noValue or 0) > 0 then table.insert(hidden, info.noValue .. " no TSM value") end
  if #hidden > 0 then table.insert(parts, "hidden: " .. table.concat(hidden, ", ")) end
  if (info.loading or 0) > 0 then table.insert(parts, info.loading .. " loading") end
  return table.concat(parts, "  |  ")
end

S.FOOTER = "Score = expected copper/day; grey value = region average (no realm value); [G] = gear; region data "
  .. "overstates realm demand"

ns.Command("shelves", function()
  ns.UI.Show()
  ns.UI.SetMode("shelves")
end)
