-- Modules/Cooldowns.lua: profession cooldowns (Mooncloth, the Alchemy transmutes, ...) for every character.
-- The cooldown lengths come from the data (Data/Recipes.lua cd / cdCat, from the Forever DB2 SpellCooldowns and
-- SpellCategories). When each character is ready again is read in game: at the profession window
-- (C_TradeSkillUI.GetRecipeCooldown, else C_Spell.GetSpellCooldown) and right after a craft (UNIT_SPELLCAST_SUCCEEDED).
-- It is stored per character as an absolute time() so it survives a relog: ns.char.cooldowns[spell] = ready time
-- (0 = ready when read).
local _, ns = ...
local C = {}
ns.Cooldowns = C
local Util, PL = ns.Util, ns.Planner

local GREY, GREEN, ORANGE, BLUE = "|cff808080", "|cff40ff40", "|cffff8040", "|cff66ccff"
local GCD = 1.5   -- a spell cooldown this short is the global cooldown, not the recipe's

-- Recipes with a cooldown in the data, by spell ID.
function C.Spells()
  local out = {}
  for spell, r in pairs(ns.Recipes) do
    if PL.Cooldown(r) then table.insert(out, spell) end
  end
  table.sort(out)
  return out
end

-- Seconds until a known recipe is ready (0 = ready), read from the client; nil when no API answers.
local function remaining(spell)
  if ns.API("C_TradeSkillUI.GetRecipeCooldown") then
    local ok, cd = ns.Call("C_TradeSkillUI.GetRecipeCooldown", spell)
    if ok then
      if cd == nil then return 0 end
      if type(cd) == "number" then return cd > 0 and cd or 0 end
    end
  end
  local function fromStart(start, duration)
    if type(start) ~= "number" or type(duration) ~= "number" then return nil end
    if duration <= GCD or start <= 0 then return 0 end
    return math.max(0, start + duration - GetTime())
  end
  if ns.API("C_Spell.GetSpellCooldown") then
    local ok, info = ns.Call("C_Spell.GetSpellCooldown", spell)
    if ok and type(info) == "table" then
      local left = fromStart(info.startTime, info.duration)
      if left then return left end
    end
  end
  if ns.API("GetSpellCooldown") then
    local ok, start, duration = ns.Call("GetSpellCooldown", spell)
    if ok then return fromStart(start, duration) end
  end
  return nil
end

local function store()
  ns.char.cooldowns = ns.char.cooldowns or {}
  return ns.char.cooldowns
end

-- Reads the ready time of this character's known cooldown recipes (the profession window is open). → recipes read
function C.Read()
  if not ns.char then return 0 end
  local n, tried = 0, 0
  for _, spell in ipairs(C.Spells()) do
    if ns.char.known[spell] then
      tried = tried + 1
      -- A cooldown may be a secret value while cooldowns are restricted: a failed read keeps the stored time.
      local ok, left = pcall(remaining, spell)
      if ok and left then
        n = n + 1
        store()[spell] = left > 0 and math.floor(time() + left + 0.5) or 0
      end
    end
  end
  if tried > 0 and n == 0 then ns.Error("cooldowns: no recipe cooldown could be read") end
  return n
end

-- After a craft: the recipe, and every recipe of its shared category (the transmutes), wait the cooldown.
function C.Started(spell)
  local r = ns.Recipes[spell]
  local cd = PL.Cooldown(r)
  if not ns.char or not cd then return false end
  local ready = time() + cd
  local cds = store()
  for _, other in ipairs(C.Spells()) do
    local o = ns.Recipes[other]
    if other == spell or (r.cdCat and o.cdCat == r.cdCat) then
      cds[other] = math.max(cds[other] or 0, ready)
    end
  end
  ns.Fire("DATA_CHANGED")
  return true
end

ns.On("UNIT_SPELLCAST_SUCCEEDED", function(unit, _, spell)
  if unit == "player" and type(spell) == "number" then C.Started(spell) end
end)

-- Rows --------------------------------------------------------------------------------------------------------------

local function charName(key)
  local name, realm = key:match("^(.-)%-(.+)$")
  if not name then return key end
  local here = GetRealmName and GetRealmName() or realm
  return realm == here and name or key
end

local function charKnows(key, char, spell, line)
  if ns.char == char then return ns.Professions.IsKnown(spell, line) end
  return char.known and char.known[spell] == true
end

