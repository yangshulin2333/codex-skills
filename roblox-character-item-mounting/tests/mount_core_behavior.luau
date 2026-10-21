-- Offline contracts only. Mocks do not establish engine weld/GUI/physics behavior.
local fs = require("@lune/fs")
local luau = require("@lune/luau")
local roblox = require("@lune/roblox")
local CFrame, Vector3 = roblox.CFrame, roblox.Vector3
local nativeTypeof = typeof
local now, server, count = 100, true, 0
local deferred = {}
local timers, warnings = {}, {}
local equipDelay, lastEquipped = 0, nil
local function later(delay, callback) table.insert(timers, { at = now + delay, callback = callback }) end
local function waitTask(dt)
	now += dt
	local again = true
	while again do
		again = false
		for i = #timers, 1, -1 do
			if timers[i].at <= now then
				local timer = table.remove(timers, i)
				timer.callback()
				again = true
			end
		end
	end
	return dt
end
local function flushDeferred()
	while #deferred > 0 do table.remove(deferred, 1)() end
end
local function check(condition, label)
	assert(condition, label)
	count += 1
	print("PASS " .. label)
end
local function rejected(callback, expected, label)
	local ok, reason = pcall(callback)
	check(not ok and string.find(tostring(reason), expected, 1, true) ~= nil, label)
end
local function close(a, b)
	local delta = a:ToObjectSpace(b)
	local _, angle = delta:ToAxisAngle()
	return delta.Position.Magnitude < 0.0001 and math.abs(angle) < 0.0001
end
local function signal()
	local event = { listeners = {} }
	function event:Connect(callback)
		local connection = { active = true, callback = callback }
		function connection:Disconnect() self.active = false end
		table.insert(self.listeners, connection)
		return connection
	end
	function event:Fire(...)
		for _, connection in self.listeners do
			if connection.active then connection.callback(...) end
		end
	end
	function event:Count()
		local total = 0
		for _, connection in self.listeners do if connection.active then total += 1 end end
		return total
	end
	return event
end
local methods = {}
local classes = {
	Part = { BasePart = true }, MeshPart = { BasePart = true },
	WeldConstraint = { Constraint = true }, RigidConstraint = { Constraint = true },
	Weld = { JointInstance = true }, ManualWeld = { JointInstance = true },
	Motor6D = { JointInstance = true },
	Script = { LuaSourceContainer = true }, LocalScript = { LuaSourceContainer = true },
	ModuleScript = { LuaSourceContainer = true },
}
local mt = {}
function mt.__index(self, key)
	if methods[key] then return methods[key] end
	if key == "Parent" then return rawget(self, "_parent") end
	if key == "WorldCFrame" and self._class == "Attachment" then
		return self.Parent.CFrame * self.CFrame
	end
	if key == "WorldPosition" and self._class == "Attachment" then return self.WorldCFrame.Position end
	if key == "Position" and self:IsA("BasePart") then return self.CFrame.Position end
	if key == "ClassName" then return self._class end
	return self._props[key]
end
function mt.__newindex(self, key, value)
	if key == "Parent" then
		local old = rawget(self, "_parent")
		if old then
			for i, child in old._children do if child == self then table.remove(old._children, i); break end end
		end
		rawset(self, "_parent", value)
		if value then table.insert(value._children, self) end
	elseif key == "Position" and self:IsA("BasePart") then self.CFrame = CFrame.new(value)
	else self._props[key] = value end
end
local function create(class, name, parent)
	local self = setmetatable({ _class = class, _props = {}, _children = {}, _attrs = {}, _instance = true }, mt)
	self.Name, self.Archivable = name or class, true
	self.Destroying = signal()
	if self:IsA("BasePart") or class == "Attachment" then self.CFrame = CFrame.new() end
	if self:IsA("BasePart") then
		self.Anchored, self.CanCollide, self.CanTouch, self.Massless = false, true, true, false
		self.Size = Vector3.new(1, 1, 1)
	end
	if class == "Tool" then
		self.Grip, self.RequiresHandle = CFrame.new(), true
		self.Equipped, self.Unequipped = signal(), signal()
	end
	if class == "Humanoid" then self.RigType, self.Health = "R15", 100 end
	if class == "ProximityPrompt" then self.Triggered, self.Enabled, self.MaxActivationDistance = signal(), true, 10 end
	self.Parent = parent
	return self
