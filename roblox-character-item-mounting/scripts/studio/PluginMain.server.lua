-- Local Studio plugin entrypoint. This is not a gameplay installation script.
-- Import all three siblings into ONE plugin Model: this Script, MountCore
-- ModuleScript and MountWorkbench ModuleScript. Save that Model as a local plugin.
if not plugin then
    return
end

local core = require(script.Parent:WaitForChild("MountCore"))
local workbench = require(script.Parent:WaitForChild("MountWorkbench"))
local controller = workbench.Start(plugin, core)

-- Keep lifetime local to this plugin: no fixed _G name or project lookup.
plugin.Unloading:Connect(function()
    controller:Destroy()
end)
