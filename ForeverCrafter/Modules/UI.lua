-- Modules/UI.lua: the results window. Filters on top, a sortable list of crafts on the left and the selected
-- craft's chain, shopping list and how to learn it on the right. Two modes: "My character" (this character's
-- recipes and skill) and "What-if" (every profession at a skill cap, chains across professions).
local _, ns = ...
local UI = {}
ns.UI = UI
local Util = ns.Util

local BACKDROP = {
  bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
  edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
  tile = true, tileSize = 16, edgeSize = 16,
  insets = { left = 4, right = 4, top = 4, bottom = 4 },
}
local ROWS, ROW_H = 18, 20
local COLORS = {
  orange = "ffff8040", yellow = "ffffff00", green = "ff40c040", grey = "ff808080", unknown = "ffffffff",
}
local COLUMNS = {
  char = {
    { key = "name", label = "Recipe", width = 196 },
    { key = "profit", label = "Profit", width = 92 },
    { key = "pct", label = "%", width = 48 },
    { key = "where", label = "Sell", width = 50 },
    { key = "listings", label = "Listed", width = 50 },
  },
  whatIf = {
    { key = "name", label = "Recipe", width = 150 },
    { key = "profit", label = "Profit", width = 80 },
    { key = "pct", label = "%", width = 40 },
    { key = "profs", label = "Profs", width = 76 },
    { key = "conf", label = "Conf", width = 52 },
    { key = "where", label = "Sell", width = 38 },
  },
}
local MAX_COLUMNS = 6
local PL = ns.Planner

local function whatIf()
  return ns.settings.mode == "whatIf"
end

local function columns()
  return COLUMNS[whatIf() and "whatIf" or "char"]
end

local frame, rows, detail
UI.results, UI.view, UI.stats = {}, {}, {}
UI.offset = 0
UI.selected = nil

local function text(parent, size, r, g, b)
  local fs = parent:CreateFontString(nil, "OVERLAY", size == "small" and "GameFontHighlightSmall" or "GameFontHighlight")
  fs:SetJustifyH("LEFT")
  fs:SetJustifyV("TOP")
  if r then fs:SetTextColor(r, g, b) end
  return fs
end

function UI.ShowHint(owner, lines)
  if not GameTooltip then return end
  GameTooltip:SetOwner(owner, "ANCHOR_LEFT")
  for i, l in ipairs(lines) do
    if i == 1 then GameTooltip:SetText(l) else GameTooltip:AddLine(l, 1, 1, 1, true) end
  end
  GameTooltip:Show()
end

function UI.HideHint()
  if GameTooltip then GameTooltip:Hide() end
end

-- Filtering and sorting -----------------------------------------------------------------------------------------

-- "Min+BS": the professions a what-if chain needs, in the order the chain uses them.
function UI.ProfsText(r)
  local out = {}
  for _, p in ipairs(r.profs or {}) do table.insert(out, PL.ShortName(p.line)) end
  return table.concat(out, "+")
end

local function sortValue(r, key)
  if key == "name" then return r.name end
  if key == "profs" then return (r.primaries or 0) * 1000 + #(r.profs or {}) end
  if key == "conf" then return r.conf or 0 end
  if key == "pct" then return r.pct or -math.huge end
  if key == "where" then return r.where end
  if key == "listings" then return r.sell.listings or 0 end
  return r.profit
end

