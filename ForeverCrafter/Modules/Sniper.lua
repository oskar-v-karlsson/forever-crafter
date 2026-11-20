-- Modules/Sniper.lua: watch the AH for cheap reagents of the crafts you ticked (Snipe box on a result row) and buy
-- them with one click each. A ticked row's AH-bought reagents are watched with the row's cheap-batch quantities, minus
-- what is in your bags and what you bought that is still in the mail. Each reagent gets a max price that keeps the
-- row at a share (Keep g/h, default 90%) of the g/h it would earn if its AH sale price fell 10% (no cushion for a
-- vendor sale): the room left is spread as one markup over all of the row's AH reagents, so any mix of buys at or
-- under the max prices keeps the floor.
-- Searches use C_AuctionHouse.SendSearchQuery on the watched items only (throttled, round robin). Buying needs a
-- click: StartCommoditiesPurchase and PlaceBid are restricted (Blizzard_APIDocumentationGenerated/
-- AuctionHouseDocumentation.lua, Forever); a commodity's quoted price is checked against the max before
-- ConfirmCommoditiesPurchase, else the purchase is cancelled.
local _, ns = ...
local S = {}
ns.Sniper = S
local Util, PL = ns.Util, ns.Planner

S.CUSHION = 0.10       -- an AH-sold output's price may fall this much; the floor is measured there
S.GAP = 1.5            -- seconds between two searches (the AH allows 100 per minute)
S.REPEAT = 6           -- seconds before the same item is searched again
S.TIMEOUT = 10         -- seconds to wait for a search's results or a purchase quote
S.TICK = 0.5
S.MET = "every reagent need is met; raise a craft's Target to keep buying"
S.DEFAULT_FLOOR = 0.9

local function now()
  if GetTime then return GetTime() end
  return time()
end

local function store()
  local st = ns.char.snipe
  st.targets = st.targets or {}
  return st
end

function S.Floor()
  local f = ns.settings.snipeFloor or S.DEFAULT_FLOOR
  if f < 0 then f = 0 elseif f > 0.99 then f = 0.99 end
  return f
end

-- Max prices of a row -------------------------------------------------------------------------------------------

-- Which sale a ticked row is sniped for: the vendor with Vendor shuffles on or when the vendor pays best.
function S.Kind(r)
  if r.sell.vendor and (ns.settings.vendorShuffles or r.where == "vendor") then return "vendor" end
  return "ah"
end

-- The path behind the g/h column of a row's sale (the best-g/h path when it differs). → { W, C, tree, batch, time,
-- gh, fast } or nil (no price for that sale, or not profitable)
function S.Path(r, kind)
  local n = r.n
  if kind == "vendor" then
    if not r.sell.vendor then return nil end
    local W = math.floor(r.sell.vendor * n)
    local gh, fast = PL.VendorPerHour(r)
    if fast then
      return { W = W, C = fast.cost, tree = fast.batchTree, batch = fast.batch, time = fast.time, gh = gh, fast = true }
    end
    if not r.vendorBatch or not r.vendorProfit then return nil end
    return { W = W, C = W - r.vendorProfit, tree = r.vendorBatchTree, batch = r.vendorBatch, time = r.time, gh = gh }
  end
  if not r.sell.ah then return nil end
  local W = math.floor(r.sell.ah * n)
  local gh, fast = PL.AHPerHour(r)
  if fast then
    return { W = W, C = fast.cost, tree = fast.batchTree, batch = fast.batch, time = fast.time, gh = gh, fast = true }
  end
  if not r.batch or not r.batchTree or r.where ~= "ah" then return nil end
  return { W = W, C = r.cost, tree = r.batchTree, batch = r.batch, time = r.time, gh = gh }
end

-- A row's limits: W = worth per craft, Wc = after the cushion, C = batch-average cost per craft, room = (1 - floor) x
-- (Wc - C), markup = room / the AH reagents' cost per craft; reagents = { [itemID] = { max, qty, unit } } (qty = the
-- whole batch, unit = the batch's average AH price). noRoom: Wc <= C; noAH: nothing bought on the AH.
function S.RowLimit(r, kind, floor)
  floor = floor or S.Floor()
  local lim = { spell = r.spell, name = r.name, kind = kind, mode = r.whatIf and "whatIf" or "char", out = r.out,
    floor = floor, reagents = {}, ahCost = 0, est = kind == "vendor" and r.vendorEst or nil }
  local p = S.Path(r, kind)
  if not p then
    lim.noRoom = true
    return lim
  end
  local cushion = kind == "ah" and S.CUSHION or 0
  lim.W, lim.C, lim.batch, lim.time, lim.gh, lim.fast = p.W, p.C, p.batch, p.time, p.gh, p.fast
  lim.cd = r.cd
  lim.Wc = math.floor((1 - cushion) * p.W)
  local ahCost = 0
  for _, e in ipairs(PL.ShoppingList(p.tree)) do
    if e.src == "ah" and e.qty > 0 then
      ahCost = ahCost + e.cost
      lim.reagents[e.id] = { qty = math.ceil(e.qty - 1e-9), unit = e.cost / e.qty }
    end
  end
  lim.ahCost = ahCost / p.batch
  return S.ApplyFloor(lim, floor)
end

-- The parts of a row's limits that depend on the Keep g/h share (so it can change without the craft results).
function S.ApplyFloor(lim, floor)
  lim.floor = floor
  if not lim.W then return lim end
  local pct = math.floor(floor * 100 + 0.5)
  lim.room = (lim.Wc - lim.C) * (100 - pct) / 100
  lim.noRoom = lim.room <= 0 or nil
  lim.noAH = lim.ahCost <= 0 or nil
  lim.markup, lim.floorGh = nil, nil
  if lim.noRoom or lim.noAH then
    for _, g in pairs(lim.reagents) do g.max = nil end
    return lim
  end
  lim.markup = lim.room / lim.ahCost
  for _, g in pairs(lim.reagents) do g.max = math.floor(g.unit * (1 + lim.markup) + 1e-6) end
  if lim.time and lim.time > 0 and not lim.cd then
    lim.floorGh = (lim.Wc - lim.C) * pct / 100 / lim.time * 3600
  end
  return lim
