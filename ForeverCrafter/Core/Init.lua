-- Core/Init.lua: namespace, safe event bus, saved variables and the /crafter command.
local ADDON, ns = ...
ns.ADDON = ADDON
ns.VERSION = "0.1.0"
do
  local getMeta = C_AddOns and C_AddOns.GetAddOnMetadata
  if getMeta then
    local ok, v = pcall(getMeta, ADDON, "Version")
    if ok and type(v) == "string" and v ~= "" then ns.VERSION = v end
  end
end

ns.missingEvents = {}
ns.errors = {}   -- real failures (a handler or API call raised an error)
ns.log = {}      -- debug log

function ns.Print(msg)
  if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff33ccffForeverCrafter|r: " .. tostring(msg)) end
end

local function keep(list, msg)
  table.insert(list, date("%H:%M:%S") .. " " .. tostring(msg))
  if #list > 50 then table.remove(list, 1) end
end

function ns.Debug(msg)
  keep(ns.log, msg)
  if ForeverCrafterDB and ForeverCrafterDB.settings and ForeverCrafterDB.settings.debug then ns.Print(msg) end
end

function ns.Error(msg)
  keep(ns.errors, msg)
  ns.Debug("error: " .. tostring(msg))
end

-- Resolve a global or dotted API name at runtime ("C_AuctionHouse.ReplicateItems"). → function or nil
function ns.API(path)
  local obj = _G
  for part in string.gmatch(path, "[^%.]+") do
    if type(obj) ~= "table" then return nil end
    obj = obj[part]
  end
  if type(obj) == "function" then return obj end
  return nil
end

-- pcall an API by name. → ok, results...
function ns.Call(path, ...)
  local fn = ns.API(path)
  if not fn then return false, "missing " .. path end
  return pcall(fn, ...)
end

-- Event bus. RegisterEvent throws on events the client does not know, so every registration is protected.
local eventFrame = CreateFrame("Frame")
local handlers = {}
function ns.On(event, fn)
  if not handlers[event] then
    handlers[event] = {}
    local ok, err = pcall(eventFrame.RegisterEvent, eventFrame, event)
    if not ok then
      ns.missingEvents[event] = tostring(err)
      ns.Debug("cannot register " .. event .. ": " .. tostring(err))
    end
  end
  table.insert(handlers[event], fn)
end
eventFrame:SetScript("OnEvent", function(_, event, ...)
  local list = handlers[event]
  if not list then return end
  for _, fn in ipairs(list) do
    local ok, err = pcall(fn, ...)
    if not ok then ns.Error(event .. ": " .. tostring(err)) end
  end
end)

-- Internal messages between modules ("SCAN_DONE", "DATA_CHANGED", ...).
local listeners = {}
function ns.Listen(msg, fn)
  listeners[msg] = listeners[msg] or {}
  table.insert(listeners[msg], fn)
end
function ns.Fire(msg, ...)
  for _, fn in ipairs(listeners[msg] or {}) do
    local ok, err = pcall(fn, ...)
    if not ok then ns.Error(msg .. ": " .. tostring(err)) end
  end
end

-- Saved variables.
local DEFAULTS = {
  settings = {
    minimap = true,
    minimapAngle = 225,
    debug = false,
    -- cut = AH cut as a fraction set with /crafter cut (overrides the one read from sale invoices)
    showKnown = true,
    showLearnable = true,
    profession = 0,        -- skill line ID, 0 = all
    minProfit = 0,         -- copper
    minListings = 1,       -- the result must have at least this many AH listings to count as AH-sellable
    sort = "profit",
    sortDesc = true,
  },
  realms = {},      -- realm key → { time, items = { [itemID] = { min, qty, n, ladder = {{unit, qty}, ...} } } }
  vendorSeen = {},  -- itemID → { unit, stack, limited, time, npc } from MERCHANT_SHOW (authoritative)
  deposit = {},     -- itemID → deposit for one item, 12 h (C_AuctionHouse.CalculateCommodityDeposit)
  -- cutSeen = { pct, n, time } from sale invoices (GetInboxInvoiceInfo)
  chars = {},       -- "Name-Realm" → per-character state
}
local CHAR_DEFAULTS = {
  skills = {},      -- skill line → { rank, max, time }
  known = {},       -- recipe spell ID → true (trade-skill window or NEW_RECIPE_LEARNED)
  listed = {},      -- skill line → { time, complete, ids = { [spellID] = true } } from the trade-skill window
  schematics = {},  -- spell ID → { skill, name, out = {id, min, max}, reagents = {{id, n}} } from GetRecipeSchematic
  difficulty = {},  -- spell ID → TradeskillRelativeDifficulty (0 optimal .. 3 trivial)
}

