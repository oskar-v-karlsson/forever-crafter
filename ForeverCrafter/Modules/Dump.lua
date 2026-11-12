-- /crafter dump: saves what the game client knows about the open profession (every recipe it lists, learned or
-- not, with reagents, output and the game's "how to learn" text) and about items the data files lack, into
-- ForeverCrafterDB.dump. tools/gen_data.py client-dump reads it from the SavedVariables file into research/client/,
-- where it comes before Wowhead Forever (see SOURCES.md, source "client").
local _, ns = ...
local Util = ns.Util
local P = ns.Professions

local D = {}
ns.Dump = D

D.VERSION = 1
local ITEM_TRIES = 10   -- passes of one second each for items the client has not loaded yet

local function store()
  local d = ns.db.dump
  if type(d) ~= "table" or d.v ~= D.VERSION then
    d = { v = D.VERSION, lines = {}, items = {} }
    ns.db.dump = d
  end
  d.noItem = d.noItem or {}  -- items the client gave no info for after every pass → time asked
  local ok, version, build, _, toc = ns.Call("GetBuildInfo")
  if ok then d.client = { version = version, build = build, toc = toc } end
  return d
end

-- Reads the open profession window into d.lines[line]. → line, recipes listed, unlearned, with source text
function D.Profession(d)
  if P.IsForeign() then return nil end
  local ids = P.RecipeIDs()
  if not ids or #ids == 0 then return nil end
  local line, info = P.CurrentLine(ids)
  if not line then return nil end
  local recipes, unlearned, withText = {}, 0, 0
  for _, id in ipairs(ids) do
    local ok, r = ns.Call("C_TradeSkillUI.GetRecipeInfo", id)
    if ok and type(r) == "table" then
      local e = { n = r.name, l = r.learned and true or nil }
      local s = P.ReadSchematic(id, line)
      if s then
        e.o, e.r = s.out, s.reagents
        e.n = e.n or s.name
      end
      if not r.learned then
        unlearned = unlearned + 1
        local okT, text = ns.Call("C_TradeSkillUI.GetRecipeSourceText", id)
        if okT and type(text) == "string" and text ~= "" then
          e.s = text
          withText = withText + 1
        end
      end
      recipes[id] = e
    end
  end
  local okF, faction = ns.Call("UnitFactionGroup", "player")
  d.lines[line] = {
    time = time(), rank = info and info.skillLevel or nil, faction = okF and faction or nil,
    complete = unlearned > 0, n = #ids, recipes = recipes,
  }
  return line, #ids, unlearned, withText
end

-- Items to ask the client about: those with no ItemSparse row in the data, and any the dumped recipes use that the
-- data does not have.
local function wantedItems(d)
  local want = {}
  for id, e in pairs(ns.Items) do
    if e.missing then want[id] = true end
  end
  for _, ln in pairs(d.lines) do
    for _, e in pairs(ln.recipes) do
      if e.o and not ns.Items[e.o[1]] then want[e.o[1]] = true end
      for _, rg in ipairs(e.r or {}) do
        if not ns.Items[rg[1]] then want[rg[1]] = true end
      end
    end
  end
  return want
end

local function readItem(id)
  local get = ns.API("C_Item.GetItemInfo") or ns.API("GetItemInfo")
  if not get then return nil end
  local ok, name, _, quality, _, _, _, _, stack, _, _, sell, classID, subclassID, bind = pcall(get, id)
  if not ok or not name then return nil end
  return { n = name, q = quality, sell = sell, stack = stack, class = classID, sub = subclassID, bind = bind }
end

local itemsRunning = false

-- Asks the client for the wanted items, retrying the ones it has not loaded yet. done(found, asked) at the end.
function D.Items(d, done)
  if itemsRunning then return end
  itemsRunning = true
  local want, asked = wantedItems(d), 0
  for _ in pairs(want) do asked = asked + 1 end
  local function pass(try)
    for id in pairs(want) do
      local e = readItem(id)
      if e then
        e.time = time()
        d.items[id] = e
        d.noItem[id] = nil
        want[id] = nil
      else
        ns.Call("C_Item.RequestLoadItemDataByID", id)
      end
    end
    if next(want) and try < ITEM_TRIES then
      C_Timer.After(1, function() pass(try + 1) end)
      return
    end
    itemsRunning = false
    local left = 0
    for id in pairs(want) do
      left = left + 1
      d.noItem[id] = time()
    end
    if done then done(asked - left, asked) end
  end
  pass(1)
end

local function finish(d, line, n, unlearned, withText)
  if line then
    ns.Print(string.format("dump: %s, %d recipes (%d unlearned, %d with the game's source text)",
      Util.LineName(line), n, unlearned, withText))
    if unlearned == 0 then
      ns.Print("dump: the window listed no unlearned recipes; tick \"Unlearned\" in its filter and dump again")
    end
  else
    ns.Print("dump: no profession window open - only item data. Open a profession and dump again for its recipes")
  end
  D.Items(d, function(found, asked)
    local lines = {}
    for l in pairs(d.lines) do table.insert(lines, Util.LineName(l)) end
    table.sort(lines)
    ns.Print(string.format("dump: item data for %d of %d items. Saved so far: %s", found, asked,
      #lines > 0 and table.concat(lines, ", ") or "no professions"))
    ns.Print("dump: log out or /reload to write it to WTF\\Account\\<account>\\SavedVariables\\ForeverCrafter.lua")
  end)
end

ns.Command("dump", function(arg)
  if (arg or ""):lower() == "clear" then
    ns.db.dump = nil
    ns.Print("dump cleared")
    return
  end
  local d = store()
  local okS, shown = ns.Call("C_TradeSkillUI.GetShowUnlearned")
  if okS and shown == false and #(P.RecipeIDs() or {}) > 0 and not P.IsForeign() then
    -- List the unlearned recipes too, read the window once it has updated, then put the player's filter back.
    ns.Call("C_TradeSkillUI.SetShowUnlearned", true)
    C_Timer.After(0.5, function()
      local line, n, unlearned, withText = D.Profession(d)
      ns.Call("C_TradeSkillUI.SetShowUnlearned", false)
      finish(d, line, n, unlearned, withText)
    end)
    return
  end
  finish(d, D.Profession(d))
end)
