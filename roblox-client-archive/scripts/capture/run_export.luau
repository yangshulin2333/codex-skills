-- Local client-readable archive; does not request server content.
-- Credit: UniversalSynSaveInstance https://discord.gg/wx4ThpAsmw
-- Modified source and all dependency licenses are retained alongside this script.

-- CAPTURE_CONFIG
assert(game.PlaceId == CONFIG.placeId and game.GameId == CONFIG.universeId, "Client identity differs from this run")
local outputDirectory = CONFIG.outputDirectory
pcall(makefolder, outputDirectory)
local outputPath = outputDirectory .. "/scene.rbxlx"
assert(type(readfile) == "function" and type(writefile) == "function", "Executor file API unavailable")
assert(not (type(isfile) == "function" and isfile(outputPath)), "scene.rbxlx already exists; preserve it before rerunning")

local HttpService = game:GetService("HttpService")
local launcherState = {OutputPath = outputPath, PlaceId = game.PlaceId, GameId = game.GameId, StartedUnix = os.time(), RemoteDecompile = false, BytecodeRequested = true, ExcludedEngineTrees = {"CoreGui", "CorePackages", "PlatformLibraries"}}
writefile(outputDirectory .. "/export_start.json", HttpService:JSONEncode(launcherState))

local source = readfile(CONFIG.toolsDirectory .. "/saveinstance-offline.luau")
local chunk, compileError = loadstring(source, "saveinstance-offline")
assert(chunk, compileError)
local save = chunk()
print("[CLIENT_ARCHIVE] Export started: " .. outputPath)

save({
    FilePath = outputPath,
    XML = true,
    mode = "full",
    Decompile = false,
    SaveBytecode = true,
    BytecodeTimeout = 3,
    DecompileIgnore = {},
    IgnoreList = {"CoreGui", "CorePackages", "PlatformLibraries"},
    IsolateLocalPlayer = true,
    IsolatePlayers = true,
    IsolateStarterPlayer = true,
    SavePlayerCharacters = true,
    SaveNotCreatable = true,
    NilInstances = type(getnilinstances) == "function",
    IgnoreDefaultPlayerScripts = false,
    IgnoreDefaultProperties = false,
    IgnoreNotArchivable = true,
    SafeMode = false,
    KillAllScripts = false,
    BoostFPS = false,
    ShutdownWhenDone = false,
    AntiIdle = false,
    AlternativeWritefile = false,
    ShowStatus = true,
    ReadMe = true,
})

local env = getgenv and getgenv() or _G or shared
writefile(outputDirectory .. "/unknown_class_remaps.json", HttpService:JSONEncode(env.CLIENT_ARCHIVE_REMAPS or {}))
launcherState.FinishedUnix = os.time()
launcherState.RemappedClasses = #(env.CLIENT_ARCHIVE_REMAPS or {})
launcherState.FilePresent = type(isfile) == "function" and isfile(outputPath) or false
if launcherState.FilePresent then
    local data = readfile(outputPath)
    launcherState.OutputBytes = #data
    launcherState.XmlRootPresent = string.find(data, '<roblox version="4">', 1, true) ~= nil
    launcherState.XmlEndPresent = string.find(data, "</roblox>", math.max(1, #data - 200), true) ~= nil
end
writefile(outputDirectory .. "/export_finish.json", HttpService:JSONEncode(launcherState))
print("[CLIENT_ARCHIVE] Export finished: " .. HttpService:JSONEncode(launcherState))