end

-- The Keep g/h box. f = share (0 .. 0.99)
function S.SetFloor(f)
  ns.settings.snipeFloor = f
  f = S.Floor()
  for _, lim in pairs(store().rows) do S.ApplyFloor(lim, f) end
  ns.Fire("SNIPE_CHANGED")
end

-- Ticked rows ----------------------------------------------------------------------------------------------------

function S.IsTicked(spell)
  return ns.char ~= nil and store().rows[spell] ~= nil
end

function S.Limit(spell)
  return store().rows[spell]
end

S.MAX_TARGET = 9999

-- A recipe with a cooldown makes one craft per cooldown: its target is always its batch of 1.
local function once(spell)
  return PL.Cooldown(PL.Recipe(spell)) ~= nil
end

-- A ticked craft's target: how many crafts to buy reagents for. nil = its cheap batch.
function S.Target(spell)
  if not ns.char or once(spell) then return nil end
  return store().targets[spell]
end

-- n = an integer 1 .. MAX_TARGET (1 for a cooldown recipe), or nil / blank for the batch. → true if accepted
function S.SetTarget(spell, n)
  if n == nil or n == "" then
    store().targets[spell] = nil
  else
    n = tonumber(n)
    local max = once(spell) and 1 or S.MAX_TARGET
    if not n or n ~= math.floor(n) or n < 1 or n > max then return false end
    store().targets[spell] = not once(spell) and n or nil
  end
  ns.Fire("SNIPE_CHANGED")
  return true
end

-- "target 150 crafts (batch 50)"; just "target 50 crafts (batch)" without a Target.
function S.TargetText(lim)
  local t = S.Target(lim.spell)
  if not lim.batch then return t and string.format("target %d crafts", t) or "no batch" end
  if not t then return string.format("target %d crafts (batch)", lim.batch) end
  return string.format("target %d crafts (batch %d)", t, lim.batch)
end

-- How many of a reagent the craft needs at its target: the batch quantity scaled, rounded up.
function S.TargetQty(spell, lim, g)
  local t = S.Target(spell)
  if not t or not lim.batch or lim.batch <= 0 then return g.qty end
  return math.ceil(g.qty / lim.batch * t - 1e-9)
end

function S.Toggle(r)
  local rows = store().rows
  if rows[r.spell] then
    rows[r.spell] = nil
    store().targets[r.spell] = nil
    ns.Print("no longer sniping for " .. r.name)
  else
    local lim = S.RowLimit(r, S.Kind(r))
    rows[r.spell] = lim
    if lim.noRoom then
      ns.Print(r.name .. ": no room - the craft keeps less than " .. math.floor(lim.floor * 100 + 0.5)
        .. "% of its g/h at any higher reagent price. Nothing is sniped for it.")
    elseif lim.noAH then
      ns.Print(r.name .. ": no AH reagents to snipe.")
    else
      local parts = {}
      for id, g in pairs(lim.reagents) do
        table.insert(parts, string.format("%s x%d up to %s", Util.ItemName(id), g.qty, Util.Money(g.max)))
      end
      table.sort(parts)
      ns.Print(string.format("sniping for %s (%s sale, batch %d): %s", r.name, lim.kind == "vendor" and "vendor" or "AH",
        lim.batch, table.concat(parts, ", ")))
    end
  end
  ns.Fire("SNIPE_CHANGED")
end

function S.Clear()
  store().rows = {}
  store().targets = {}
  ns.Fire("SNIPE_CHANGED")
end

function S.ForgetBought()
  store().bought = {}
  ns.Fire("SNIPE_CHANGED")
end

-- Fresh results (a new scan, a changed setting): recompute the limits of the ticked rows they contain. Rows ticked in
-- the other mode, or no longer in the results, keep their last limits.
function S.Update(results, mode)
  if not ns.char then return end
  local rows = store().rows
  if not next(rows) then return end
  local floor = S.Floor()
  for _, r in ipairs(results) do
    local old = rows[r.spell]
    if old and old.mode == mode then
      local kind = old.kind
      if kind == "vendor" and not r.sell.vendor then kind = "ah" end
      rows[r.spell] = S.RowLimit(r, kind, floor)
    end
  end
end

-- What you have ----------------------------------------------------------------------------------------------------

local function bagCount(id)
  local ok, n = ns.Call("C_Item.GetItemCount", id)
  if not ok or type(n) ~= "number" then ok, n = ns.Call("GetItemCount", id) end
  return ok and type(n) == "number" and n or 0
end

-- → owned (bags + bought still in the mail), bags, in the mail. AH purchases go to the mailbox: when the bag count
-- rises, that much of what was bought has arrived.
function S.Owned(id)
  local cur = bagCount(id)
  local b = store().bought[id]
  if b then
    if cur > b.bagsAt then b.n = math.max(0, b.n - (cur - b.bagsAt)) end
    b.bagsAt = cur
    if b.n <= 0 then
      store().bought[id] = nil
      b = nil
    end
  end
  local mail = b and b.n or 0
  return cur + mail, cur, mail
end

local function addBought(id, n)
  local bought = store().bought
  local b = bought[id]
  local cur = bagCount(id)
  if b then
    b.n, b.bagsAt = b.n + n, cur
  else
    bought[id] = { n = n, bagsAt = cur }
  end
end

-- Watch list ------------------------------------------------------------------------------------------------------