-- One row per character and cooldown recipe of a profession the character has. state: "ready", "wait" (ready at
-- .ready), "unread" (open the profession window), "learn" (the skill allows it), "skill" (needs .need, has .rank).
-- Recipes nobody can learn (learn 9999) are left out. → rows, { ready (C.Ready), known, chars }
function C.Rows(now)
  now = now or time()
  local rows, results, info = {}, {}, { ready = 0, known = 0, chars = 0 }
  local spells = C.Spells()
  local keys = {}
  for key in pairs(ns.db.chars or {}) do table.insert(keys, key) end
  table.sort(keys)
  for _, key in ipairs(keys) do
    local char = ns.db.chars[key]
    local any = false
    for _, spell in ipairs(spells) do
      local r = ns.Recipes[spell]
      local line = Util.ParentLine(r.skill)
      local skill = char.skills and char.skills[line]
      if skill then
        local known = charKnows(key, char, spell, line)
        if known or (r.learn or 9999) < 9999 then
          any = true
          if results[spell] == nil then results[spell] = PL.CooldownResult(spell) or false end
          local o = { key = key .. ":" .. spell, char = key, charName = charName(key), recipe = spell, r = r,
            line = line, rank = skill.rank, need = r.learn, known = known, res = results[spell] or nil }
          o.spell = o.key
          if known then
            info.known = info.known + 1
            local t = char.cooldowns and char.cooldowns[spell]
            if t == nil then
              o.state = "unread"
            elseif t <= now then
              o.state = "ready"
            else
              o.state, o.ready = "wait", t
            end
          elseif skill.rank < (r.learn or 0) then
            o.state = "skill"
          elseif ns.char ~= char and not (char.listed and char.listed[line]) then
            o.state = "unread"   -- another character that may know it: its window was never read
          else
            o.state = "learn"
          end
          table.insert(rows, o)
        end
      end
    end
    if any then info.chars = info.chars + 1 end
  end
  info.ready = C.Ready(rows)
  C.info = info
  return rows, info
end

function C.List()
  return (C.Rows())
end

-- What is ready now, a shared category counted once per character. → n, best row (most profit) or nil
function C.Ready(rows)
  local seen, n, best = {}, 0, nil
  for _, o in ipairs(rows) do
    if o.state == "ready" then
      local g = o.char .. ":" .. (o.r.cdCat and ("c" .. o.r.cdCat) or ("s" .. o.recipe))
      local p = o.res and o.res.profit
      if not seen[g] then
        seen[g] = true
        n = n + 1
      end
      if p and (not best or p > best.res.profit) then best = o end
    end
  end
  return n, best
end

-- "3 cooldowns ready (best: Mooncloth 36g on Hana)" or nil
function C.LoginText()
  local n, best = C.Ready((C.Rows()))
  if n == 0 then return nil end
  local s = string.format("%d cooldown%s ready", n, n == 1 and "" or "s")
  if best and best.res.profit > 0 then
    s = s .. string.format(" (best: %s %s on %s)", best.r.name, Util.Money(best.res.profit), best.charName)
  end
  return s
end

ns.OnLogin(function()
  if ns.settings.cdLogin == false then return end
  -- After the login chat; the prices and item names are there by then.
  C_Timer.After(8, function()
    local ok, text = pcall(C.LoginText)
    if not ok then
      ns.Error("cooldowns: " .. tostring(text))
    elseif text then
      ns.Print(text .. " - /crafter cd")
    end
  end)
end)

-- Panel (the Cooldowns tab) -----------------------------------------------------------------------------------------

C.COLUMNS = {
  { key = "cchar", label = "Character", width = 120 },
  { key = "crecipe", label = "Recipe", width = 200 },
  { key = "cprofit", label = "Profit", width = 90, hint = "Profit of one craft at today's AH prices, every reagent "
    .. "bought (AH or vendor). ~ = estimate; - = a reagent or the output has no price." },
  { key = "csell", label = "Sell", width = 46 },
  { key = "ccd", label = "Cooldown", width = 70, hint = "How long the recipe waits after a craft (Forever DB2). "
    .. "Shared: every Alchemy transmute waits for the one you made." },
  { key = "cready", label = "Ready", width = 250, hint = "When this character can craft it again: read at the "
    .. "profession window and after each craft, kept across logins. Not learned: the skill it needs." },
}

local function readyText(o, now)
  if o.state == "ready" then return GREEN .. "Ready|r" end
  if o.state == "wait" then return "in " .. ns.UI.TimeText(o.ready - now, true) end
  if o.state == "unread" then return GREY .. "open the profession window|r" end
  local need = Util.LineName(o.line) .. " " .. tostring(o.need)
  if o.state == "learn" then return BLUE .. "learn now|r (" .. need .. ")" end
  return ORANGE .. "learn at " .. need .. "|r (you " .. o.rank .. ")"
end

local STATE_ORDER = { ready = 0, wait = 1, unread = 2, learn = 3, skill = 4 }

