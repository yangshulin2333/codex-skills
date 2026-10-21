-- Read-only data inspection. Imported modules are Lune builtins; archived scripts never run.
local fs = require("@lune/fs")
local process = require("@lune/process")
local serde = require("@lune/serde")
local roblox = require("@lune/roblox")

assert(#process.args == 2, "Usage: lune run classify_containers.luau INPUT_JSON OUTPUT_JSON")
local input = serde.decode("json", fs.readFile(process.args[1]))
local results = {}
local animationPayload = { KeyframeSequence = true, CurveAnimation = true }
local rigEvidenceClasses = { Humanoid = true, AnimationController = true, Motor6D = true, Bone = true }
local animationClasses = { KeyframeSequence = true, Keyframe = true, Pose = true, NumberPose = true, AnimationRigData = true, KeyframeMarker = true, CurveAnimation = true,
    FloatCurve = true, Vector3Curve = true, RotationCurve = true, Animation = true }

for _, entry in input.containers do
    local record = { sha256 = entry.sha256, sourcePath = entry.path, success = false }
    local ok, result = pcall(function()
        -- Deserialization constructs an offline DOM; it does not run Script/LocalScript/ModuleScript.
        local roots = roblox.deserializeModel(fs.readFile(entry.path))
        local classes, rootClasses, rootNames = {}, {}, {}
        local nodeCount, hasGeometry, hasPayload, hasRig = 0, false, false, false
        local scripts, animationClassCounts, rigClassCounts = {}, {}, {}
        local animations = {}
        local names = {}
        for _, root in roots do
            table.insert(rootClasses, root.ClassName)
            table.insert(rootNames, root.Name)
            if root.ClassName == "KeyframeSequence" then
                local keyframes, poseNames = {}, {}
                local startTime, endTime = math.huge, -math.huge
                for _, child in root:GetChildren() do
                    if child.ClassName == "Keyframe" then
                        table.insert(keyframes, { name = child.Name, time = child.Time })
                        startTime = math.min(startTime, child.Time)
                        endTime = math.max(endTime, child.Time)
                    end
                end
                for _, child in root:GetDescendants() do
                    if child.ClassName == "Pose" or child.ClassName == "NumberPose" then poseNames[child.Name] = true end
                end
                local sortedPoseNames = {}
                for name in poseNames do table.insert(sortedPoseNames, name) end
                table.sort(sortedPoseNames)
                table.sort(keyframes, function(a, b) return a.time < b.time end)
                local animation = { name = root.Name, class = root.ClassName, keyframeCount = #keyframes,
                    keyframes = keyframes, poseNames = sortedPoseNames }
                if #keyframes > 0 then
                    animation.firstKeyframeTime = startTime
                    animation.lastKeyframeTime = endTime
                    animation.durationFromTimeZero = endTime
                    animation.keyframeTimeSpan = endTime - startTime
                end
                local loopOk, loop = pcall(function() return root.Loop end)
                if loopOk then animation.loop = loop end
                local priorityOk, priority = pcall(function() return root.Priority end)
                if priorityOk then animation.priority = tostring(priority) end
                table.insert(animations, animation)
            elseif root.ClassName == "CurveAnimation" then
                table.insert(animations, { name = root.Name, class = root.ClassName,
                    timingAssessment = "curve values not decoded; no duration claim" })
            end
            local nodes = { root }
            for _, child in root:GetDescendants() do table.insert(nodes, child) end
            for _, node in nodes do
                local class = node.ClassName
                classes[class] = (classes[class] or 0) + 1
                nodeCount += 1
                if class == "Model" or node:IsA("BasePart") then hasGeometry = true end
                if animationPayload[class] then hasPayload = true end
                if rigEvidenceClasses[class] then
                    hasRig = true
                    rigClassCounts[class] = (rigClassCounts[class] or 0) + 1
                end
                if animationClasses[class] then animationClassCounts[class] = (animationClassCounts[class] or 0) + 1 end
                if class == "Script" or class == "LocalScript" or class == "ModuleScript" then
                    table.insert(scripts, { class = class, name = node.Name })
                end
                if (class == "KeyframeSequence" or class == "CurveAnimation" or class == "Model") and #names < 20 then
                    table.insert(names, { class = class, name = node.Name })
                end
            end
        end
        local category = "unclassified_container"
        if hasPayload and not hasGeometry then category = "animation_payload"
        elseif hasPayload and hasGeometry then category = "mixed_animation_and_model_container"
        elseif hasGeometry and hasRig then category = "model_with_rig_class_evidence"
        elseif hasGeometry then category = "model_container"
        elseif classes.Animation then category = "animation_reference_only_container" end
        return { success = true, classification = category, rootClasses = rootClasses, rootNames = rootNames,
            classCounts = classes, instanceCount = nodeCount, animationClassCounts = animationClassCounts,
            rigClassCounts = rigClassCounts, scriptInstancesNotExecuted = scripts, namedContainers = names,
            animations = animations,
            method = "@lune/roblox.deserializeModel + offline instance classes; no archived script execution" }
    end)
    if ok then
        for key, value in result do record[key] = value end
    else
        record.classification = "unclassified_container"
        record.error = tostring(result)
    end
    table.insert(results, record)
end
fs.writeFile(process.args[2], serde.encode("json", { schemaVersion = 1, method = "data-only static Roblox container DOM inspection", containers = results }, true))
print(serde.encode("json", { inspectedContainers = #results, report = process.args[2] }))
