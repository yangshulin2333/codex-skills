-- CAPTURE_CONFIG
assert(game.PlaceId == CONFIG.placeId and game.GameId == CONFIG.universeId, "Client identity differs from this run")
local HttpService = game:GetService("HttpService")
local sessionMetadata={placeId=game.PlaceId,universeId=game.GameId,capturedUnix=os.time(),
    scope="Read-only current replicated values and visible labels; template/player-level evidence is not assumed to be a floor",candidates={}}
local stateKeys={floor=true,currentfloor=true,floornumber=true,floorcount=true,level=true,currentlevel=true,
    stage=true,currentstage=true,round=true,currentround=true,map=true,currentmap=true,mapname=true,
    floorname=true,floortype=true,room=true,currentroom=true,loadingmap=true,generatingmap=true}
local function stateName(name) return string.lower(tostring(name)):gsub("[^%w]","") end
local function addState(item,key,value,kind)
    if type(value)=="string" then value=value:sub(1,500)
    elseif typeof(value)=="Instance" then value={reference=value:GetFullName(),class=value.ClassName}
    elseif type(value)~="number" and type(value)~="boolean" then return end
    table.insert(sessionMetadata.candidates,{path=item:GetFullName(),class=item.ClassName,key=key,value=value,kind=kind})
end
local function inspectState(item)
    if stateKeys[stateName(item.Name)] and item:IsA("ValueBase") then
        local ok,value=pcall(function() return item.Value end)
        if ok then addState(item,"Value",value,"replicated-value") end
    end
    if item:IsA("Folder") or item:IsA("Model") or item.ClassName=="Player" or item==game or item==workspace then
        local ok,attributes=pcall(function() return item:GetAttributes() end)
        if ok then for key,value in pairs(attributes) do
            if stateKeys[stateName(key)] then addState(item,key,value,"attribute") end
        end end
    end
    if item:IsA("TextLabel") or item:IsA("TextButton") or item:IsA("TextBox") then
        local ok,text=pcall(function() return item.Text end)
        if ok and (stateKeys[stateName(item.Name)] or string.lower(text):match("floor[^%d]*%d+")) then
            addState(item,"Text",text,"visible-label")
        end
    end
end
inspectState(game)
local root = CONFIG.outputDirectory
if not isfolder(root) then makefolder(root) end
local properties = {
    MeshPart = {"MeshId", "TextureID"},
    SpecialMesh = {"MeshId", "TextureId"},
    Decal = {"Texture"},
    Texture = {"Texture"},
    ImageLabel = {"Image"},
    ImageButton = {"Image"},
    Sound = {"SoundId"},
    AudioPlayer = {"Asset"},
    Animation = {"AnimationId"},
    ParticleEmitter = {"Texture"},
    Beam = {"Texture"},
    Trail = {"Texture"},
    Sky = {"SkyboxBk", "SkyboxDn", "SkyboxFt", "SkyboxLf", "SkyboxRt", "SkyboxUp", "MoonTextureId", "SunTextureId"},
    SurfaceAppearance = {"ColorMap", "NormalMap", "RoughnessMap", "MetalnessMap"},
    MaterialVariant = {"ColorMap", "NormalMap", "RoughnessMap", "MetalnessMap"},
    Shirt = {"ShirtTemplate"},
    Pants = {"PantsTemplate"},
    ShirtGraphic = {"Graphic"},
    VideoFrame = {"Video"},
    WrapLayer = {"CageMeshId", "ReferenceMeshId"},
    WrapTarget = {"CageMeshId"},
}
local functions = {}
for _, name in ipairs({"writefile", "readfile", "appendfile", "makefolder", "isfolder", "getscriptbytecode", "decompile", "gethiddenproperty", "getproperties", "getnilinstances", "saveinstance"}) do
    local env = getgenv and getgenv() or _G
    functions[name] = type(env[name]) == "function"
end
local assets, classes, scripts, services = {}, {}, {}, {}
local exportScopeClasses, excludedRootClasses = {}, {}
local excludedRoots = {CoreGui=true, CorePackages=true, PlatformLibraries=true}
local function addAsset(value, item, property)
    if type(value) ~= "string" or value == "" then return end
    local entry = assets[value]
    if not entry then
        local id = value:match("rbxassetid://(%d+)") or value:match("[?&]id=(%d+)")
        entry = {uri = value, id = id, references = {}}
        assets[value] = entry
    end
    table.insert(entry.references, {path = item:GetFullName(), class = item.ClassName, property = property})
end
for _, item in ipairs(game:GetChildren()) do
    table.insert(services, {name = item.Name, class = item.ClassName})
end
local descendants = game:GetDescendants()
for index, item in ipairs(descendants) do
    pcall(inspectState,item)
    classes[item.ClassName] = (classes[item.ClassName] or 0) + 1
    local top = item
    while top.Parent and top.Parent ~= game do top = top.Parent end
    local scopeCounts = excludedRoots[top.Name] and excludedRootClasses or exportScopeClasses
    scopeCounts[item.ClassName] = (scopeCounts[item.ClassName] or 0) + 1
    local props = properties[item.ClassName]
    if props then
        for _, property in ipairs(props) do
            local ok, value = pcall(function() return item[property] end)
            if ok then addAsset(value, item, property) end
        end
    end
    if item:IsA("TextLabel") or item:IsA("TextButton") or item:IsA("TextBox") then
        local ok, family = pcall(function() return item.FontFace.Family end)
        if ok then addAsset(family, item, "FontFace.Family") end
    end
    if item:IsA("LuaSourceContainer") then
        local ok, source = pcall(function() return item.Source end)
        table.insert(scripts, {path = item:GetFullName(), class = item.ClassName, sourceReadable = ok and type(source) == "string" and #source > 0})
    end
    if index % 250 == 0 then task.wait() end
end
local assetList = {}
for _, asset in pairs(assets) do table.insert(assetList, asset) end
table.sort(assetList, function(a, b) return a.uri < b.uri end)
local result = {
    placeId = game.PlaceId,
    universeId = game.GameId,
    placeVersion = game.PlaceVersion,
    snapshotEpoch = os.time(),
    outputFolder = root,
    instanceCount = #descendants,
    classCounts = classes,
    exportScopeClassCounts = exportScopeClasses,
    excludedRootClassCounts = excludedRootClasses,
    exportScopeExcludedRoots = {"CoreGui", "CorePackages", "PlatformLibraries"},
    topLevelServices = services,
    scriptCount = #scripts,
    scripts = scripts,
    assetCount = #assetList,
    assets = assetList,
    capabilities = functions,
    streamingEnabled = workspace.StreamingEnabled,
    currentSessionMetadata = sessionMetadata,
    scope = "Instances and asset references currently readable by the client.",
}
writefile(root .. "/inventory.json", HttpService:JSONEncode(result))
writefile(root .. "/current-session-metadata.json",HttpService:JSONEncode(sessionMetadata))
writefile(root .. "/inventory-complete.txt", tostring(#descendants) .. " instances; " .. tostring(#assetList) .. " asset URIs")
print("ARCHIVE_INVENTORY_COMPLETE " .. root .. " " .. #descendants .. " instances " .. #assetList .. " asset URIs")
