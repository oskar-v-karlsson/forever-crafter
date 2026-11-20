-- Modules/Farm.lua: farm sessions. While a session runs it counts what you loot (CHAT_MSG_LOOT, your own "You
-- receive loot" lines only: purchases, crafts and quest rewards are other messages) and the money you loot
-- (CHAT_MSG_MONEY, else the PLAYER_MONEY rise right next to it), and the time per zone (GetRealZoneText). The clock
-- stops while you are paused, AFK (UnitIsAFK) or logged out. Items are valued at the best of: the Empty shelves
-- suggestion (rarely listed items), the realm's AH min, both less the AH cut, or the vendor sell price.
-- ns.char.farm = { current = the running or paused session, sessions = the last KEEP finished ones (newest first) }.
local _, ns = ...
local F = {}
ns.Farm = F
local Util = ns.Util

local GREY, GREEN, ORANGE = "|cff808080", "|cff40ff40", "|cffff8040"
F.KEEP = 20
local MONEY_WINDOW = 1   -- seconds a PLAYER_MONEY rise and an unread CHAT_MSG_MONEY line may be apart

-- English client strings (GlobalStrings) when the client has none.
local FALLBACK = {
  LOOT_ITEM_SELF = "You receive loot: %s.",
  LOOT_ITEM_SELF_MULTIPLE = "You receive loot: %sx%d.",
  YOU_LOOT_MONEY = "You loot %s",
  LOOT_MONEY_SPLIT = "Your share of the loot is %s.",
  LOOT_MONEY_SPLIT_GUILD = "Your share of the loot is %s. (%s deposited to guild bank)",
  GOLD_AMOUNT = "%d Gold",
  SILVER_AMOUNT = "%d Silver",
  COPPER_AMOUNT = "%d Copper",
}

local function global(name)
  local v = rawget(_G, name)
  return type(v) == "string" and v ~= "" and v or FALLBACK[name]
end

-- A client format string ("You receive loot: %sx%d.") as an anchored Lua pattern.
function F.Pattern(fmt)
  local p = fmt:gsub("[%^%$%(%)%.%[%]%*%+%-%?]", "%%%0")
  p = p:gsub("%%%d?%$?s", "(.-)"):gsub("%%%d?%$?d", "(%%d+)")
  return "^" .. p .. "$"
end

local patterns
local function loadPatterns()
  if patterns then return patterns end
  patterns = {
    multiple = F.Pattern(global("LOOT_ITEM_SELF_MULTIPLE")),
    single = F.Pattern(global("LOOT_ITEM_SELF")),
    money = { F.Pattern(global("LOOT_MONEY_SPLIT_GUILD")), F.Pattern(global("LOOT_MONEY_SPLIT")),
      F.Pattern(global("YOU_LOOT_MONEY")) },
    coins = {
      { global("GOLD_AMOUNT"):gsub("%%d", "(%%d+)"), 10000 },
      { global("SILVER_AMOUNT"):gsub("%%d", "(%%d+)"), 100 },
      { global("COPPER_AMOUNT"):gsub("%%d", "(%%d+)"), 1 },
    },
  }
  return patterns
end
function F.ResetPatterns() patterns = nil end

-- A loot chat line: → item ID, count; nil when it is not your own loot.
function F.ParseLoot(text)
  if type(text) ~= "string" then return nil end
  local p = loadPatterns()
  local link, n = text:match(p.multiple)
  if not link then
    link = text:match(p.single)
    n = 1
  end
  local id = link and link:match("item:(%d+)")
  if not id then return nil end
  return tonumber(id), tonumber(n) or 1
end

-- A money loot line ("You loot 1 Gold, 2 Silver"): → copper, or nil when it does not parse.
function F.ParseMoney(text)
  if type(text) ~= "string" then return nil end
  local p = loadPatterns()
  local amount
  for _, pat in ipairs(p.money) do
    amount = text:match(pat)
    if amount then break end
  end
  if not amount then return nil end
  local total, any = 0, false
  for _, c in ipairs(p.coins) do
    local v = amount:match(c[1])
    if v then
      total = total + tonumber(v) * c[2]
      any = true
    end
  end
  return any and total or nil
end

-- Session state -----------------------------------------------------------------------------------------------------

local function store()
  ns.char.farm = ns.char.farm or { sessions = {} }
  ns.char.farm.sessions = ns.char.farm.sessions or {}
  return ns.char.farm
end

function F.Current()
  return ns.char and store().current or nil
end

local function zoneNow()
  local ok, z = ns.Call("GetRealZoneText")
  if not ok or type(z) ~= "string" or z == "" then ok, z = ns.Call("GetZoneText") end
  return ok and type(z) == "string" and z ~= "" and z or "Unknown"
end

-- Seconds the session has run (paused time left out).
function F.Elapsed(cur, now)
  if not cur then return 0 end
  return cur.acc + (cur.since and ((now or time()) - cur.since) or 0)
end

local function creditZone(cur, now)
  if cur.since and cur.zone then
    cur.zones[cur.zone] = (cur.zones[cur.zone] or 0) + math.max(0, now - cur.zoneAt)
  end
  cur.zoneAt = now
end

local changed = function() ns.Fire("DATA_CHANGED") end

function F.Start()
  if not ns.char then return false end
  local cur = F.Current()
  if cur then
    if not cur.since then F.Resume() end
    return false
  end
  local now = time()
  store().current = { start = now, acc = 0, since = now, money = 0, items = {}, zones = {}, zone = zoneNow(),
    zoneAt = now }
  changed()
  return true
end

-- reason: "you", "afk" or "logout"
function F.Pause(reason)
  local cur = F.Current()
  if not cur or not cur.since then return false end
  local now = time()
  creditZone(cur, now)
  cur.acc = cur.acc + math.max(0, now - cur.since)
  cur.since, cur.paused = nil, reason or "you"
  changed()
  return true
end

function F.Resume()
  local cur = F.Current()
  if not cur or cur.since then return false end
  local now = time()
  cur.since, cur.paused = now, nil
  cur.zone, cur.zoneAt = zoneNow(), now
  changed()
  return true
end

function F.Running()
  local cur = F.Current()
  return cur ~= nil and cur.since ~= nil
end

-- What one looted item is worth to you. → copper each, "shelf" | "AH" | "vendor" | nil (no price)
function F.Value(id)
  local cut = ns.Pricing.Cut()
  local best, how
  local function try(v, label)
    if v and v > 0 and (not best or v > best) then best, how = v, label end
  end
  local min, qty, known = ns.Scanner.Listed(id)
  if known and qty <= (tonumber(ns.settings.shelfMaxListed) or 5) then
    local val = ns.Sales.Money("DBMarket", id) or ns.Sales.Money("DBRegionSaleAvg", id)
    if val then try(math.floor(val * (1 - cut)), "shelf") end
  end
  if min then try(math.floor(min * (1 - cut)), "AH") end
  try(Util.SellPrice(id), "vendor")
  return best or 0, how
end

-- The session's items with their values: → rows { id, n, each, value, how }, item value total
function F.ItemRows(cur)
  local rows, total = {}, 0
  if not cur then return rows, 0 end
  for id, n in pairs(cur.items) do
    local each, how
    if cur.values and cur.values[id] then
      each, how = cur.values[id][1], cur.values[id][2]
    else
      each, how = F.Value(id)
    end
    local o = { spell = id, id = id, n = n, each = each, value = each * n, how = how }
    total = total + o.value
    table.insert(rows, o)
  end
  return rows, total
end

-- The zone the session spent the most time in.
local function mainZone(cur)
  local best, bestT
  for z, t in pairs(cur.zones) do
    if not bestT or t > bestT or (t == bestT and z < best) then best, bestT = z, t end
  end
  return best or cur.zone or "Unknown"
end

-- Totals of a session (running or saved): → { elapsed, money, items, total, gph, zone }
function F.Totals(cur, now)
  local _, items = F.ItemRows(cur)
  local elapsed = cur.elapsed or F.Elapsed(cur, now)
  local total = cur.money + items
  return { elapsed = elapsed, money = cur.money, items = items, total = total,
    gph = elapsed > 0 and total * 3600 / elapsed or nil, zone = cur.saved and cur.zoneName or mainZone(cur) }
end

-- Ends the session: its item values are frozen and it is kept with the last KEEP. → the saved session or nil
function F.Stop()
  local cur = F.Current()
  if not cur then return nil end
  local now = time()
  if cur.since then
    creditZone(cur, now)
    cur.acc = cur.acc + math.max(0, now - cur.since)
    cur.since = nil
  end
  cur.values = {}
  for id in pairs(cur.items) do
    local each, how = F.Value(id)
    cur.values[id] = { each, how }
  end
  local t = F.Totals(cur, now)
  local saved = { start = cur.start, stop = now, elapsed = cur.acc, money = cur.money, items = cur.items,
    values = cur.values, zones = cur.zones, zoneName = t.zone, itemValue = t.items, total = t.total, saved = true }
  local s = store()
  table.insert(s.sessions, 1, saved)
  while #s.sessions > F.KEEP do table.remove(s.sessions) end
  s.current = nil
  changed()
  return saved
end

-- Events ------------------------------------------------------------------------------------------------------------

function F.OnLoot(text)
  local cur = F.Current()
  if not cur or not cur.since then return end
  local id, n = F.ParseLoot(text)
  if not id then return end
  cur.items[id] = (cur.items[id] or 0) + n
  changed()
end

-- A money line that parses counts itself, and its PLAYER_MONEY rise (before or after it) is dropped. One that does
-- not parse (another client language) takes the rise right next to it instead.
local lastMoney, rise, riseAt, unreadAt, parsedAt
function F.OnMoneyLine(text)
  local cur = F.Current()
  if not cur or not cur.since then return end
  local c = F.ParseMoney(text)
  if c then
    cur.money = cur.money + c
    if rise and GetTime() - riseAt <= MONEY_WINDOW then
      rise = nil
    else
      rise, parsedAt = nil, GetTime()
    end
  elseif rise and GetTime() - riseAt <= MONEY_WINDOW then
    cur.money = cur.money + rise
    rise = nil
  else
    unreadAt = GetTime()
  end
  changed()
end

function F.OnPlayerMoney()
  local now = GetMoney and GetMoney() or nil
  if not now then return end
  local delta = lastMoney and now - lastMoney or 0
  lastMoney = now
  local cur = F.Current()
  if delta <= 0 or not cur or not cur.since then return end
  if parsedAt and GetTime() - parsedAt <= MONEY_WINDOW then
    parsedAt = nil
  elseif unreadAt and GetTime() - unreadAt <= MONEY_WINDOW then
    cur.money = cur.money + delta
    unreadAt = nil
    changed()
  else
    rise, riseAt = delta, GetTime()
  end
end

ns.On("CHAT_MSG_LOOT", function(text) F.OnLoot(text) end)
ns.On("CHAT_MSG_MONEY", function(text) F.OnMoneyLine(text) end)
ns.On("PLAYER_MONEY", function() F.OnPlayerMoney() end)
ns.On("ZONE_CHANGED_NEW_AREA", function()
  local cur = F.Current()
  if not cur then return end
  local now = time()
  creditZone(cur, now)
  cur.zone = zoneNow()
end)
ns.On("PLAYER_FLAGS_CHANGED", function(unit)
  if unit ~= "player" then return end
  local ok, afk = ns.Call("UnitIsAFK", "player")
  if not ok then return end
  local cur = F.Current()
  if not cur then return end
  if afk and cur.since then
    F.Pause("afk")
  elseif not afk and cur.paused == "afk" then
    F.Resume()
  end
end)
ns.On("PLAYER_LOGOUT", function()
  if ns.char and F.Running() then F.Pause("logout") end
end)
ns.OnLogin(function()
  lastMoney = GetMoney and GetMoney() or nil
  local cur = F.Current()
  if cur and cur.paused == "logout" then
    F.Resume()
    ns.Print("farm session resumed (" .. ns.UI.TimeText(F.Elapsed(cur), true) .. " so far) - /crafter farm stop to end it")
  end
end)

-- Best farms: every saved session of every character, by zone.
function F.BestRows()
  local by, rows = {}, {}
  for key, char in pairs(ns.db.chars or {}) do
    for _, sess in ipairs(char.farm and char.farm.sessions or {}) do
      local z = sess.zoneName or "Unknown"
      local o = by[z]
      if not o then
        o = { spell = z, zone = z, chars = {}, nChars = 0, sessions = 0, time = 0, gold = 0, money = 0, best = nil }
        by[z] = o
        table.insert(rows, o)
      end
      if not o.chars[key] then
        o.chars[key] = true
        o.nChars = o.nChars + 1
      end
      o.sessions = o.sessions + 1
      o.time = o.time + (sess.elapsed or 0)
      o.gold = o.gold + (sess.total or 0)
      o.money = o.money + (sess.money or 0)
      local g = (sess.elapsed or 0) > 0 and (sess.total or 0) * 3600 / sess.elapsed or nil
      if g and (not o.best or g > o.best) then o.best = g end
    end
  end
  for _, o in ipairs(rows) do o.gph = o.time > 0 and o.gold * 3600 / o.time or nil end
  return rows
end

-- The session the "This session" view shows: the current one, else the last finished one.
function F.Shown()
  local cur = F.Current()
  if cur then return cur, false end
  local s = ns.char and store().sessions[1]
  return s, s ~= nil
end

function F.BestView()
  return ns.settings.farmView == "best"
end

function F.List()
  if F.BestView() then return F.BestRows() end
  local cur = F.Shown()
  return (F.ItemRows(cur))
end

-- Panel (the Farm tab) ----------------------------------------------------------------------------------------------

F.SESSION_COLUMNS = {
  { key = "fitem", label = "Item", width = 260 },
  { key = "fcount", label = "Count", width = 56 },
  { key = "feach", label = "Each", width = 96, hint = "What one is worth to you: the best of the Empty shelves "
    .. "suggestion (rarely listed items) or the realm's AH min, both less the AH cut, or the vendor sell price." },
  { key = "fvalue", label = "Value", width = 96 },
  { key = "fhow", label = "Priced by", width = 110, hint = "shelf = Empty shelves suggestion less the cut; AH = the "
    .. "realm's min less the cut; vendor = the vendor sell price. Running sessions use today's prices; finished "
    .. "ones keep the prices at Stop." },
}
F.BEST_COLUMNS = {
  { key = "fzone", label = "Zone", width = 200, hint = "The zone each session spent the most time in." },
  { key = "fchars", label = "Characters", width = 130 },
  { key = "fsess", label = "Sessions", width = 60 },
  { key = "ftime", label = "Time", width = 76 },
  { key = "fgold", label = "Earned", width = 100, hint = "Looted money plus the items' value at Stop." },
  { key = "fgph", label = "g/h", width = 76, hint = "Earned / time over every session in the zone." },
  { key = "fbest", label = "Best", width = 76, hint = "The best single session's g/h." },
}

function F.Columns()
  return F.BestView() and F.BEST_COLUMNS or F.SESSION_COLUMNS
end

local function charList(o)
  local names = {}
  for key in pairs(o.chars) do table.insert(names, (key:match("^(.-)%-") or key)) end
  table.sort(names)
  return table.concat(names, ", ")
end

function F.SortValue(o, key)
  if key == "fitem" then return Util.ItemName(o.id) end
  if key == "fcount" then return o.n end
  if key == "feach" then return o.each end
  if key == "fvalue" then return o.value end
  if key == "fhow" then return o.how or "" end
  if key == "fzone" then return o.zone end
  if key == "fchars" then return o.nChars end
  if key == "fsess" then return o.sessions end
  if key == "ftime" then return o.time end
  if key == "fgold" then return o.gold end
  if key == "fbest" then return o.best or -math.huge end
  return o.gph or -math.huge
end

function F.CellText(o, key)
  if key == "fitem" then return Util.ItemText(o.id) end
  if key == "fcount" then return tostring(o.n) end
  if key == "feach" then return o.each > 0 and Util.Money(o.each) or "—" end
  if key == "fvalue" then return o.value > 0 and Util.Money(o.value) or "—" end
  if key == "fhow" then return o.how or (GREY .. "no price|r") end
  if key == "fzone" then return o.zone end
  if key == "fchars" then return charList(o) end
  if key == "fsess" then return tostring(o.sessions) end
  if key == "ftime" then return ns.UI.TimeText(o.time, true) end
  if key == "fgold" then return Util.Money(o.gold) end
  if key == "fgph" then return ns.UI.PerHourText(o.gph) end
  if key == "fbest" then return ns.UI.PerHourText(o.best) end
  return ""
end

local HOW_TEXT = { shelf = "the Empty shelves suggestion less the AH cut", AH = "the realm's AH min less the AH cut",
  vendor = "the vendor sell price" }

function F.OptionLines(o, out)
  if o.zone then
    table.insert(out, o.zone)
    table.insert(out, string.format("%d session%s by %s: %s in %s = %s", o.sessions, o.sessions == 1 and "" or "s",
      charList(o), Util.Money(o.gold), ns.UI.TimeText(o.time), ns.UI.PerHourText(o.gph) .. "/h"))
    table.insert(out, "Looted money " .. Util.Money(o.money) .. ", items " .. Util.Money(o.gold - o.money))
    return
  end
  table.insert(out, Util.ItemText(o.id))
  table.insert(out, string.format("%d looted, %s each = %s", o.n, Util.Money(o.each), Util.Money(o.value)))
  table.insert(out, "Priced by " .. (HOW_TEXT[o.how] or "nothing: no AH, shelf or vendor price"))
end

local function sessionLine(cur, last)
  local t = F.Totals(cur)
  local state
  if last then
    state = "last session"
  elseif cur.since then
    state = GREEN .. "running|r"
  else
    state = ORANGE .. "paused" .. (cur.paused == "afk" and " (AFK)" or "") .. "|r"
  end
  return string.format("%s, %s in %s: money %s + items %s = %s, %s", state, ns.UI.TimeText(t.elapsed, true), t.zone,
    Util.Money(t.money), Util.Money(t.items), Util.Money(t.total), ns.UI.PerHourText(t.gph) .. "/h")
end

function F.DetailText(o)
  local out = {}
  if o then
    F.OptionLines(o, out)
    table.insert(out, "")
  end
  local cur, last = F.Shown()
  if cur then
    table.insert(out, "|cffffd100" .. (last and "Last session" or "This session") .. "|r")
    table.insert(out, sessionLine(cur, last))
    local zones = {}
    for z, t in pairs(cur.zones) do table.insert(zones, { z, t }) end
    table.sort(zones, function(a, b) return a[2] > b[2] end)
    for _, z in ipairs(zones) do table.insert(out, "  " .. z[1] .. ": " .. ns.UI.TimeText(z[2], true)) end
    table.insert(out, "")
  end
  table.insert(out, "Start a session, farm, then Stop: the addon counts your loot and looted money and measures your "
    .. "real gold per hour. The clock stops while paused, AFK or logged out. Best farms compares the zones over "
    .. "your last " .. F.KEEP .. " sessions per character.")
  table.insert(out, "")
  table.insert(out, GREY .. "Counted: your own loot lines (not purchases, crafts or quest rewards) and looted money. "
    .. "Items are valued at today's realm prices less the AH cut, or the vendor price.|r")
  return table.concat(out, "\n")
end

function F.StatusText(n)
  if F.BestView() then
    local sessions = 0
    for _, o in ipairs(F.BestRows()) do sessions = sessions + o.sessions end
    return string.format("Best farms: %d zones, %d saved sessions", n, sessions)
  end
  local cur, last = F.Shown()
  if not cur then return "Farm: no session yet - press Start (or /crafter farm start)" end
  return "Farm: " .. sessionLine(cur, last) .. "  |  " .. n .. " items"
end

F.FOOTER = "Value = count x each; priced by shelf / AH (both less the AH cut) or vendor; the clock stops when "
  .. "paused, AFK or logged out"

-- The window's clock: while it shows a running session, refresh once a second.
local ticking = false
function F.Tick()
  if ticking then return end
  ticking = true
  C_Timer.After(1, function()
    ticking = false
    if ns.settings.tab == "farm" and ns.UI.IsShown() and F.Running() and not F.BestView() then
      ns.UI.RefreshStatus()
      F.Tick()
    end
  end)
end

ns.Command("farm", function(arg)
  if arg == "start" then
    if F.Start() then
      ns.Print("farm session started in " .. F.Current().zone)
    else
      ns.Print("a farm session is already running")
    end
  elseif arg == "stop" then
    local s = F.Stop()
    if s then
      ns.Print(string.format("farm session saved: %s in %s, %s = %s", ns.UI.TimeText(s.elapsed, true), s.zoneName,
        Util.Money(s.total), ns.UI.PerHourText(s.elapsed > 0 and s.total * 3600 / s.elapsed or nil) .. "/h"))
    else
      ns.Print("no farm session running")
    end
  elseif arg == "pause" then
    if not F.Pause("you") and not F.Resume() then ns.Print("no farm session running") end
  else
    ns.UI.Show()
    ns.UI.SetMode("farm")
  end
end)
