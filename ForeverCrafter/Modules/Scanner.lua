-- Modules/Scanner.lua: one full auction house snapshot with C_AuctionHouse.ReplicateItems.
-- For every item the recipes use it keeps the lowest unit buyout, the quantity and listing count, and a
-- price ladder (cheapest steps first) so the planner can price buying N of an item.
local _, ns = ...
local S = {}
ns.Scanner = S
local Util = ns.Util

local BATCH = 2000          -- listings read per frame
local TIMEOUT = 60          -- seconds to wait for REPLICATE_ITEM_LIST_UPDATE
local LADDER_STEPS = 20
local THROTTLE = 15 * 60    -- assumed ReplicateItems cooldown (Retail value; unverified in Forever)

S.ahOpen = false
S.state = "idle"            -- idle | waiting | reading
local lastRequest

function S.Prices()
  local r = ns.db and ns.db.realms[ns.RealmKey()]
  return r and r.items or nil, r and r.time or nil
end

function S.Price(id)
  local items = S.Prices()
  return items and items[id] or nil
end

local function itemIDFromLink(link)
  if type(link) ~= "string" then return nil end
  return tonumber(link:match("item:(%d+)"))
end

-- Builds the per-item summary from raw listings { [id] = { {unit, qty}, ... } }.
function S.Summarise(raw)
  local items = {}
  for id, list in pairs(raw) do
    table.sort(list, function(a, b) return a[1] < b[1] end)
    local ladder, qty = {}, 0
    for _, l in ipairs(list) do
      qty = qty + l[2]
      local last = ladder[#ladder]
      if last and last[1] == l[1] then
        last[2] = last[2] + l[2]
      elseif #ladder < LADDER_STEPS then
        table.insert(ladder, { l[1], l[2] })
      end
    end
    items[id] = { min = list[1][1], qty = qty, n = #list, ladder = ladder }
  end
  return items
end

local function finish(raw, count)
  local items = S.Summarise(raw)
  local n = 0
  for _ in pairs(items) do n = n + 1 end
  ns.db.realms[ns.RealmKey()] = { time = time(), items = items, listings = count }
  S.state = "idle"
  ns.Print(string.format("snapshot done: %d listings, %d items used by recipes", count, n))
  ns.Fire("SCAN_DONE")
  ns.Fire("DATA_CHANGED")
end

local function read()
  if S.state ~= "waiting" then return end
  S.state = "reading"
  local okN, total = ns.Call("C_AuctionHouse.GetNumReplicateItems")
  total = okN and tonumber(total) or 0
  if total <= 0 then
    S.state = "idle"
    ns.Print("the auction house returned no listings - try again later")
    ns.Fire("DATA_CHANGED")
    return
  end
  local raw, count, index = {}, 0, 0
  local function step()
    if not S.ahOpen then
      S.state = "idle"
      ns.Print("auction house closed - snapshot cancelled")
      ns.Fire("DATA_CHANGED")
      return
    end
    -- Index base is not documented; reading 0..total and skipping empty slots covers both.
    local stop = math.min(index + BATCH, total)
    while index <= stop do
      local ok, _, _, stack, _, _, _, _, _, _, buyout, _, _, _, _, _, _, itemID =
        ns.Call("C_AuctionHouse.GetReplicateItemInfo", index)
      if ok and stack then
        if not itemID then
          local okL, link = ns.Call("C_AuctionHouse.GetReplicateItemLink", index)
          itemID = okL and itemIDFromLink(link) or nil
        end
        buyout = tonumber(buyout) or 0
        stack = tonumber(stack) or 0
        if itemID and ns.Items[itemID] and buyout > 0 and stack > 0 then
          raw[itemID] = raw[itemID] or {}
          table.insert(raw[itemID], { math.ceil(buyout / stack), stack })
          count = count + 1
        end
      end
      index = index + 1
    end
    ns.Fire("SCAN_PROGRESS", index, total)
    if index > total then
      finish(raw, count)
    else
      C_Timer.After(0, step)
    end
  end
  step()
end

function S.Start()
  if not S.ahOpen then
    ns.Print("open the auction house first")
    return false
  end
  if S.state ~= "idle" then
    ns.Print("a snapshot is already running")
    return false
  end
  if not ns.API("C_AuctionHouse.ReplicateItems") then
    ns.Print("C_AuctionHouse.ReplicateItems is not available in this client")
    return false
  end
  if lastRequest and time() - lastRequest < THROTTLE then
    ns.Print(string.format("the server may still be throttling the full snapshot (%d min since the last one)",
      math.floor((time() - lastRequest) / 60)))
  end
  local ok, err = ns.Call("C_AuctionHouse.ReplicateItems")
  if not ok then
    ns.Print("snapshot request failed: " .. tostring(err))
    return false
  end
  lastRequest = time()
  ns.db.lastReplicate = lastRequest
  S.state = "waiting"
  ns.Print("snapshot requested - this can take a while on a full auction house")
  ns.Fire("DATA_CHANGED")
  C_Timer.After(TIMEOUT, function()
    if S.state == "waiting" then
      ns.Debug("no REPLICATE_ITEM_LIST_UPDATE after " .. TIMEOUT .. " s, reading what is there")
      read()
    end
  end)
  return true
end

ns.On("REPLICATE_ITEM_LIST_UPDATE", function()
  -- The list can arrive in parts; wait a moment for more before reading it.
  if S.state ~= "waiting" then return end
  S.updates = (S.updates or 0) + 1
  local mine = S.updates
  C_Timer.After(2, function()
    if mine == S.updates then read() end
  end)
end)

ns.On("AUCTION_HOUSE_SHOW", function()
  S.ahOpen = true
  ns.Fire("DATA_CHANGED")
end)
ns.On("AUCTION_HOUSE_CLOSED", function()
  S.ahOpen = false
  ns.Fire("DATA_CHANGED")
end)

ns.OnLogin(function() lastRequest = ns.db.lastReplicate end)

function S.PrintStatus()
  local items, t = S.Prices()
  local n = 0
  for _ in pairs(items or {}) do n = n + 1 end
  ns.Print(string.format("AH snapshot (%s): %s, %d items", ns.RealmKey(), Util.Age(t), n))
end

ns.Command("scan", function() S.Start() end)
