-- Server Script. Set these sibling ObjectValues in Studio, not project paths:
-- CoreModule -> MountCore ModuleScript; Template -> trusted ServerStorage template;
-- Prompt -> Workspace ProximityPrompt. Set the attributes documented below.
local container = script.Parent
local function reference(name, className)
	local value = container:FindFirstChild(name)
	assert(value and value:IsA("ObjectValue") and value.Value and value.Value:IsA(className),
		"Configure ObjectValue " .. name .. " -> " .. className)
	return value.Value
end

local core = require(reference("CoreModule", "ModuleScript"))
local template = reference("Template", "Instance")
assert(template:IsDescendantOf(game:GetService("ServerStorage")), "Keep trusted equipment templates in ServerStorage")
local disconnect = core.BindPickup(reference("Prompt", "ProximityPrompt"), template, {
	OwnerId = script:GetAttribute("OwnerId"),
	RecipeId = script:GetAttribute("RecipeId"),
	TargetPartName = script:GetAttribute("TargetPartName"), -- Accessory only, e.g. Head
	TargetAttachmentName = script:GetAttribute("TargetAttachmentName"), -- e.g. HatAttachment
	CooldownSeconds = script:GetAttribute("CooldownSeconds") or 1,
	MaxDistance = script:GetAttribute("MaxDistance") or 10,
	OnResult = function(player, success, result)
		if success then print("Mounted", result.ClassName, "for", player.Name)
		else warn("Mount pickup rejected: " .. tostring(result)) end
	end,
})
script.Destroying:Connect(disconnect)
