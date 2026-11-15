-- Modules/Pricing.lua: what an item costs to buy and what it is worth when sold.
-- Buy: the AH snapshot ladder for the needed quantity, or a vendor (merchant seen in game, else the static
-- vendor list with the DB2 price as an estimate). Sell: max(AH lowest buyout - 1c after cut and deposit,
-- vendor sell price). Merchants the player opens and AH sale invoices in the mailbox refine the numbers.
local _, ns = ...
local P = {}
ns.Pricing = P
local Util = ns.Util

P.ASSUMED_CUT = 0.05        -- unverified for Forever; replaced by sale invoices or /crafter cut
P.THIN = 3                  -- fewer listings than this = thin market
local DEPOSIT_DURATION = 1  -- luaIndex 1 = shortest duration (AUCTION_DURATION_ONE in the Forever AH UI)

-- AH cut as a fraction. → cut, label
function P.Cut()
  local s = ns.settings
  if s and s.cut then return s.cut, "set by you" end
  local seen = ns.db and ns.db.cutSeen
  if seen and seen.pct then return seen.pct, "from " .. seen.n .. " sale invoice(s)" end
  return P.ASSUMED_CUT, "assumed"
end

-- Vendor price for one item. → unit, label ("merchant" | "estimate"), limited  or nil
function P.VendorUnit(id)
  local seen = ns.db and ns.db.vendorSeen[id]
  if seen and seen.unit then return seen.unit, "merchant", seen.limited end
  local v = ns.Vendor[id]
  if v and not v.limited and not v.recipe and v.price > 0 then
    return v.price / math.max(v.vstack or 1, 1), "estimate", false
  end
  return nil
end