end
function methods:IsA(class)
	return class == "Instance" or class == self._class or (classes[self._class] and classes[self._class][class]) == true
end
function methods:GetChildren() return table.clone(self._children) end
function methods:GetDescendants()
	local result = {}
	local function visit(node)
		for _, child in node._children do table.insert(result, child); visit(child) end
	end
	visit(self)
	return result
end
function methods:FindFirstChild(name)
	for _, child in self._children do if child.Name == name then return child end end
end
function methods:FindFirstChildOfClass(class)
	for _, child in self._children do if child:IsA(class) then return child end end
end
function methods:IsDescendantOf(ancestor)
	local at = self.Parent
	while at do if at == ancestor then return true end; at = at.Parent end
	return false
end
function methods:GetAttribute(key) return self._attrs[key] end
function methods:SetAttribute(key, value) self._attrs[key] = value end
function methods:Destroy()
	if self.Destroyed then return end
	self.Destroying:Fire()
	for _, child in self:GetChildren() do child:Destroy() end
	self.Parent = nil
	self._props.Destroyed = true
end
function methods:Clone()
	local map = {}
	local function copy(node)
		local clone = create(node._class)
		map[node] = clone
		for key, value in node._props do
			if key ~= "Destroying" and key ~= "Equipped" and key ~= "Unequipped" and key ~= "Triggered" then clone[key] = value end
		end
		clone._attrs = table.clone(node._attrs)
		for _, child in node._children do copy(child).Parent = clone end
		return clone
	end
	local root = copy(self)
	for _, clone in map do
		for key, value in clone._props do
			if nativeTypeof(value) == "table" and value._instance and map[value] then clone[key] = map[value] end
		end
	end
	return root
end
local world = create("Workspace", "Workspace")
local players = create("Players", "Players")
local storage = create("ServerStorage", "ServerStorage")
local run = { IsServer = function() return server end }
function players:GetPlayerFromCharacter(character)
	for _, player in self:GetChildren() do if player.Character == character then return player end end
end
function methods:EquipTool(tool)
	local character = self.Parent
	local player = players:GetPlayerFromCharacter(character)
	for _, existing in character:GetChildren() do
		if existing:IsA("Tool") then
			for _, old in character:FindFirstChild("RightHand"):GetDescendants() do
				if old:IsA("JointInstance") and old.Part1 == existing:FindFirstChild("Handle") then old:Destroy() end
			end
			existing.Parent = player:FindFirstChildOfClass("Backpack")
			existing.Unequipped:Fire()
		end
	end
	tool.Parent = character
	local hand = character:FindFirstChild("RightHand")
	tool.EquipGeneration = (tool.EquipGeneration or 0) + 1
	local generation = tool.EquipGeneration
	lastEquipped = tool
	local function createNativeJoint()
		if tool.Destroyed or tool.Parent ~= character or tool.EquipGeneration ~= generation then return end
		local weld = create("Weld", "RightGrip", hand)
		weld.Part0, weld.Part1 = hand, tool:FindFirstChild("Handle")
		-- Reproduce the engine discrepancy: default C0 can differ from avatar data.
		weld.C0, weld.C1 = CFrame.new(0, -.2, 0) * CFrame.Angles(math.pi / 2, 0, 0), tool.Grip
	end
	if equipDelay == 0 then createNativeJoint()
	elseif equipDelay < math.huge then later(equipDelay, createNativeJoint) end
	tool.Equipped:Fire()
end
function methods:UnequipTools()
	local player = players:GetPlayerFromCharacter(self.Parent)
	for _, tool in self.Parent:GetChildren() do
		if tool:IsA("Tool") then
			for _, joint in self.Parent:FindFirstChild("RightHand"):GetDescendants() do
				if joint:IsA("JointInstance") and joint.Part1 == tool:FindFirstChild("Handle") then joint:Destroy() end
			end
			tool.Parent = player:FindFirstChildOfClass("Backpack")
			tool.Unequipped:Fire()
		end
	end
end
function methods:AddAccessory(item)
	item.Parent = self.Parent
	local handle = item:FindFirstChild("Handle")
	for _, body in self.Parent:GetChildren() do
		if body:IsA("BasePart") then
			for _, attachment in body:GetChildren() do
				local counterpart = handle:FindFirstChild(attachment.Name)
				if attachment:IsA("Attachment") and counterpart then
					local weld = create("Weld", "AccessoryWeld", handle)
					weld.Part0, weld.Part1 = body, handle
					weld.C0, weld.C1 = attachment.CFrame, counterpart.CFrame
					return
				end
			end
		end
	end
