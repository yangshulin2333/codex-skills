# 配方三：ProximityPrompt 拾取后穿戴

这是触发/发放层，不是第三种挂载数学。**先让 Accessory 或 Tool 单独穿戴成功，再接按键领取。**

最小职责划分：

```text
可信模板：要复制给玩家的物品
Visual：地上的展示副本，只管外观
Hitbox + ProximityPrompt：交互位置和按键提示
服务器：校验并复制、穿戴
客户端：可选的漂浮旋转表现
```

## 一、先分清模板与展示

1. 把已经校准的无脚本刚性模板放进 `ServerStorage`。
2. 在 Workspace 创建一个拾取点 Model；插入 `Hitbox` Part，设置 `Anchored=true`、`CanCollide=false`、`Transparency=1`，移动到交互位置。
3. 在 Hitbox 下插入 `ProximityPrompt`。设置 `ActionText`、`ObjectText`、`KeyboardKeyCode`、`MaxActivationDistance`、`HoldDuration`。
4. 创建独立的 `Visual` Model，复制物品外观进去。展示零件可以 Anchored，关闭碰撞。不要移动或发放 Visual，也不要把它当作模板。

示例层级中的名字仅用于说明；提供的脚本通过 ObjectValue 绑定实际对象，不按这些名字查 Workspace。

```text
ServerStorage
└─ 校准好的 Tool / Accessory 模板
Workspace
└─ 拾取点 (Model)
   ├─ Hitbox (Part)
   │  └─ ProximityPrompt
   └─ Visual (Model，仅展示)
```

`HoldDuration=0` 是按一下；大于 0 则按住直到完成。提示器在什么地方，服务器就检查玩家距什么地方，别把它放在不断漂浮的展示零件上。

## 二、连接服务器示例

在 `ServerScriptService` 中创建一个 Folder，按下列结构放置文件与配置。这里是新建测试绑定，不应覆盖已有发放服务。

```text
拾取绑定 (Folder)
├─ PickupEquip (Script) ← scripts/examples/PickupEquip.server.lua
├─ CoreModule (ObjectValue) → 项目内的 MountCore ModuleScript
├─ Template (ObjectValue) → ServerStorage 中的实际模板
└─ Prompt (ObjectValue) → 场景内的实际 ProximityPrompt
```

1. 把 [MountCore.lua](../scripts/studio/MountCore.lua) 作为项目内的 ModuleScript 放在服务器可访问的位置，并让 `CoreModule.Value` 指向它。
2. 把[服务器示例](../scripts/examples/PickupEquip.server.lua)放入上面的 Script。
3. 分别设置 `Template.Value` 与 `Prompt.Value`。不要让客户端传任意模板路径或资产 ID 决定发什么。
4. 在 Script 的 **Attributes / 属性** 中添加下表配置。
5. 在 Prompt 上添加 `MountOwnerId` 与 `MountRecipeId` 两个字符串属性，值分别与 Script 的 `OwnerId`、`RecipeId` **相同**。这一步声明这个提示器属于本绑定。

| Script 属性 | 类型 | 如何填写 |
|---|---|---|
| OwnerId | string | 当前挂载系统的稳定标识，由项目命名，不是玩家账号 |
| RecipeId | string | 该领取配方的稳定标识；同配方用于防止重复叠加 |
| TargetPartName | string | Accessory 的身体部位名，例如 Head；以实际 Rig 为准 |
| TargetAttachmentName | string | Accessory 的同名身体挂点；Tool 使用标准右手配方 |
| CooldownSeconds | number | 同玩家触发间隔，默认 1 秒；允许 0.1～60 |
| MaxDistance | number | 服务器允许距离上限，默认 10；大于 0 且不超过 100，同时受 Prompt 距离限制 |

Accessory 的身体部位/挂点必须显式配置。Tool 不能靠修改这些字符串就变成左手装备。缺配置或挂点不匹配时应查看 Output 中的拒绝原因，不让脚本静默“凑合成功”。

### 内置示例的范围

- 只复制可信、无 Script/LocalScript/ModuleScript 的刚性模板；拒绝未知脚本、骨骼和非刚性机构。它不会帮你剥掉原物品脚本后强行发放。
- Tool 通过标准 `Humanoid:EquipTool` 装备，等待原生关节就绪并对齐后才确认成功；这一步可能 yield，超时会失败。Accessory 通过 `Humanoid:AddAccessory` 穿戴。
- 只替换同 `OwnerId + RecipeId` 标记的已发物品，保留无关帽子、工具和其他系统装备。
- 服务器检查角色、存活、距离、提示器归属与冷却。Prompt 显示出来不等于服务器可以省略校验。
- 当前示例不提供库存扣减、花费、永久解锁、掉线保存或全服唯一拾取。需要这些规则时接入项目原服务。

已有带攻击脚本的 Tool：用工作台保存 Grip，保留原发放/装备与攻击逻辑，并按 [Tool 运行时配方](tool-grip.md#运行时手侧关节也必须对齐)绑定 `BindToolAlignment` 或等价对齐；不要把本示例当作所有 Tool 的通用背包系统，也不要只改 Grip 就承诺实际姿态完全一致。

## 三、可选：让展示物漂浮

1. 把 [PickupFloat.client.lua](../scripts/examples/PickupFloat.client.lua) 作为 LocalScript 放到 `StarterPlayerScripts`。
2. 在该 LocalScript **下面**插入一个 `ObjectValue`，命名为 `Visual`；将 `Value` 指向场景里的独立展示 Model 或 BasePart。
3. 展示物的每个 BasePart 都设为 `Anchored=true`、`CanCollide=false`，再 Play 检查漂浮。

这个客户端脚本只影响展示，不负责权限、发放或角色校准；流式加载导致 Visual 暂时不可见时，还需按项目实际 Streaming 设置处理。

漂浮动画每帧从初始 Pivot 计算，不累积上帧偏移。只对 Visual 操作，不把服务器模板和实际穿戴物锚定到场景。

## 四、Play 后这样验收

1. 点击 **Play**，走向展示点；在合理距离内看到按键提示。
2. 按提示键；如有 HoldDuration，按住到完成。
3. 在服务器侧角色中检查物品已经被复制并正确穿戴。Tool 应真正处于装备状态。
4. 走动、跳跃，检查不被固定在场景中。
5. 重复触发：只保留同配方的一份物品，其他系统物品不应消失。
6. 多人玩法另开至少两个客户端验证：A 触发不应错误发给 B。单人通过不代表多人已验收。

服务器条件测试还应覆盖远距离、角色死亡、Prompt 禁用与快速重复请求；人工没法触发这些输入时，用隔离测试或受控服务调用验证，并明确不是实际按键操作。

官方依据：[ProximityPrompt](https://create.roblox.com/docs/reference/engine/classes/ProximityPrompt)、[客户端/服务器边界安全](https://create.roblox.com/docs/scripting/security/client-server-boundary)。
