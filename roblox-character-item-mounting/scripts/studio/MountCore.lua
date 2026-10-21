-- Rigid R15 item mounting. This ModuleScript is usable in Studio and on the server.
-- No plugin services, project paths, network calls, rewards, or persistent inventory.
local MountCore = {}
local snapshots = setmetatable({}, { __mode = "k" })
local alignmentBindings = setmetatable({}, { __mode = "k" })
local JOINT_NOT_READY = "native Tool joint is not ready"

local function fail(message)
	error("MountCore: " .. message, 3)
end

local function instance(value, className, label)
	if typeof(value) ~= "Instance" or not value:IsA(className) then
		fail(label .. " must be a " .. className)
	end
	return value
end

local function nonempty(value, label)
	if type(value) ~= "string" or value == "" or #value > 128 then
		fail(label .. " must be a nonempty string (at most 128 bytes)")
	end
	return value
end

local function finite(value)
	return type(value) == "number" and value == value and math.abs(value) < math.huge
end

local function frame(value, label)
	if typeof(value) ~= "CFrame" then fail(label .. " must be a CFrame") end
	for _, component in { value:GetComponents() } do
		if not finite(component) then fail(label .. " contains a non-finite component") end
	end
	return value
end

local function kindOf(template)
	instance(template, "Instance", "template")
	if template:IsA("Accessory") then return "Accessory" end
	if template:IsA("Tool") and template.RequiresHandle then return "Tool" end
	fail("template must be an Accessory or a Tool with RequiresHandle enabled")
end

local function uniqueChild(parent, name, className, required)
	local found
	for _, child in parent:GetChildren() do
		if child.Name == name then
			if found or not child:IsA(className) then
				fail("ambiguous or invalid " .. name .. " in " .. parent.Name)
			end
			found = child
		end
	end
	if required and not found then fail("missing " .. name .. " in " .. parent.Name) end
	return found
end

local function r15Target(attachment)
	instance(attachment, "Attachment", "targetAttachment")
	local part = instance(attachment.Parent, "BasePart", "targetAttachment.Parent")
	uniqueChild(part, attachment.Name, "Attachment", true)
	local character = instance(part.Parent, "Model", "target body parent")
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if not humanoid or humanoid.RigType ~= Enum.HumanoidRigType.R15 then
		fail("only standard R15 body attachments are supported; R6/custom rigs need a separate adapter")
	end
	return character, humanoid
end

function MountCore.GetHandle(template)
	kindOf(template)
	return uniqueChild(template, "Handle", "BasePart", true)
end

function MountCore.ComputeOffset(itemWorldCFrame, targetAttachmentWorldCFrame)
	return frame(itemWorldCFrame, "itemWorldCFrame"):ToObjectSpace(
		frame(targetAttachmentWorldCFrame, "targetAttachmentWorldCFrame")
	)
end

function MountCore.GetMountCFrame(template, options)
	local kind = kindOf(template)
	local handle = MountCore.GetHandle(template)
	if kind == "Tool" then return template.Grip end
	local name = nonempty(options and options.AttachmentName, "AttachmentName")
	return uniqueChild(handle, name, "Attachment", true).CFrame
end

