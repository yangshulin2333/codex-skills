---
name: roblox-character-item-mounting
description: 在 Roblox 中将刚性物品对齐并挂载到角色，支持 Accessory 饰品、Tool 握持和 ProximityPrompt 拾取穿戴；包含假人手动拖动校准、原生 Studio 操作卡及可选插件。用于帽子、背饰、鞋子、武器等，不用于分层服装、骨骼蒙皮或动作制作。
---

# Roblox 角色物品挂载与对齐

把物品挂到角色上的通用知识点：**选择物品和身体挂点 → 在假人上手动摆好 → 保存相对偏移 → 实际穿戴验证。**

位置和角度由用户决定。工具负责记录和应用，不自动吸附、归位、缩放或替用户选择握法。

## 选择一个分支

| 用户想做什么 | 分支配方 | 保存与应用方式 |
|---|---|---|
| 帽子、背饰、脚饰或始终佩戴的刚性物品 | [Accessory](references/accessory.md) | Handle 内的同名 Attachment；服务器 `Humanoid:AddAccessory` |
| 斧子、剑等可装备/收起的物品 | [Tool 握持](references/tool-grip.md) | `Tool.Grip`；标准右手关节与身体挂点对齐 |
| 靠近展示物，按键后领取/穿戴 | [拾取穿戴](references/pickup-equip.md) | 触发层调用前两者，不另造挂载规则 |

给人讲解或安装编辑器时先读[操作卡](references/operation-guide.md)；验收、回滚和排错读[验收卡](references/acceptance.md)。只加载当前分支需要的细节。

## 执行前绑定

从用户所选对象或明确的项目路径确认以下输入，不能把示例名当作实际对象：

- `ITEM`：需要保存的 Accessory 或 Tool 模板；不把临时展示副本当模板。
- `RIG`：用于校准的参考角色；与运行时角色体型、比例尽量一致。
- `TARGET_ATTACHMENT`：Rig 身体 BasePart 内实际存在的 Attachment。
- `MODE`：Accessory / Tool / 拾取；拾取还需要可信模板与 Prompt。
- `SAVE_DESTINATION`：模板、插件或项目的保存位置。

存在多个候选且无法唯一确定时，先请用户选择。不要按玩家名、PlaceId、资产 ID 或某个固定游戏对象查找。

## 关键约束

1. 统一的是相对变换原理，不是 API。Accessory 使用同名挂点；Tool 保存 Grip，并核对运行时手侧关节 C0 与身体握点一致。插件的 `MountGrip` 只是自定义校准标记，Roblox 不会因它同名而自动完成 Tool 握持。
2. 先保存项目/复制待修改模板，记录 Grip、Attachment CFrame 与物理属性。只改用户指定模板，不删无关装备或脚本；外来模型脚本先审查。
3. 当前辅助实现面向刚性、唯一 Handle 的物品与 R15。其他 Rig、左手 Tool、自定义装备框架先检查实际挂点/关节合同，不声称自动兼容。
4. 不默认改比例。多个零件必须连接到 Handle；缺失、重复或有歧义的挂点应报错，不能静默选第一个。
5. 校准仅在 Edit 模式。真实穿戴零件不 Anchored、不碰撞；场景展示副本和临时预览可以 Anchored，两者不要混用。
6. 发放/穿戴由服务器校验玩家、角色存活、可信模板、距离和频率；客户端漂浮动画只负责表现。示例不是交易、持久化或完整背包系统。

## 可执行资源

- [原生插件模型](assets/CharacterItemMounting.rbxmx)：导入并保存为本地插件后，使用 Studio 选择对象与移动/旋转工具；源码仍是维护源。
- [MountCore.lua](scripts/studio/MountCore.lua)：相对变换、校准、恢复、复制准备、服务器装备与拾取绑定。内置发放只接收无脚本刚性模板；已有攻击 Tool 保留原发放/玩法脚本，复用校准并按 Tool 配方接入 `BindToolAlignment` / `AlignEquippedTool` 或等价适配。模块不含编辑器 UI。
- [MountWorkbench.lua](scripts/studio/MountWorkbench.lua) 与 [PluginMain.server.lua](scripts/studio/PluginMain.server.lua)：仅 Studio 插件上下文，不能当作游戏运行脚本。
- [独立穿戴测试](scripts/examples/TestEquip.server.lua)：没有现成发放系统时，用 ObjectValue 绑定模板和模块即可 Play 自动穿戴；测试后移除，不依赖拾取配方。
- [拾取服务器示例](scripts/examples/PickupEquip.server.lua)、[可选漂浮示例](scripts/examples/PickupFloat.client.lua)：通过 ObjectValue 指定依赖，不依赖固定场景路径。
- [build_plugin.py](scripts/build_plugin.py)：Python 标准库离线生成原生插件模型；`python scripts/build_plugin.py --check` 只检查模型能否由当前三份 Luau 源码复现，不修改文件。它不验证插件已加载或运行效果。

没有 Studio 连接/MCP 时，按操作卡让人操作，或交付可审查源码；不要伪称已经修改或运行。支持读取普通 Markdown 的 AI 可以使用本技能，自动发现与工具调用取决于其宿主环境。

## 完成标准

至少在真实 Play 中确认：摆好的相对姿态一致、移动时跟随、角色不卡住；Tool 还要装备/收起，拾取还要实际完成 Prompt 交互并检查重复领取。模型能加载、源码编译、数值公式通过都不能代替这些结果。

交付时列出改动对象、分支、保存的字段、执行结果、回滚方式和未验证范围；按[验收卡](references/acceptance.md)留下可复查证据。安装插件、生成预览、自动同步、保存项目、重启加载是不同状态，分别报告。
