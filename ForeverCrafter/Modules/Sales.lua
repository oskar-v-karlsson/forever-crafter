-- Modules/Sales.lua: how many of an item sell per day in the region, from TradeSkillMaster (see SOURCES.md,
-- "TradeSkillMaster sales data"). Per item: the TSM addon's live region value when it is loaded and returns one,
-- otherwise the bundled snapshot (Data/Sales.lua) for the game's region. Only filters results; never prices.
local _, ns = ...
local S = {}
ns.Sales = S

local KEYS = { perDay = "DBRegionSoldPerDay", rate = "DBRegionSaleRate" }
local SCALES = { 1, 100, 1000 }
local PROBES = 25
local RATE_PROBES = 200   -- recipe outputs probed for the scale when the region has no snapshot
local REGION_BY_NUMBER = { [1] = "US", [3] = "EU" }   -- GetCurrentRegion(); assumed, see SOURCES.md

local cache, region, regionName, scale, scaleTried

function S.Reset()
  cache, region, regionName, scale, scaleTried = {}, nil, nil, nil, false
end

-- Called when the planner starts a run: a scale detection that found no TSM values may be tried once more (TSM loads
-- its data after login). Never per item: each try probes the TSM addon up to a few hundred times.
function S.NewRun()
  scaleTried = false
end
S.Reset()
ns.Listen("RESET", S.Reset)

-- → snapshot key ("us" | "eu" | nil), the game's region name or number as text (nil if the game gives none)
function S.Region()
  if regionName == nil then
    local ok, name = ns.Call("GetCurrentRegionName")
    if not ok or type(name) ~= "string" or name == "" then
      local ok2, n = ns.Call("GetCurrentRegion")
      name = ok2 and n and (REGION_BY_NUMBER[n] or ("region " .. tostring(n))) or false
    end
    regionName = name
    local key = name and name:lower()
    region = (key and ns.SalesData and ns.SalesData.regions[key]) and key or false
  end
  return region or nil, regionName or nil
end

local function snapshotRegion()
  local key = S.Region()
  return key and ns.SalesData.regions[key] or nil
end

local function liveAPI()
  local api = rawget(_G, "TSM_API")
  if type(api) == "table" and type(api.GetCustomPriceValue) == "function" then return api end
end

function S.LiveLoaded()
  return liveAPI() ~= nil
end

local function raw(key, id)
  local api = liveAPI()
  if not api then return nil end
  local ok, v = pcall(api.GetCustomPriceValue, key, "i:" .. id)
  if ok and type(v) == "number" then return v end
end

local function nearest(ratio)
  local best, bestD
  for _, s in ipairs(SCALES) do
    local d = math.abs(math.log(ratio / s))
    if not bestD or d < bestD then best, bestD = s, d end
  end
  return best
end