S.seen = {}    -- itemID → { time, commodity, listings = { { unit, qty, total, auctionID }, ... } cheapest first }

-- One entry per reagent of the ticked rows: { id, rows = { { spell, name, kind, max, qty } } (highest max first), max
-- (the highest), need, owned, bags, mail }.
function S.Watch()
  local byID, list = {}, {}
  if not ns.char then return list end
  for spell, lim in pairs(store().rows) do
    if not lim.noRoom and not lim.noAH then
      for id, g in pairs(lim.reagents) do
        local w = byID[id]
        if not w then
          w = { id = id, spell = id, name = Util.ItemName(id), rows = {} }
          byID[id] = w
          table.insert(list, w)
        end
        table.insert(w.rows, { spell = spell, name = lim.name, kind = lim.kind, max = g.max,
          qty = S.TargetQty(spell, lim, g), unit = g.unit })
      end
    end
  end
  for _, w in ipairs(list) do
    table.sort(w.rows, function(a, b)
      if a.max ~= b.max then return a.max > b.max end
      return a.spell < b.spell
    end)
    w.max = w.rows[1].max
    w.owned, w.bags, w.mail = S.Owned(w.id)
    w.need = S.NeedAt(w, 0)
    w.deal = S.Deal(w)
  end
  table.sort(list, function(a, b) return a.id < b.id end)
  return list
end

-- How many more to buy at unit price p: the rows whose max is at least p, less what you own (owned items go to the
-- rows with the lowest max first; they are the hardest to fill).
function S.NeedAt(w, p)
  local above, below = 0, 0
  for _, row in ipairs(w.rows) do
    if row.max >= p then above = above + row.qty else below = below + row.qty end
  end
  return math.max(0, above - math.max(0, w.owned - below))
end

-- The strictest max among the rows a purchase at unit price p is for.
local function maxFor(w, p)
  local m
  for _, row in ipairs(w.rows) do
    if row.max >= p and (not m or row.max < m) then m = row.max end
  end
  return m
end

-- The best buy from the last search. A commodity purchase takes the cheapest units: buy as many as the rows can use,
-- the dearer units going to the rows with a higher max (the units at a price p or more must fit in the need of the
-- rows whose max is at least p). budget = each unit at the max of the row it fills (owned items fill the lowest-max
-- rows first, each unit the lowest-max row that accepts its price and still needs it): the quote is confirmed only
-- at or under it. An item auction is bought whole: the cheapest one at or under the max that is not
-- bigger than the need. → { qty, total, avg, max, budget, commodity, auctionID } or nil
function S.Deal(w)
  local seen = S.seen[w.id]
  if not seen or w.need <= 0 then return nil end
  if seen.commodity then
    local left, owned = {}, w.owned or 0
    for i = #w.rows, 1, -1 do                    -- lowest max first
      local row = w.rows[i]
      local fill = math.min(owned, row.qty)
      owned = owned - fill
      table.insert(left, { max = row.max, n = row.qty - fill })
    end
    local q, total, budget, limit = 0, 0, 0, math.huge
    for _, l in ipairs(seen.listings) do
      if l.unit > w.max then break end
      limit = math.min(limit, q + S.NeedAt(w, l.unit))
      local take = math.min(l.qty, limit - q)
      if take <= 0 then break end
      q, total = q + take, total + take * l.unit
      for _, row in ipairs(left) do
        if take <= 0 then break end
        if row.max >= l.unit and row.n > 0 then
          local n = math.min(take, row.n)
          row.n, take, budget = row.n - n, take - n, budget + n * row.max
        end
      end
      if take > 0 then budget = budget + take * maxFor(w, l.unit) end
    end
    if q == 0 then return nil end
    return { qty = q, total = total, avg = total / q, max = math.floor(budget / q), budget = budget,
      commodity = true }
  end
  for _, l in ipairs(seen.listings) do
    if l.unit > w.max then break end
    if l.qty <= S.NeedAt(w, l.unit) then
      return { qty = l.qty, total = l.total, avg = l.unit, max = maxFor(w, l.unit), auctionID = l.auctionID }
    end
  end
  return nil
end

-- Search results --------------------------------------------------------------------------------------------------

local function byUnit(a, b) return a.unit < b.unit end

local function watched(id)
  for _, lim in pairs(store().rows) do
    if lim.reagents and lim.reagents[id] and not lim.noRoom then return true end
  end
  return false
end

function S.ReadCommodity(id)
  if not ns.char or not watched(id) then return end
  local ok, n = ns.Call("C_AuctionHouse.GetNumCommoditySearchResults", id)
  if not ok or type(n) ~= "number" then
    ns.Error("sniper: GetNumCommoditySearchResults: " .. tostring(n))
    return
  end
  local listings = {}
  for i = 1, n do
    local got, info = ns.Call("C_AuctionHouse.GetCommoditySearchResultInfo", id, i)
    if got and type(info) == "table" and info.unitPrice and info.quantity then
      local qty = info.quantity - (info.numOwnerItems or 0)
      if qty > 0 then
        table.insert(listings, { unit = info.unitPrice, qty = qty, total = info.unitPrice * qty })
      end
    end
  end
  table.sort(listings, byUnit)
  S.seen[id] = { time = now(), commodity = true, listings = listings }
  if S.current and S.current.id == id then S.current = nil end
  ns.Fire("SNIPE_CHANGED")
end

