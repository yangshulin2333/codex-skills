local fs = require("@lune/fs")
local luau = require("@lune/luau")
local count = 0
local function visit(directory)
	for _, name in fs.readDir(directory) do
		local path = directory .. "/" .. name
		if fs.isDir(path) then visit(path)
		elseif name:match("%.lua$") or name:match("%.luau$") then
			luau.compile(fs.readFile(path))
			count += 1
			print("COMPILE_OK " .. path)
		end
	end
end
visit("../scripts")
assert(count >= 3, "missing core/example sources")
print("ALL_LUAU_SOURCES_COMPILE_OK count=" .. count)
