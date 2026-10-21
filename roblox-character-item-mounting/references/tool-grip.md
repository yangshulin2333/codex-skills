# 配方二：Tool 握持校准

适合可装备、收起、响应点击的斧子、剑、手电筒等。本技能只负责**挂到手上与握持姿态**，不替代攻击命中、动画、伤害或背包系统。

## 先做成这个结构

```text
ItemTemplate (Tool)
└─ Handle (BasePart / MeshPart，直接子对象且唯一)
   └─ MountGrip (Attachment，本工具写入的可选校准标记)
```

1. 插入 `Tool`，将真实网格作为直接子对象命名为 `Handle`。
2. 物理 Tool 使用 `RequiresHandle=true`；多个零件连接到唯一 Handle。
3. 运行时零件 `Anchored=false`、`CanCollide=false`、`Massless=true`。
4. 工作台校准时保留原装备、点击与动画逻辑；先确认它们没有每帧覆盖 Grip。内置 MountCore 发放/拾取示例只处理无脚本刚性模板；带玩法脚本的 Tool 沿用项目原发放逻辑，不剥掉脚本后强行使用示例。

`MountGrip` 是本技能的约定，不是引擎特殊名称。**仅添加同名 Attachment 并不等于完成 Tool 装备。** 标准 Tool 的最终保存字段是 `Tool.Grip`。

## 人只需要拖动

1. 按[操作卡](operation-guide.md)选择 R15 参考 Rig 的 `RightHand.RightGripAttachment`。
2. 选择要保存的 Tool 模板，创建预览。
3. 选中预览物品，用 **移动/旋转** 调握持点和方向。不要拖动原模板、手部 Attachment 或整个 Rig。
4. 开启自动同步时，松手后读取成功提示；关闭时点击 **保存当前姿态**。
5. 如需改大小，先结束预览，显式调整模板比例并重新创建；编辑器默认不会缩放。

不要在正式模板上加一个把物品焊到假人的 WeldConstraint；预览应该能自由移动，保存后再让运行时握持关节跟随角色。

### 不安装插件：原生数值调节

选中实际 Tool 模板，在 Properties 中编辑 `Grip` 的位置与朝向（界面可能展开为分量），再 Play 装备观察；Stop 后继续调数值。不要修改 Play 中的临时副本后以为模板也已保存。

这条原生路线是数值试调，**没有“拖模型后自动同步”的能力**。需要直接在假人上拖动，就安装本技能工作台；它不依赖 AI/MCP 连接。若当前界面不便编辑 Grip，则使用工作台，不编造并不存在的菜单或数值。

## 为什么这样能保存握点

```lua
-- A：摆好的 Handle 世界 CFrame；H：右手握持 Attachment 的世界 CFrame
local grip = A:ToObjectSpace(H)
tool.Grip = grip
-- 工作台还可把相同局部变换写入 Handle.MountGrip，便于检查
-- 根据保存值重建预览：A = H * tool.Grip:Inverse()
```

这里使用的是 **Handle.CFrame**，不是外层 Model 的 Pivot。改变 Pivot 不应悄悄改变握持计算基准。最终效果还要检查实际装备后的握持关节，不能只证明 `Tool.Grip` 写入成功。

当前内置装备配方使用 Roblox 标准右手 Tool 行为。R6、左手装备、双持、自定义关节或动画覆盖需要额外适配；不能通过把 `RightHand` 文本改成 `LeftHand` 就声称兼容。

## 运行时：手侧关节也必须对齐

`Tool.Grip` 记录的是物品侧偏移。**原生装备生成的手侧关节 C0，不保证与该角色的 RightGripAttachment.CFrame 相同**；体型比例等差异可能让“预览正确、装备略偏”。不要靠反向挪预览去掩盖这个差异。

本技能以身体 Attachment 为预览基准，因此运行时关节必须满足：

```text
Part0 = 实际角色的 RightHand
Part1 = 实际装备 Tool 的 Handle
C0 = RightHand.RightGripAttachment.CFrame
C1 = Tool.Grip

RightHand.CFrame * C0 ≈ Handle.CFrame * C1
```

### 内置发放流程

MountCore 的 `Equip` 为新 Tool 克隆绑定 `BindToolAlignment(tool)`，并在首次 `Humanoid:EquipTool` 后等待原生关节就绪再对齐。**Equip 可能 yield**：内部以约 0.05 秒间隔检查，等待上限为 2 秒，只重试“原生关节尚未就绪”，不把其他非法输入当作可重试条件。超时明确报失败，不把“Tool 已经放入角色”伪报为校准成功。

Equip 只有成功时才返回装备实例。首次等待中被收起或换角色，会清理本次克隆并报 `Equip cancelled`，不是返回 nil 冒充成功；调用方应按错误处理，不重复发放无关物品。

