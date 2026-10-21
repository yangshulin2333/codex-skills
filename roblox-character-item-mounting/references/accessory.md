# 配方一：Accessory 饰品挂载

适合帽子、背饰、鞋子、始终跟随身体的刚性道具。需要装备/收起的斧子或剑通常选 [Tool 配方](tool-grip.md)。

## 先做成这个结构

```text
ItemTemplate (Accessory)
└─ Handle (BasePart / MeshPart，直接子对象且唯一)
   └─ 与目标身体挂点同名的 Attachment
```

1. 在 Explorer 中插入 `Accessory`。
2. 把真实网格放进去，作为直接子对象并命名 `Handle`；不要只改外层 Model 的名字。
3. 多零件物品保留唯一 Handle，其他零件用 WeldConstraint 等连到 Handle。不要把整个物品与假人焊死后再调姿态。
4. 运行时穿戴零件设置 `Anchored=false`、`CanCollide=false`、`Massless=true`。仅用于校准的副本可以临时固定。

不要为了“整理”删除导入原件。先复制，审查未知 Script/LocalScript，避免穿戴时意外运行外来逻辑。

## 选择身体上的真实挂点

在参考 Rig 中展开目标身体部位，选中其下的 Attachment，再按[操作卡](operation-guide.md)使用工作台。目标由用户选择，不用死记名称。

| 用途示例 | R15 常见部位 | 常见挂点（以实际 Rig 为准） |
|---|---|---|
| 帽子 | Head | HatAttachment |
| 背饰 | UpperTorso | BodyBackAttachment |
| 手持饰品 | RightHand | RightGripAttachment |
| 脚饰 | LeftFoot / RightFoot | 检查该角色实际提供的挂点 |

同名挂点必须位于目标身体零件内。不要把另一个 Accessory 中的同名点误当作身体挂点。重复同名点会造成歧义，先整理或明确目标。

Handle 内若还有另一个能与角色身体匹配的 Attachment，AddAccessory 可能选错身体位置。内置 Equip 会拒绝这种多匹配，不能只看“已经 Parent 到角色”就认为正确；先备份并确认真正需要的挂点，再人工整理多余身体匹配点。普通不与身体匹配的辅助挂点可以保留，工具不会自动删除用户附件。

## 人工对齐的关键动作

1. 把物品预览摆到假人上，用 **移动/旋转** 调到想要的位置。
2. 保持物品外观不动，把 Handle 内的 Attachment 对齐到身体 Attachment 的世界位置与朝向。
3. 保存的是 **Handle 内的本地 Attachment.CFrame**，不是把身体 Attachment 的本地 Position 原样抄过去。

工作台负责第 2、3 步。不连接 MCP 也能安装并操作工作台；**没有 MCP 不等于没有插件**。

### 不安装插件：原生属性操作

这条路线适用于当前 Studio 的 Properties 允许编辑 Attachment 世界数据的情况：

1. 在 Workspace 把 `Handle` 用移动/旋转工具摆到假人上想要的位置。此时不要先把它焊到角色身上。
2. 在 Explorer 中，从目标身体部位复制 Attachment（帽子通常是 `Head.HatAttachment`），粘贴到物品 `Handle` 内，保留同名。
3. 选中**身体里的** Attachment，在 Properties 找到 `WorldCFrame` 下的 Position / Orientation，或界面对应的 `WorldPosition` / `WorldOrientation`，记下世界位置和世界朝向。
4. 选中**Handle 里的**同名 Attachment，将它的对应世界位置、世界朝向设成刚记录的相同值。只改物品 Attachment，不再挪动 Handle。
5. 检查两个挂点在世界中重合并同向；然后按下面的独立 Play 步骤穿戴验证。

**不要复制两者的本地 Position / Orientation**，它们的父零件不同，本地数值相等不代表世界中对齐。若你当前版本的世界属性只读或没有编辑入口，这条原生属性路线不适用；改用本技能插件完成换算，不需要反复输命令，也不要声称所有 Studio 版本都能直接粘贴 WorldCFrame。

数学关系（供 AI/开发者核对）：

```lua
-- A：用户摆好的 Handle 世界 CFrame；H：身体 Attachment 的世界 CFrame
local offset = A:ToObjectSpace(H)
itemAttachment.CFrame = offset
-- 对齐后：A * offset == H
```