function C.SortValue(o, key)
  if key == "cchar" then return o.charName end
  if key == "crecipe" then return o.r.name or "" end
  if key == "cprofit" then return o.res and o.res.profit or -math.huge end
  if key == "csell" then return o.res and o.res.where or "" end
  if key == "ccd" then return o.r.cd end
  -- Ready: ready first, then the soonest, then the window to open, then what to learn (closest skill first).
  local s = STATE_ORDER[o.state] * 1e9
  if o.state == "wait" then return s + o.ready - time() end
  if o.state == "skill" then return s + (o.need - o.rank) end
  return s
end

function C.CellText(o, key)
  if key == "cchar" then return o.charName end
  if key == "crecipe" then return (o.known and "" or (BLUE .. "[L]|r ")) .. (o.r.name or tostring(o.recipe)) end
  if key == "cprofit" then
    local res = o.res
    if not res then return "—" end
    local m = Util.Money(res.profit) .. (res.est and " ~" or "")
    return res.profit > 0 and m or (GREY .. m .. "|r")
  end
  if key == "csell" then
    if not o.res then return "—" end
    return o.res.where == "ah" and "AH" or "vendor"
  end
  if key == "ccd" then
    return ns.UI.TimeText(o.r.cd, true) .. (o.r.cdCat and (GREY .. " sh|r") or "")
  end
  if key == "cready" then return readyText(o, time()) end
  return ""
end

local function catLine(r)
  local cat = r.cdCat and ns.CooldownCategories[r.cdCat]
  if not cat then return nil end
  return string.format("Shares the %s cooldown: after any of them, all wait (one per cooldown in total).", cat.name)
end

function C.OptionLines(o, out)
  table.insert(out, o.r.name .. " - " .. o.charName)
  table.insert(out, Util.LineName(o.line) .. ", cooldown " .. ns.UI.TimeText(o.r.cd))
  local cat = catLine(o.r)
  if cat then table.insert(out, cat) end
  table.insert(out, "Ready: " .. readyText(o, time()))
  if o.res then
    table.insert(out, string.format("Profit %s per craft (cost %s, sells for %s, %s)", Util.Money(o.res.profit),
      Util.Money(o.res.cost), Util.Money(o.res.value), o.res.where == "ah" and "AH" or "vendor"))
  else
    table.insert(out, "No profit: a reagent or the output has no price (scan the AH)")
  end
end

function C.DetailText(o)
  local out = {}
  if not o then
    table.insert(out, "Select a row on the left.")
    table.insert(out, "")
    table.insert(out, "Recipes with a cooldown make one craft per cooldown, for every character with the profession. "
      .. "Ready times are read when a character opens the profession window and after each craft, and kept "
      .. "across logins. [L] = not learned yet: worth levelling the profession or learning the recipe?")
    return table.concat(out, "\n")
  end
  C.OptionLines(o, out)
  if o.res then
    table.insert(out, "")
    table.insert(out, "|cffffd100Reagents (one craft)|r")
    for _, e in ipairs(PL.ShoppingList(o.res.tree)) do
      table.insert(out, string.format("  %d x %s  %s  (%s)", math.ceil(e.qty - 1e-9), Util.ItemName(e.id),
        Util.Money(e.cost), e.src == "ah" and "AH" or "vendor"))
    end
  end
  if not o.known then
    table.insert(out, "")
    local acq = ns.char == ns.db.chars[o.char] and PL.Acquire(o.r, o.recipe) or nil
    table.insert(out, "Learn: " .. Util.LineName(o.line) .. " " .. tostring(o.need)
      .. (acq and acq.text and acq.text ~= "" and ("; " .. acq.text) or ""))
  end
  table.insert(out, "")
  table.insert(out, GREY .. "Cooldown lengths: Forever DB2 SpellCooldowns / SpellCategories. ~ = estimated price.|r")
  return table.concat(out, "\n")
end

function C.StatusText(n)
  local info = C.info or { ready = 0, known = 0, chars = 0 }
  local _, t = ns.Scanner.Prices()
  local parts = { string.format("Cooldowns: %d ready (%d known recipes on %d character%s)", info.ready, info.known,
    info.chars, info.chars == 1 and "" or "s"), "Snapshot: " .. Util.Age(t), n .. " rows" }
  if not t then table.insert(parts, ORANGE .. "open the AH and press Scan|r") end
  return table.concat(parts, "  |  ")
end

C.FOOTER = "Profit = one craft at today's AH; [L] = not learned yet; sh = shared cooldown (one transmute per cooldown)"

ns.Command("cd", function(arg)
  if arg == "login" then
    ns.settings.cdLogin = ns.settings.cdLogin == false
    ns.Print("cooldown line at login " .. (ns.settings.cdLogin and "on" or "off"))
    return
  end
  ns.UI.Show()
  ns.UI.SetMode("cd")
end)