function S.ReadItems(key)
  local id = type(key) == "table" and key.itemID
  if not id or not ns.char or not watched(id) then return end
  local ok, n = ns.Call("C_AuctionHouse.GetNumItemSearchResults", key)
  if not ok or type(n) ~= "number" then
    ns.Error("sniper: GetNumItemSearchResults: " .. tostring(n))
    return
  end
  local listings = {}
  for i = 1, n do
    local got, info = ns.Call("C_AuctionHouse.GetItemSearchResultInfo", key, i)
    if got and type(info) == "table" and info.buyoutAmount and info.auctionID and not info.containsOwnerItem then
      local qty = math.max(info.quantity or 1, 1)
      table.insert(listings, { unit = info.buyoutAmount / qty, qty = qty, total = info.buyoutAmount,
        auctionID = info.auctionID })
    end
  end
  table.sort(listings, byUnit)
  S.seen[id] = { time = now(), commodity = false, listings = listings }
  if S.current and S.current.id == id then S.current = nil end
  ns.Fire("SNIPE_CHANGED")
end

-- Scan loop ----------------------------------------------------------------------------------------------------

S.running = false
S.current = nil      -- { id, sent } search in flight
S.lastSend = -math.huge
S.stopReason = nil
local token = 0

function S.Stop(reason)
  if S.running then token = token + 1 end
  S.running, S.current, S.stopReason = false, nil, reason
  if reason then ns.Print("sniper stopped: " .. reason) end
  ns.Fire("SNIPE_CHANGED")
end

local function itemKey(id)
  local ok, key = ns.Call("C_AuctionHouse.MakeItemKey", id)
  if ok and type(key) == "table" then return key end
  return { itemID = id, itemLevel = 0, itemSuffix = 0, battlePetSpeciesID = 0 }
end

-- The watched reagent to search next: still needed, searched longest ago (and not within S.REPEAT). → id, any needed
local function nextItem(t)
  local best, bestTime, anyNeed
  for _, w in ipairs(S.Watch()) do
    if w.need > 0 then
      anyNeed = true
      local seen = S.seen[w.id]
      local at = seen and seen.time or -math.huge
      if t - at >= S.REPEAT and (not best or at < bestTime) then best, bestTime = w.id, at end
    end
  end
  return best, anyNeed
end

function S.Step()
  if not S.running then return end
  if not ns.Scanner.ahOpen then return S.Stop("the auction house closed") end
  if ns.Scanner.state ~= "idle" or S.pending then return end
  local t = now()
  if S.current then
    if t - S.current.sent < S.TIMEOUT then return end
    ns.Debug("sniper: no results for " .. S.current.id)
    S.seen[S.current.id] = { time = t, commodity = true, listings = {}, timedOut = true }
    S.current = nil
  end
  if t - S.lastSend < S.GAP then return end
  local okReady, ready = ns.Call("C_AuctionHouse.IsThrottledMessageSystemReady")
  if okReady and ready == false then return end
  local id, anyNeed = nextItem(t)
  if not anyNeed then return S.Stop(S.MET) end
  if not id then return end
  local sorts = { { sortOrder = Enum and Enum.AuctionHouseSortOrder and Enum.AuctionHouseSortOrder.Price or 0,
    reverseSort = false } }
  local ok, err = ns.Call("C_AuctionHouse.SendSearchQuery", itemKey(id), sorts, true)
  if not ok then
    ns.Error("sniper: SendSearchQuery: " .. tostring(err))
    return S.Stop("the AH search API failed (/crafter errors)")
  end
  S.current, S.lastSend = { id = id, sent = t }, t
  ns.Fire("SNIPE_CHANGED")
end

local function loop(my)
  if my ~= token or not S.running then return end
  local ok, err = pcall(S.Step)
  if not ok then
    ns.Error("sniper: " .. tostring(err))
    S.Stop("error (/crafter errors)")
    return
  end
  if my == token and S.running then C_Timer.After(S.TICK, function() loop(my) end) end
end

function S.Start()
  if not ns.Scanner.ahOpen then
    ns.Print("open the auction house first")
    return
  end
  if not ns.API("C_AuctionHouse.SendSearchQuery") then
    ns.Error("sniper: C_AuctionHouse.SendSearchQuery missing")
    ns.Print("this client has no AH search API; the sniper cannot run")
    return
  end
  local _, anyNeed = nextItem(now())
  if not anyNeed then
    ns.Print(next(store().rows) and ("nothing to snipe: " .. S.MET)
      or "nothing to snipe: tick the Snipe box of a craft first")
    return
  end
  token = token + 1
  S.running, S.stopReason = true, nil
  ns.Fire("SNIPE_CHANGED")
  loop(token)
end

-- Buying ---------------------------------------------------------------------------------------------------------

S.pending = nil   -- { id, qty, max, budget, stage = "quote"|"confirm"|"click"|"bid", auctionID, started, unit, total, seq }
S.late = nil      -- a confirmed purchase the AH did not answer in time: a late COMMODITY_PURCHASE_SUCCEEDED still counts
S.CLICK_WAIT = 60 -- seconds a quote waits for the Confirm click

local function money()
  local ok, m = ns.Call("GetMoney")
  return ok and type(m) == "number" and m or nil
end

local function finish(msg)
  S.pending = nil
  if msg then ns.Print(msg) end
  ns.Fire("SNIPE_CHANGED")
end

local function cancelQuote(msg)
  ns.Call("C_AuctionHouse.CancelCommoditiesPurchase")
  finish(msg)
end

-- A timeout for the purchase's current stage; a later stage (or another purchase) makes it a no-op.
local function arm(p, secs)
  p.seq = (p.seq or 0) + 1
  local seq, stage = p.seq, p.stage
  C_Timer.After(secs, function()
    if S.pending ~= p or p.seq ~= seq or p.stage ~= stage then return end
    if stage == "bid" then
      finish("no answer from the auction house; check your mail before buying again")
    elseif stage == "confirm" then
      S.late = p                                 -- it may still go through: do not cancel
      finish("no answer from the auction house yet; check your mail before buying more")
    elseif stage == "click" then
      cancelQuote("not confirmed in time; cancelled")
    else
      cancelQuote("no price quote from the auction house; cancelled")
    end
  end)
end

