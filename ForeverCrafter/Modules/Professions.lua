-- Modules/Professions.lua: the player's professions and skill, and the recipe list of the trade-skill window.
-- Skill ranks: C_SkillInfo.GetSkillLineInfoByID (what the Camelot Skills tab uses), then GetProfessions /
-- GetProfessionInfo, then the open trade-skill window. Recipes: when the player opens a profession window the
-- addon reads every recipe there (learned and unlearned), which is authoritative over the static data.
local _, ns = ...
local P = {}
ns.Professions = P
local Util = ns.Util

local BASIC_REAGENT = 1   -- Enum.CraftingReagentType.Basic

-- Primary professions and secondary skills with recipes in the data (parent lines only).
function P.Lines()
  local out = {}
  for line, d in pairs(ns.SkillLines) do
    if d.parent == 0 then table.insert(out, line) end
  end
  table.sort(out, function(a, b) return Util.LineName(a) < Util.LineName(b) end)
  return out
end

local function store(skills, line, rank, maxRank)
  line = Util.ParentLine(line)
  if not ns.SkillLines[line] or not rank or rank <= 0 then return end
  local cur = skills[line]
  if not cur or rank >= cur.rank then
    skills[line] = { rank = rank, max = maxRank or rank, time = time() }
  end
end

-- Re-reads skill ranks. Keeps the old table when no API answers (e.g. during loading).
function P.ReadSkills()
  if not ns.char then return end
  local skills, answered = {}, false
  if ns.API("C_SkillInfo.GetSkillLineInfoByID") then
    for line in pairs(ns.SkillLines) do
      local ok, info = ns.Call("C_SkillInfo.GetSkillLineInfoByID", line)
      if ok then answered = true end
      if ok and type(info) == "table" and not info.isHeader then store(skills, line, info.rank, info.maxRank) end
    end
  end
  if ns.API("GetProfessions") and ns.API("GetProfessionInfo") then
    local ok, a, b, c, d, e, f = ns.Call("GetProfessions")
    if ok then
      answered = true
      for _, index in pairs({ a, b, c, d, e, f }) do
        local ok2, _, _, rank, maxRank, _, _, skillLine = ns.Call("GetProfessionInfo", index)
        if ok2 and skillLine then store(skills, skillLine, rank, maxRank) end
      end
    end
  end
  if answered then
    -- A window read is kept when the other APIs did not report that profession.
    for line, s in pairs(ns.char.skills) do
      if not skills[line] and s.fromWindow then skills[line] = s end
    end
    ns.char.skills = skills
  end
end

function P.Rank(line)
  local s = ns.char and ns.char.skills[Util.ParentLine(line)]
  return s and s.rank or nil
end

-- Known: read from the profession window, or (before the window was opened once) the spellbook check.
function P.IsKnown(spell, line)
  local char = ns.char
  if not char then return false end
  if char.known[spell] then return true end
  local listed = char.listed[line]
  if listed and listed.ids then return false end
  local ok, v = ns.Call("C_SpellBook.IsSpellKnown", spell)
  if ok and v then return true end
  ok, v = ns.Call("IsPlayerSpell", spell)
  return ok and v or false
end

-- Hidden: the profession window listed every recipe (learned and unlearned) and this one was not there.
function P.IsHidden(spell, line)
  local listed = ns.char and ns.char.listed[line]
  return listed and listed.complete and not listed.ids[spell] or false
end

local function readSchematic(id, line)
  local ok, s = ns.Call("C_TradeSkillUI.GetRecipeSchematic", id, false)
  if not ok or type(s) ~= "table" or not s.outputItemID then return nil end
  local reagents = {}
  for _, slot in ipairs(s.reagentSlotSchematics or {}) do
    local r = slot.reagents and slot.reagents[1]
    if r and r.itemID and slot.reagentType == BASIC_REAGENT and slot.required ~= false then
      table.insert(reagents, { r.itemID, slot.quantityRequired or 1 })
    end
  end
  return {
    skill = line, name = s.name,
    out = { s.outputItemID, s.quantityMin or 1, s.quantityMax or s.quantityMin or 1 },
    reagents = reagents,
  }
end

local function recipeIDs()
  local ok, ids = ns.Call("C_TradeSkillUI.GetAllRecipeIDs")
  if ok and type(ids) == "table" and #ids > 0 then return ids end
  ok, ids = ns.Call("C_TradeSkillUI.GetFilteredRecipeIDs")
  if ok and type(ids) == "table" then return ids end
  return nil
end

local function currentLine(ids)
  for _, fn in ipairs({ "C_TradeSkillUI.GetBaseProfessionInfo", "C_TradeSkillUI.GetChildProfessionInfo" }) do
    local ok, info = ns.Call(fn)
    if ok and type(info) == "table" then
      local line = info.parentProfessionID or info.professionID
      if line and ns.SkillLines[Util.ParentLine(line)] then return Util.ParentLine(line), info end
    end
  end
  -- Fall back to the skill line most of the listed recipes belong to.
  local count, best = {}, nil
  for _, id in ipairs(ids) do
    local r = ns.Recipes[id]
    if r then
      count[r.skill] = (count[r.skill] or 0) + 1
      if not best or count[r.skill] > count[best] then best = r.skill end
    end
  end
  return best, nil