-- Only marker/Grip changes. Never repositions the source mesh or changes its size.
-- Returned snapshot is registered privately, so changing its public fields cannot
-- redirect RestorePose to another item. Keep the first snapshot for entry rollback.
function MountCore.ApplyPose(template, targetAttachment, previewHandleCFrame, options)
	local kind = kindOf(template)
	local handle = MountCore.GetHandle(template)
	r15Target(targetAttachment)
	if kind == "Tool" and (targetAttachment.Name ~= "RightGripAttachment"
		or targetAttachment.Parent.Name ~= "RightHand") then
		fail("Tool calibration only supports RightHand.RightGripAttachment")
	end
	local markerName = if kind == "Accessory" then targetAttachment.Name
		else nonempty(options and options.MarkerName, "Tool MarkerName")
	nonempty(markerName, "attachment name")
	local marker = uniqueChild(handle, markerName, "Attachment", false)
	local offset = MountCore.ComputeOffset(previewHandleCFrame, targetAttachment.WorldCFrame)
	local before = {
		Template = template, Handle = handle, Kind = kind, Marker = marker,
		MarkerName = markerName, MarkerCreated = marker == nil,
		BeforeMarkerCFrame = marker and marker.CFrame or nil,
		BeforeGrip = if kind == "Tool" then template.Grip else nil,
	}
	local ok, reason = pcall(function()
		if not marker then
			marker = Instance.new("Attachment")
			marker.Name = markerName
			marker.Parent = handle
		end
		marker.CFrame = offset
		-- Assignment to Attachment can canonicalize the matrix: read it back.
		if kind == "Tool" then template.Grip = marker.CFrame end
	end)
	if not ok then
		pcall(function()
			if before.MarkerCreated then
				if marker then marker:Destroy() end
			else marker.CFrame = before.BeforeMarkerCFrame end
			if kind == "Tool" then template.Grip = before.BeforeGrip end
		end)
		fail("ApplyPose failed and attempted rollback: " .. tostring(reason))
	end
	before.Marker = marker
	local snapshot = {
		Template = template, Kind = kind, Marker = marker, MarkerName = markerName,
		MarkerCreated = before.MarkerCreated, BeforeMarkerCFrame = before.BeforeMarkerCFrame,
		BeforeGrip = before.BeforeGrip, AfterCFrame = marker.CFrame,
	}
	snapshots[snapshot] = before
	return snapshot
end

function MountCore.RestorePose(snapshot)
	local before = snapshots[snapshot]
	if not before then fail("unknown or already restored pose snapshot") end
	if before.Handle.Parent ~= before.Template or before.Marker.Parent ~= before.Handle
		or before.Marker.Name ~= before.MarkerName then
		fail("snapshot target changed; refusing to modify another object")
	end
	-- Validate before the first write. The registered target, not public fields, wins.
	kindOf(before.Template)
	if before.Kind == "Tool" then before.Template.Grip = before.BeforeGrip end
	if before.MarkerCreated then before.Marker:Destroy()
	else before.Marker.CFrame = before.BeforeMarkerCFrame end
	snapshots[snapshot] = nil
	return true
end

local function identity(options)
	return nonempty(options and options.OwnerId, "OwnerId"),
		nonempty(options and options.RecipeId, "RecipeId")
end

local function rigidTemplate(template)
	local handle = MountCore.GetHandle(template)
	if not template.Archivable then fail("template must be Archivable") end
	for _, node in template:GetDescendants() do
		if not node.Archivable then fail("all template descendants must be Archivable") end
		if node:IsA("LuaSourceContainer") or node:IsA("Bone") or node:IsA("WrapLayer")
			or node:IsA("WrapTarget") then
			fail("only script-free rigid templates are supported; inspect/remove scripts and layered/skinned content")
		end
		if node:IsA("Constraint") and not node:IsA("WeldConstraint") then
			fail("non-rigid constraints require a separate mounting adapter")
		end
		if node:IsA("JointInstance") and not node:IsA("Weld") and not node:IsA("ManualWeld") then
			fail("animated joints require a separate mounting adapter")
		end
		if node:IsA("WeldConstraint") or node:IsA("JointInstance") then
			if (node.Part0 and not node.Part0:IsDescendantOf(template))
				or (node.Part1 and not node.Part1:IsDescendantOf(template)) then fail("joint references an external part") end
		end
	end
	return handle
end