end
local env = {
	game = { GetService = function(_, name) return ({ Players = players, RunService = run, ServerStorage = storage })[name] end },
	workspace = world, CFrame = CFrame, Vector3 = Vector3,
	Instance = { new = function(class) return create(class) end },
	Enum = { HumanoidRigType = { R15 = "R15", R6 = "R6" } },
	os = { clock = function() return now end },
	task = { defer = function(callback) table.insert(deferred, callback) end, wait = waitTask },
	typeof = function(value)
		return type(value) == "table" and value._instance and "Instance" or nativeTypeof(value)
	end,
	warn = function(message) table.insert(warnings, message) end,
}
local core = luau.load(fs.readFile("../scripts/studio/MountCore.lua"), { environment = env })()
local player = create("Player", "TestPlayer", players)
local backpack = create("Backpack", "Backpack", player)
local character = create("Model", "Character", world)
player.Character = character
local humanoid = create("Humanoid", "Humanoid", character)
local root = create("Part", "HumanoidRootPart", character)
local hand = create("Part", "RightHand", character)
hand.CFrame = CFrame.new(4, 3, -2) * CFrame.Angles(.2, -.7, .4)
local target = create("Attachment", "RightGripAttachment", hand)
target.CFrame = CFrame.new(.2, -.5, 0) * CFrame.Angles(.1, .3, .2)
local head = create("Part", "Head", character)
local hatTarget = create("Attachment", "HatAttachment", head)
hatTarget.CFrame = CFrame.new(0, .6, 0)
local function toolTemplate()
	local tool = create("Tool", "SharedName", storage)
	local handle = create("MeshPart", "Handle", tool)
	handle.CFrame = CFrame.new(12, 1, -4)
	handle.Anchored = true
	for i = 1, 2 do
		local part = create("Part", "Detail" .. i, tool)
		part.CFrame = handle.CFrame * CFrame.new(i, 0, 0)
		part.Anchored = true
	end
	return tool, handle
end
local options = { OwnerId = "fixture.mount", RecipeId = "fixture.recipe" }
local tool, handle = toolTemplate()
local initialGrip, initialMeshFrame, initialSize = tool.Grip, handle.CFrame, handle.Size
local desired = CFrame.new(-4, 2, 5) * CFrame.Angles(.8, -.6, .2)
local offset = core.ComputeOffset(desired, target.WorldCFrame)
check(close(desired * offset, target.WorldCFrame), "offset roundtrip includes translation and rotation")
rejected(function() core.ApplyPose(tool, hatTarget, desired, { MarkerName = "MountGrip" }) end,
	"RightHand.RightGripAttachment", "Tool rejects non-hand target before mutation")
check(handle:FindFirstChild("MountGrip") == nil and tool.Grip == initialGrip, "wrong target preserves Tool")
rejected(function() core.ApplyPose(tool, target, desired, {}) end, "MarkerName", "Tool requires explicit custom marker name")
local snapshot = core.ApplyPose(tool, target, desired, { MarkerName = "MountGrip" })
check(close(tool.Grip, offset) and tool.Grip == handle:FindFirstChild("MountGrip").CFrame, "Tool grip and canonical marker agree")
check(handle.CFrame == initialMeshFrame and handle.Size == initialSize, "calibration does not move or resize source mesh")
snapshot.Template = create("Tool", "NotTheTarget")
core.RestorePose(snapshot)
check(tool.Grip == initialGrip and handle:FindFirstChild("MountGrip") == nil, "rollback deletes new marker and restores exact grip despite public snapshot tampering")
rejected(function() core.RestorePose(snapshot) end, "unknown", "consumed rollback snapshot rejected")
local originalMarker = create("Attachment", "MountGrip", handle)
originalMarker.CFrame = CFrame.new(1, 2, 3) * CFrame.Angles(.2, .1, .3)
local originalMarkerFrame = originalMarker.CFrame
local second = core.ApplyPose(tool, target, desired, { MarkerName = "MountGrip" })
core.RestorePose(second)
check(originalMarker.Parent == handle and originalMarker.CFrame == originalMarkerFrame and tool.Grip == initialGrip,
	"rollback preserves existing marker identity and exact original matrix")
