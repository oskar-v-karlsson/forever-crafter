-- Core/Util.lua: money text, item names and prices from the client with the generated data as fallback.
local _, ns = ...
local Util = {}
ns.Util = Util

-- 12345 → "1g 23s 45c" with coloured units; negative values get a minus sign.
function Util.Money(copper)
  if copper == nil then return "?" end
  local neg = copper < 0
  copper = math.floor(math.abs(copper) + 0.5)
  local g, s, c = math.floor(copper / 10000), math.floor(copper / 100) % 100, copper % 100
  local parts = {}
  if g > 0 then table.insert(parts, g .. "|cffffd700g|r") end
  if s > 0 or (g > 0 and c > 0) then table.insert(parts, s .. "|cffc7c7cfs|r") end
  if c > 0 or #parts == 0 then table.insert(parts, c .. "|cffeda55fc|r") end
  return (neg and "-" or "") .. table.concat(parts, " ")
end

-- "1.5" / "1g 50s" / "150s" / "20c" → copper, nil when it does not parse.
function Util.ParseMoney(text)
  text = (text or ""):lower():gsub("%s+", "")
  if text == "" then return 0 end
  local plain = tonumber(text)
  if plain then return math.floor(plain * 10000 + 0.5) end
  local total, matched = 0, false
  for n, unit in text:gmatch("([%d%.]+)([gsc])") do
    local v = tonumber(n)
    if not v then return nil end
    total = total + v * (unit == "g" and 10000 or unit == "s" and 100 or 1)
    matched = true
  end
  if not matched then return nil end
  return math.floor(total + 0.5)
end

-- C_TradeSkillUI.GetRecipeSourceText output ("Vendor: X|nZone: Y", with colour and money icon codes) on one line.
function Util.SourceText(text)
  text = tostring(text or ""):gsub("|n", "; "):gsub("^[;%s]+", ""):gsub("[;%s]+$", "")
  return text
end

local QUALITY_COLORS = {
  [0] = "ff9d9d9d", [1] = "ffffffff", [2] = "ff1eff00", [3] = "ff0070dd", [4] = "ffa335ee", [5] = "ffff8000",
}

-- Client item info (name, quality, sell price), cached once loaded.
local info = {}
local function clientInfo(id)
  local c = info[id]
  if c then return c end
  local get = ns.API("C_Item.GetItemInfo") or ns.API("GetItemInfo")
  if get then
    local ok, name, _, quality, _, _, _, _, stack, _, _, sell = pcall(get, id)
    if ok and name then
      c = { name = name, q = quality, sell = sell, stack = stack }
      info[id] = c
      return c
    end
  end
  ns.Call("C_Item.RequestLoadItemDataByID", id)
  return nil
end
Util.ClientInfo = clientInfo

function Util.ItemName(id)
  local c = clientInfo(id)
  if c and c.name then return c.name end
  local d = ns.Items[id]
  if d and d.name and d.name ~= "" then return d.name end
  return "item:" .. tostring(id)
end

function Util.ItemText(id)
  local c = clientInfo(id)
  local d = ns.Items[id]
  local q = (c and c.q) or (d and d.q) or 1
  return "|c" .. (QUALITY_COLORS[q] or QUALITY_COLORS[1]) .. Util.ItemName(id) .. "|r"
end

-- Vendor sell price for one item: the client's value when loaded, else DB2 ItemSparse.SellPrice, which the
-- Wowhead Forever tooltips contradict for some items (research/crosscheck_*.txt). Items without an ItemSparse row
-- carry the price from their Wowhead Forever page or tooltip. → copper, "client"|"db2"|"wowhead" or nil
function Util.SellPrice(id)
  local c = clientInfo(id)
  if c and c.sell then return c.sell, "client" end
  local d = ns.Items[id]
  if d and d.sell then return d.sell, d.missing and "wowhead" or "db2" end
  return nil
end

function Util.IsBoP(id)
  local d = ns.Items[id]
  return d and d.bop or false
end

function Util.Round(x, step)
  step = step or 1
  return math.floor(x / step + 0.5) * step
end

function Util.Age(t)
  if not t then return "never" end
  local s = (time() - t)
  if s < 90 then return s .. " s ago" end
  if s < 5400 then return math.floor(s / 60) .. " min ago" end
  if s < 172800 then return math.floor(s / 3600) .. " h ago" end
  return math.floor(s / 86400) .. " days ago"
end

-- Profession name for a skill line (child lines map to their parent).
function Util.ParentLine(line)
  local d = ns.SkillLines[line]
  if d and d.parent and d.parent ~= 0 then return d.parent end
  return line
end

function Util.LineName(line)
  local d = ns.SkillLines[Util.ParentLine(line)]
  return d and d.name or ("skill " .. tostring(line))
end

-- Wowhead Forever source codes (WH.Wow.getSourceName on wowhead.com/forever, 2026-11-12).
Util.SOURCE_NAMES = {
  [1] = "Crafted", [2] = "Drop", [3] = "PvP", [4] = "Quest", [5] = "Vendor", [6] = "Trainer", [7] = "Discovery",
  [10] = "Starter", [14] = "Black Market", [15] = "Disenchanted", [16] = "Fished", [17] = "Gathered",
  [19] = "Mined", [21] = "Pickpocketed", [23] = "Skinned",
  [101] = "Container (object)", [102] = "Container (item)",
}

local FROM_ROLE = { vendor = "Sold by", drop = "Dropped by", npc = "NPC", quest = "Quest", object = "Object",
  item = "Item", zone = "Zone" }

-- Where Wowhead Forever says a recipe item comes from (Data/Items.lua from). → text or nil
function Util.FromText(id)
  local d = ns.Items[id]
  if not d or not d.from then return nil end
  local out = {}
  for _, f in ipairs(d.from) do
    local role, name, zone = f[1], f[2], f[3]
    if role == "zone" then
      table.insert(out, "Zone: " .. zone)
    else
      table.insert(out, (FROM_ROLE[role] or role) .. ": " .. name .. (zone ~= "" and (" (" .. zone .. ")") or ""))
    end
  end
  return table.concat(out, ", ")
end

-- The first NPC Wowhead Forever lists as selling an item (Data/Vendor.lua npcs). → " (name, zone +N)" or ""
function Util.VendorNPC(id)
  local v = ns.Vendor[id]
  if not v or not v.npcs or not v.npcs[1] then return "" end
  local n = v.npcs[1]
  local more = (v.nNpc or 1) > 1 and string.format(" +%d", v.nNpc - 1) or ""
  return " (" .. n[1] .. (n[2] ~= "" and (", " .. n[2]) or "") .. more .. ")"
end

function Util.Sources(list)
  if not list or #list == 0 then return "source unknown" end
  local out = {}
  for _, c in ipairs(list) do table.insert(out, Util.SOURCE_NAMES[c] or ("source " .. c)) end
  return table.concat(out, ", ")
end