-- Cost of buying qty from the AH snapshot. → total, estimate (beyond the snapshot's cheapest price steps), the
-- highest unit price paid; or nil if fewer are listed
function P.AHBuy(id, qty)
  local p = ns.Scanner.Price(id)
  if not p or p.qty < qty then return nil end
  local steps = p.steps
  if not steps then
    -- A snapshot saved by an older version: ladder = { {unit, qty}, ... }
    steps = {}
    for _, s in ipairs(p.ladder or {}) do
      steps[#steps + 1], steps[#steps + 2] = s[1], s[2]
    end
  end
  local left, total = qty, 0
  for i = 1, #steps, 2 do
    local take = math.min(left, steps[i + 1])
    total = total + take * steps[i]
    left = left - take
    if left <= 0 then return total, false, steps[i] end
  end
  -- The ladder keeps only the cheapest steps; price the rest at the last one (a lower bound).
  local last = steps[#steps - 1]
  return total + left * last, true, last
end

-- Deposit for posting one item, cached from the client when the AH is open. → copper or nil
function P.Deposit(id)
  return ns.db and ns.db.deposit[id] or nil
end

-- Worth of one item. → { unit, where = "ah"|"vendor", ah, vendor, vendorEst, listings, qty, thin, deposit } or nil
function P.SellValue(id)
  local out = { vendor = nil, ah = nil }
  local sell, from = Util.SellPrice(id)
  if sell and sell > 0 then out.vendor, out.vendorEst = sell, from ~= "client" end
  if not Util.IsBoP(id) then
    local p = ns.Scanner.Price(id)
    if p then
      out.listings, out.qty, out.min = p.n, p.qty, p.min
      out.thin = p.n < P.THIN
      local minListings = ns.settings and ns.settings.minListings or 1
      if p.n >= minListings then
        out.deposit = P.Deposit(id)
        out.ah = math.floor((p.min - 1) * (1 - P.Cut())) - (out.deposit or 0)
      end
    end
  end
  if out.ah and (not out.vendor or out.ah >= out.vendor) then
    out.unit, out.where = out.ah, "ah"
  elseif out.vendor then
    out.unit, out.where = out.vendor, "vendor"
  else
    return nil
  end
  return out
end

-- Merchant capture: any merchant the player opens gives exact prices for what it sells. Forever loads the Mainline
-- MerchantFrame, which reads C_MerchantFrame.GetItemInfo (a table); the global GetMerchantItemInfo is in the Classic
-- (Vanilla/TBC) frames only, so it is just a fallback.
local merchantAnnounce = false   -- one chat line per merchant visit
local merchantFailed = {}        -- each kind of failure is recorded once per session

-- Records a failure (once per session) and, on a new visit, says so in chat.
local function merchantError(msg)
  if not merchantFailed[msg] then
    merchantFailed[msg] = true
    ns.Error("merchant: " .. msg)
  end
  if merchantAnnounce then
    merchantAnnounce = false
    ns.Print(string.format("could not read the vendor prices from %s; see /crafter errors",
      (UnitName and UnitName("npc")) or "this merchant"))
  end
end

-- One merchant slot. → { price, stack, available, extended, currency } or nil, why
local function merchantSlot(i)
  if ns.API("C_MerchantFrame.GetItemInfo") then
    local ok, info = ns.Call("C_MerchantFrame.GetItemInfo", i)
    if not ok then return nil, "C_MerchantFrame.GetItemInfo: " .. tostring(info) end
    if type(info) ~= "table" then return nil, "C_MerchantFrame.GetItemInfo returned " .. type(info) end
    return { price = info.price, stack = info.stackCount, available = info.numAvailable,
             extended = info.hasExtendedCost, currency = info.currencyID }
  end
  local r = { ns.Call("GetMerchantItemInfo", i) }
  if not r[1] then return nil, "GetMerchantItemInfo: " .. tostring(r[2]) end
  -- name, texture, price, stackCount, numAvailable, isPurchasable, isUsable, extendedCost, currencyID
  return { price = r[4], stack = r[5], available = r[6], extended = r[9], currency = r[10] }
end

-- Item id of a merchant slot: GetMerchantItemID, else the id in GetMerchantItemLink. → id or nil
local function merchantItemID(i)
  local ok, id = ns.Call("GetMerchantItemID", i)
  if ok and type(id) == "number" and id > 0 then return id end
  local okL, link = ns.Call("GetMerchantItemLink", i)
  if okL and type(link) == "string" then return tonumber(string.match(link, "item:(%d+)")) end
  return nil
end

local function captureMerchant()
  if not ns.db then return end
  local okN, n = ns.Call("GetMerchantNumItems")
  if not okN or type(n) ~= "number" then
    merchantError("cannot count the merchant's items (" .. tostring(n) .. ")")
    return
  end
  if n == 0 then return end
  if not ns.API("C_MerchantFrame.GetItemInfo") and not ns.API("GetMerchantItemInfo") then
    merchantError("no API for merchant prices (C_MerchantFrame.GetItemInfo or GetMerchantItemInfo)")
    return
  end
  if not ns.API("GetMerchantItemID") and not ns.API("GetMerchantItemLink") then
    merchantError("no API for merchant item ids (GetMerchantItemID or GetMerchantItemLink)")
    return
  end
  local npc = UnitName and UnitName("npc") or nil
  local count, failed, changed, why = 0, 0, false, nil
  for i = 1, n do
    local slot, err = merchantSlot(i)
    if not slot then
      failed, why = failed + 1, why or err
    elseif type(slot.price) == "number" and slot.price > 0 and not slot.extended and not slot.currency then
      local id = merchantItemID(i)
      if id then
        local stack = (type(slot.stack) == "number" and slot.stack > 0) and slot.stack or 1
        -- numAvailable: -1 = unlimited, 0 = sold out, N = limited stock (the Mainline frame greys out 0 and shows N)
        local unit, limited = slot.price / stack, (slot.available or -1) >= 0
        local old = ns.db.vendorSeen[id]
        if not old or old.unit ~= unit or old.limited ~= limited or old.stack ~= stack then changed = true end
        ns.db.vendorSeen[id] = { unit = unit, stack = stack, limited = limited, time = time(), npc = npc }
        count = count + 1
      else
        failed, why = failed + 1, why or "no item id"
      end
    end
  end
  local who = npc or "this merchant"
  if merchantAnnounce and count > 0 then
    merchantAnnounce = false
    ns.Print(string.format("%d vendor price%s from %s", count, count == 1 and "" or "s", who))
  end
  if failed > 0 then
    merchantError(string.format("could not read %d of %d items from %s (%s)", failed, n, who, tostring(why)))
  end
  ns.Debug(string.format("merchant %s: %d of %d items, %d failed", who, count, n, failed))
  if changed then ns.Fire("DATA_CHANGED") end
end

local merchantPending = false
local function merchantSoon()
  if merchantPending then return end
  merchantPending = true
  C_Timer.After(0.5, function()
    merchantPending = false
    local ok, err = pcall(captureMerchant)
    if not ok then ns.Error("merchant: " .. tostring(err)) end
  end)
end
ns.On("MERCHANT_SHOW", function()
  merchantAnnounce = true
  merchantSoon()
end)
ns.On("MERCHANT_UPDATE", merchantSoon)
ns.On("MERCHANT_CLOSED", function() merchantAnnounce = false end)

-- AH sale invoices: consignment / sale price = the AH cut on this server.
local function captureInvoices()
  if not ns.db then return end
  local okN, n = ns.Call("GetInboxNumItems")
  if not okN or not n then return end
  local best
  for i = 1, n do
    local ok, kind, _, _, bid, _, _, consignment = ns.Call("GetInboxInvoiceInfo", i)
    if ok and kind == "seller" and bid and bid >= 10000 and consignment and consignment > 0 then
      local pct = Util.Round(consignment / bid, 0.001)
      best = best or {}
      best[pct] = (best[pct] or 0) + 1
    end
  end
  if not best then return end
  local pct, count = nil, 0
  for p, c in pairs(best) do
    if c > count then pct, count = p, c end
  end
  local seen = ns.db.cutSeen
  if not seen or seen.pct ~= pct or seen.n < count then
    ns.db.cutSeen = { pct = pct, n = count, time = time() }
    ns.Debug(string.format("AH cut from invoices: %.1f%%", pct * 100))
    ns.Fire("DATA_CHANGED")
  end
end
ns.On("MAIL_INBOX_UPDATE", function()
  local ok, err = pcall(captureInvoices)
  if not ok then ns.Error("invoices: " .. tostring(err)) end
end)

-- Deposits for recipe outputs, read in batches while the AH is open.
local function captureDeposits()
  if not ns.db or not ns.API("C_AuctionHouse.CalculateCommodityDeposit") then return end
  local ids, seen = {}, {}
  for _, r in pairs(ns.Recipes) do
    local id = r.out[1]
    if not seen[id] and not Util.IsBoP(id) then
      seen[id] = true
      table.insert(ids, id)
    end
  end
  local i = 1
  local function step()
    if not ns.Scanner.ahOpen then return end
    for _ = 1, 200 do
      local id = ids[i]
      if not id then
        ns.Fire("DATA_CHANGED")
        return
      end
      local ok, d = ns.Call("C_AuctionHouse.CalculateCommodityDeposit", id, DEPOSIT_DURATION, 1)
      if ok and type(d) == "number" then ns.db.deposit[id] = d end
      i = i + 1
    end
    C_Timer.After(0, step)
  end
  step()
end
ns.Listen("SCAN_DONE", captureDeposits)

function P.PrintStatus()
  local cut, label = P.Cut()
  local merchants = 0
  for _ in pairs(ns.db.vendorSeen) do merchants = merchants + 1 end
  ns.Print(string.format("AH cut %.1f%% (%s); %d merchant prices captured", cut * 100, label, merchants))
end

ns.Command("cut", function(rest)
  local v = tonumber((rest or ""):match("[%d%.]+"))
  if not v then
    ns.settings.cut = nil
    local cut, label = P.Cut()
    ns.Print(string.format("AH cut back to %.1f%% (%s)", cut * 100, label))
  elseif v < 0 or v >= 100 then
    ns.Print("give the cut in percent, e.g. /crafter cut 5")
    return
  else
    ns.settings.cut = v / 100
    ns.Print(string.format("AH cut set to %.1f%%", v))
  end
  ns.Fire("DATA_CHANGED")
end)
