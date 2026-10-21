-- Studio-only visual authoring. No network calls, game IDs or project-specific objects.
-- Native Move/Rotate changes a preview clone; MountCore stores its relative mount.
-- Require this ModuleScript from a local Studio plugin, not a gameplay Script.
local Workspace = game:GetService("Workspace")
local Selection = game:GetService("Selection")
local RunService = game:GetService("RunService")
local StudioTest = game:GetService("StudioTestService")
local History = game:GetService("ChangeHistoryService")
local UserInput = game:GetService("UserInputService")
local Http = game:GetService("HttpService")

local Workbench = {}
local PREVIEW_NAME = "CharacterItemMountPreview"
local DEFAULT_MARKER = "MountGrip"

-- The captured Edit DataModel alone can report IsEdit() during a global Play test.
-- Fail closed if Studio's global mode cannot be read; never silently allow writes.
function Workbench.IsEditorMode()
    local ok, active = pcall(function()
        return StudioTest.EditModeActive
    end)
    return RunService:IsStudio() and RunService:IsEdit() and ok and active == true
end

local function closeCFrame(a, b)
    local relative = a:ToObjectSpace(b)
    local _, angle = relative:ToAxisAngle()
    return relative.Position.Magnitude < 1e-5 and math.abs(angle) < 1e-5
end

local function findRig(instance)
    local current = instance
    while current and current ~= game do
        if current:IsA("Model") and current:FindFirstChildOfClass("Humanoid") then
            return current
        end
        current = current.Parent
    end
    return nil
end

local function assertR15(rig)
    local humanoid = rig and rig:FindFirstChildOfClass("Humanoid")
    assert(humanoid and humanoid.RigType == Enum.HumanoidRigType.R15,
        "第一版只支持含 Humanoid 的 R15 Rig；请不要选择 R6 或散装模型")
end

-- Map an instance into an exact clone before scripts/constraints are removed.
-- Child indices, rather than names alone, preserve duplicate-name hierarchies.
local function cloneCounterpart(sourceRoot, cloneRoot, sourceChild)
    local indices = {}
    local current = sourceChild
    while current ~= sourceRoot do
        local parent = assert(current.Parent, "目标挂点已离开 Rig")
        local index = table.find(parent:GetChildren(), current)
        assert(index, "无法定位目标挂点")
        table.insert(indices, 1, index)
        current = parent
    end
    local counterpart = cloneRoot
    for _, index in ipairs(indices) do
        counterpart = assert(counterpart:GetChildren()[index], "Rig 克隆层级不一致")
    end
    return counterpart
end