humanoid.RigType = "R6"
rejected(function() core.ApplyPose(tool, target, desired, { MarkerName = "MountGrip" }) end, "R15", "R6 calibration rejected")
humanoid.RigType = "R15"
check(originalMarker.CFrame == originalMarkerFrame and tool.Grip == initialGrip, "R6 rejection makes no writes")
rejected(function() core.ApplyPose(tool, target, "bad", { MarkerName = "MountGrip" }) end, "CFrame", "bad pose rejected before writes")
check(originalMarker.CFrame == originalMarkerFrame, "bad pose preserves existing marker")
local duplicateTarget = create("Attachment", "RightGripAttachment", hand)
rejected(function() core.ApplyPose(tool, target, desired, { MarkerName = "MountGrip" }) end,
	"ambiguous", "duplicate target attachment rejected before calibration")
check(originalMarker.CFrame == originalMarkerFrame and tool.Grip == initialGrip, "duplicate target rejection preserves Tool")
duplicateTarget:Destroy()
local accessory = create("Accessory", "SharedName", storage)
local accessoryHandle = create("Part", "Handle", accessory)
local accessoryPart = create("Part", "Adornment", accessory)
local accessorySnapshot = core.ApplyPose(accessory, hatTarget, desired)
check(accessoryHandle:FindFirstChild("HatAttachment") ~= nil and
	close(desired * core.GetMountCFrame(accessory, { AttachmentName = "HatAttachment" }), hatTarget.WorldCFrame),
	"Accessory calibrates target's matching attachment name")
core.RestorePose(accessorySnapshot)
check(accessoryHandle:FindFirstChild("HatAttachment") == nil, "Accessory rollback removes newly created marker")
core.ApplyPose(accessory, hatTarget, desired)
local copy = core.PrepareClone(tool, options)
local copyParts, welds = 0, 0
for _, part in copy:GetDescendants() do
	if part:IsA("BasePart") then
		copyParts += 1
		check(not part.Anchored and not part.CanCollide and not part.CanTouch and part.Massless, "clone part is wearable, not anchored display")
	elseif part:IsA("WeldConstraint") then
		welds += 1
		check(part.Part0 == core.GetHandle(copy) and part.Part1:IsDescendantOf(copy), "weld references only clone parts")
	end
end
check(copyParts == 3 and welds == 2, "multipart clone has exactly Handle-to-detail rigid welds")
check(handle.Anchored and handle.CanCollide and handle.CanTouch and not handle.Massless, "clone preparation leaves source physics unchanged")
check(copy:GetAttribute("MountOwnerId") == options.OwnerId and copy:GetAttribute("MountRecipeId") == options.RecipeId,
	"clone carries scoped ownership")
local badWeld = create("WeldConstraint", "External", handle)
badWeld.Part1 = root
rejected(function() core.PrepareClone(tool, options) end, "external", "external joint reference rejected even with nil Part0")
badWeld:Destroy()
local badScript = create("Script", "Unreviewed", tool)
rejected(function() core.PrepareClone(tool, options) end, "script-free", "unreviewed embedded scripts not cloned")
badScript:Destroy()
local badJoint = create("Motor6D", "Animated", tool)
rejected(function() core.PrepareClone(tool, options) end, "animated", "animated template rejected instead of flattened")
badJoint:Destroy()
local unrelated = create("Tool", "SharedName", backpack)
local differentOwner = create("Accessory", "SharedName", character)
differentOwner:SetAttribute("MountOwnerId", "someone-else")
differentOwner:SetAttribute("MountRecipeId", options.RecipeId)
local duplicate = core.PrepareClone(tool, options)
duplicate.Parent = backpack
local equipped = core.Equip(player, tool, options)
flushDeferred()
check(equipped.Parent == character and equipped ~= tool, "Tool equips a clone onto active character")
check(duplicate.Destroyed == true, "only this owner's same-recipe duplicate removed after success")
check(unrelated.Parent == backpack and differentOwner.Parent == character, "same-name unowned and other-owner items preserved")
check(hand:FindFirstChild("RightGrip").C1 == equipped.Grip, "Humanoid adapter consumes calibrated Tool grip (mock)")
check(hand:FindFirstChild("RightGrip").C0 == target.CFrame,
	"Core.Equip corrects native default C0 to avatar attachment after EquipTool")