-- The TSM addon's values may be stored scaled (x100, x1000); its documentation could not be read. Compared with
-- the snapshot when the region has one, else from the sale rate (0-1 raw). → scale table, or nil (no values yet)
local function detectScale()
  local snap = snapshotRegion()
  if snap then
    local ids = {}
    for id, e in pairs(snap.items) do
      if e[1] >= 1 and e[2] > 0 then table.insert(ids, id) end
    end
    table.sort(ids)
    local ratios = { perDay = {}, rate = {} }
    local probed = 0
    for _, id in ipairs(ids) do
      local d, r = raw(KEYS.perDay, id), raw(KEYS.rate, id)
      if d and d > 0 then table.insert(ratios.perDay, d / snap.items[id][1]) end
      if r and r > 0 then table.insert(ratios.rate, r / snap.items[id][2]) end
      probed = probed + 1
      if probed >= PROBES then break end
    end
    if #ratios.perDay >= 3 and #ratios.rate >= 3 then
      local out = { how = "compared with the snapshot (" .. #ratios.perDay .. " items)" }
      for k, list in pairs(ratios) do
        table.sort(list)
        out[k] = nearest(list[math.ceil(#list / 2)])
      end
      return out
    end
  end
  -- No snapshot to compare with: the largest sale rate of some recipe outputs (raw values are 0-1).
  local maxRate, n, probed = 0, 0, 0
  for _, r in pairs(ns.Recipes) do
    if r.out then
      local v = raw(KEYS.rate, r.out[1])
      if v then
        n = n + 1
        if v > maxRate then maxRate = v end
      end
      probed = probed + 1
      if probed >= RATE_PROBES or n >= PROBES then break end
    end
  end
  if n < 3 then return nil end
  local s = maxRate <= 1 and 1 or maxRate <= 100 and 100 or 1000
  return { perDay = s, rate = s, how = "from the sale rate (" .. n .. " items)" }
end

local function liveScale()
  if not liveAPI() then return nil end
  if not scale and not scaleTried then
    scaleTried = true
    scale = detectScale()
  end
  return scale
end

-- → { perDay, rate, src = "tsm" | "snapshot", updated = snapshot date (snapshot only) } or nil (no data)
function S.Get(id)
  if not id then return nil end
  local c = cache[id]
  if c ~= nil then return c or nil end
  local out
  local sc = liveScale()
  if sc then
    local d = raw(KEYS.perDay, id)
    if d then
      local r = raw(KEYS.rate, id)
      out = { perDay = d / sc.perDay, rate = r and r / sc.rate, src = "tsm" }
    end
  end
  if not out then
    local snap = snapshotRegion()
    local e = snap and snap.items[id]
    if e then out = { perDay = e[1], rate = e[2], src = "snapshot", updated = snap.updated } end
  end
  -- TSM loaded but no values yet (its data loads after login): try again next time.
  if sc or not liveAPI() then cache[id] = out or false end
  return out
end

-- "12", "3.4", "0.25" or "—" (no data)
function S.Format(perDay)
  if not perDay then return "—" end
  if perDay >= 10 then return tostring(math.floor(perDay + 0.5)) end
  if perDay >= 1 then return string.format("%.1f", perDay) end
  return string.format("%.2f", perDay)
end

local function snapshotLabel()
  local snap = snapshotRegion()
  local _, name = S.Region()
  if snap then return "TSM " .. name .. " snapshot " .. snap.updated:sub(1, 10) end
  return "no TSM snapshot for " .. (name or "this region")
end

-- Short text for the window's status line.
function S.StatusText()
  local sc = liveScale()
  if sc then return "Sold/day: TSM live, else " .. snapshotLabel() end
  return "Sold/day: " .. snapshotLabel()
end

-- One detail-pane line for a result's output item.
function S.DetailText(sales)
  if not sales then return "No TSM sales data for this item" end
  local _, name = S.Region()
  local from = sales.src == "tsm" and "TSM live" or ("TSM snapshot " .. sales.updated:sub(1, 10))
  local line = string.format("Sells ~%s/day in %s (%s)", S.Format(sales.perDay), name or "the region", from)
  if sales.rate then line = line .. string.format(", sale rate %d%%", math.floor(sales.rate * 100 + 0.5)) end
  return line
end

function S.PrintStatus()
  local key, name = S.Region()
  local snap = snapshotRegion()
  ns.Print(string.format("sold/day: region %s; %s", name or "unknown",
    snap and string.format("TSM snapshot %s (%s)", key:upper(), snap.updated) or "no TSM snapshot for it"))
  if not liveAPI() then
    ns.Print("sold/day: TradeSkillMaster not loaded, using the snapshot")
  else
    local sc = liveScale()
    if sc then
      ns.Print(string.format("sold/day: TradeSkillMaster live, scale %d (sale rate %d), %s", sc.perDay, sc.rate, sc.how))
    else
      ns.Print("sold/day: TradeSkillMaster loaded but has no region data yet (TSM Desktop App?), using the snapshot")
    end
  end
  ns.Print(string.format("sold/day: filter %s", (ns.settings.minSoldPerDay or 0) > 0
    and ("hides AH sales under " .. ns.settings.minSoldPerDay .. "/day") or "off"))
end