-- Source template is never changed. Clone is rebuilt as one rigid assembly.
function MountCore.PrepareClone(template, options)
	local ownerId, recipeId = identity(options)
	rigidTemplate(template)
	local copy = template:Clone()
	local handle = MountCore.GetHandle(copy)
	for _, node in copy:GetDescendants() do
		if node:IsA("WeldConstraint") or node:IsA("JointInstance") then node:Destroy() end
	end
	for _, node in copy:GetDescendants() do
		if node:IsA("BasePart") then
			node.Anchored = false
			node.CanCollide = false
			node.CanTouch = false
			node.Massless = true
			if node ~= handle then
				local weld = Instance.new("WeldConstraint")
				weld.Name = "MountRigidWeld"
				weld.Part0, weld.Part1, weld.Parent = handle, node, handle
			end
		end
	end
	copy:SetAttribute("MountOwnerId", ownerId)
	copy:SetAttribute("MountRecipeId", recipeId)
	return copy
end

local function serverOnly()
	if not game:GetService("RunService"):IsServer() then fail("this operation is server-only") end
end

local function liveCharacter(player)
	instance(player, "Player", "player")
	local players = game:GetService("Players")
	if player.Parent ~= players then fail("player is no longer connected") end
	local character = instance(player.Character, "Model", "player.Character")
	if not character:IsDescendantOf(workspace) or players:GetPlayerFromCharacter(character) ~= player then
		fail("character is not this connected player's active Workspace character")
	end
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if not humanoid or humanoid.Health <= 0 or humanoid.RigType ~= Enum.HumanoidRigType.R15 then
		fail("a living standard R15 Humanoid is required")
	end
	local root = uniqueChild(character, "HumanoidRootPart", "BasePart", true)
	return character, humanoid, root
end

local function targetFor(character, kind, options)
	local partName = if kind == "Tool" then "RightHand" else nonempty(options.TargetPartName, "TargetPartName")
	local attachmentName = if kind == "Tool" then "RightGripAttachment"
		else nonempty(options.TargetAttachmentName, "TargetAttachmentName")
	local part = uniqueChild(character, partName, "BasePart", true)
	local attachment = uniqueChild(part, attachmentName, "Attachment", true)
	r15Target(attachment)
	-- AddAccessory searches by name; duplicate body names make its result ambiguous.
	for _, body in character:GetChildren() do
		if body:IsA("BasePart") then
			for _, child in body:GetChildren() do
				if child:IsA("Attachment") and child.Name == attachmentName and child ~= attachment then
					fail("duplicate body attachment name: " .. attachmentName)
				end
			end
		end
	end
	return attachment
end

-- Native Tool joints can use a default C0 rather than the scaled avatar's actual
-- RightGripAttachment. Grip calibration alone does not guarantee world alignment.
-- Call after each real server-side equip, including in an existing equip service.
-- This adapter touches ONLY the already-created joint for this Tool's Handle.
function MountCore.AlignEquippedTool(character, tool)
	serverOnly()
	instance(character, "Model", "character")
	if not character:IsDescendantOf(workspace) then fail("character must be in Workspace") end
	local humanoid = character:FindFirstChildOfClass("Humanoid")
	if not humanoid or humanoid.Health <= 0 or humanoid.RigType ~= Enum.HumanoidRigType.R15 then
		fail("a living standard R15 Humanoid is required")
	end
	if kindOf(tool) ~= "Tool" or tool.Parent ~= character then
		fail("Tool must already be equipped in this character")
	end
	local handle = MountCore.GetHandle(tool)
	local target = targetFor(character, "Tool", {})
	local hand = target.Parent
	local joint
	for _, candidate in hand:GetDescendants() do
		if candidate:IsA("JointInstance") and candidate.Part0 == hand and candidate.Part1 == handle then
			if joint then fail("multiple native joints match this Tool; refusing ambiguous alignment") end
			joint = candidate
		end
	end
	if not joint then fail(JOINT_NOT_READY .. "; wait in the equip owner with a bounded timeout") end
	local desiredC0 = frame(target.CFrame, "RightGripAttachment.CFrame")
	local desiredC1 = frame(tool.Grip, "Tool.Grip")
	local beforeC0, beforeC1 = joint.C0, joint.C1
	local ok, reason = pcall(function() joint.C0, joint.C1 = desiredC0, desiredC1 end)
	if not ok then
		pcall(function() joint.C0, joint.C1 = beforeC0, beforeC1 end)
		fail("Tool joint alignment failed and attempted rollback: " .. tostring(reason))
	end
	return joint