local nativeJoint = hand:FindFirstChild("RightGrip")
nativeJoint.C0 = CFrame.new(0, -.2, 0) * CFrame.Angles(math.pi / 2, 0, 0)
check(not close(nativeJoint.C0, target.CFrame), "fixture reproduces default joint/body attachment mismatch")
local otherHandle = create("Part", "OtherToolHandle")
local unrelatedJoint = create("Weld", "UnrelatedGrip", hand)
unrelatedJoint.Part0, unrelatedJoint.Part1 = hand, otherHandle
unrelatedJoint.C0, unrelatedJoint.C1 = CFrame.new(7, 8, 9), CFrame.new(2, 3, 4)
local unrelatedC0, unrelatedC1 = unrelatedJoint.C0, unrelatedJoint.C1
check(core.AlignEquippedTool(character, equipped) == nativeJoint
	and nativeJoint.C0 == target.CFrame and nativeJoint.C1 == equipped.Grip,
	"explicit adapter aligns only this Tool's existing native joint")
check(unrelatedJoint.C0 == unrelatedC0 and unrelatedJoint.C1 == unrelatedC1,
	"alignment leaves other Tool joints untouched")
local nativeC0, nativeC1 = nativeJoint.C0, nativeJoint.C1
local ambiguous = create("Motor6D", "SecondMatchingGrip", hand)
ambiguous.Part0, ambiguous.Part1 = hand, core.GetHandle(equipped)
rejected(function() core.AlignEquippedTool(character, equipped) end, "multiple native joints",
	"ambiguous native joint mapping rejected")
check(nativeJoint.C0 == nativeC0 and nativeJoint.C1 == nativeC1, "ambiguous mapping makes no joint writes")
ambiguous:Destroy()
nativeJoint.Parent = nil
rejected(function() core.AlignEquippedTool(character, equipped) end, "not ready",
	"missing native joint rejected without creating replacement")
check(hand:FindFirstChild("RightGrip") == nil, "missing-joint failure does not create a new joint")
nativeJoint.Parent = hand
local detached = core.PrepareClone(tool, options)
detached.Parent = backpack
rejected(function() core.AlignEquippedTool(character, detached) end, "already be equipped",
	"alignment refuses backpack or another character's Tool")
local binding1, binding2 = core.BindToolAlignment(equipped), core.BindToolAlignment(equipped)
check(binding1 == binding2 and equipped.Equipped:Count() == 1, "duplicate binding reuses one Tool-only listener")
humanoid:UnequipTools()
flushDeferred()
check(equipped.Parent == backpack and hand:FindFirstChild("RightGrip") == nil,
	"unequip removes native joint without adapter creating another")
humanoid:EquipTool(equipped)
local rebuiltJoint = hand:FindFirstChild("RightGrip")
check(rebuiltJoint ~= nativeJoint and not close(rebuiltJoint.C0, target.CFrame),
	"re-equip fixture recreates mismatching default native joint")
flushDeferred()
check(rebuiltJoint.C0 == target.CFrame and rebuiltJoint.C1 == equipped.Grip,
	"Equipped binding aligns rebuilt joint on re-equip")
check(unrelatedJoint.C0 == unrelatedC0 and unrelatedJoint.C1 == unrelatedC1,
	"re-equip binding preserves unrelated joints")
binding1()
check(equipped.Equipped:Count() == 0 and rebuiltJoint.C0 == target.CFrame,
	"disconnect removes listener without undoing saved alignment")
humanoid:UnequipTools()
humanoid:EquipTool(equipped)
flushDeferred()
check(not close(hand:FindFirstChild("RightGrip").C0, target.CFrame),
	"disconnected adapter does not modify future re-equip joints")
core.BindToolAlignment(equipped)
flushDeferred()
check(hand:FindFirstChild("RightGrip").C0 == target.CFrame,
	"binding an already equipped Tool schedules initial alignment")
local disposable = core.PrepareClone(tool, options)
core.BindToolAlignment(disposable)
check(disposable.Equipped:Count() == 1, "disposable Tool has one alignment listener")
disposable:Destroy()
check(disposable.Equipped:Count() == 0 and disposable.Destroying:Count() == 0,
	"Tool destruction disconnects alignment and cleanup listeners")