function UI.ApplyFilter()
  local s = ns.settings
  local view = {}
  local wi = whatIf()
  for _, r in ipairs(UI.results) do
    local ok
    if wi then
      ok = r.whatIf and true or false
      if ok and s.profession ~= 0 then
        ok = false
        for _, p in ipairs(r.profs) do
          if p.line == s.profession then ok = true end
        end
      end
    else
      ok = not r.whatIf and ((r.known and s.showKnown) or (r.learnable and s.showLearnable))
      if ok and s.profession ~= 0 and r.line ~= s.profession then ok = false end
    end
    if ok and r.profit < math.max(s.minProfit or 0, 1) then ok = false end
    if ok then table.insert(view, r) end
  end
  local key, desc = s.sort or "profit", s.sortDesc ~= false
  table.sort(view, function(a, b)
    local x, y = sortValue(a, key), sortValue(b, key)
    if x ~= y then
      if desc then return x > y end
      return x < y
    end
    return a.spell < b.spell
  end)
  UI.view = view
  local maxOffset = math.max(#view - ROWS, 0)
  if UI.offset > maxOffset then UI.offset = maxOffset end
end

local function apply(results, stats)
  UI.results, UI.stats = results, stats
  if UI.selected then
    local still
    for _, r in ipairs(results) do
      if r.spell == UI.selected.spell then still = r end
    end
    UI.selected = still
  end
  UI.ApplyFilter()
end

-- What-if runs are spread over frames (Planner.RunAsync); the list keeps the last results until the new ones are in.
function UI.Recompute()
  if whatIf() then
    UI.calculating = "0 / " .. PL.WhatIfSets(PL.WhatIfOptions())
    PL.RunAsync({ whatIf = ns.settings.whatIf }, function(i, n)
      UI.calculating = i .. " / " .. n
      if frame and frame:IsShown() then frame.status:SetText(UI.StatusText()) end
    end, function(results, stats)
      UI.calculating = nil
      apply(results, stats)
      UI.Refresh()
    end)
    return
  end
  PL.CancelAsync()
  UI.calculating = nil
  local ok, results, stats = pcall(PL.Run)
  if not ok then
    ns.Error("planner: " .. tostring(results))
    results, stats = {}, {}
  end
  apply(results, stats)
end

-- After a what-if setting changed.
function UI.SettingsChanged()
  if UI.IsShown() then
    UI.Recompute()
    UI.Refresh()
  end
end

-- Detail pane ---------------------------------------------------------------------------------------------------

local SRC_TEXT = { ah = "AH", vendor = "vendor", craft = "craft" }

local function nodeLines(node, depth, out)
  local pad = string.rep("    ", depth)
  local qty = node.qty == math.floor(node.qty) and tostring(node.qty) or string.format("%.1f", node.qty)
  if node.src == "craft" then
    local r = ns.Planner.Recipe(node.spell)
    table.insert(out, string.format("%s|cffffd100Craft|r %s x%s  (%d craft%s of %s)  %s", pad, Util.ItemText(node.id),
      qty, node.crafts, node.crafts == 1 and "" or "s", r and r.name or "?", Util.Money(node.cost)))
    for _, c in ipairs(node.children) do nodeLines(c, depth + 1, out) end
  else
    local note = node.est and " ~" or ""
    if node.limited then note = note .. " (limited stock)" end
    table.insert(out, string.format("%sBuy %s x%s from %s%s  %s", pad, Util.ItemText(node.id), qty, SRC_TEXT[node.src],
      note, Util.Money(node.cost)))
  end
end

local function confText(level)
  return "|c" .. PL.CONF_COLOR[level] .. PL.CONF[level] .. "|r"
end
UI.ConfText = confText

local function whatIfHeader(r, out)
  local opts = PL.WhatIfOptions()
  local need = {}
  for _, p in ipairs(r.profs) do
    table.insert(need, Util.LineName(p.line) .. " " .. p.rank .. (p.secondary and " (secondary)" or ""))
  end
  table.insert(out, string.format("|cff66ccffWhat-if|r: needs %s; %d primary profession%s", table.concat(need, ", "),
    r.primaries, r.primaries == 1 and "" or "s"))
  local by = ""
  if r.conf > 1 and #r.steps > 1 then
    local st = ns.Recipes[r.confSpell] or PL.Recipe(r.confSpell)
    by = " (set by " .. (st and st.name or tostring(r.confSpell)) .. ")"
  end
  table.insert(out, "Confidence: " .. confText(r.conf) .. by .. string.format("  |  cap %d%s", opts.cap,
    next(opts.overrides) and " with overrides" or ""))
end

local function whatIfSteps(r, out)
  table.insert(out, "")
  table.insert(out, "|cffffd100Recipes in the chain:|r")
  for _, st in ipairs(r.steps) do
    local learn = st.known and "known on this character" or ("learn: " .. st.acquire.text)
    table.insert(out, string.format("  %s %s: %s - %s - %s", PL.ShortName(st.line), st.learn or "?",
      st.name or tostring(st.spell), confText(st.conf), learn))
  end
  local unlearned = 0
  for _, st in ipairs(r.steps) do
    if not st.known then unlearned = unlearned + 1 end
  end
  if unlearned == 0 then
    table.insert(out, "Nothing to learn: this character knows every recipe in the chain.")
    return
  end
  local line = string.format("Learning %d recipe%s costs %s", unlearned, unlearned == 1 and "" or "s",
    Util.Money(r.learnCost))
  if r.learnUnknown > 0 then
    line = line .. string.format(" plus %d with no known price", r.learnUnknown)
  end
  if r.payback then
    line = line .. string.format("; pays back after %d craft%s", r.payback, r.payback == 1 and "" or "s")
  end
  table.insert(out, line .. ". Profit does not include it (or the cost of learning the professions).")
end

function UI.DetailText(r)
  if not r then
    if whatIf() then
      return "Select a craft on the left.\n\nWhat-if: a character with every profession at the skill cap (and any "
        .. "overrides). Any recipe the cap allows, from any profession, can be a step in a chain, as long as the "
        .. "chain needs no more primary professions than the limit (Cooking and First Aid do not count). "
        .. "Confidence says how sure it is that a recipe can be learned; a chain has its least sure recipe's level."
    end
    return "Select a craft on the left.\n\nProfit = what the result sells for (AH lowest buyout - 1c after the AH "
      .. "cut and deposit, or a vendor) minus the cheapest way to get the reagents (AH, vendor, or crafting them "
      .. "with a recipe you know)."
  end
  local out = {}
  local col = COLORS[r.color] or COLORS.unknown
  table.insert(out, string.format("|c%s%s|r  (%s)", col, r.name, Util.LineName(r.line)))
  if r.whatIf then
    whatIfHeader(r, out)
  elseif r.known then
    table.insert(out, "Known recipe" .. (r.runtime and " (read from your profession window)" or ""))
  else
    table.insert(out, "|cff66ccffNot learned yet|r - your skill allows it. Learn: " .. r.acquire.text)
    if r.payback then
      table.insert(out, string.format("Learning pays back after %d craft%s.", r.payback, r.payback == 1 and "" or "s"))
    end
  end
  table.insert(out, "")
  local s = r.sell
  local n = r.n == math.floor(r.n) and tostring(r.n) or string.format("%.1f (average)", r.n)
  table.insert(out, string.format("Makes %s x %s", n, Util.ItemText(r.out)))
  if ns.Planner.CountUnknown(ns.Planner.Recipe(r.spell)) then
    table.insert(out, "  ~ the game data gives no count for this craft; 1 is assumed. Open the profession window to "
      .. "read the real count.")
  end
  local cut, cutLabel = ns.Pricing.Cut()
  if s.ah then
    table.insert(out, string.format("AH: lowest %s, %d listing%s (%d items) -> %s each after %.1f%% cut (%s)%s",
      Util.Money(s.min), s.listings, s.listings == 1 and "" or "s", s.qty, Util.Money(s.ah), cut * 100, cutLabel,
      s.deposit and (" and " .. Util.Money(s.deposit) .. " deposit") or ", deposit unknown"))
  elseif s.listings then
    table.insert(out, string.format("AH: %d listing%s - below your minimum, not counted", s.listings,
      s.listings == 1 and "" or "s"))
  else
    table.insert(out, "AH: none in the snapshot")
  end
  table.insert(out, "Vendor: " .. (s.vendor and (Util.Money(s.vendor) .. (s.vendorEst and " ~" or ""))
    or "cannot be sold"))
  table.insert(out, string.format("Sell to the %s: %s  |  Cost %s  |  |cff40ff40Profit %s|r%s",
    r.where == "ah" and "AH" or "vendor", Util.Money(r.value), Util.Money(r.cost), Util.Money(r.profit),
    r.pct and string.format(" (%d%%)", math.floor(r.pct * 100 + 0.5)) or ""))
  if s.thin and r.where == "ah" then
    table.insert(out, "|cffff8040Thin market:|r few listings, the price may not hold.")
  end
  table.insert(out, "")
  local steps = ns.Planner.Steps(r.tree)
  table.insert(out, steps > 1 and string.format("|cffffd100Chain (%d crafts):|r", steps) or "|cffffd100Craft:|r")
  nodeLines(r.tree, 0, out)
  if r.whatIf then whatIfSteps(r, out) end
  table.insert(out, "")
  table.insert(out, "|cffffd100Shopping list:|r")
  for _, e in ipairs(ns.Planner.ShoppingList(r.tree)) do
    table.insert(out, string.format("  %d x %s - %s%s%s  %s", e.qty, Util.ItemText(e.id), SRC_TEXT[e.src],
      e.src == "vendor" and Util.VendorNPC(e.id) or "", e.est and " ~" or "", Util.Money(e.cost)))
  end
  if r.est then
    table.insert(out, "")
    table.insert(out, "~ = estimate: a vendor price from game data not yet seen at a merchant or not yet loaded by the "
      .. "client, or more AH items than the snapshot's 20 cheapest price steps. Visit the vendor once, or rescan, to "
      .. "make it exact.")
  end
  return table.concat(out, "\n")
end

-- Window --------------------------------------------------------------------------------------------------------

local function professionLabel()
  local line = ns.settings.profession
  if line == 0 then return "All professions" end
  if whatIf() then
    return Util.LineName(line) .. " (cap " .. PL.CapFor(PL.WhatIfOptions(), line) .. ")"
  end
  local rank = ns.Professions.Rank(line)
  return Util.LineName(line) .. (rank and (" " .. rank) or "")
end

local function cycleProfession()
  local lines = { 0 }
  for _, line in ipairs(ns.Professions.Lines()) do
    if whatIf() or ns.Professions.Rank(line) then table.insert(lines, line) end
  end
  local cur = ns.settings.profession
  local nextLine = lines[1]
  for i, line in ipairs(lines) do
    if line == cur then nextLine = lines[i % #lines + 1] end
  end
  ns.settings.profession = nextLine
  UI.ApplyFilter()
  UI.Refresh()
end

local function maxPrimariesText(n)
  return n == 0 and "any" or tostring(n)
end

function UI.StatusText()
  local _, t = ns.Scanner.Prices()
  local parts = {}
  if whatIf() then
    if UI.calculating then table.insert(parts, "|cffffd100Calculating... " .. UI.calculating .. "|r") end
    local o = PL.WhatIfOptions()
    local n = 0
    for _ in pairs(o.overrides) do n = n + 1 end
    table.insert(parts, string.format("What-if: cap %d%s, max %s primary professions, confidence down to %s", o.cap,
      n > 0 and string.format(" (%d override%s)", n, n == 1 and "" or "s") or "", maxPrimariesText(o.maxPrimaries),
      PL.CONF[o.minConf]))
  end
  if ns.Scanner.state == "waiting" then
    table.insert(parts, "|cffffd100Waiting for the auction house...|r")
  elseif ns.Scanner.state == "reading" then
    table.insert(parts, "|cffffd100Reading listings " .. (UI.progress or "") .. "|r")
  else
    table.insert(parts, "Snapshot: " .. Util.Age(t))
  end
  local cut, label = ns.Pricing.Cut()
  table.insert(parts, string.format("AH cut %.1f%% (%s)", cut * 100, label))
  local st = UI.stats
  table.insert(parts, string.format("%d profitable of %d recipes", #UI.view, st.evaluated or 0))
  if (st.noPrice or 0) > 0 then table.insert(parts, st.noPrice .. " with an unpriced reagent") end
  if not t then table.insert(parts, "|cffff8040open the AH and press Scan|r") end
  return table.concat(parts, "  |  ")
end
local statusText = UI.StatusText

local function editBox(parent, width, label, x, get, set, y)
  local l = text(parent, "small")
  l:SetPoint("TOPLEFT", x, y or -42)
  l:SetText(label)
  local e = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
  e:SetSize(width, 20)
  e:SetPoint("LEFT", l, "RIGHT", 8, 0)
  e:SetAutoFocus(false)
  e:SetScript("OnShow", function(self) self:SetText(get()) end)
  local function commit(self)
    set(self:GetText())
    self:SetText(get())
    self:ClearFocus()
    UI.ApplyFilter()
    UI.Refresh()
  end
  e:SetScript("OnEnterPressed", commit)
  e:SetScript("OnEditFocusLost", function(self) self:SetText(get()) end)
  e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
  e:SetText(get())
  e.label = l
  return e
end

local function checkBox(parent, label, x, key)
  local c = CreateFrame("CheckButton", nil, parent, "UICheckButtonTemplate")
  c:SetSize(24, 24)
  c:SetPoint("TOPLEFT", x, -36)
  local l = text(c, "small")
  l:SetPoint("LEFT", c, "RIGHT", 2, 0)
  l:SetText(label)
  c:SetChecked(ns.settings[key])
  c:SetScript("OnClick", function(self)
    ns.settings[key] = self:GetChecked() and true or false
    UI.ApplyFilter()
    UI.Refresh()
  end)
  return c
end

local function button(parent, width, label, onClick)
  local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
  b:SetSize(width, 22)
  b:SetText(label)
  b:SetScript("OnClick", onClick)
  return b
end

local function hint(owner, lines)
  owner:SetScript("OnEnter", function(self) UI.ShowHint(self, type(lines) == "function" and lines() or lines) end)
  owner:SetScript("OnLeave", UI.HideHint)
end

function UI.SetMode(mode)
  ns.settings.mode = mode == "whatIf" and "whatIf" or "char"
  UI.selected, UI.offset = nil, 0
  local line = ns.settings.profession
  if not whatIf() and line ~= 0 and not ns.Professions.Rank(line) then ns.settings.profession = 0 end
  if not whatIf() and UI.overrides then UI.overrides:Hide() end
  local sortable = false
  for _, col in ipairs(columns()) do
    if col.key == ns.settings.sort then sortable = true end
  end
  if not sortable then ns.settings.sort, ns.settings.sortDesc = "profit", true end
  UI.results, UI.stats = {}, {}
  UI.ApplyFilter()
  UI.Recompute()
  UI.Refresh()
end

-- Popup with a skill cap box per profession; blank = the global skill cap.
local function buildOverrides()
  local primary, secondary = PL.ProfessionLines()
  local lines = {}
  for _, l in ipairs(primary) do table.insert(lines, l) end
  for _, l in ipairs(secondary) do table.insert(lines, l) end
  local f = CreateFrame("Frame", "ForeverCrafterOverrides", frame, "BackdropTemplate")
  f:SetSize(230, 74 + #lines * 24)
  f:SetPoint("TOPRIGHT", frame, "TOPRIGHT", -40, -34)
  f:SetFrameStrata("FULLSCREEN_DIALOG")
  if f.SetBackdrop then
    f:SetBackdrop(BACKDROP)
    f:SetBackdropColor(0.04, 0.06, 0.1, 0.98)
    f:SetBackdropBorderColor(0.4, 0.6, 0.9, 1)
  end
  f:EnableMouse(true)
  local t = text(f, nil, 1, 0.82, 0)
  t:SetPoint("TOPLEFT", 12, -10)
  t:SetText("Skill cap per profession")
  local sub = text(f, "small", 0.7, 0.7, 0.7)
  sub:SetPoint("TOPLEFT", 12, -28)
  sub:SetText("Blank = the Skill cap box")
  f.boxes = {}
  for i, line in ipairs(lines) do
    local e = editBox(f, 40, Util.LineName(line) .. (PL.IsSecondary(line) and " (secondary)" or ""), 12, function()
      local v = ns.settings.whatIf.overrides[line]
      return v and tostring(v) or ""
    end, function(v)
      local n = tonumber(v)
      if v == "" or not n then
        ns.settings.whatIf.overrides[line] = nil
      elseif n >= 1 then
        ns.settings.whatIf.overrides[line] = math.floor(n)
      end
      UI.SettingsChanged()
    end, -26 - i * 24)
    e:ClearAllPoints()
    e:SetPoint("TOPLEFT", f, "TOPLEFT", 170, -22 - i * 24)
    e.line = line
    f.boxes[line] = e
  end
  local clear = button(f, 90, "Clear all", function()
    local o = ns.settings.whatIf.overrides
    for k in pairs(o) do o[k] = nil end
    for _, e in pairs(f.boxes) do e:SetText("") end
    UI.SettingsChanged()
  end)
  clear:SetPoint("BOTTOMLEFT", 12, 10)
  local done = button(f, 70, "Close", function() f:Hide() end)
  done:SetPoint("BOTTOMRIGHT", -12, 10)
  f:Hide()
  return f
end

local function layoutColumns()
  local mode = ns.settings.mode
  if frame.layoutMode == mode then return end
  frame.layoutMode = mode
  local cols = columns()
  local x = 0
  for i, h in ipairs(frame.headers) do
    local col = cols[i]
    h.col = col
    h:ClearAllPoints()
    if col then
      h:SetWidth(col.width)
      h:SetPoint("TOPLEFT", x + 4, 0)
      h:Show()
      for _, row in ipairs(rows) do
        local fs = row.cells[i]
        fs:ClearAllPoints()
        fs:SetPoint("LEFT", x + 2, 0)
        fs:SetWidth(col.width - 4)
        fs:Show()
      end
      x = x + col.width
    else
      h:Hide()
      for _, row in ipairs(rows) do row.cells[i]:Hide() end
    end
  end
end

local function cellText(r, key)
  if key == "name" then
    local col = COLORS[r.color] or COLORS.unknown
    local name = "|c" .. col .. r.name .. "|r"
    if not r.known then name = "|cff66ccff[L]|r " .. name end
    if ns.Planner.Steps(r.tree) > 1 then name = name .. " |cffaaaaaa+chain|r" end
    return name
  elseif key == "profit" then
    return Util.Money(r.profit)
  elseif key == "pct" then
    return r.pct and (math.floor(r.pct * 100 + 0.5) .. "%") or "-"
  elseif key == "where" then
    return r.where == "ah" and (r.sell.thin and "|cffff8040AH|r" or "AH") or "vendor"
  elseif key == "listings" then
    return r.sell.listings and tostring(r.sell.listings) or "-"
  elseif key == "profs" then
    return UI.ProfsText(r)
  elseif key == "conf" then
    if not r.conf then return "-" end
    return "|c" .. PL.CONF_COLOR[r.conf] .. PL.CONF_SHORT[r.conf] .. "|r"
  end
  return ""
end

local function build()
  frame = CreateFrame("Frame", "ForeverCrafterFrame", UIParent, "BackdropTemplate")
  frame:SetSize(860, 520)
  frame:SetPoint("CENTER")
  frame:SetFrameStrata("DIALOG")
  frame:SetToplevel(true)
  if frame.SetBackdrop then
    frame:SetBackdrop(BACKDROP)
    frame:SetBackdropColor(0.04, 0.06, 0.1, 0.95)
    frame:SetBackdropBorderColor(0.4, 0.6, 0.9, 1)
  end
  frame:EnableMouse(true)
  frame:SetMovable(true)
  frame:SetClampedToScreen(true)
  frame:RegisterForDrag("LeftButton")
  frame:SetScript("OnDragStart", frame.StartMoving)
  frame:SetScript("OnDragStop", frame.StopMovingOrSizing)
  if UISpecialFrames then table.insert(UISpecialFrames, "ForeverCrafterFrame") end
  frame.title = text(frame, nil, 1, 0.82, 0)
  frame.title:SetPoint("TOPLEFT", 14, -12)
  frame.title:SetText("ForeverCrafter " .. ns.VERSION)
  local close = CreateFrame("Button", nil, frame, "UIPanelCloseButton")
  close:SetPoint("TOPRIGHT", -2, -2)

  frame.mode = button(frame, 130, "", function() UI.SetMode(whatIf() and "char" or "whatIf") end)
  frame.mode:SetPoint("TOPLEFT", 170, -8)
  hint(frame.mode, { "My character / What-if", "My character: this character's recipes and skill.",
    "What-if: every profession at a skill cap, with chains across professions." })
  -- What-if controls (title row, shown in what-if mode only).
  local wi = {}
  wi.cap = editBox(frame, 36, "Skill cap", 312, function()
    return tostring(ns.settings.whatIf.cap or PL.DEFAULT_CAP)
  end, function(v)
    local n = tonumber(v)
    if n and n >= 1 then
      ns.settings.whatIf.cap = math.floor(n)
      UI.SettingsChanged()
    end
  end, -12)
  wi.overrides = button(frame, 80, "Overrides...", function()
    UI.overrides = UI.overrides or buildOverrides()
    UI.overrides:SetShown(not UI.overrides:IsShown())
  end)
  wi.overrides:SetPoint("TOPLEFT", 420, -8)
  hint(wi.overrides, { "Skill cap per profession", "Overrides the Skill cap box for single professions.",
    "Also: /crafter cap <profession> <n|clear>" })
  wi.conf = button(frame, 120, "", function()
    local w = ns.settings.whatIf
    w.minConf = (w.minConf or 4) % #PL.CONF + 1
    UI.SettingsChanged()
  end)
  wi.conf:SetPoint("TOPLEFT", 506, -8)
  hint(wi.conf, function()
    local lines = { "Minimum confidence", "How sure it must be that each recipe in a chain can be learned:" }
    for i, label in ipairs(PL.CONF) do
      table.insert(lines, (i == PL.WhatIfOptions().minConf and "> " or "  ") .. i .. " " .. label)
    end
    return lines
  end)
  wi.max = button(frame, 130, "", function()
    local w = ns.settings.whatIf
    local cycle = { [1] = 2, [2] = 3, [3] = 0, [0] = 1 }
    w.maxPrimaries = cycle[w.maxPrimaries or 2] or 2
    UI.SettingsChanged()
  end)
  wi.max:SetPoint("TOPLEFT", 632, -8)
  hint(wi.max, { "Max primary professions", "The most primary professions a chain may need (1, 2, 3 or any).",
    "Cooking and First Aid are secondary and do not count." })
  frame.wi = wi

  frame.prof = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  frame.prof:SetSize(160, 22)
  frame.prof:SetPoint("TOPLEFT", 12, -36)
  frame.prof:SetScript("OnClick", cycleProfession)
  frame.known = checkBox(frame, "Known", 182, "showKnown")
  frame.learn = checkBox(frame, "Learnable", 262, "showLearnable")
  frame.minProfit = editBox(frame, 60, "Min profit (g)", 372, function()
    return tostring((ns.settings.minProfit or 0) / 10000)
  end, function(v)
    local c = Util.ParseMoney(v)
    if c and c >= 0 then ns.settings.minProfit = c end
  end)
  frame.minListings = editBox(frame, 32, "Min AH listings", 540, function()
    return tostring(ns.settings.minListings or 1)
  end, function(v)
    local n = tonumber(v)
    if n and n >= 1 then
      ns.settings.minListings = math.floor(n)
      UI.Recompute()
    end
  end)
  frame.scan = CreateFrame("Button", nil, frame, "UIPanelButtonTemplate")
  frame.scan:SetSize(90, 22)
  frame.scan:SetPoint("TOPRIGHT", -14, -36)
  frame.scan:SetText("Scan AH")
  frame.scan:SetScript("OnClick", function() ns.Scanner.Start() end)

  frame.status = text(frame, "small", 0.8, 0.8, 0.8)
  frame.status:SetPoint("TOPLEFT", 14, -66)
  frame.status:SetWidth(830)

  -- List.
  local list = CreateFrame("Frame", nil, frame)
  list:SetPoint("TOPLEFT", 10, -86)
  list:SetSize(460, (ROWS + 1) * ROW_H + 4)
  list:EnableMouseWheel(true)
  list:SetScript("OnMouseWheel", function(_, delta)
    UI.offset = math.max(0, math.min(UI.offset - delta * 3, math.max(#UI.view - ROWS, 0)))
    UI.Refresh()
  end)
  frame.list = list
  frame.headers = {}
  for _ = 1, MAX_COLUMNS do
    local h = CreateFrame("Button", nil, list)
    h:SetSize(50, ROW_H)
    h.text = text(h, "small", 1, 0.82, 0)
    h.text:SetPoint("LEFT", 2, 0)
    h:SetScript("OnClick", function(self)
      local key = self.col.key
      if ns.settings.sort == key then
        ns.settings.sortDesc = not ns.settings.sortDesc
      else
        ns.settings.sort, ns.settings.sortDesc = key, key ~= "name" and key ~= "profs" and key ~= "conf"
      end
      UI.ApplyFilter()
      UI.Refresh()
    end)
    table.insert(frame.headers, h)
  end
  rows = {}
  for i = 1, ROWS do
    local row = CreateFrame("Button", nil, list)
    row:SetSize(452, ROW_H)
    row:SetPoint("TOPLEFT", 4, -i * ROW_H)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight")
    row.sel = row:CreateTexture(nil, "BACKGROUND")
    row.sel:SetAllPoints()
    row.sel:SetColorTexture(0.3, 0.5, 0.9, 0.25)
    row.cells = {}
    for _ = 1, MAX_COLUMNS do
      local fs = text(row, "small")
      fs:SetJustifyV("MIDDLE")
      if fs.SetWordWrap then fs:SetWordWrap(false) end
      table.insert(row.cells, fs)
    end
    row:SetScript("OnClick", function(self)
      UI.selected = self.result
      UI.Refresh()
    end)
    row:SetScript("OnEnter", function(self)
      local r = self.result
      if not r then return end
      local lines = { r.name, Util.LineName(r.line) .. (r.known and "" or " - not learned yet"),
        "Cost " .. Util.Money(r.cost) .. ", sells for " .. Util.Money(r.value) }
      if r.whatIf then
        table.insert(lines, "Needs " .. UI.ProfsText(r) .. "; confidence " .. PL.CONF[r.conf])
      end
      UI.ShowHint(self, lines)
    end)
    row:SetScript("OnLeave", UI.HideHint)
    rows[i] = row
  end
  frame.footer = text(frame, "small", 0.7, 0.7, 0.7)
  frame.footer:SetPoint("BOTTOMLEFT", 14, 12)

  -- Detail pane.
  local scroll = CreateFrame("ScrollFrame", "ForeverCrafterDetailScroll", frame, "UIPanelScrollFrameTemplate")
  scroll:SetPoint("TOPLEFT", 480, -90)
  scroll:SetPoint("BOTTOMRIGHT", -32, 30)
  local child = CreateFrame("Frame", nil, scroll)
  child:SetSize(340, 10)
  scroll:SetScrollChild(child)
  detail = text(child, "small")
  detail:SetPoint("TOPLEFT", 0, 0)
  detail:SetWidth(340)
  if detail.SetSpacing then detail:SetSpacing(2) end
  frame.detail, frame.detailChild = detail, child

  frame:SetScript("OnShow", function()
    UI.Recompute()
    UI.Refresh()
  end)
end

function UI.Refresh()
  if not frame or not frame:IsShown() then return end
  local wi = whatIf()
  layoutColumns()
  frame.mode:SetText(wi and "Mode: What-if" or "Mode: My character")
  for _, c in pairs(frame.wi) do c:SetShown(wi) end
  frame.wi.cap.label:SetShown(wi)
  if wi then
    local o = PL.WhatIfOptions()
    frame.wi.conf:SetText("Min conf: " .. PL.CONF_SHORT[o.minConf])
    frame.wi.max:SetText("Max primaries: " .. maxPrimariesText(o.maxPrimaries))
  elseif UI.overrides then
    UI.overrides:Hide()
  end
  frame.known:SetShown(not wi)
  frame.learn:SetShown(not wi)
  frame.prof:SetText(professionLabel())
  frame.known:SetChecked(ns.settings.showKnown)
  frame.learn:SetChecked(ns.settings.showLearnable)
  frame.scan:SetEnabled(ns.Scanner.ahOpen and ns.Scanner.state == "idle")
  frame.status:SetText(statusText())
  for _, h in ipairs(frame.headers) do
    if h.col then
      local mark = ""
      if ns.settings.sort == h.col.key then mark = ns.settings.sortDesc and " v" or " ^" end
      h.text:SetText(h.col.label .. mark)
    end
  end
  for i, row in ipairs(rows) do
    local r = UI.view[UI.offset + i]
    row.result = r
    if r then
      for c, h in ipairs(frame.headers) do
        if h.col then row.cells[c]:SetText(cellText(r, h.col.key)) end
      end
      row.sel:SetShown(UI.selected ~= nil and UI.selected.spell == r.spell)
      row:Show()
    else
      row:Hide()
    end
  end
  local n = #UI.view
  frame.footer:SetText(n > 0 and string.format("%d-%d of %d   (scroll with the mouse wheel; [L] = not learned yet)",
    UI.offset + 1, math.min(UI.offset + ROWS, n), n) or "nothing profitable with these filters")
  detail:SetText(UI.DetailText(UI.selected))
  frame.detailChild:SetHeight(math.max(detail:GetStringHeight() + 10, 10))
end

function UI.Show()
  if not frame then build() end
  frame:Show()
end

function UI.Toggle()
  if frame and frame:IsShown() then
    frame:Hide()
  else
    UI.Show()
  end
end

function UI.IsShown()
  return frame ~= nil and frame:IsShown()
end

local pending = false
ns.Listen("DATA_CHANGED", function()
  if not UI.IsShown() or pending then return end
  pending = true
  C_Timer.After(0.2, function()
    pending = false
    UI.Recompute()
    UI.Refresh()
  end)
end)
ns.Listen("SCAN_PROGRESS", function(i, total)
  UI.progress = string.format("%d / %d", math.min(i, total), total)
  if frame and frame:IsShown() then frame.status:SetText(statusText()) end
end)

ns.Command("show", UI.Toggle)

-- /crafter cap: print the what-if caps; cap <n>: the global cap; cap <profession> <n|clear>: one profession.
local function findLine(name)
  name = name:lower()
  local primary, secondary = PL.ProfessionLines()
  local lines = {}
  for _, l in ipairs(primary) do table.insert(lines, l) end
  for _, l in ipairs(secondary) do table.insert(lines, l) end
  for _, l in ipairs(lines) do
    if PL.ShortName(l):lower() == name then return l end
  end
  local found
  for _, l in ipairs(lines) do
    if Util.LineName(l):lower():sub(1, #name) == name then
      if found then return nil, "ambiguous" end
      found = l
    end
  end
  return found
end

ns.Command("cap", function(rest)
  local w = ns.settings.whatIf
  rest = (rest or ""):lower():match("^%s*(.-)%s*$")
  if rest == "" then
    local parts = {}
    for line, n in pairs(w.overrides) do table.insert(parts, Util.LineName(line) .. " " .. n) end
    table.sort(parts)
    ns.Print(string.format("what-if skill cap %d%s", w.cap or PL.DEFAULT_CAP,
      #parts > 0 and ("; overrides: " .. table.concat(parts, ", ")) or ""))
    return
  end
  local n = tonumber(rest)
  if n then
    if n < 1 then
      ns.Print("give a skill rank, e.g. /crafter cap 150")
      return
    end
    w.cap = math.floor(n)
    ns.Print("what-if skill cap set to " .. w.cap)
    UI.SettingsChanged()
    return
  end
  local name, value = rest:match("^(.-)%s+(%S+)$")
  if not name then
    ns.Print("usage: /crafter cap [<profession>] <n|clear>")
    return
  end
  local line, err = findLine(name)
  if not line then
    ns.Print(err == "ambiguous" and ("more than one profession starts with \"" .. name .. "\"")
      or ("no profession \"" .. name .. "\""))
    return
  end
  if value == "clear" then
    w.overrides[line] = nil
    ns.Print(Util.LineName(line) .. " uses the what-if skill cap (" .. (w.cap or PL.DEFAULT_CAP) .. ")")
  else
    local v = tonumber(value)
    if not v or v < 1 then
      ns.Print("usage: /crafter cap <profession> <n|clear>")
      return
    end
    w.overrides[line] = math.floor(v)
    ns.Print(Util.LineName(line) .. " what-if cap set to " .. w.overrides[line])
  end
  if UI.overrides then
    for _, e in pairs(UI.overrides.boxes) do e:SetText(w.overrides[e.line] and tostring(w.overrides[e.line]) or "") end
  end
  UI.SettingsChanged()
end)
