-- Modules/Minimap.lua: minimap button and the addon compartment entry (left click: window, right click: scan).
local _, ns = ...
local M = {}
ns.Minimap = M
local UI = ns.UI

local button
local RADIUS = 105

local function hint()
  local _, t = ns.Scanner.Prices()
  return { "ForeverCrafter", "Left click: results window", "Right click: scan the AH (AH window open)",
    "Snapshot: " .. ns.Util.Age(t) }
end

local function click(mouseButton)
  if mouseButton == "RightButton" then
    ns.Scanner.Start()
  else
    UI.Toggle()
  end
end

local function place()
  local a = math.rad(ns.settings.minimapAngle or 225)
  button:ClearAllPoints()
  button:SetPoint("CENTER", Minimap, "CENTER", math.cos(a) * RADIUS, math.sin(a) * RADIUS)
end

local function build()
  button = CreateFrame("Button", "ForeverCrafterMinimapButton", Minimap)
  button:SetSize(31, 31)
  button:SetFrameStrata("MEDIUM")
  button:SetFrameLevel(8)
  button:RegisterForClicks("LeftButtonUp", "RightButtonUp")
  button:RegisterForDrag("LeftButton")
  button:SetHighlightTexture("Interface\\Minimap\\UI-Minimap-ZoomButton-Highlight")
  local bg = button:CreateTexture(nil, "BACKGROUND")
  bg:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
  bg:SetSize(20, 20)
  bg:SetPoint("TOPLEFT", 7, -5)
  local icon = button:CreateTexture(nil, "ARTWORK")
  icon:SetTexture("Interface\\Icons\\INV_Misc_Coin_01")
  icon:SetSize(20, 20)
  icon:SetPoint("TOPLEFT", 7, -5)
  local border = button:CreateTexture(nil, "OVERLAY")
  border:SetTexture("Interface\\Minimap\\MiniMap-TrackingBorder")
  border:SetSize(53, 53)
  border:SetPoint("TOPLEFT")
  button:SetScript("OnClick", function(_, b) click(b) end)
  button:SetScript("OnEnter", function(self) UI.ShowHint(self, hint()) end)
  button:SetScript("OnLeave", UI.HideHint)
  button:SetScript("OnDragStart", function(self)
    self:SetScript("OnUpdate", function()
      local mx, my = Minimap:GetCenter()
      local cx, cy = GetCursorPosition()
      local scale = Minimap:GetEffectiveScale()
      ns.settings.minimapAngle = math.deg(math.atan2(cy / scale - my, cx / scale - mx))
      place()
    end)
  end)
  button:SetScript("OnDragStop", function(self) self:SetScript("OnUpdate", nil) end)
end

function M.Update()
  if not ns.settings.minimap then
    if button then button:Hide() end
    return
  end
  if not button then build() end
  place()
  button:Show()
end

ns.OnLogin(function() M.Update() end)

ns.Command("minimap", function()
  ns.settings.minimap = not ns.settings.minimap
  M.Update()
  ns.Print("minimap button " .. (ns.settings.minimap and "shown" or "hidden"))
end)

-- Addon compartment (## AddonCompartmentFunc* in the TOC).
function ForeverCrafter_OnCompartmentClick(_, mouseButton)
  if ns.ready then click(mouseButton) end
end

function ForeverCrafter_OnCompartmentEnter(_, frame)
  if ns.ready and frame then UI.ShowHint(frame, hint()) end
end

function ForeverCrafter_OnCompartmentLeave()
  UI.HideHint()
end
