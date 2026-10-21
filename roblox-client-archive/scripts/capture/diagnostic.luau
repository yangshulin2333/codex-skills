-- CAPTURE_CONFIG
assert(game.PlaceId == CONFIG.placeId and game.GameId == CONFIG.universeId, "Wrong client identity")
assert(type(writefile) == "function" and type(readfile) == "function" and type(makefolder) == "function", "File API unavailable")
assert(game:IsLoaded(), "Wait until the game is loaded")
assert(not isfolder(CONFIG.outputDirectory), "Capture folder already exists; preserve it and bind another run")
makefolder(CONFIG.outputDirectory)
local token = "ARCHIVE_PROBE_" .. tostring(os.time())
local path = CONFIG.outputDirectory .. "/diagnostic-probe.txt"
writefile(path, token)
assert(readfile(path) == token, "Executor file write/read mismatch")
local result = {placeId=game.PlaceId, universeId=game.GameId, placeVersion=game.PlaceVersion,
    playerName=game:GetService("Players").LocalPlayer and game:GetService("Players").LocalPlayer.Name,
    diagnosticToken=token, loaded=game:IsLoaded(), streamingEnabled=workspace.StreamingEnabled,
    scope="Local read/write and current client identity; not proof of a complete scene export"}
writefile(CONFIG.outputDirectory .. "/diagnostic.json", game:GetService("HttpService"):JSONEncode(result))
print(token .. " REAL_CLIENT_EXECUTION_CONFIRMED")