local function confirm(p)
  p.stage = "confirm"
  arm(p, S.TIMEOUT)
  local ok, err = ns.Call("C_AuctionHouse.ConfirmCommoditiesPurchase", p.id, p.qty)
  if not ok then
    ns.Error("sniper: ConfirmCommoditiesPurchase: " .. tostring(err))
    cancelQuote("purchase failed: " .. tostring(err))
  end
end

-- What the Buy button does now. → label, entry (or nil)
function S.BuyTarget(selected)
  if S.pending then
    if S.pending.stage == "click" then return "Confirm " .. S.pending.qty .. " x " .. Util.ItemName(S.pending.id) end
    return "Buying...", nil
  end
  local best
  for _, w in ipairs(S.Watch()) do
    if w.deal and selected and w.id == selected.id then return S.BuyLabel(w), w end
    if w.deal and (not best or (w.max - w.deal.avg) / w.max > (best.max - best.deal.avg) / best.max) then best = w end
  end
  if best then return S.BuyLabel(best), best end
  return "Buy", nil
end

function S.BuyLabel(w)
  return string.format("Buy %d x %s", w.deal.qty, w.name)
end

-- The Buy click (a hardware event: the restricted purchase calls must run in it). w = a Watch entry, or nil for the
-- best deal.
function S.Buy(w)
  local p = S.pending
  if p then
    if p.stage == "click" then
      local okLeft, left = ns.Call("C_AuctionHouse.GetQuoteDurationRemaining")
      if okLeft and type(left) == "number" and left <= 0 then return cancelQuote("the price quote ran out; try again") end
      confirm(p)
    end
    return
  end
  if not ns.Scanner.ahOpen then return ns.Print("open the auction house first") end
  if not w then
    local _
    _, w = S.BuyTarget(nil)
  end
  local deal = w and w.deal
  if not deal then return ns.Print("no deal at or under the max price yet") end
  S.late = nil
  local m = money()
  if m and m < deal.total then return ns.Print("not enough money for " .. Util.Money(deal.total)) end
  if deal.commodity then
    S.pending = { id = w.id, qty = deal.qty, max = deal.max, budget = deal.budget, stage = "quote", started = now() }
    local ok, err = ns.Call("C_AuctionHouse.StartCommoditiesPurchase", w.id, deal.qty, math.ceil(deal.avg))
    if not ok then
      ns.Error("sniper: StartCommoditiesPurchase: " .. tostring(err))
      return finish("purchase failed: " .. tostring(err))
    end
  else
    S.pending = { id = w.id, qty = deal.qty, max = deal.max, stage = "bid", auctionID = deal.auctionID,
      total = deal.total, started = now() }
    local ok, err = ns.Call("C_AuctionHouse.PlaceBid", deal.auctionID, deal.total)
    if not ok then
      ns.Error("sniper: PlaceBid: " .. tostring(err))
      return finish("purchase failed: " .. tostring(err))
    end
  end
  if S.pending then arm(S.pending, S.TIMEOUT) end
  ns.Fire("SNIPE_CHANGED")
end

local function bought(p, total)
  addBought(p.id, p.qty)
  if S.seen[p.id] then S.seen[p.id].time = -math.huge end
  finish(string.format("bought %d x %s for %s (sent to your mailbox)", p.qty, Util.ItemName(p.id), Util.Money(total)))
end

-- The quote, or a new one after a confirm (the price changed): over the budget cancels. A new quote after a confirm
-- is not confirmed by itself; it waits for a click.
ns.On("COMMODITY_PRICE_UPDATED", function(unit, total)
  local p = S.pending
  if not p or p.stage == "bid" then return end
  local requote = p.stage ~= "quote"
  p.unit, p.total = unit, total
  if not total or total > p.budget then
    return cancelQuote(string.format("%d x %s now cost %s, over the max %s; cancelled", p.qty, Util.ItemName(p.id),
      Util.Money(total or 0), Util.Money(p.budget)))
  end
  local m = money()
  if m and total and m < total then return cancelQuote("not enough money for " .. Util.Money(total)) end
  if requote then
    p.stage = "click"
    arm(p, S.CLICK_WAIT)
    ns.Print(string.format("the price changed to %s (within the max): press Confirm", Util.Money(total)))
    return ns.Fire("SNIPE_CHANGED")
  end
  confirm(p)
end)

ns.On("COMMODITY_PRICE_UNAVAILABLE", function()
  if S.pending and S.pending.stage == "quote" then cancelQuote("no price available any more; cancelled") end
end)

ns.On("COMMODITY_PURCHASE_SUCCEEDED", function()
  local p = S.pending
  if p and (p.stage == "confirm" or p.stage == "click") then
    bought(p, p.total or 0)
  elseif not p and S.late then
    p, S.late = S.late, nil
    bought(p, p.total or 0)
  end
end)

ns.On("COMMODITY_PURCHASE_FAILED", function()
  S.late = nil
  if S.pending then finish("the purchase failed (someone may have bought it first)") end
end)

ns.On("AUCTION_HOUSE_PURCHASE_COMPLETED", function(auctionID)
  local p = S.pending
  if p and p.stage == "bid" and p.auctionID == auctionID then bought(p, p.total) end
end)

ns.On("AUCTION_HOUSE_SHOW_ERROR", function(err)
  local p = S.pending
  if p and p.stage == "bid" then finish("the purchase failed (AH error " .. tostring(err) .. ")") end
end)

-- A restricted call was blocked: ConfirmCommoditiesPurchase from an event handler needs a second click instead.
local function blocked(...)
  local p = S.pending
  if not p then return end
  local parts = {}
  for i = 1, select("#", ...) do parts[i] = tostring((select(i, ...))) end
  local what = table.concat(parts, " ")
  if not what:find("AuctionHouse") and not what:find("Purchase") and not what:find("PlaceBid") then return end
  ns.Error("sniper: blocked: " .. what)
  if p.stage == "confirm" and what:find("ConfirmCommoditiesPurchase") then
    p.stage = "click"
    arm(p, S.CLICK_WAIT)
    ns.Print("the game wants a click to confirm: press Confirm")
    ns.Fire("SNIPE_CHANGED")
  else
    finish("the game blocked the purchase (/crafter errors)")
  end
