-- tools/wow_stub.lua: a small fake of the WoW: Forever client API, enough to load ForeverCrafter and drive it
-- offline (tools/check.py): skills, the trade-skill window, the AH replicate snapshot, merchants, mail invoices
-- and the frames of the results window. It is not a model of real client behaviour (see "Verify in game").

STUB = {
  shown = {},       -- every text passed to SetText
  prints = {},
  timers = {},
  frames = {},
  now = 1800000000, -- time()
  meta = {},        -- ForeverCrafter's TOC metadata (C_AddOns.GetAddOnMetadata)
  skills = {},      -- skill line → { rank, max } (C_SkillInfo.GetSkillLineInfoByID)
  known = {},       -- spell ID → true (C_SpellBook.IsSpellKnown)
  -- trade-skill window: { line, rank, max, recipes = { [spell] = { learned, difficulty, schematic, source } },
  --   showUnlearned = bool }; nil = closed
  ts = nil,
  auctions = {},    -- { {itemID, stack, buyout}, ... } (C_AuctionHouse replicate list)
  replicateCalls = 0,
  deposits = {},    -- itemID → deposit
  merchant = nil,   -- { npc, items = { {id, price, stack, available}, ... } }
  invoices = {},    -- { {kind, bid, consignment}, ... }
  items = {},       -- itemID → { name, quality, sell } (C_Item.GetItemInfo; nil = not cached)
  badEvents = {},   -- event → true: RegisterEvent throws, like the client does for unknown events
  faction = "Alliance",
}

-- Frames ------------------------------------------------------------------------------------------
local Obj = {}
local methods = {}
Obj.__index = function(_, k)
  local m = methods[k]
  if m then return m end
  -- Unknown CamelCase names are client methods: accept and ignore. Lower-case names are addon fields: nil.
  if type(k) == "string" and k:match("^[A-Z]") then return function() end end
  return nil
end

local function new(kind, name, parent)
  local o = setmetatable({
    __kind = kind, __name = name, __parent = parent, __scripts = {}, __events = {}, __shown = true,
    __text = "", __w = 100, __h = 20, __checked = false, __enabled = true,
  }, Obj)
  table.insert(STUB.frames, o)
  return o
end
STUB.new = new

function methods:SetScript(n, f) self.__scripts[n] = f end
function methods:GetScript(n) return self.__scripts[n] end
function methods:HookScript(n, f)
  local old = self.__scripts[n]
  self.__scripts[n] = function(...) if old then old(...) end f(...) end
end
function methods:RegisterEvent(e)
  if STUB.badEvents[e] then error("Attempt to register unknown event \"" .. e .. "\"") end
  self.__events[e] = true
end
function methods:UnregisterEvent(e) self.__events[e] = nil end
function methods:Show() self.__shown = true; if self.__scripts.OnShow then self.__scripts.OnShow(self) end end
function methods:Hide() self.__shown = false; if self.__scripts.OnHide then self.__scripts.OnHide(self) end end
function methods:SetShown(v) if v then self:Show() else self:Hide() end end
function methods:IsShown() return self.__shown end
function methods:IsVisible() return self.__shown end
function methods:SetText(t)
  self.__text = t
  if t ~= nil then table.insert(STUB.shown, tostring(t)) end
end
function methods:GetText() return self.__text end
function methods:SetWidth(w) self.__w = w end
function methods:SetHeight(h) self.__h = h end
function methods:SetSize(w, h) self.__w, self.__h = w, h end
function methods:GetWidth() return self.__w end
function methods:GetHeight() return self.__h end
function methods:SetPoint(...) self.__points = { ... } end
function methods:GetStringHeight()
  local _, n = tostring(self.__text or ""):gsub("\n", "")
  return (n + 1) * 14
end
function methods:CreateFontString(name) return new("FontString", name, self) end
function methods:CreateTexture(name) return new("Texture", name, self) end
function methods:GetName() return self.__name end
function methods:GetParent() return self.__parent end
function methods:GetCenter() return 50, 50 end
function methods:GetEffectiveScale() return 1 end
function methods:SetScrollChild(c) self.__child = c end
function methods:IsEnabled() return self.__enabled end
function methods:SetEnabled(v) self.__enabled = not not v end
function methods:GetChecked() return self.__checked end
function methods:SetChecked(v) self.__checked = not not v end
function methods:SetTexture(t) self.__texture = t end
function methods:Click(button)
  local f = self.__scripts.OnClick
  if f then f(self, button or "LeftButton", false) end