end

-- EquipTool may return before its native joint appears. Retry only that one
-- transient state, for at most two seconds. All validation errors fail at once.
local function waitForToolAlignment(character, tool, player, stillActive)
	local deadline = os.clock() + 2
	local players = game:GetService("Players")
	while true do
		if (stillActive and not stillActive()) or tool.Parent ~= character
			or not character:IsDescendantOf(workspace)
			or (player and (player.Parent ~= players or player.Character ~= character)) then
			return nil, "Cancelled"
		end
		local ok, result = pcall(MountCore.AlignEquippedTool, character, tool)
		if ok then return result, "Aligned" end
		if not string.find(tostring(result), JOINT_NOT_READY, 1, true) then
			return nil, "Rejected", tostring(result)
		end
		local remaining = deadline - os.clock()
		if remaining <= 0 then return nil, "Timeout", "native Tool joint was not ready within 2 seconds" end
		task.wait(math.min(0.05, remaining))
	end
end

-- Equip/unequip recreates the native joint. Bind once per actual Tool instance.
-- Each deferred equip adaptation has a two-second bound; no heartbeat, global
-- character listener, or unbounded retry. Disconnect is not an undo of C0/C1.
function MountCore.BindToolAlignment(tool)
	serverOnly()
	if kindOf(tool) ~= "Tool" then fail("alignment binding requires a Tool") end
	MountCore.GetHandle(tool)
	if alignmentBindings[tool] then return alignmentBindings[tool] end
	local active = true
	local connections = {}
	local function disconnect()
		if not active then return end
		active = false
		alignmentBindings[tool] = nil
		for _, connection in connections do connection:Disconnect() end
	end
	local function schedule()
		local character = tool.Parent
		if not character or not character:IsA("Model") then return end
		local player = game:GetService("Players"):GetPlayerFromCharacter(character)
		task.defer(function()
			if not active then return end
			local joint, state, reason = waitForToolAlignment(character, tool, player, function() return active end)
			-- Normal unequip/destruction/character change is not a spurious warning.
			if not joint and state ~= "Cancelled" then
				warn("MountCore Tool alignment rejected: " .. tostring(reason))
			end
		end)
	end
	connections[1] = tool.Equipped:Connect(schedule)
	connections[2] = tool.Destroying:Connect(disconnect)
	alignmentBindings[tool] = disconnect
	if tool.Parent and tool.Parent:IsA("Model") then schedule() end
	return disconnect
end

function MountCore.Equip(player, template, options)
	serverOnly()
	local ownerId, recipeId = identity(options)
	local character, humanoid = liveCharacter(player)
	local kind = kindOf(template)
	local target = targetFor(character, kind, options)
	if kind == "Accessory" then
		local handle = MountCore.GetHandle(template)
		uniqueChild(handle, target.Name, "Attachment", true)
		-- AddAccessory chooses by matching attachment names. A second match could
		-- silently bind to a different body part even though parenting succeeded.
		for _, marker in handle:GetChildren() do
			if marker:IsA("Attachment") and marker.Name ~= target.Name then
				for _, body in character:GetChildren() do
					if body:IsA("BasePart") then
						for _, bodyMarker in body:GetChildren() do
							if bodyMarker:IsA("Attachment") and bodyMarker.Name == marker.Name then
								fail("Accessory has an additional body-matching attachment: " .. marker.Name)
								end
						end
					end
				end
			end
		end
	end
	local backpack = player:FindFirstChildOfClass("Backpack")
	if not backpack then fail("player Backpack is unavailable") end
	local copy = MountCore.PrepareClone(template, options)
	local stopAlignment
	local ok, reason = pcall(function()
		if kind == "Accessory" then humanoid:AddAccessory(copy)
		else
			stopAlignment = MountCore.BindToolAlignment(copy)
			copy.Parent = backpack
			humanoid:EquipTool(copy)
			local joint, state, detail = waitForToolAlignment(character, copy, player)
			if not joint then
				if state == "Cancelled" then fail("Equip cancelled: Tool or character changed while waiting for the native joint") end
				fail(detail)
			end
		end
		if copy.Parent ~= character then fail("Humanoid did not equip the clone") end
	end)
	if not ok then
		if stopAlignment then stopAlignment() end
		copy:Destroy()
		fail("equip failed: " .. tostring(reason))
	end
	-- Equip succeeded first. Never delete unrelated items, even if names are equal.
	for _, container in { character, backpack } do
		for _, child in container:GetChildren() do
			if child ~= copy and (child:IsA("Accessory") or child:IsA("Tool"))
				and child:GetAttribute("MountOwnerId") == ownerId
				and child:GetAttribute("MountRecipeId") == recipeId then child:Destroy() end
		end
	end
	return copy