end
ns.On("ADDON_ACTION_BLOCKED", blocked)
ns.On("ADDON_ACTION_FORBIDDEN", blocked)

ns.On("COMMODITY_SEARCH_RESULTS_UPDATED", function(id) S.ReadCommodity(id) end)
ns.On("ITEM_SEARCH_RESULTS_UPDATED", function(key) S.ReadItems(key) end)
ns.On("AUCTION_HOUSE_CLOSED", function()
  if S.pending then
    if S.pending.stage ~= "bid" then ns.Call("C_AuctionHouse.CancelCommoditiesPurchase") end
    S.pending = nil
  end
  if S.running then S.Stop("the auction house closed") end
end)

-- Sniper tab ------------------------------------------------------------------------------------------------------

S.COLUMNS = {
  { key = "name", label = "Reagent", width = 170 },
  { key = "need", label = "Need", width = 46, hint = "How many more to buy: the ticked crafts' batches less what is in "
    .. "your bags and what you bought that is still in the mail." },
  { key = "have", label = "Have", width = 50, hint = "In your bags plus bought and still in the mail." },
  { key = "max", label = "Max price", width = 80, hint = "The most to pay per item: keeps each ticked craft at Keep g/h "
    .. "of its g/h (AH sales: of the g/h after a 10% price drop)." },
  { key = "cheap", label = "Cheapest", width = 80, hint = "Cheapest listing in the last search (your own excluded)." },
  { key = "dqty", label = "Deal qty", width = 56, hint = "How many the Buy button buys: listings at or under the max, up "
    .. "to the need." },
  { key = "davg", label = "Deal avg", width = 80, hint = "Average price per item of that deal." },
  { key = "under", label = "Under max", width = 64, hint = "How far the deal is under the max price." },
  { key = "seen", label = "Searched", width = 56, hint = "Time since the last search for it." },
  { key = "rows", label = "For", width = 100 },
}

S.FOOTER = "Buy = one purchase per click; Need 0 = done (raise a craft's Target to buy more); searches run only "
  .. "while the AH is open"

-- The ticked crafts above the reagent list.
S.CRAFT_COLUMNS = {
  { key = "craft", label = "Ticked craft", width = 290 },
  { key = "sale", label = "Sale", width = 60, hint = "The sale the max prices are worked out for: Vendor (a vendor "
    .. "shuffle, Vend g/h) or AH (AH g/h, measured after a 10% price drop)." },
  { key = "batch", label = "Batch", width = 60, hint = "The craft's cheap batch from the last scan: how many crafts the "
    .. "cheap listings were enough for." },
  { key = "target", label = "Target", width = 70, hint = "How many crafts to buy reagents for. Blank = the batch. Raise "
    .. "it to keep sniping when new cheap listings keep appearing; the max prices stay the same, so every craft still "
    .. "keeps Keep g/h. 1 to " .. S.MAX_TARGET .. "; Enter to set." },
  { key = "time", label = "Time", width = 70, hint = "Crafting time for the Target: Target x the time of one craft "
    .. "(the path of the g/h column)." },
  { key = "profit", label = "Profit (at max)", width = 110, hint = "Profit for the Target if every AH reagent is bought "
    .. "at its max price: Target x (sale - batch-average cost - room) at today's sale price. Buying cheaper earns more. "
    .. "~ = the vendor price is an estimate; - = no room or no AH reagents." },
  { key = "floorgh", label = "Floor g/h", width = 100, hint = "The g/h a craft keeps at worst, when every reagent is "
    .. "bought at its max price (AH sales: after a 10% price drop)." },
}

-- How many crafts a ticked craft is sniped for: its Target, else its batch.
function S.TargetCount(lim)
  return S.Target(lim.spell) or lim.batch
end

-- The profit of one craft with every AH reagent bought at its max: W - (C + room). nil = no room / no AH reagents.
function S.ProfitAtMax(lim)
  if not lim.W or lim.noRoom or lim.noAH then return nil end
  return lim.W - (lim.C + lim.room)
end

-- One craft's totals for its Target. → profit (nil = no room), seconds (nil = unknown)
function S.CraftTotals(lim)
  local n = S.TargetCount(lim)
  if not n then return nil, nil end
  local p = S.ProfitAtMax(lim)
  local t = lim.time and lim.time > 0 and n * lim.time or nil
  return p and n * p, t
end

-- Over all ticked crafts with room: { profit, time, gh, crafts, est }. g/h counts only crafts with a known time.
function S.Totals()
  local tot = { profit = 0, time = 0, crafts = 0 }
  local timedProfit = 0
  for _, lim in ipairs(S.Crafts()) do
    local p, t = S.CraftTotals(lim)
    if p then
      tot.profit, tot.crafts = tot.profit + p, tot.crafts + 1
      if lim.est then tot.est = true end
      if t then tot.time, timedProfit = tot.time + t, timedProfit + p end
    end
  end
  if tot.time > 0 then tot.gh = timedProfit / tot.time * 3600 end
  return tot
end

function S.TotalText()
  local tot = S.Totals()
  if tot.crafts == 0 then return "Total: no ticked craft with room" end
  local UI = ns.UI
  return string.format("Total for %d craft%s at Target: time %s, profit at max %s%s, %s", tot.crafts,
    tot.crafts == 1 and "" or "s", tot.time > 0 and UI.TimeText(tot.time) or "—",
    Util.Money(math.floor(tot.profit + 0.5)), tot.est and " ~" or "",
    tot.gh and (Util.Money(math.floor(tot.gh + 0.5)) .. "/h") or "g/h unknown")
