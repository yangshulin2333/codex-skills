-- 仅用于 Play 验证挂载；测试结束后删除整个测试 Folder，不是正式发放系统。
-- 本 Script 的兄弟 ObjectValue：CoreModule -> MountCore，Template -> ServerStorage 模板。
local Players = game:GetService("Players")
local container = script.Parent
local function reference(name, className)
	local value = container:FindFirstChild(name)
	assert(value and value:IsA("ObjectValue") and value.Value and value.Value:IsA(className),
		"Configure ObjectValue " .. name .. " -> " .. className)
	return value.Value
end

local core = require(reference("CoreModule", "ModuleScript"))
local template = reference("Template", "Instance")
assert(template:IsDescendantOf(game:GetService("ServerStorage")), "Put the test template in ServerStorage")
local options = {
	OwnerId = script:GetAttribute("OwnerId"),
	RecipeId = script:GetAttribute("RecipeId"),
	TargetPartName = script:GetAttribute("TargetPartName"),
	TargetAttachmentName = script:GetAttribute("TargetAttachmentName"),
}
local partName = template:IsA("Tool") and "RightHand" or options.TargetPartName
local attachmentName = template:IsA("Tool") and "RightGripAttachment" or options.TargetAttachmentName
for _, key in { "OwnerId", "RecipeId" } do
	assert(type(options[key]) == "string" and options[key] ~= "", "Set nonempty test attribute " .. key)
end
assert(type(partName) == "string" and partName ~= "", "Set nonempty test attribute TargetPartName")
assert(type(attachmentName) == "string" and attachmentName ~= "", "Set nonempty test attribute TargetAttachmentName")

local connections = {}
local seenPlayers = setmetatable({}, { __mode = "k" })
local seenCharacters = setmetatable({}, { __mode = "k" })
local active = true
local function give(player, character)
	if seenCharacters[character] then return end
	seenCharacters[character] = true
	task.spawn(function()
		-- CharacterAdded 时身体和背包可能尚未就绪；有界等待，不无限卡住。
		local humanoid = character:WaitForChild("Humanoid", 10)
		local root = character:WaitForChild("HumanoidRootPart", 10)
		local part = character:WaitForChild(partName, 10)
		local attachment = part and part:WaitForChild(attachmentName, 10)
		local backpack = player:WaitForChild("Backpack", 10)
		if not active or player.Character ~= character then return end
		if not (humanoid and root and attachment and backpack) then
			warn("Mount test failed: character body, target attachment, or Backpack did not become ready")
			return
		end
		-- Equip 复制模板并验证 R15 / 存活 / 挂点，只替换同归属和配方标记的旧物品。
		local ok, result = pcall(core.Equip, player, template, options)
		if ok then print("Mount test equipped: " .. result.ClassName)
		else warn("Mount test failed: " .. tostring(result)) end
	end)
end

local function bind(player)
	if seenPlayers[player] then return end
	seenPlayers[player] = true
	table.insert(connections, player.CharacterAdded:Connect(function(character) give(player, character) end))
	if player.Character then give(player, player.Character) end -- 同时覆盖脚本启动前已经存在的玩家。
end
table.insert(connections, Players.PlayerAdded:Connect(bind))
for _, player in Players:GetPlayers() do bind(player) end
script.Destroying:Connect(function()
	active = false
	for _, connection in connections do connection:Disconnect() end
end)
