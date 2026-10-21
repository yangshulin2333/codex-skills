-- CAPTURE_CONFIG
assert(game.PlaceId == CONFIG.placeId and game.GameId == CONFIG.universeId, "Client identity differs from this run")
-- Read-only metadata and one small voxel probe; no terrain or character changes.
local H = game:GetService("HttpService")
local T = workspace.Terrain
local root = CONFIG.outputDirectory .. "/terrain"
if not isfolder(root) then makefolder(root) end
local function vec(v) return {v.X, v.Y, v.Z} end
local result = {
    schema = "codex-terrain-probe-v1", placeId = game.PlaceId, universeId = game.GameId,
    timestamp = os.time(), streamingEnabled = workspace.StreamingEnabled,
    notes = {"MaxExtents is the possible editable region, not a loaded-terrain boundary.",
             "Terrain.Size is recorded as metadata only, not assumed to bound occupied voxels."},
    APIs = {}, metadata = {}, geometry = {},
}
for _, prop in ipairs({"Size", "Position", "WaterColor", "WaterReflectance", "WaterTransparency", "WaterWaveSize", "WaterWaveSpeed"}) do
    local ok, value = pcall(function() return T[prop] end)
    if ok then
        if typeof(value) == "Vector3" then value = vec(value)
        elseif typeof(value) == "Color3" then value = {value.R, value.G, value.B} end
        result.metadata[prop] = value
    else result.metadata[prop .. "Error"] = tostring(value) end
end
local okExtent, ext = pcall(function() return T.MaxExtents end)
if okExtent then result.metadata.MaxExtents = {min=vec(ext.Min), max=vec(ext.Max)} end
local okCount, cellCount = pcall(function() return T:CountCells() end)
result.APIs.CountCells = {ok=okCount, result=okCount and cellCount or tostring(cellCount)}
local player = game:GetService("Players").LocalPlayer
local char = player and player.Character
local part = char and (char:FindFirstChild("HumanoidRootPart") or char.PrimaryPart)
local center = (part and part.Position) or (workspace.CurrentCamera and workspace.CurrentCamera.CFrame.Position) or Vector3.zero
result.playerCenter = vec(center)
local nearMin, nearMax, rawMin, rawMax
local total, near, huge, far = 0, 0, 0, 0
local bins = {}
for i, item in ipairs(workspace:GetDescendants()) do
    if item:IsA("BasePart") and item ~= T then
        local ok, p, size = pcall(function() return item.Position, item.Size end)
        if ok then
            total += 1
            rawMin = rawMin and rawMin:Min(p) or p
            rawMax = rawMax and rawMax:Max(p) or p
            if size.X > 4096 or size.Y > 4096 or size.Z > 4096 then huge += 1 end
            if (p - center).Magnitude <= 2048 and size.X <= 4096 and size.Y <= 4096 and size.Z <= 4096 then
                near += 1
                local half = size / 2
                nearMin = nearMin and nearMin:Min(p - half) or (p - half)
                nearMax = nearMax and nearMax:Max(p + half) or (p + half)
                local bx, bz = math.floor(p.X / 512), math.floor(p.Z / 512)
                bins[tostring(bx) .. "," .. tostring(bz)] = true
            else far += 1 end
        end
    end
    if i % 1000 == 0 then task.wait() end
end
local binList = {}
for key in pairs(bins) do table.insert(binList, key) end
table.sort(binList)
result.geometry = {partCount=total, nearbyPartCount=near, oversizedPartCount=huge, excludedOrDistant=far,
                   rawCenterMin=rawMin and vec(rawMin), rawCenterMax=rawMax and vec(rawMax),
                   nearbyMin=nearMin and vec(nearMin), nearbyMax=nearMax and vec(nearMax), nearbyHorizontal512Bins=binList}
local origin = Vector3.new(math.floor(center.X / 4) * 4 - 32, math.floor(center.Y / 4) * 4 - 48, math.floor(center.Z / 4) * 4 - 32)
local region = Region3.new(origin, origin + Vector3.new(64, 64, 64))
local okChannels, channels = pcall(function() return T:ReadVoxelChannels(region, 4, {"SolidMaterial", "SolidOccupancy", "LiquidOccupancy"}) end)
result.APIs.ReadVoxelChannels = {ok=okChannels, error=not okChannels and tostring(channels) or nil}
local mats, occs, liquids
if okChannels then
    mats, occs, liquids = channels.SolidMaterial, channels.SolidOccupancy, channels.LiquidOccupancy
else
    local okRead, a, b = pcall(function() return T:ReadVoxels(region, 4) end)
    result.APIs.ReadVoxels = {ok=okRead, error=not okRead and tostring(a) or nil}
    if okRead then mats, occs = a, b end
end
if mats then
    local dims = mats.Size or Vector3.new(#mats, #mats[1], #mats[1][1])
    local runs, lastM, lastO, lastL, count, filled = {}, nil, nil, nil, 0, 0
    local materials = {}
    local function flush()
        if count > 0 then
            table.insert(runs, count); table.insert(runs, lastM); table.insert(runs, lastO); table.insert(runs, lastL)
        end
    end
    for x=1,dims.X do for y=1,dims.Y do for z=1,dims.Z do
        local m, o, l = mats[x][y][z], occs[x][y][z], liquids and liquids[x][y][z] or 0
        materials[tostring(m.Value)] = m.Name
        if o > 0 or l > 0 then filled += 1 end
        if m.Value ~= lastM or o ~= lastO or l ~= lastL then
            flush(); lastM, lastO, lastL, count = m.Value, o, l, 1
        else count += 1 end
    end end end
    flush()
    local payload = {schema="codex-terrain-rle-v1", origin=vec(origin), resolution=4, size=vec(dims),
                     order="x-major,y-middle,z-fastest", fields={"runLength","Enum.Material.Value","occupancy","liquidOccupancy"},
                     method=okChannels and "ReadVoxelChannels" or "ReadVoxels", runs=runs, materials=materials}
    writefile(root .. "/probe-chunk.json", H:JSONEncode(payload))
    result.probe = {origin=vec(origin), size=vec(dims), nonempty=filled, voxels=dims.X*dims.Y*dims.Z, output="probe-chunk.json"}
end
local okCopy, copy = pcall(function()
    local c = origin / 4
    return T:CopyRegion(Region3int16.new(Vector3int16.new(c.X,c.Y,c.Z),Vector3int16.new(c.X+15,c.Y+15,c.Z+15)))
end)
result.APIs.CopyRegion = {ok=okCopy, result=okCopy and copy.ClassName or tostring(copy)}
if okCopy then copy:Destroy() end
writefile(root .. "/probe-summary.json", H:JSONEncode(result))
writefile(root .. "/probe-complete.txt", "Probe finished; no game objects were modified.")
print("ARCHIVE_TERRAIN_PROBE_COMPLETE " .. root)