Accessory 的物品 Attachment 名字要与身体 Attachment 一致。一个物品挂到左脚、另一个挂右脚是两个独立模板，不要让同一 Handle 同时承担两个独立身体挂点。

## 实际穿戴

1. 把校准好的模板放到项目约定的模板容器。服务器专用资产可放 `ServerStorage`；客户端确需读模型时再考虑 `ReplicatedStorage`。
2. 有现成发放系统时，通过服务器复制模板并调用 `Humanoid:AddAccessory(clone)`；不要移动唯一模板到角色里。**还没有发放系统时，完成下面的独立测试步骤**，不用先做拾取点，也不依赖 MCP。
3. 点击 **Play**，确认玩家角色上出现物品。走、转身、跳跃，检查跟随、穿模和碰撞。
4. Stop 后查看模板校准仍在，再保存项目。不要以 Play 中的角色副本代替编辑模式模板。

使用内置 MountCore 装备时，显式提供 `OwnerId`、`RecipeId`、`TargetPartName` 与 `TargetAttachmentName`。其去重只处理同一归属/配方标记的物品，不清空角色全部饰品。

### 没有发放系统：独立 Play 测试

以下仅用于测试无脚本刚性模板。**它会给本次 Play 的每个玩家自动穿戴测试物品，包含新玩家、已有玩家和重生角色。** 不收钱、不写云数据；不要留在正式游戏中当奖励发放系统。

1. 把已经校准的 Accessory 模板放进 `ServerStorage`，不要再复制场景展示物。
2. 在 `ServerScriptService` 插入 `ModuleScript`，命名 `MountCore`，粘贴 [MountCore.lua](../scripts/studio/MountCore.lua) 的全部内容。
3. 在 `ServerScriptService` 创建一个测试 Folder。在里面新建 `Script`，命名 `TestEquip`，粘贴 [TestEquip.server.lua](../scripts/examples/TestEquip.server.lua) 全部内容。
4. 在测试 Folder 下创建两个 `ObjectValue`，与 Script 并列，不要放在 Script 下面：

```text
ServerScriptService
├─ MountCore (ModuleScript)
└─ 测试文件夹 (Folder)
   ├─ TestEquip (Script)
   ├─ CoreModule (ObjectValue) → 上面的 MountCore
   └─ Template (ObjectValue) → ServerStorage 中校准好的 Accessory
```

5. 选中 `CoreModule`，在 Properties 的 `Value` 中选择上面的 ModuleScript；同样设置 `Template.Value`，指向实际模板。
6. 选中 `TestEquip` Script，在 **Attributes / 属性** 中添加下面四个 **string** 属性：

| 属性 | 帽子测试如何填写 |
|---|---|
| OwnerId | 给当前项目自定一个测试系统标识，不是玩家账号 |
| RecipeId | 给本次物品测试自定一个配方标识 |
| TargetPartName | `Head` |
| TargetAttachmentName | 该 R15 头部实际存在的挂点名，通常是 `HatAttachment` |

7. 点击 **Play**，不要只点 Run。无需走近或按 E，脚本会复制模板并穿戴到角色上。Output 成功时显示 `Mount test equipped: Accessory`；失败显示 `Mount test failed:` 后跟原因。
8. 检查帽子位置、移动跟随与碰撞，再点击 **Stop**。测试后删除整个测试 Folder；`MountCore` 只有项目其他逻辑仍需要时才保留，不能误删其他系统的模块。

改测背饰或其他部位时，修改的是最后两个属性与模板 ObjectValue，不复制玩家名或固定场景路径。单独穿戴已通过后，才继续接[拾取配方](pickup-equip.md)。

## 成功与失败

- **成功**：真实角色上的外观相对位置与参考 Rig 一致；跟随运动，不卡住角色。
- **穿上但歪了**：先查是否混淆本地/世界 CFrame，再查模板与角色体型、同名挂点及是否有运行脚本覆盖。
- **穿不上**：查容器类型、唯一直接 Handle、身体同名点；查看 Output，不能只凭“Parent 在角色下”判断成功。
- **角色不能移动**：查每一个 BasePart 的 Anchored/碰撞属性及残留外部约束。

官方依据：[Accessory](https://create.roblox.com/docs/reference/engine/classes/Accessory)、[Humanoid:AddAccessory](https://create.roblox.com/docs/reference/engine/classes/Humanoid#AddAccessory)。本配方仅处理刚性挂载，不处理分层服装的包裹变形。