end

-- Ticked crafts, by name. → { lim, ... }
function S.Crafts()
  local list = {}
  if not ns.char then return list end
  for _, lim in pairs(store().rows) do table.insert(list, lim) end
  table.sort(list, function(a, b)
    if (a.name or "") ~= (b.name or "") then return (a.name or "") < (b.name or "") end
    return a.spell < b.spell
  end)
  return list
end

function S.CraftCellText(lim, key)
  if key == "craft" then
    local mark = ""
    if lim.noRoom then mark = " |cffff8040no room|r" elseif lim.noAH then mark = " |cff808080no AH reagents|r" end
    return (lim.cd and "|cffffd100[cd]|r " or "") .. (lim.name or "?") .. mark
  end
  if key == "sale" then return lim.kind == "vendor" and "Vendor" or "AH" end
  if key == "batch" then return lim.batch and tostring(lim.batch) or "—" end
  if key == "target" then
    local t = S.Target(lim.spell)
    return t and tostring(t) or ""
  end
  if key == "time" then
    local _, t = S.CraftTotals(lim)
    return t and ns.UI.TimeText(t, true) or "—"
  end
  if key == "profit" then
    local p = S.CraftTotals(lim)
    return p and (Util.Money(math.floor(p + 0.5)) .. (lim.est and " ~" or "")) or "—"
  end
  if key == "floorgh" then
    if lim.noRoom or lim.noAH then return "—" end
    if lim.cd then return "|cff808080per cooldown|r" end
    return lim.floorGh and (Util.Money(math.floor(lim.floorGh + 0.5)) .. "/h") or "—"
  end
  return ""
end

local function ago(t)
  if not t or t == -math.huge then return "—" end
  local d = math.max(0, now() - t)
  if d < 60 then return math.floor(d) .. "s" end
  if d < 3600 then return math.floor(d / 60) .. "m" end
  return math.floor(d / 3600) .. "h"
end