local function fill(dst, src)
  for k, v in pairs(src) do
    if dst[k] == nil then
      if type(v) == "table" then
        dst[k] = {}
        fill(dst[k], v)
      else
        dst[k] = v
      end
    elseif type(v) == "table" and type(dst[k]) == "table" then
      fill(dst[k], v)
    end
  end
end

function ns.CharKey()
  local name = UnitName and UnitName("player") or "?"
  local realm = GetRealmName and GetRealmName() or "?"
  return tostring(name) .. "-" .. tostring(realm)
end

-- Auction prices are kept per realm and faction (the AH a character sees).
function ns.RealmKey()
  local realm = GetRealmName and GetRealmName() or "?"
  local faction = UnitFactionGroup and UnitFactionGroup("player") or "?"
  return tostring(realm) .. "-" .. tostring(faction)
end

ns.On("ADDON_LOADED", function(name)
  if name ~= ADDON then return end
  ForeverCrafterDB = ForeverCrafterDB or {}
  fill(ForeverCrafterDB, DEFAULTS)
  ns.db = ForeverCrafterDB
  ns.settings = ns.db.settings
end)

ns.loginCallbacks = {}
function ns.OnLogin(fn)
  table.insert(ns.loginCallbacks, fn)
end

ns.On("PLAYER_LOGIN", function()
  local key = ns.CharKey()
  ns.db.chars[key] = ns.db.chars[key] or {}
  fill(ns.db.chars[key], CHAR_DEFAULTS)
  ns.char = ns.db.chars[key]
  ns.ready = true
  for _, fn in ipairs(ns.loginCallbacks) do
    local ok, err = pcall(fn)
    if not ok then ns.Error("login: " .. tostring(err)) end
  end
end)

-- /crafter
local commands = {}
function ns.Command(name, fn)
  commands[name] = fn
end

local function help()
  ns.Print("/crafter              - results window")
  ns.Print("/crafter scan         - full AH snapshot (AH window open)")
  ns.Print("/crafter cut <pct>    - set the AH cut in percent (blank: back to the measured/assumed one)")
  ns.Print("/crafter minimap      - show or hide the minimap button")
  ns.Print("/crafter status       - professions, snapshot age, AH cut")
  ns.Print("/crafter reset        - forget prices, merchant data and this character's recipe data")
  ns.Print("/crafter debug        - toggle debug output")
end

SLASH_FOREVERCRAFTER1 = "/crafter"
SLASH_FOREVERCRAFTER2 = "/forevercrafter"
SlashCmdList.FOREVERCRAFTER = function(msg)
  msg = (msg or ""):match("^%s*(.-)%s*$")
  local cmd, rest = msg:match("^(%S*)%s*(.-)$")
  cmd = (cmd or ""):lower()
  if not ns.ready then return end
  local fn = commands[cmd == "" and "show" or cmd]
  if fn then
    local ok, err = pcall(fn, rest)
    if not ok then
      ns.Error("/crafter " .. cmd .. ": " .. tostring(err))
      ns.Print("error: " .. tostring(err))
    end
  else
    help()
  end
end
ns.Command("help", help)
ns.Command("debug", function()
  ns.settings.debug = not ns.settings.debug
  ns.Print("debug " .. (ns.settings.debug and "on" or "off"))
  for event in pairs(ns.missingEvents) do ns.Print("event not in this client: " .. event) end
  for _, e in ipairs(ns.errors) do ns.Print(e) end
end)
ns.Command("reset", function()
  ns.db.realms = {}
  ns.db.vendorSeen = {}
  ns.db.deposit = {}
  ns.db.cutSeen = nil
  ns.db.chars[ns.CharKey()] = {}
  fill(ns.db.chars[ns.CharKey()], CHAR_DEFAULTS)
  ns.char = ns.db.chars[ns.CharKey()]
  ns.Print("prices, merchant data and this character's recipe data cleared")
  ns.Fire("RESET")
  ns.Fire("DATA_CHANGED")
end)
