# 操作卡：把物品摆到假人上，再保存挂点

**你调外观，工作台记住这个姿态。** 不需要每次输入命令，不会替你自动吸附、归位或改大小。

## 一、第一次安装

需要 Roblox Studio。AI 连接/MCP 不是必要条件。

1. 先保存当前项目，建议在测试副本里首次使用。
2. 下载本技能的 [CharacterItemMounting.rbxmx](../assets/CharacterItemMounting.rbxmx)。不要把 GitHub 网页另存为 `.rbxmx`，应下载文件原始内容。
3. 在 Studio 的 Explorer 中选中 `ServerStorage`，通过 **从文件插入 / Insert from File** 导入该模型。
4. 选中导入的插件根对象，从 **插件 / Plugins** 菜单选择 **保存为本地插件 / Save as Local Plugin**，确认保存。不同 Studio 版本的菜单位置可能变化，按操作名称查找。
5. 在插件工具栏找到 **角色物品挂载 → 挂载工作台**。点开后，面板标题为 **角色物品挂载 · Rig预览**。
6. 若还未出现按钮，先看 Output；必要时保存项目后重启 Studio，不能把“文件已复制”当作“插件已加载”。不要为安装本技能擅自改全局调试或权限设置。
7. 确认插件正常后，移除项目中刚导入的安装用模型。插件是编辑器工具，不应随游戏发布；模板和校准数据则保留在项目内。

插件模型与源码应保持一致。需要人工组装时，创建一个 Model，放入以下三个**兄弟对象**，分别粘贴对应文件全部内容，再保存根对象为本地插件：

```text
插件根对象 (Model)
├─ MountCore       (ModuleScript) ← scripts/studio/MountCore.lua
├─ MountWorkbench  (ModuleScript) ← scripts/studio/MountWorkbench.lua
└─ PluginMain      (Script)       ← scripts/studio/PluginMain.server.lua
```

