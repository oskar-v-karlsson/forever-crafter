-- Modules/UI.lua: the results window. Filters on top, a sortable list of crafts on the left and the selected
-- craft's chain, shopping list and how to learn it on the right.
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
  { key = "name", label = "Recipe", width = 196 },
  { key = "profit", label = "Profit", width = 92 },
  { key = "pct", label = "%", width = 48 },
  { key = "where", label = "Sell", width = 50 },
  { key = "listings", label = "Listed", width = 50 },
}

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

local function sortValue(r, key)
  if key == "name" then return r.name end
  if key == "pct" then return r.pct or -math.huge end
  if key == "where" then return r.where end
  if key == "listings" then return r.sell.listings or 0 end
  return r.profit
end

function UI.ApplyFilter()
  local s = ns.settings
  local view = {}
  for _, r in ipairs(UI.results) do
    local ok = (r.known and s.showKnown) or (r.learnable and s.showLearnable)
    if ok and s.profession ~= 0 and r.line ~= s.profession then ok = false end
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

function UI.Recompute()
  local ok, results, stats = pcall(ns.Planner.Run)
  if not ok then
    ns.Error("planner: " .. tostring(results))
    results, stats = {}, {}
  end
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

function UI.DetailText(r)
  if not r then
    return "Select a craft on the left.\n\nProfit = what the result sells for (AH lowest buyout - 1c after the AH "
      .. "cut and deposit, or a vendor) minus the cheapest way to get the reagents (AH, vendor, or crafting them "
      .. "with a recipe you know)."
  end
  local out = {}
  local col = COLORS[r.color] or COLORS.unknown
  table.insert(out, string.format("|c%s%s|r  (%s)", col, r.name, Util.LineName(r.line)))
  if r.known then
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
  table.insert(out, "")
  table.insert(out, "|cffffd100Shopping list:|r")
  for _, e in ipairs(ns.Planner.ShoppingList(r.tree)) do
    table.insert(out, string.format("  %d x %s - %s%s  %s", e.qty, Util.ItemText(e.id), SRC_TEXT[e.src],
      e.est and " ~" or "", Util.Money(e.cost)))
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
  local rank = ns.Professions.Rank(line)
  return Util.LineName(line) .. (rank and (" " .. rank) or "")
end

local function cycleProfession()
  local lines = { 0 }
  for _, line in ipairs(ns.Professions.Lines()) do
    if ns.Professions.Rank(line) then table.insert(lines, line) end
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

local function statusText()
  local _, t = ns.Scanner.Prices()
  local parts = {}
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

local function editBox(parent, width, label, x, get, set)
  local l = text(parent, "small")
  l:SetPoint("TOPLEFT", x, -42)
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
  return e
end

local function checkBox(parent, label, x, key)
  local c = CreateFrame("CheckButton", nil, parent, "UICheckButtonTemplate")
  c:SetSize(24, 24)
  c:SetPoint("TOPLEFT", x, -36)
  local l = text(parent, "small")
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
  local x = 4
  frame.headers = {}
  for _, col in ipairs(COLUMNS) do
    local h = CreateFrame("Button", nil, list)
    h:SetSize(col.width, ROW_H)
    h:SetPoint("TOPLEFT", x, 0)
    h.text = text(h, "small", 1, 0.82, 0)
    h.text:SetPoint("LEFT", 2, 0)
    h:SetScript("OnClick", function()
      if ns.settings.sort == col.key then
        ns.settings.sortDesc = not ns.settings.sortDesc
      else
        ns.settings.sort, ns.settings.sortDesc = col.key, col.key ~= "name"
      end
      UI.ApplyFilter()
      UI.Refresh()
    end)
    h.col = col
    table.insert(frame.headers, h)
    x = x + col.width
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
    local cx = 0
    for _, col in ipairs(COLUMNS) do
      local fs = text(row, "small")
      fs:SetPoint("LEFT", cx + 2, 0)
      fs:SetWidth(col.width - 4)
      fs:SetJustifyV("MIDDLE")
      if fs.SetWordWrap then fs:SetWordWrap(false) end
      table.insert(row.cells, fs)
      cx = cx + col.width
    end
    row:SetScript("OnClick", function(self)
      UI.selected = self.result
      UI.Refresh()
    end)
    row:SetScript("OnEnter", function(self)
      local r = self.result
      if not r then return end
      UI.ShowHint(self, { r.name, Util.LineName(r.line) .. (r.known and "" or " - not learned yet"),
        "Cost " .. Util.Money(r.cost) .. ", sells for " .. Util.Money(r.value) })
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
  frame.prof:SetText(professionLabel())
  frame.known:SetChecked(ns.settings.showKnown)
  frame.learn:SetChecked(ns.settings.showLearnable)
  frame.scan:SetEnabled(ns.Scanner.ahOpen and ns.Scanner.state == "idle")
  frame.status:SetText(statusText())
  for _, h in ipairs(frame.headers) do
    local mark = ""
    if ns.settings.sort == h.col.key then mark = ns.settings.sortDesc and " v" or " ^" end
    h.text:SetText(h.col.label .. mark)
  end
  for i, row in ipairs(rows) do
    local r = UI.view[UI.offset + i]
    row.result = r
    if r then
      local col = COLORS[r.color] or COLORS.unknown
      local name = "|c" .. col .. r.name .. "|r"
      if not r.known then name = "|cff66ccff[L]|r " .. name end
      if ns.Planner.Steps(r.tree) > 1 then name = name .. " |cffaaaaaa+chain|r" end
      row.cells[1]:SetText(name)
      row.cells[2]:SetText(Util.Money(r.profit))
      row.cells[3]:SetText(r.pct and (math.floor(r.pct * 100 + 0.5) .. "%") or "-")
      row.cells[4]:SetText(r.where == "ah" and (r.sell.thin and "|cffff8040AH|r" or "AH") or "vendor")
      row.cells[5]:SetText(r.sell.listings and tostring(r.sell.listings) or "-")
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