end

local function promptPosition(prompt)
	local parent = prompt.Parent
	if parent and parent:IsA("Attachment") then return parent.WorldPosition end
	if parent and parent:IsA("BasePart") then return parent.Position end
	if parent and parent:IsA("Model") and parent.PrimaryPart then return parent.PrimaryPart.Position end
	fail("Prompt must be inside an Attachment, BasePart, or Model with a PrimaryPart")
end

-- Triggered is server-owned; no RemoteEvent accepts a template or arbitrary item.
-- Multiple players can reuse this station. Stock/rewards/persistence are game logic.
function MountCore.BindPickup(prompt, template, options)
	serverOnly()
	instance(prompt, "ProximityPrompt", "prompt")
	local ownerId, recipeId = identity(options)
	local cooldown = options.CooldownSeconds or 1
	local maxDistance = options.MaxDistance or 10
	if not finite(cooldown) or cooldown < 0.1 or cooldown > 60 then fail("CooldownSeconds must be within 0.1..60") end
	if not finite(maxDistance) or maxDistance <= 0 or maxDistance > 100 then fail("MaxDistance must be within 0..100") end
	if prompt:GetAttribute("MountOwnerId") ~= ownerId or prompt:GetAttribute("MountRecipeId") ~= recipeId then
		fail("Prompt ownership attributes do not match this binding")
	end
	rigidTemplate(template)
	if not prompt:IsDescendantOf(workspace) then fail("Prompt must be in Workspace") end
	promptPosition(prompt)
	local attempts = setmetatable({}, { __mode = "k" })
	local busy = setmetatable({}, { __mode = "k" })
	local connection = prompt.Triggered:Connect(function(player)
		local acquired = false
		local ok, result = pcall(function()
			if not prompt.Enabled or not prompt:IsDescendantOf(workspace) then fail("station is unavailable") end
			if prompt:GetAttribute("MountOwnerId") ~= ownerId or prompt:GetAttribute("MountRecipeId") ~= recipeId then
				fail("station ownership changed")
			end
			local _, _, root = liveCharacter(player)
			local now = os.clock()
			if busy[player] or (attempts[player] and now - attempts[player] < cooldown) then fail("rate limited") end
			attempts[player] = now
			local distanceLimit = math.min(maxDistance, prompt.MaxActivationDistance)
			local distance = (root.Position - promptPosition(prompt)).Magnitude
			if not finite(distanceLimit) or distanceLimit <= 0
				or not finite(distance) or distance > distanceLimit then fail("out of pickup range") end
			busy[player] = true
			acquired = true
			return MountCore.Equip(player, template, options)
		end)
		-- A rejected concurrent attempt must not clear another callback's lock
		-- while that callback is yielding for its native equip joint.
		if acquired then busy[player] = nil end
		if options.OnResult then
			local callbackOk, callbackError = pcall(options.OnResult, player, ok, result)
			if not callbackOk then warn("MountCore OnResult failed: " .. tostring(callbackError)) end
		end
	end)
	return function() connection:Disconnect() end
end

return MountCore
