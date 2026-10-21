-- Optional LocalScript in StarterPlayerScripts. It animates DISPLAY ONLY.
-- Child ObjectValue Visual -> an independent, anchored BasePart or Model in Workspace.
-- Do not point Visual at the real wearable template or an equipped item.
local reference = script:FindFirstChild("Visual")
assert(reference and reference:IsA("ObjectValue"), "Set this LocalScript's Visual ObjectValue")
local visual = reference.Value
assert(visual and (visual:IsA("BasePart") or visual:IsA("Model")), "Visual must be a BasePart or Model")
local parts = if visual:IsA("BasePart") then { visual } else visual:GetDescendants()
for _, part in parts do
	if part:IsA("BasePart") then
		assert(part.Anchored and not part.CanCollide, "All display parts must be Anchored and noncolliding")
	end
end
local origin = visual:GetPivot()
local time = 0
local connection = game:GetService("RunService").RenderStepped:Connect(function(dt)
	if not visual.Parent then return end
	time += dt
	visual:PivotTo(origin * CFrame.new(0, math.sin(time * 2) * 0.25, 0) * CFrame.Angles(0, time * 0.6, 0))
end)
script.Destroying:Connect(function()
	connection:Disconnect()
	if visual.Parent then visual:PivotTo(origin) end
end)