local accessoryOptions = { OwnerId = "fixture.mount", RecipeId = "hat", TargetPartName = "Head", TargetAttachmentName = "HatAttachment" }
local equippedAccessory = core.Equip(player, accessory, accessoryOptions)
check(equippedAccessory.Parent == character and core.GetHandle(equippedAccessory):FindFirstChild("AccessoryWeld") ~= nil,
	"Accessory uses Humanoid:AddAccessory path (mock)")
local extraMatch = create("Attachment", "RightGripAttachment", accessoryHandle)
rejected(function() core.Equip(player, accessory, accessoryOptions) end, "additional body-matching",
	"Accessory with a second body-matching attachment is rejected")
check(extraMatch.Parent == accessoryHandle and accessory.Parent == storage and equippedAccessory.Parent == character,
	"ambiguous Accessory rejection neither edits template nor deletes existing equipment")
extraMatch:Destroy()
local helperMarker = create("Attachment", "VisualOnlyMarker", accessoryHandle)
local helperClone = core.Equip(player, accessory, accessoryOptions)
check(core.GetHandle(helperClone):FindFirstChild("VisualOnlyMarker") ~= nil,
	"Accessory keeps helper attachments that match no body attachment")
server = false
rejected(function() core.Equip(player, tool, options) end, "server-only", "client equip rejected")
rejected(function() core.AlignEquippedTool(character, equipped) end, "server-only", "client joint alignment rejected")
rejected(function() core.BindToolAlignment(equipped) end, "server-only", "client alignment binding rejected")
server = true
humanoid.Health = 0
rejected(function() core.Equip(player, tool, options) end, "living", "dead character equip rejected")
humanoid.Health = 100
local interaction = create("Part", "Interaction", world)
interaction.Position = Vector3.new(0, 0, 0)
local prompt = create("ProximityPrompt", "Prompt", interaction)
prompt:SetAttribute("MountOwnerId", options.OwnerId)
prompt:SetAttribute("MountRecipeId", options.RecipeId)
local results = {}
local pickupOptions = table.clone(options)
pickupOptions.OnResult = function(_, success, result) table.insert(results, { success = success, result = result }) end
pickupOptions.MaxDistance, pickupOptions.CooldownSeconds = 8, 1
local cleanup = core.BindPickup(prompt, tool, pickupOptions)
prompt.Triggered:Fire(player)
check(results[#results].success and results[#results].result.Parent == character, "server Triggered equips nearby player")
local firstPickup = results[#results].result
prompt.Triggered:Fire(player)
check(not results[#results].success and string.find(results[#results].result, "rate limited", 1, true) ~= nil,
	"rapid repeat pickup is rate limited")
check(firstPickup.Parent == character, "rate rejection preserves equipped item")
now += 2
root.Position = Vector3.new(9, 0, 0)
prompt.Triggered:Fire(player)
check(not results[#results].success and string.find(results[#results].result, "range", 1, true) ~= nil,
	"forged distant Triggered rejected by server distance")
now += 2
prompt.MaxActivationDistance = 3
root.Position = Vector3.new(4, 0, 0)
prompt.Triggered:Fire(player)
check(not results[#results].success, "Prompt maximum distance also constrains configured range")
now += 2
prompt.MaxActivationDistance = 10
root.Position = Vector3.new(0 / 0, 0, 0)
prompt.Triggered:Fire(player)
check(not results[#results].success and string.find(results[#results].result, "range", 1, true) ~= nil,
	"non-finite root position cannot bypass pickup distance")
now += 2
root.Position = Vector3.new()
prompt:SetAttribute("MountRecipeId", "changed")
prompt.Triggered:Fire(player)
check(not results[#results].success and string.find(results[#results].result, "ownership", 1, true) ~= nil,
	"changed prompt ownership rejected at activation")
prompt:SetAttribute("MountRecipeId", options.RecipeId)
humanoid.Health = 0
prompt.Triggered:Fire(player)
check(not results[#results].success and string.find(results[#results].result, "living", 1, true) ~= nil,
	"pickup rechecks active living character")
humanoid.Health = 100
prompt.Enabled = false
prompt.Triggered:Fire(player)
check(not results[#results].success and string.find(results[#results].result, "unavailable", 1, true) ~= nil,
	"disabled prompt rejected by server even when Triggered is forged")
prompt.Enabled = true
local beforeCleanup = #results
cleanup()
prompt.Triggered:Fire(player)
check(#results == beforeCleanup, "pickup cleanup disconnects event")
prompt:SetAttribute("MountOwnerId", "not-ours")
rejected(function() core.BindPickup(prompt, tool, pickupOptions) end, "ownership", "binding cannot claim another system's prompt")
check(firstPickup.Parent == character and tool.Parent == storage and handle.Anchored,
	"all rejected pickup attempts leave equipment and template intact")
equipDelay = .15
local delayedOptions = { OwnerId = options.OwnerId, RecipeId = "delayed" }
local began = now
local delayedTool = core.Equip(player, tool, delayedOptions)
flushDeferred()
check(now - began >= .15 and now - began < 2 and delayedTool.Parent == character,
	"Core.Equip yields for delayed native joint within bounded deadline")
check(core.AlignEquippedTool(character, delayedTool).C0 == target.CFrame,
	"delayed first equip returns only after native joint is aligned")
humanoid:UnequipTools()
equipDelay = .2
humanoid:EquipTool(delayedTool)
check(hand:FindFirstChild("RightGrip") == nil, "delayed re-equip starts without a native joint")
flushDeferred()
check(hand:FindFirstChild("RightGrip").C0 == target.CFrame,
	"bound re-equip waits for delayed native joint and aligns it")
equipDelay = math.huge
began = now
rejected(function() core.Equip(player, tool, delayedOptions) end, "within 2 seconds",
	"missing native joint times out rather than yielding indefinitely")
check(now - began >= 2 and now - began <= 2.001 and lastEquipped.Destroyed,
	"timeout is bounded and failed equip clone is cleaned up")
local warningCount = #warnings
flushDeferred()
check(#warnings == warningCount, "destroyed failed-equip binding cancels queued callback quietly")
equipDelay = .4
later(.1, function() humanoid:UnequipTools() end)
began = now
rejected(function() core.Equip(player, tool, { OwnerId = options.OwnerId, RecipeId = "cancelled" }) end,
	"Equip cancelled", "first equip interrupted by unequip reports explicit cancellation")
check(now - began < 2 and lastEquipped.Destroyed, "cancelled initial equip does not wait to deadline or retain clone")
flushDeferred()
waitTask(.5)
check(hand:FindFirstChild("RightGrip") == nil, "cancelled delayed equip does not leave a ghost native joint")
equipDelay = .4
humanoid:EquipTool(delayedTool)
later(.1, function() humanoid:UnequipTools() end)
warningCount = #warnings
flushDeferred()
check(delayedTool.Parent == backpack and #warnings == warningCount,
	"normal unequip during bound re-equip wait cancels without warning")
waitTask(.5)
humanoid:EquipTool(delayedTool)
local replacementCharacter = create("Model", "Replacement", world)
later(.1, function() player.Character = replacementCharacter end)
warningCount = #warnings
flushDeferred()
check(player.Character == replacementCharacter and #warnings == warningCount,
	"player character change cancels old-character binding wait without warning")
player.Character = character
local concurrentPrompt = create("ProximityPrompt", "ConcurrentPrompt", interaction)
concurrentPrompt:SetAttribute("MountOwnerId", options.OwnerId)
concurrentPrompt:SetAttribute("MountRecipeId", "concurrent")
local concurrentResults = {}
local stopConcurrent = core.BindPickup(concurrentPrompt, tool, {
	OwnerId = options.OwnerId, RecipeId = "concurrent", CooldownSeconds = .1,
	OnResult = function(_, success, result) table.insert(concurrentResults, { success = success, result = result }) end,
})
equipDelay = .4
later(.1, function() concurrentPrompt.Triggered:Fire(player) end)
later(.2, function() concurrentPrompt.Triggered:Fire(player) end)
concurrentPrompt.Triggered:Fire(player)
flushDeferred()
check(#concurrentResults == 3 and not concurrentResults[1].success and not concurrentResults[2].success
	and concurrentResults[3].success,
	"concurrent rejected pickups do not release the in-flight equip lock")
check(string.find(concurrentResults[1].result, "rate limited", 1, true) ~= nil
	and string.find(concurrentResults[2].result, "rate limited", 1, true) ~= nil,
	"in-flight pickup remains guarded after cooldown passes during native-joint wait")
stopConcurrent()
equipDelay = 0
print("MOUNT_CORE_BEHAVIOR_OK assertions=" .. count)