后续该 Tool 的 Equipped 事件会发起同样的有界适配。它仅支持无脚本刚性模板；该模板限制不等于要删除已有 Tool 的玩法脚本。实际完成时间仍受 Studio/服务器调度影响，不保证精确到毫秒。

没有现成发放系统时，也能使用 [Accessory 卡中的独立 Play 测试](accessory.md#没有发放系统独立-play-测试)：`Template.Value` 改指向无脚本 Tool 模板，配置 OwnerId/RecipeId；Tool 的身体目标固定为右手，不通过 TargetPartName/TargetAttachmentName 改部位。测试脚本会调用 `Equip`，无需先做拾取点。

### 接入现有攻击 Tool

保留原来的发放、`Activated`、动画和伤害逻辑。在**已有服务器发放流程**中，对实际要发给玩家的 Tool 克隆绑定一次：

```lua
-- core 是项目内已 require 的 MountCore 模块。
-- tool 是实际要发给玩家的 Tool，不是参考 Rig 或 ServerStorage 模板。
local stopAlignment = core.BindToolAlignment(tool)
-- 接着沿用项目原来的放入 Backpack / 装备逻辑，不修改 Activated。
```

如果绑定时 Tool **已经位于角色 Model 下**，绑定器也会发起一次有界适配。已有服务器流程只有在确认原生关节已经存在时，才适合直接调用 `core.AlignEquippedTool(character, tool)`；公开的 Align 方法立即检查/操作，不负责等待。不能假设 EquipTool 刚返回时关节一定已就绪。如果项目原来已按相同合同对齐，就不需要重复适配。

`BindToolAlignment` 只监听这个 Tool 的 Equipped，每次发起有界等待并尝试对齐；中途收起、销毁或换角色就安静取消，不使用常驻心跳或无限重试。超时或非法状态会 warn 失败，需按项目时序适配；它不保证修复所有自定义装备框架。Tool 销毁会自动清理，重复绑定同一个实例不会重复监听。

项目不再需要适配时调用返回的 `stopAlignment()`。它停止后续监听并取消尚未完成的适配，**不还原当前关节 C0/C1**；需要恢复当前姿态时由项目按备份/原装备逻辑处理。收起重装仍应实际复测，不能只以初次装备成功作为验收。

`AlignEquippedTool` 仅在服务器工作：验证活体 Workspace R15、Tool 已位于该角色下、唯一 RightHand/RightGripAttachment；只找连接这只手与这个 Handle 的唯一原生 JointInstance（Weld/Motor6D 等），修改其 C0/C1。它不按关节名字盲选、不新建关节、不改其他 Tool；关节缺失/多匹配或自定义装备系统不符时会报错，需按该项目实际时序或适配器处理。

## 实际装备验证

1. 没有现成发放流程，先用上面的独立 Play 测试。已有系统则确认它接入了运行时关节适配；直接放 StarterPack 只能让工具出生可领取，不等于自动具备本技能的对齐监听。
2. 点击 **Play**。独立测试会自动装备；原游戏按对应背包快捷键或图标装备，不要假设永远是 `1`。
3. 看握持点、刀刃方向和比例是否正确。走、转身、跳跃，装备/收起至少一次。
4. 若已有挥砍动作，播放一次，确认腕部和斧子没有错位。没有动作时如实记录未覆盖，不新增无关玩法。
5. Stop 后继续调整，保存项目。自动同步只写编辑模式模板，不等于自动保存到磁盘/云端，也不承诺更新已经装备的运行时副本。

## 常见问题

| 现象 | 先检查 |
|---|---|
| 预览正确，Play 又回到旧握法 | 是否改的是实际发放模板；生成代码是否仍写固定 Grip |
| 预览正确，Play 有少量固定偏移 | 实际关节 C0 是否等于身体握点 CFrame；不能只检查 C1/Grip |
| 首次正确，收起再装又偏 | 新关节是否重新对齐；重新装备是否绕过原服务器适配 |
| 装备时报原生关节未就绪/超时 | 是否过早直接调用公开 Align；是否存在自定义关节或原生关节未在等待上限内生成 |
| 物品远离手掌 | 是否用了 Model Pivot；本地/世界变换次序是否反了 |
| 整个角色被固定 | Tool 的任一零件是否仍 Anchored；是否残留连到场景的约束 |
| 加了 MountGrip 但没有握持 | Tool、直接 Handle 与运行时装备流程是否存在；Grip 是否被赋值 |
| 静止正常，挥砍不对 | 属于动画/自定义握持系统的合约问题，不能只改静态挂点掩盖 |

官方依据：[Tool 的制作、Handle 与 Grip](https://create.roblox.com/docs/players/tools)、[Tool.Grip](https://create.roblox.com/docs/reference/engine/classes/Tool#Grip)。