-- Entries for the tab (Watch entries; .spell = item ID for the list's selection).
function S.List()
  return S.Watch()
end

function S.SortValue(w, key)
  if key == "name" then return w.name end
  if key == "need" then return w.need end
  if key == "have" then return w.owned end
  if key == "max" then return w.max end
  if key == "cheap" then
    local s = S.seen[w.id]
    return s and s.listings[1] and s.listings[1].unit or math.huge
  end
  if key == "dqty" then return w.deal and w.deal.qty or -1 end
  if key == "davg" then return w.deal and w.deal.avg or math.huge end
  if key == "seen" then
    local s = S.seen[w.id]
    return s and s.time or -math.huge
  end
  if key == "rows" then return #w.rows end
  return w.deal and (w.max - w.deal.avg) / w.max or -math.huge
end

function S.CellText(w, key)
  if key == "name" then return Util.ItemText(w.id) end
  if key == "need" then return w.need > 0 and tostring(w.need) or "|cff40c040done|r" end
  if key == "have" then return w.mail > 0 and string.format("%d+%d", w.bags, w.mail) or tostring(w.bags) end
  if key == "max" then return Util.Money(w.max) end
  local s = S.seen[w.id]
  if key == "cheap" then
    if not s then return "—" end
    local l = s.listings[1]
    if not l then return "|cff808080none|r" end
    return l.unit <= w.max and ("|cff40ff40" .. Util.Money(math.floor(l.unit)) .. "|r") or Util.Money(math.floor(l.unit))
  end
  if key == "dqty" then return w.deal and tostring(w.deal.qty) or "—" end
  if key == "davg" then return w.deal and Util.Money(math.floor(w.deal.avg + 0.5)) or "—" end
  if key == "under" then
    if not w.deal then return "—" end
    return math.floor((w.max - w.deal.avg) / w.max * 100 + 0.5) .. "%"
  end
  if key == "seen" then
    if S.current and S.current.id == w.id then return "|cffffd100now|r" end
    return s and ago(s.time) or "never"
  end
  if key == "rows" then
    local first = w.rows[1].name or "?"
    return #w.rows > 1 and string.format("%s +%d", first, #w.rows - 1) or first
  end
  return ""
end

-- The math of a ticked row, as detail lines.
function S.LimitLines(lim, out)
  local f = math.floor(lim.floor * 100 + 0.5)
  if not lim.W then
    table.insert(out, "  no profitable " .. (lim.kind == "vendor" and "vendor" or "AH") .. " sale: nothing to snipe")
    return out
  end
  local sale = lim.kind == "vendor" and "vendor" or "AH"
  table.insert(out, string.format("  %s sale %s per craft%s; batch-average cost %s (batch %d%s)", sale,
    Util.Money(lim.W), lim.kind == "ah" and (", after a 10% drop " .. Util.Money(lim.Wc)) or " (no cushion)",
    Util.Money(math.floor(lim.C + 0.5)), lim.batch, lim.fast and ", fastest path" or ""))
  if lim.noRoom then
    table.insert(out, "  |cffff8040no room|r: the sale does not cover the cost" .. (lim.kind == "ah"
      and " after a 10% price drop" or ""))
    return out
  end
  table.insert(out, string.format("  room %s per craft = %d%% of (%s - %s)", Util.Money(math.floor(lim.room)), 100 - f,
    Util.Money(lim.Wc), Util.Money(math.floor(lim.C + 0.5))))
  if lim.noAH then
    table.insert(out, "  no AH reagents: nothing to snipe")
    return out
  end
  table.insert(out, string.format("  markup +%.1f%% on the AH reagents (%s per craft)", lim.markup * 100,
    Util.Money(math.floor(lim.ahCost + 0.5))))
  local ids = {}
  for id in pairs(lim.reagents) do table.insert(ids, id) end
  table.sort(ids)
  for _, id in ipairs(ids) do
    local g = lim.reagents[id]
    table.insert(out, string.format("    %s x%d: batch avg %s -> max %s", Util.ItemText(id), S.TargetQty(lim.spell, lim, g),
      Util.Money(math.floor(g.unit + 0.5)), Util.Money(g.max)))
  end
  if lim.floorGh then
    table.insert(out, string.format("  buying at the max keeps at least %s/h (%d%% of %s/h%s)",
      Util.Money(math.floor(lim.floorGh + 0.5)), f,
      Util.Money(math.floor(lim.floorGh / lim.floor + 0.5)), lim.kind == "ah" and " after the drop" or ""))
  end
  return out
end

function S.DetailText(w)
  local out = {}
  if not w then
    table.insert(out, "Select a reagent on the left.")
    table.insert(out, "")
    table.insert(out, "Tick the Snipe box of a craft in the craft list: its AH reagents are watched here with its cheap "
      .. "batch quantities (raise a craft's Target above to buy for more crafts). Open the AH and press Start: the sniper searches the watched reagents one at a time and "
      .. "lists listings at or under the max price. Press Buy for each purchase (the game needs a click per buy).")
    table.insert(out, "")
    table.insert(out, "Max price: a deal must keep the craft at Keep g/h of the g/h it would earn if its AH sale price "
      .. "fell 10% (a vendor sale has no cushion). The room left is shared as one markup over all of the craft's AH "
      .. "reagents, so any mix of buys at the max prices keeps that floor.")
    return table.concat(out, "\n")
  end
  table.insert(out, Util.ItemText(w.id))
  table.insert(out, string.format("Need %d more  |  bags %d, in the mail %d  |  max %s", w.need, w.bags, w.mail,
    Util.Money(w.max)))
  if w.deal then
    table.insert(out, string.format("|cff40ff40Deal:|r %d at %s each (%s); cancelled if the quote is over %s", w.deal.qty,
      Util.Money(math.floor(w.deal.avg + 0.5)), Util.Money(w.deal.total),
      Util.Money(w.deal.budget or w.deal.max * w.deal.qty)))
  end
  table.insert(out, "")
  table.insert(out, "|cffffd100For:|r")
  for _, row in ipairs(w.rows) do
    local lim = store().rows[row.spell]
    table.insert(out, string.format("%s (%s sale, %s): %d, max %s", row.name or "?",
      row.kind == "vendor" and "vendor" or "AH", lim and S.TargetText(lim) or "?", row.qty, Util.Money(row.max)))
    if lim then S.LimitLines(lim, out) end
  end
  local s = S.seen[w.id]
  table.insert(out, "")
  if s then
    table.insert(out, string.format("|cffffd100Last search (%s ago, %s):|r", ago(s.time),
      s.commodity and "commodity" or "item auctions"))
    for i, l in ipairs(s.listings) do
      if i > 10 then
        table.insert(out, string.format("  %d more", #s.listings - 10))
        break
      end
      local unit = Util.Money(math.floor(l.unit + 0.5))
      table.insert(out, string.format("  %d x %s%s", l.qty, l.unit <= w.max and ("|cff40ff40" .. unit .. "|r") or unit,
        s.commodity and "" or (" (" .. Util.Money(l.total) .. " for the lot)")))
    end
    if #s.listings == 0 then table.insert(out, s.timedOut and "  no answer" or "  none listed") end
  else
    table.insert(out, "Not searched yet.")
  end
  return table.concat(out, "\n")
end

function S.OptionLines(w, out)
  table.insert(out, w.name)
  table.insert(out, string.format("Need %d, max %s", w.need, Util.Money(w.max)))
  for _, row in ipairs(w.rows) do
    table.insert(out, string.format("%s: %d up to %s", row.name or "?", row.qty, Util.Money(row.max)))
  end
end

function S.StatusText(n)
  local parts = {}
  if S.running then
    table.insert(parts, "|cff40ff40Sniping|r" .. (S.current and (": " .. Util.ItemName(S.current.id)) or ""))
  else
    table.insert(parts, "Stopped" .. (S.stopReason and (" (" .. S.stopReason .. ")") or ""))
  end
  local crafts, noRoom = 0, 0
  for _, lim in pairs(store().rows) do
    crafts = crafts + 1
    if lim.noRoom then noRoom = noRoom + 1 end
  end
  table.insert(parts, string.format("%d reagent%s for %d craft%s", n, n == 1 and "" or "s", crafts,
    crafts == 1 and "" or "s"))
  if noRoom > 0 then table.insert(parts, string.format("|cffff8040%d with no room|r", noRoom)) end
  table.insert(parts, string.format("keep %d%% g/h", math.floor(S.Floor() * 100 + 0.5)))
  if S.pending then table.insert(parts, "|cffffd100buying " .. Util.ItemName(S.pending.id) .. "|r") end
  if not ns.Scanner.ahOpen then table.insert(parts, "|cffff8040open the AH|r") end
  return table.concat(parts, "  |  ")
end

-- /crafter snipe [start|stop|clear|forget]
ns.Command("snipe", function(rest)
  rest = (rest or ""):lower():match("^%s*(.-)%s*$")
  if rest == "start" then
    S.Start()
  elseif rest == "stop" then
    S.Stop()
  elseif rest == "clear" then
    S.Clear()
    ns.Print("no crafts ticked for sniping")
  elseif rest == "forget" then
    S.ForgetBought()
    ns.Print("forgot what the sniper bought")
  elseif rest == "" then
    if ns.UI then
      ns.UI.Show()
      ns.UI.SetMode("snipe")
    end
  else
    ns.Print("usage: /crafter snipe [start|stop|clear|forget]")
  end
end)