end

local triedUnlearned, restoreUnlearned = {}, false

-- Reads the open trade-skill window. → true when something was captured
function P.Capture()
  local char = ns.char
  if not char then return false end
  local ok, linked = ns.Call("C_TradeSkillUI.IsTradeSkillLinked")
  if ok and linked then return false end
  ok, linked = ns.Call("C_TradeSkillUI.IsNPCCrafting")
  if ok and linked then return false end
  local ids = recipeIDs()
  if not ids or #ids == 0 then return false end
  local line, info = currentLine(ids)
  if not line then return false end
  if info and info.skillLevel and info.skillLevel > 0 then
    char.skills[line] = { rank = info.skillLevel, max = info.maxSkillLevel or info.skillLevel, time = time(),
      fromWindow = true }
  end
  local all, sawUnlearned, learned = {}, false, 0
  for _, id in ipairs(ids) do
    local okI, r = ns.Call("C_TradeSkillUI.GetRecipeInfo", id)
    if okI and type(r) == "table" then
      all[id] = true
      if r.learned then
        learned = learned + 1
        char.known[id] = true
        if r.relativeDifficulty then char.difficulty[id] = r.relativeDifficulty end
        local s = readSchematic(id, line)
        if s then char.schematics[id] = s end
      else
        sawUnlearned = true
      end
    end
  end
  -- Known recipes of this profession that are no longer listed were unlearned (profession dropped).
  for id in pairs(char.known) do
    local r = ns.Recipes[id] or char.schematics[id]
    if r and Util.ParentLine(r.skill) == line and not all[id] then char.known[id] = nil end
  end
  local prev = char.listed[line]
  local complete = sawUnlearned
  if not sawUnlearned and prev and prev.complete then
    -- The window shows only learned recipes now (e.g. after restoring the player's filter); the earlier full list
    -- still says which unlearned recipes exist.
    for id in pairs(all) do prev.ids[id] = true end
    all, complete = prev.ids, true
  end
  char.listed[line] = { time = time(), complete = complete, ids = all, learned = learned }
  ns.Debug(string.format("%s: %d recipes, %d learned, unlearned listed: %s", Util.LineName(line), #ids, learned,
    tostring(sawUnlearned)))

  if restoreUnlearned then
    restoreUnlearned = false
    ns.Call("C_TradeSkillUI.SetShowUnlearned", false)
  elseif not sawUnlearned and not triedUnlearned[line] then
    -- Ask once per session for the unlearned list too, then put the player's filter back.
    triedUnlearned[line] = true
    local okS, shown = ns.Call("C_TradeSkillUI.GetShowUnlearned")
    if okS and shown == false then
      restoreUnlearned = true
      ns.Call("C_TradeSkillUI.SetShowUnlearned", true)
    end
  end
  ns.Fire("DATA_CHANGED")
  return true
end

local pending = false
local function captureSoon()
  if pending then return end
  pending = true
  C_Timer.After(0.3, function()
    pending = false
    local ok, err = pcall(P.Capture)
    if not ok then ns.Error("capture: " .. tostring(err)) end
  end)
end

ns.On("TRADE_SKILL_SHOW", captureSoon)
ns.On("TRADE_SKILL_LIST_UPDATE", captureSoon)
ns.On("TRADE_SKILL_DATA_SOURCE_CHANGED", captureSoon)
ns.On("TRADE_SKILL_CLOSE", function()
  if restoreUnlearned then
    restoreUnlearned = false
    ns.Call("C_TradeSkillUI.SetShowUnlearned", false)
  end
end)
ns.On("NEW_RECIPE_LEARNED", function(recipeID)
  if ns.char and recipeID then
    ns.char.known[recipeID] = true
    ns.Fire("DATA_CHANGED")
  end
end)
ns.On("SKILL_LINES_CHANGED", function()
  if ns.ready then
    P.ReadSkills()
    ns.Fire("DATA_CHANGED")
  end
end)

ns.OnLogin(function() P.ReadSkills() end)
ns.Listen("RESET", function() P.ReadSkills() end)

ns.Command("status", function()
  local any = false
  for _, line in ipairs(P.Lines()) do
    local s = ns.char.skills[line]
    if s then
      any = true
      local listed = ns.char.listed[line]
      local note = "open the profession window once for exact recipes"
      if listed then
        local learnable = 0
        for id in pairs(listed.ids) do
          local r = ns.Recipes[id]
          if r and not ns.char.known[id] and ns.Planner and ns.Planner.Learnable(id, r) then
            learnable = learnable + 1
          end
        end
        note = string.format("window read %s: %d known, %d learnable%s", Util.Age(listed.time), listed.learned,
          learnable, listed.complete and "" or " (unlearned not listed)")
      end
      ns.Print(string.format("%s %d/%d - %s", Util.LineName(line), s.rank, s.max, note))
    end
  end
  if not any then ns.Print("no professions found") end
  if ns.Scanner then ns.Scanner.PrintStatus() end
  if ns.Pricing then ns.Pricing.PrintStatus() end
end)