local function selectedOne(explicit)
    if explicit then
        assert(typeof(explicit) == "Instance", "参数必须是 Studio Instance")
        return explicit
    end
    local selected = Selection:Get()
    assert(#selected == 1, "请在资源管理器中只选中一个对象")
    return selected[1]
end

local function itemFrom(instance)
    local current = instance
    while current and current ~= game do
        if current:IsA("Tool") or current:IsA("Accessory") then
            return current
        end
        current = current.Parent
    end
    error("请选择 Tool / Accessory 本体，或其内部的 Handle")
end

local function sanitizeClone(model, isRig)
    for _, descendant in ipairs(model:GetDescendants()) do
        if descendant:IsA("LuaSourceContainer") then
            descendant:Destroy()
        elseif descendant:IsA("BasePart") then
            descendant.Anchored = true
            descendant.CanCollide = false
            descendant.CanTouch = false
            descendant.CanQuery = not isRig
            descendant.Locked = isRig
        elseif descendant:IsA("Constraint") then
            descendant.Enabled = false
        elseif descendant:IsA("JointInstance") and not isRig then
            -- All copied parts remain at their authored world transforms. Removing
            -- copied welds prevents them from overriding a native model transform.
            descendant:Destroy()
        elseif descendant:IsA("Trail") or descendant:IsA("ParticleEmitter") then
            descendant.Enabled = false
        elseif descendant:IsA("Sound") then
            descendant.Playing = false
        end
    end
    if isRig then
        local humanoid = model:FindFirstChildOfClass("Humanoid")
        if humanoid then
            humanoid.DisplayDistanceType = Enum.HumanoidDisplayDistanceType.None
        end
    end
end

local function moveHandle(model, handle, desiredCFrame)
    -- Do not assume Model pivot == Handle: custom PivotOffsets are supported.
    local delta = desiredCFrame * handle.CFrame:Inverse()
    model:PivotTo(delta * model:GetPivot())
end

local function components(cframe)
    return { cframe:GetComponents() }
end

function Workbench.Start(pluginObject, core)
    assert(pluginObject and pluginObject:IsA("Plugin"), "需要 Studio Plugin 上下文")
    core = core or require(script.Parent:WaitForChild("MountCore"))
    assert(type(core.GetHandle) == "function" and type(core.ApplyPose) == "function"
        and type(core.RestorePose) == "function" and type(core.GetMountCFrame) == "function",
        "MountCore API 不完整")

    local self = {
        plugin = pluginObject,
        core = core,
        sessionId = Http:GenerateGUID(false),
        connections = {},
        previewConnections = {},
        generation = 0,
        syncCount = 0,
        undoCount = 0,
        redoCount = 0,
        autoSync = true,
        dirty = false,
        writing = false,
        ownRecording = false,
        suspended = false,
        destroyed = false,
        lastReason = "先选 Rig / 身体挂点，再选 Tool / Accessory；不会移动源对象",
    }

    function self:Status(message)
        self.lastReason = message
        if self.status then
            self.status.Text = message
        end
    end

    function self:CancelPending()
        self.generation += 1
        self.dirty = false
    end

    function self:CanEdit()
        return not self.destroyed and not self.suspended and Workbench.IsEditorMode()
            and self.root and self.root.Parent == Workspace
            and self.previewModel and self.previewModel.Parent == self.root
            and self.previewHandle and self.previewHandle:IsDescendantOf(self.previewModel)
            and self.previewTarget and self.previewTarget:IsDescendantOf(self.root)
            and self.item and self.item.Parent and self.sourceHandle
            and self.sourceHandle.Parent == self.item
            and self.sourceTarget and self.sourceTarget.Parent
    end

    function self:EndPreview()
        self:CancelPending()
        for _, connection in ipairs(self.previewConnections) do
            connection:Disconnect()
        end
        table.clear(self.previewConnections)
        if self.root then
            self.root:Destroy()
        end
        self.root, self.previewModel, self.previewHandle, self.previewTarget = nil, nil, nil, nil
        self.entrySnapshot, self.entryOffset, self.activeMarkerName = nil, nil, nil
        self.ignoreProgrammaticCFrame = nil
        self:Status("预览已结束；保留已保存挂点，未保存的拖动不会写入模板")
    end

    function self:CaptureRig(explicit)
        assert(Workbench.IsEditorMode(), "请先停止 Play，再选择参考 Rig / 挂点")
        local chosen = selectedOne(explicit)
        assert(not self.root or not chosen:IsDescendantOf(self.root), "请选择原始 Rig，不要选择预览副本")
        local rig, attachment
        if chosen:IsA("Attachment") then
            assert(chosen.Parent and chosen.Parent:IsA("BasePart"), "挂点必须直接位于身体 BasePart 下")
            rig, attachment = findRig(chosen), chosen
        else
            assert(chosen:IsA("Model"), "请选择 R15 Rig 模型，或身体部位中的 Attachment")
            rig = chosen
            local hand = rig:FindFirstChild("RightHand")
            attachment = hand and hand:FindFirstChild("RightGripAttachment")
            assert(attachment and attachment:IsA("Attachment"),
                "此 Rig 缺少 RightHand.RightGripAttachment；请直接选择其他身体 Attachment")
        end
        assertR15(rig)
        assert(attachment:IsDescendantOf(rig), "目标 Attachment 不在所选 Rig 内")
        -- A tool/accessory's own marker is not a body anchor.
        local body = attachment.Parent
        assert(body.Parent == rig, "请选择 Rig 身体部位内的 Attachment，不要选择饰品或工具内的挂点")
        self:EndPreview()
        self.rig, self.sourceTarget = rig, attachment
        if self.rigLabel then
            self.rigLabel.Text = "Rig / 挂点：" .. rig.Name .. " / " .. body.Name .. "." .. attachment.Name
        end
        self:Status("已选择身体挂点；源 Rig 的位置、姿态和 Attachment 均未修改")
        return rig, attachment
    end

    function self:CaptureItem(explicit)
        assert(Workbench.IsEditorMode(), "请先停止 Play，再选择物品模板")
        local chosen = selectedOne(explicit)
        assert(not self.root or not chosen:IsDescendantOf(self.root), "请选择原物品模板，不要选择预览副本")
        local item = itemFrom(chosen)
        local handle = self.core.GetHandle(item)
        assert(item.Archivable, "物品 Archivable=false，无法克隆；请先在属性面板启用")
        self:EndPreview()
        self.item, self.sourceHandle = item, handle
        if self.itemLabel then
            self.itemLabel.Text = "物品：" .. item.ClassName .. " / " .. item.Name
        end
        self:Status("已选择物品；拖动只操作预览，保存只修改模板挂点 / Tool.Grip")
        return item, handle
    end

    function self:GetToolMarkerName()
        local name = self.markerInput and self.markerInput.Text or DEFAULT_MARKER
        name = name:match("^%s*(.-)%s*$")
        assert(#name > 0, "Tool 辅助挂点名称不能为空")
        assert(#name <= 80, "Tool 辅助挂点名称过长")
        return name
    end

    function self:Options()
        return {
            MarkerName = self.activeMarkerName or self:GetToolMarkerName(),
            AttachmentName = self.sourceTarget and self.sourceTarget.Name,
        }
    end

    function self:ReadTemplateOffset(allowMissingAccessory)
        if self.item:IsA("Accessory") and allowMissingAccessory then
            local count = 0
            for _, child in ipairs(self.sourceHandle:GetChildren()) do
                if child.Name == self.sourceTarget.Name then
                    count += 1
                end
            end
            if count == 0 then
                return CFrame.identity
            end
        end
        return self.core.GetMountCFrame(self.item, self:Options())
    end

    function self:SelectPreview()
        if not self:CanEdit() then
            return false
        end
        Selection:Set({ self.previewModel })
        return true
    end

    function self:BuildPreview()
        assert(Workbench.IsEditorMode(), "请先停止 Play，再创建预览")
        if self:CanEdit() then
            return self:SelectPreview()
        end
        assert(self.rig and self.rig.Parent and self.sourceTarget and self.sourceTarget.Parent,
            "请先点击“使用所选 Rig / 挂点”")
        assert(self.item and self.item.Parent, "请先点击“使用所选 Tool / Accessory”")
        assertR15(self.rig)
        if self.item:IsA("Tool") then
            local hand = self.rig:FindFirstChild("RightHand")
            assert(hand and self.sourceTarget.Parent == hand and self.sourceTarget.Name == "RightGripAttachment",
                "原生 Tool 仅支持 RightHand.RightGripAttachment；其他身体挂点请使用 Accessory 分支")
        end
        assert(self.rig.Archivable, "Rig Archivable=false，无法克隆；请先在属性面板启用")
        self.sourceHandle = self.core.GetHandle(self.item)
        self:EndPreview()
        self.activeMarkerName = self:GetToolMarkerName()
        self.entryOffset = self:ReadTemplateOffset(true)

        local root = Instance.new("Model")
        root.Name = PREVIEW_NAME
        root:SetAttribute("EditorOnly", true)
        root:SetAttribute("MountWorkbenchSession", self.sessionId)
        local success, failure = pcall(function()
            local rig = assert(self.rig:Clone(), "Rig 不可克隆")
            local target = cloneCounterpart(self.rig, rig, self.sourceTarget)
            rig.Name = "参考Rig"
            sanitizeClone(rig, true)
            -- Derive placement from the selected source's pivot/bounds. No fixed
            -- map coordinates and no forced hand/arm pose are introduced.
            local _, size = rig:GetBoundingBox()
            local sourcePivot = self.rig:GetPivot()
            rig:PivotTo(sourcePivot * CFrame.new(math.max(size.X * 1.35, 1), 0, 0))
            rig.Parent = root

            local preview = Instance.new("Model")
            preview.Name = "拖动此物品"
            local clonedItem = assert(self.item:Clone(), "物品不可克隆")
            local handle = self.core.GetHandle(clonedItem)
            sanitizeClone(clonedItem, false)
            clonedItem.Parent = preview
            preview.PrimaryPart = handle
            preview.Parent = root
            moveHandle(preview, handle, target.WorldCFrame * self.entryOffset:Inverse())

            local outline = Instance.new("SelectionBox")
            outline.Name = "EditorOutline"
            outline.Adornee = preview
            outline.LineThickness = 0.025
            outline.Color3 = Color3.fromRGB(255, 199, 74)
            outline.SurfaceTransparency = 1
            outline.Parent = root

            local cleanup = Instance.new("Script")
            cleanup.Name = "EditorOnlyCleanup"
            cleanup.Source = "-- This is an authoring-only clone, never a gameplay asset.\nscript.Parent:Destroy()\n"
            cleanup.Parent = root

            self.root, self.previewModel, self.previewHandle, self.previewTarget = root, preview, handle, target
            self.ignoreProgrammaticCFrame = handle.CFrame
            self.suspended = false
            root.Parent = Workspace
            table.insert(self.previewConnections, root.Destroying:Connect(function()
                if self.root == root then
                    self:CancelPending()
                    self.root, self.previewModel, self.previewHandle, self.previewTarget = nil, nil, nil, nil
                    self.entrySnapshot, self.entryOffset, self.activeMarkerName = nil, nil, nil
                    self.ignoreProgrammaticCFrame = nil
                    self:Status("预览已删除；模板中已保存的挂点未被自动改动")
                end
            end))
            table.insert(self.previewConnections, handle:GetPropertyChangedSignal("CFrame"):Connect(function()
                -- Studio can defer Changed until AFTER an internal PivotTo has
                -- returned and `writing` is false. Retain its actual final frame
                -- so Reset/Refresh echoes never schedule an unintended save.
                if self.ignoreProgrammaticCFrame and closeCFrame(handle.CFrame, self.ignoreProgrammaticCFrame) then
                    return
                end
                self.ignoreProgrammaticCFrame = nil
                if not self.writing then
                    self.dirty = true
                    self:Schedule()
                end
            end))
        end)
        if not success then
            root:Destroy()
            self.root, self.previewModel, self.previewHandle, self.previewTarget = nil, nil, nil, nil
            error(failure)
        end
        self:SelectPreview()
        self:Status("拖动“拖动此物品”模型：移动 / 旋转；不吸附、不自动决定位置")
        return true
    end

    function self:ApplyPose(reason)
        if not self:CanEdit() or self.writing then
            return false, "NotEditOrNoPreview"
        end
        local expected = self.core.ComputeOffset(self.previewHandle.CFrame, self.previewTarget.WorldCFrame)
        local markerName = self.item:IsA("Accessory") and self.sourceTarget.Name or self.activeMarkerName
        local marker = self.sourceHandle:FindFirstChild(markerName)
        local namedCount = 0
        for _, child in ipairs(self.sourceHandle:GetChildren()) do
            if child.Name == markerName then namedCount += 1 end
        end
        if namedCount == 1 and marker and marker:IsA("Attachment") and closeCFrame(expected, marker.CFrame)
            and (not self.item:IsA("Tool") or self.item.Grip == marker.CFrame) then
            self.dirty = false
            self:Status("挂点已一致；预览未被移动")
            return true, "NoChange"
        end
        local began, recording = pcall(History.TryBeginRecording, History,
            "CharacterItemMountSave", "保存角色物品挂载姿态")
        if not began or not recording then
            self:Status("Studio 正在记录其他操作；松开鼠标后重试或点击保存")
            return false, "RecordingBusy"
        end
        self.ownRecording, self.writing = true, true
        local ok, snapshot = pcall(self.core.ApplyPose, self.item, self.previewTarget,
            self.previewHandle.CFrame, self:Options())
        self.writing = false
        local operation = ok and Enum.FinishRecordingOperation.Commit or Enum.FinishRecordingOperation.Cancel
        local finished, finishError = pcall(History.FinishRecording, History, recording, operation)
        self.ownRecording = false
        if not ok or not finished then
            if ok then
                pcall(self.core.RestorePose, snapshot)
            end
            local message = tostring(not ok and snapshot or finishError)
            self:Status("保存失败：" .. message)
            return false, message
        end
        -- The first successful write owns the entry baseline. Later autosyncs
        -- must not replace it with the immediately previous intermediate pose.
        self.entrySnapshot = self.entrySnapshot or snapshot
        self.dirty = false
        self.syncCount += 1
        self:Status(string.format("已保存 #%d；下次穿戴 / 装备使用此姿态。请正常保存 place", self.syncCount))
        return true, reason or "Saved"
    end

    function self:Schedule()
        if not self:CanEdit() or self.writing or not self.autoSync then
            return
        end
        self.dirty = true
        self.generation += 1
        local generation = self.generation
        local function flush(attempt)
            if generation ~= self.generation or not self.dirty or not self:CanEdit() or not self.autoSync then
                return
            end
            if UserInput:IsMouseButtonPressed(Enum.UserInputType.MouseButton1) then
                if attempt < 300 then
                    task.delay(0.1, function() flush(attempt + 1) end)
                end
                return
            end
            local ok, reason = self:ApplyPose("NativeMoveRotate")
            if not ok and reason == "RecordingBusy" and attempt < 12 then
                task.delay(0.1, function() flush(attempt + 1) end)
            end
        end
        task.delay(0.2, function() flush(0) end)
    end

    function self:SetAutoSync(enabled)
        assert(type(enabled) == "boolean", "enabled 必须是 boolean")
        self.autoSync = enabled
        self.generation += 1
        if self.autoButton then
            self.autoButton.Text = enabled and "自动同步：开启" or "自动同步：关闭"
        end
        -- Turning autosync on does not silently commit an unsaved pose. It starts
        -- with the next deliberate drag; Save is always available explicitly.
        self:Status(enabled and "自动同步已开启；下一次拖动后保存，不会吸附或归位"
            or "自动同步已关闭；可自由试摆，满意后点击“保存当前姿态”")
        return enabled
    end

    function self:RefreshFromTemplate()
        assert(self:CanEdit(), "请先创建编辑预览，并停止 Play")
        local offset = self:ReadTemplateOffset(true)
        self:CancelPending()
        self:MovePreviewInternally(self.previewTarget.WorldCFrame * offset:Inverse())
        self:SelectPreview()
        self:Status("已按模板挂点刷新预览；这是你主动点击的刷新，不是自动归位")
        return true
    end

    function self:MovePreviewInternally(desiredCFrame)
        local wasWriting = self.writing
        self.writing = true
        local ok, err = pcall(moveHandle, self.previewModel, self.previewHandle, desiredCFrame)
        if ok then
            -- Read back engine-normalized components rather than assuming the
            -- requested CFrame survived Model/PivotOffset arithmetic bit-exactly.
            self.ignoreProgrammaticCFrame = self.previewHandle.CFrame
        end
        self.writing = wasWriting
        assert(ok, err)
    end

    function self:ResetEntry()
        assert(self:CanEdit(), "请先创建编辑预览，并停止 Play")
        self:CancelPending()
        local snapshot = self.entrySnapshot
        if snapshot then
            local began, recording = pcall(History.TryBeginRecording, History,
                "CharacterItemMountRestore", "恢复本次挂载编辑初值")
            assert(began and recording, "Studio 正在记录其他操作，请稍后再恢复")
            self.ownRecording, self.writing = true, true
            local ok, err = pcall(self.core.RestorePose, snapshot)
            self.writing = false
            local finished, finishError = pcall(History.FinishRecording, History, recording,
                ok and Enum.FinishRecordingOperation.Commit or Enum.FinishRecordingOperation.Cancel)
            self.ownRecording = false
            assert(ok and finished, tostring(err or finishError))
            self.entrySnapshot = nil
        end
        self:MovePreviewInternally(self.previewTarget.WorldCFrame * self.entryOffset:Inverse())
        self:SelectPreview()
        self:Status("已恢复创建本次预览前的模板挂点与预览姿态")
        return true
    end

    function self:GetSnapshot()
        local result = {
            active = self:CanEdit() and true or false,
            suspended = self.suspended,
            autoSync = self.autoSync,
            dirty = self.dirty,
            status = self.lastReason,
            syncCount = self.syncCount,
            undoCount = self.undoCount,
            redoCount = self.redoCount,
            widgetEnabled = self.widget and self.widget.Enabled or false,
        }
        if self.item then
            result.itemPath = self.item:GetFullName()
            result.itemKind = self.item.ClassName
            if self.item:IsA("Tool") then result.toolGrip = components(self.item.Grip) end
        end
        if self.sourceTarget then result.targetPath = self.sourceTarget:GetFullName() end
        if self.sourceHandle then
            result.sourceHandleCFrame = components(self.sourceHandle.CFrame)
            result.sourceHandleSize = { self.sourceHandle.Size.X, self.sourceHandle.Size.Y, self.sourceHandle.Size.Z }
            local markerName = self.item:IsA("Accessory") and self.sourceTarget and self.sourceTarget.Name or self.activeMarkerName
            local marker = markerName and self.sourceHandle:FindFirstChild(markerName)
            if marker and marker:IsA("Attachment") then result.marker = components(marker.CFrame) end
        end
        if self.previewHandle then result.previewHandle = components(self.previewHandle.CFrame) end
        if self.previewTarget then result.previewTarget = components(self.previewTarget.WorldCFrame) end
        if self.root then result.previewParent = self.root.Parent and self.root.Parent:GetFullName() or "nil" end
        return result
    end

    function self:Destroy()
        if self.destroyed then return end
        self.destroyed = true
        self:EndPreview()
        for _, connection in ipairs(self.connections) do connection:Disconnect() end
        table.clear(self.connections)
        if self.widget then self.widget:Destroy() end
        if self.toolbar then self.toolbar:Destroy() end
    end

    local toolbar = pluginObject:CreateToolbar("角色物品挂载")
    self.toolbar = toolbar
    local toggle = toolbar:CreateButton("CharacterItemMountWorkbench", "手动摆放 Rig 上的物品，再保存挂点", "", "挂载工作台")
    toggle.ClickableWhenViewportHidden = true
    local info = DockWidgetPluginGuiInfo.new(Enum.InitialDockState.Right, true, false, 360, 620, 300, 460)
    local widget = pluginObject:CreateDockWidgetPluginGui("CharacterItemMountWorkbench", info)
    widget.Title = "角色物品挂载 · Rig预览"
    self.widget = widget
    local background = Instance.new("ScrollingFrame")
    background.Name = "Controls"
    background.Size = UDim2.fromScale(1, 1)
    background.CanvasSize = UDim2.fromOffset(0, 690)
    background.ScrollBarThickness = 6
    background.BorderSizePixel = 0
    background.BackgroundColor3 = Color3.fromRGB(30, 36, 40)
    background.Parent = widget
    local y = 10
    local function label(name, text, height)
        local control = Instance.new("TextLabel")
        control.Name = name
        control.Position = UDim2.fromOffset(12, y)
        control.Size = UDim2.new(1, -28, 0, height)
        control.BackgroundTransparency = 1
        control.TextColor3 = Color3.fromRGB(223, 231, 221)
        control.Font = Enum.Font.SourceSans
        control.TextSize = 16
        control.TextWrapped = true
        control.TextXAlignment = Enum.TextXAlignment.Left
        control.Text = text
        control.Parent = background
        y += height + 6
        return control
    end
    local function button(name, text, callback)
        local control = Instance.new("TextButton")
        control.Name = name
        control.Position = UDim2.fromOffset(12, y)
        control.Size = UDim2.new(1, -28, 0, 32)
        control.BackgroundColor3 = Color3.fromRGB(64, 91, 84)
        control.TextColor3 = Color3.fromRGB(245, 245, 231)
        control.Font = Enum.Font.SourceSans
        control.TextSize = 16
        control.Text = text
        control.Parent = background
        y += 38
        table.insert(self.connections, control.MouseButton1Click:Connect(function()
            local ok, err = pcall(callback)
            if not ok then self:Status("操作失败：" .. tostring(err)) end
        end))
        return control
    end
    label("Instructions", "1 选 Rig / 身体 Attachment\n2 选 Tool / Accessory 模板\n3 创建预览，手动移动 / 旋转物品", 64)
    self.rigLabel = label("RigSelection", "Rig / 挂点：未选择", 34)
    button("CaptureRig", "使用所选 Rig / 挂点", function() self:CaptureRig() end)
    self.itemLabel = label("ItemSelection", "物品：未选择", 34)
    button("CaptureItem", "使用所选 Tool / Accessory", function() self:CaptureItem() end)
    label("MarkerHint", "Tool 辅助挂点名（创建前设置；Accessory 使用身体挂点同名）", 40)
    local input = Instance.new("TextBox")
    input.Name = "ToolMarkerName"
    input.Position = UDim2.fromOffset(12, y)
    input.Size = UDim2.new(1, -28, 0, 30)
    input.BackgroundColor3 = Color3.fromRGB(46, 51, 55)
    input.TextColor3 = Color3.fromRGB(245, 245, 231)
    input.Font = Enum.Font.SourceSans
    input.TextSize = 16
    input.ClearTextOnFocus = false
    input.Text = DEFAULT_MARKER
    input.Parent = background
    self.markerInput = input
    y += 36
    table.insert(self.connections, input.FocusLost:Connect(function()
        if self.root and input.Text ~= self.activeMarkerName then
            self:Status("本次预览仍使用旧挂点名；结束预览再创建，才会采用新名称")
        end
    end))
    button("BuildPreview", "创建 / 选中预览", function() self:BuildPreview() end)
    self.autoButton = button("AutoSync", "自动同步：开启", function() self:SetAutoSync(not self.autoSync) end)
    button("RefreshFromTemplate", "从模板刷新预览", function() self:RefreshFromTemplate() end)
    button("SavePose", "保存当前姿态", function()
        local ok, reason = self:ApplyPose("ManualSave")
        assert(ok, reason)
    end)
    button("ResetEntry", "恢复本次初值", function() self:ResetEntry() end)
    button("EndPreview", "结束预览", function() self:EndPreview() end)
    self.status = label("Status", self.lastReason, 76)
    background.CanvasSize = UDim2.fromOffset(0, y + 12)

    table.insert(self.connections, toggle.Click:Connect(function() widget.Enabled = not widget.Enabled end))
    table.insert(self.connections, History.OnUndo:Connect(function()
        self:CancelPending()
        self.undoCount += 1
        self:Status("已撤销；不会立即自动重写。需要时点击“从模板刷新预览”")
    end))
    table.insert(self.connections, History.OnRedo:Connect(function()
        self:CancelPending()
        self.redoCount += 1
        self:Status("已重做；下一次拖动可继续同步")
    end))
    table.insert(self.connections, History.OnRecordingFinished:Connect(function()
        if self.dirty and not self.ownRecording then self:Schedule() end
    end))
    local function updateMode()
        if self.destroyed then return end
        if not Workbench.IsEditorMode() then
            if not self.suspended then
                self:CancelPending()
                self.suspended = true
                if self.root then self.root.Parent = nil end
                self:Status("Play 中暂停：不修改模板；Stop 后恢复同一预览姿态")
            end
        elseif self.suspended then
            self.suspended = false
            if self.root then self.root.Parent = Workspace end
            self:Status("已回到编辑模式；预览姿态原样恢复，未自动写入模板")
        end
    end
    table.insert(self.connections, StudioTest:GetPropertyChangedSignal("EditModeActive"):Connect(updateMode))
    table.insert(self.connections, pluginObject.Unloading:Connect(function() self:Destroy() end))
    updateMode()
    print("[CharacterItemMountWorkbench] Ready: selection-driven R15 Tool / Accessory mounting; no source pose changes")
    return self
end

return Workbench