end

function CreateFrame(kind, name, parent, template)
  local o = new(kind, name, parent)
  o.__template = template
  if name then _G[name] = o end
  return o
end

UIParent = new("Frame", "UIParent")
Minimap = new("Frame", "Minimap")
GameTooltip = new("GameTooltip", "GameTooltip")
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) table.insert(STUB.prints, tostring(m)) end }
SlashCmdList = {}
UISpecialFrames = {}

function STUB.fire(event, ...)
  for _, f in ipairs(STUB.frames) do
    if f.__events[event] and f.__scripts.OnEvent then f.__scripts.OnEvent(f, event, ...) end
  end
end

-- Lua helpers the client adds ---------------------------------------------------------------------
date = os.date
STUB.clock = 0   -- seconds the fake client has run; C_Timer delays advance it
time = function() return STUB.now + math.floor(STUB.clock) end
GetTime = os.clock
tinsert, tremove = table.insert, table.remove

-- Timers run when the harness calls STUB.runTimers(horizon): every timer due within `horizon` seconds (default
-- 10), earliest first, moving the clock forward. A longer delay (e.g. the scanner's 60 s timeout) stays pending.
C_Timer = {}
function C_Timer.After(delay, fn)
  table.insert(STUB.timers, { due = STUB.clock + (delay or 0), fn = fn })
end
function STUB.runTimers(horizon)
  local limit = STUB.clock + (horizon or 10)
  for _ = 1, 200000 do
    local best
    for i, t in ipairs(STUB.timers) do
      if t.due <= limit and (not best or t.due < STUB.timers[best].due) then best = i end
    end
    if not best then
      STUB.clock = limit
      return
    end
    local t = table.remove(STUB.timers, best)
    if t.due > STUB.clock then STUB.clock = t.due end
    t.fn()
  end
  error("timers did not settle")
end

-- Player ------------------------------------------------------------------------------------------
function UnitName(unit)
  if unit == "npc" then return STUB.merchant and STUB.merchant.npc or nil end
  return "Hana"
end
function GetRealmName() return "Test" end
function UnitFactionGroup() return STUB.faction end
function GetCursorPosition() return 0, 0 end
function GetBuildInfo() return "1.60.1", "70888", "Nov 4 2026", 16001 end

C_AddOns = {}
function C_AddOns.GetAddOnMetadata(_, field) return STUB.meta[field] end

C_SpellBook = {}
function C_SpellBook.IsSpellKnown(id) return STUB.known[id] == true end

C_SkillInfo = {}
function C_SkillInfo.GetSkillLineInfoByID(id)
  local s = STUB.skills[id]
  if not s then return nil end
  return { skillID = id, name = "skill " .. id, isHeader = false, rank = s.rank, maxRank = s.max }
end

-- Trade-skill window ------------------------------------------------------------------------------
C_TradeSkillUI = {}
local function tsList()
  local ts, ids = STUB.ts, {}
  if not ts then return ids end
  for id, r in pairs(ts.recipes) do
    if r.learned or ts.showUnlearned then table.insert(ids, id) end
  end
  table.sort(ids)
  return ids
end
function C_TradeSkillUI.GetAllRecipeIDs() return tsList() end
function C_TradeSkillUI.GetFilteredRecipeIDs() return tsList() end
function C_TradeSkillUI.GetRecipeInfo(id)
  local r = STUB.ts and STUB.ts.recipes[id]
  if not r then return nil end
  return { recipeID = id, learned = r.learned, relativeDifficulty = r.difficulty }
end
function C_TradeSkillUI.GetRecipeSchematic(id)
  local r = STUB.ts and STUB.ts.recipes[id]
  local s = r and r.schematic
  if not s then return nil end
  local slots = {}
  for _, rg in ipairs(s.reagents) do
    table.insert(slots, { reagents = { { itemID = rg[1] } }, quantityRequired = rg[2], reagentType = 1,
      required = true })
  end
  return { recipeID = id, name = s.name, outputItemID = s.out[1], quantityMin = s.out[2], quantityMax = s.out[3],
    reagentSlotSchematics = slots }
end
function C_TradeSkillUI.GetRecipeSourceText(id)
  local r = STUB.ts and STUB.ts.recipes[id]
  return r and r.source or nil
end
function C_TradeSkillUI.GetShowUnlearned() return STUB.ts and STUB.ts.showUnlearned or false end
function C_TradeSkillUI.SetShowUnlearned(v)
  STUB.ts.showUnlearned = v
  STUB.fire("TRADE_SKILL_LIST_UPDATE")
end
function C_TradeSkillUI.GetBaseProfessionInfo()
  local ts = STUB.ts
  if not ts then return nil end
  return { professionID = ts.line, skillLevel = ts.rank, maxSkillLevel = ts.max, parentProfessionID = nil }
end
function C_TradeSkillUI.IsTradeSkillLinked() return false end
function C_TradeSkillUI.IsNPCCrafting() return false end

-- Auction house -----------------------------------------------------------------------------------
C_AuctionHouse = {}
function C_AuctionHouse.ReplicateItems() STUB.replicateCalls = STUB.replicateCalls + 1 end
function C_AuctionHouse.GetNumReplicateItems() return #STUB.auctions end
-- 0-based like the Retail client (assumption); the addon reads 0..n and skips empty slots.
function C_AuctionHouse.GetReplicateItemInfo(index)
  local a = STUB.auctions[index + 1]
  if not a then return nil end
  return "item " .. a[1], 134400, a[2], 1, true, 1, "", 0, 0, a[3], 0, nil, nil, "Seller", "Seller-Test", 0, a[1], true
end
function C_AuctionHouse.GetReplicateItemLink(index)
  local a = STUB.auctions[index + 1]
  return a and ("|Hitem:" .. a[1] .. "::::|h[x]|h") or nil
end
function C_AuctionHouse.CalculateCommodityDeposit(id) return STUB.deposits[id] end

-- Merchant and mail -------------------------------------------------------------------------------
function GetMerchantNumItems() return STUB.merchant and #STUB.merchant.items or 0 end
function GetMerchantItemID(i) local m = STUB.merchant.items[i]; return m and m[1] end
function GetMerchantItemInfo(i)
  local m = STUB.merchant.items[i]
  if not m then return nil end
  return "item " .. m[1], 134400, m[2], m[3], m[4] or -1, true, true, false, nil
end
function GetInboxNumItems() return #STUB.invoices end
function GetInboxInvoiceInfo(i)
  local v = STUB.invoices[i]
  if not v then return nil end
  return v[1], "Item", "Buyer", v[2], v[2], 0, v[3], 0, 0, 0, 1
end

-- Items -------------------------------------------------------------------------------------------
C_Item = {}
function C_Item.GetItemInfo(id)
  local d = STUB.items[id]
  if not d then return nil end
  return d.name, "|Hitem:" .. id .. "|h", d.quality or 1, 1, 1, "Trade Goods", "", 20, "", 134400, d.sell or 0, 7, 5, 0
end
function C_Item.RequestLoadItemDataByID() end

-- SavedVariables ----------------------------------------------------------------------------------
-- The text the client writes for a saved global at logout: `name = { ["key"] = value, [1] = value, ... }`.
local function ser(v, indent)
  if type(v) == "string" then return string.format("%q", v) end
  if type(v) ~= "table" then return tostring(v) end
  local keys = {}
  for k in pairs(v) do table.insert(keys, k) end
  table.sort(keys, function(a, b)
    if type(a) == type(b) then return a < b end
    return type(a) == "number"
  end)
  local out = { "{" }
  for _, k in ipairs(keys) do
    local key = type(k) == "string" and string.format("[%q]", k) or "[" .. tostring(k) .. "]"
    table.insert(out, indent .. "\t" .. key .. " = " .. ser(v[k], indent .. "\t") .. ",")
  end
  table.insert(out, indent .. "}")
  return table.concat(out, "\n")
end
function STUB.savedVariables(name)
  return "\n" .. name .. " = " .. ser(_G[name], "") .. "\n"
end