不要把 `PluginMain` 当成游戏的 ServerScript 使用。普通 Script 上下文没有插件对象，不能显示编辑器工作台。官方操作依据：[Studio plugins](https://create.roblox.com/docs/studio/plugins)。

## 二、准备你要改的东西

- 一个参考 **R15 Rig**：可从 Studio 的虚拟形象/Rig Builder 创建，也可用已有参考角色。
- 一个 **Tool 或 Accessory 模板**，其中有唯一、直接子对象 `Handle`。
- Rig 身体部位中的 **Attachment**：比如手的 RightGripAttachment，或头的 HatAttachment。

第一次操作前复制模板作备份。不要拿正在 Play 的玩家角色或场景漂浮展示物代替编辑模式模板。

| 想做什么 | 选什么物品 | 选什么目标 |
|---|---|---|
| 斧子握在手上，可装备/收起 | Tool 模板 | RightHand 内的 RightGripAttachment |
| 帽子随角色佩戴 | Accessory 模板 | Head 内实际存在的帽子挂点 |
| 背饰、脚饰等 | Accessory 模板 | 对应身体部位中的实际 Attachment |

物品只是一个 Model/MeshPart 时，先按 [Accessory](accessory.md) 或 [Tool](tool-grip.md) 配方整理。工作台不负责猜它应该是哪种装备。

## 三、选对象，再创建预览

1. 保持 **Edit 编辑模式**，不要在 Play 中校准。
2. 在 Explorer 中选中 **Rig 身体部位里的 Attachment**，点击 **使用所选 Rig / 挂点**。
   - Tool 选右手握持点。
   - Accessory 选你实际要挂的身体点。
   - 直接选整个 Rig 时，工作台默认找右手握持点；做帽子/背饰请明确选 Attachment，避免用错部位。
3. 再选中 **要保存的 Tool / Accessory 模板**，点击 **使用所选 Tool / Accessory**。也可选择模板的 Handle。
4. 检查面板显示的 Rig、物品与挂点确实是你想修改的对象。
5. 点击 **创建 / 选中预览**。
6. Explorer 中会出现临时模型 `CharacterItemMountPreview`，包含 `参考Rig` 与 **`拖动此物品`**。原 Rig 和源物品的摆放、尺寸不因此改变。

## 四、直接移动、旋转

1. 选中 **`CharacterItemMountPreview → 拖动此物品` 整个 Model**。
2. 用 Studio 顶部的 **移动** 工具拖动，让握持处/贴合处到合适位置。
3. 用 **旋转** 工具调整朝向。需要细调时降低 Studio 自身的移动/旋转步进。
4. 从正面、侧面观察，不满意就继续拖。不要只选多零件物品中的一个零件单独移动。
5. **自动同步：开启** 时，松手后等待面板确认已保存；关闭时点击 **保存当前姿态**。
6. Tool 保存到 `Tool.Grip` 与自定义校准标记；Accessory 保存到 Handle 内与身体挂点同名的 Attachment。

Tool 的标记名输入框默认为 `MountGrip`。如已有自定义标记，应在创建预览前明确改名；创建后再改输入框不影响本轮标记，需要结束后重建。Accessory 不使用这个输入框，仍按身体挂点同名规则处理。

新 Accessory 尚无物品挂点时，初始预览不代表最终摆放，也不会仅因创建预览就改源模板。先人工摆好，再确认自动保存或点击保存。

## 五、这几个按钮有什么区别

| 按钮 | 用途 | 会不会恢复旧握法 |
|---|---|---|
| 创建 / 选中预览 | 创建临时预览，或重新选中当前可拖物品 | 不替你自动决定新姿态 |
| 从模板刷新预览 | 按模板当前保存值重新摆预览 | 会覆盖尚未保存的预览摆放 |
| 保存当前姿态 | 把现在的预览姿态写入所选模板 | 保存，不归位 |
| 恢复本次初值 | 恢复本轮编辑开始时记录的校准值 | **会**，相当于本轮取消修改 |
| 结束预览 | 移除临时假人和预览物品，停止本轮同步 | 不主动撤销已经保存的校准 |
| 自动同步：开启/关闭 | 决定拖动后自动保存，还是手动点保存 | 关闭不等于回滚 |

重新开启自动同步不会立刻提交关闭期间的旧姿态；继续拖动或点击保存才会提交。结束预览会丢弃尚未保存的预览摆放，但保留已经写入模板的字段。

不要把“从模板刷新”和“恢复本次初值”当作“保存”。需要保留当前摆放时先保存，避免丢失未保存姿态。

## 六、真正运行一次

1. 按所选分支配置发放方式：Tool 可在 StarterPack 中测试，但须按[Tool 配方](tool-grip.md#运行时手侧关节也必须对齐)核对运行时手侧关节对齐；Accessory 由服务器复制并穿戴；拾取使用服务器示例。
2. 点击 **Play**。编辑器预览不应进入游戏，编辑器暂停校准。
3. Tool 用背包图标/快捷键装备；Accessory 检查是否穿到正确身体部位；拾取走到提示器旁，按提示的键完成交互。
4. 走动、转身、跳跃，观察物品跟随与碰撞。已有工具动作时再播放一次。
5. 点击 **Stop** 返回编辑模式，检查手动姿态与模板校准仍然正确。
6. 满意后按 Studio 的 **保存项目** 操作。自动同步不是自动云保存。

完整检查项与故障处理见[验收卡](acceptance.md)。

## 没有插件或 AI 不能连接 Studio

**没有 MCP：** 仍可按本卡安装本地插件，然后全程手动点按钮、拖模型；不需要 AI 远程执行。

**也不安装插件：** Accessory 可按[原生属性路线](accessory.md#不安装插件原生属性操作)复制同名挂点并对齐世界位置/朝向，但取决于当前 Studio 是否提供可编辑世界属性；Tool 可按[原生数值路线](tool-grip.md#不安装插件原生数值调节)修改 Grip 后 Play 试调，不提供拖模型自动同步。

AI 应提供对象层级、点击步骤与结果预期；若用户只能手动执行，就等待其 Output/截图反馈。不能把“给了脚本”写成“已在项目中验证”。
