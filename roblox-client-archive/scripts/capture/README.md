# 客户端采集与原始导出工具

这些工具接在“核实 Xeno 下载来源、解压、运行游戏、Attach、确认当前客户端”之后。下载/安装 Xeno、界面操作、Studio 打开和保存由完整工作流中的人工或当前 AI 的本机操作能力完成。脚本不安装执行器、不更新偏移、不替换游戏进程。

依赖：Python 3.11+ 标准库；运行生成的 Luau 需要已工作的客户端执行环境及 `readfile/writefile/isfile/isfolder/makefolder/loadstring`。字节码采集另依赖环境的 `getscriptbytecode`，没有时必须记录缺失。不是所有执行器都实现这些 API。宿主检查不需要 Roblox 运行。

## 1. 准备已核实的本地输入

复制 `../../templates/capture.example.json` 到仓库外，填入 `placeId/universeId/runId/xenoWorkspace/toolsDirectory/captureDirectory/clientFullVersion`，以及每个外部输入的本地路径和 SHA256。`toolsDirectory` 与 `captureDirectory` 是 Xeno workspace 内两个不同的、新建的相对目录，例如 `archive_tools_run1` 与 `client_archive_run1`。输入相对路径按配置文件所在目录解析；`null` 和占位值不能直接执行。

外部输入：UniversalSynSaveInstance 的 `saveinstance.luau`、4 个模块及各自许可证，以及与实际 Player 版本对应、包含属性默认值的 Full API Dump。来源由操作者单独核对、下载、检查并绑定哈希；本仓库不捆绑第三方源码、API dump 或 Xeno。历史来源如下，URL 不是固定版本或可信哈希替代品：

- [UniversalSynSaveInstance](https://github.com/luau/UniversalSynSaveInstance)
- [SomeHub：StreamBuffer / UniversalMethodFinder](https://github.com/luau/SomeHub)
- [rbx-algorithms：Base64](https://github.com/daily3014/rbx-algorithms)
- [llz4](https://github.com/RiskoZS/llz4)
- Roblox 安装/部署元数据确认实际版本后，取得对应 `https://setup.rbxcdn.com/<实际version-hash>-Full-API-Dump.json`。

若精确 Player schema 无法取得，替代的同分支 schema 必须另存实际版本映射、来源/hash、采用理由和 `exactPlayerApiMatch=false`，不能把版本化缓存键当作精确匹配。具体判断见 [完整工作流](../../references/full-workflow.md) 第 4 节。

```sh
python scripts/capture/prepare_capture.py --config /private/run/capture.json --check-only
python scripts/capture/prepare_capture.py --config /private/run/capture.json
```

从技能目录执行；Windows 使用本机实际路径。准备器仅校验、复制和生成文件，不发起网络请求、不执行第三方代码。输出在配置指定 workspace 的 toolsDirectory，包含原始 exporter 副本、修改副本、模块/许可证、版本化 API 缓存、5 个本次采集脚本及 `preparation-manifest.json`。该 manifest 为本地运行记录，不上传仓库。

修改器沿用历史成功的 USSI 布局，使用精确源码锚点并在锚点变化时停止，不承诺兼容任意新版本。它把已知模块加载改为本地文件、禁用 API 备用网络请求和 LinkedSource 网络回退、禁用远程反编译、保留能读取的 Source/字节码并记录未知类降级。源码内未执行分支可能仍有上游 URL；“离线适配”不是整份第三方代码已完成安全审计的声明。

## 2. 在当前客户端逐项执行生成的脚本

执行的是 toolsDirectory 内生成并已绑定本次身份的脚本，不能直接执行仓库中的模板。每一步都断言 PlaceId/UniverseId。示例中的路径须换为实际 toolsDirectory：

```lua
assert(loadstring(readfile("archive_tools_run1/diagnostic.luau")))()
```

先独立执行诊断，再按 [连接验证与有条件恢复](../../references/connection-recovery.md) 核对本次 native Attach、诊断写读/身份及 Player token 三项证据。先通过现场观察或可信工具确认输入属于同一 Player；`verify_connection.py` 只核对记录内容，不验证输入的 OS 进程归属或完整门禁，不能仅凭 `passed` 放行。命令和时间参数见该参考；`liveConnectionChecked=false`，不能代替现场进程/场景确认。没有真实诊断文件或 Player 标记时停止，不继续下面的导出。不要把四条命令一次粘贴后仅看最后的 toast。

确认当前会话仍有效后，依次执行并等待每步完成：

```lua
assert(loadstring(readfile("archive_tools_run1/inventory.luau")))()
assert(loadstring(readfile("archive_tools_run1/run_export.luau")))()
assert(loadstring(readfile("archive_tools_run1/terrain_probe.luau")))()
```

| 脚本 | 输入与输出 | 真实验收 |
|---|---|---|
| `diagnostic.luau` | 新建 captureDirectory，写读随机标记与 `diagnostic.json` | 在当前 Roblox 客户端日志观察对应标记，再核对落盘内容；执行器成功 toast 不够 |
| `inventory.luau` | 当前复制对象；写 `inventory.json`、会话状态候选和完成标记 | 身份、实例/资源数量、streaming 状态和脚本能力都要记录；楼层候选不自动视为当前楼层 |
| `run_export.luau` | 本地离线 exporter；写 `scene.rbxlx`、开始/完成记录、类降级报告 | 目标 XML 不得已存在；检查记录与实际字节数、完整 XML 根标签和宿主解析结果 |
| `terrain_probe.luau` | 角色/相机附近一个 64×64×64 studs 小区域 | 记录三通道接口支持情况；退回 ReadVoxels 时缺少独立液体通道，必须保留此限制 |

诊断会新建 captureDirectory，已成功后不要重跑到同目录。会话变化、需要新连接诊断且目录已占用时，保留原目录，用 `prepare_capture.py` 绑定新的 run/capture/tools 目录；不要删掉旧诊断或强行重跑。`terrain.enabled=false` 仅关闭显式范围的 `terrain_capture.luau`，当前 `validate_and_extract.py` 仍要求小范围 `terrain_probe.luau` 的完成记录与双身份；probe 不是全量地形证明。

采集不主动遍历未加载场景、不触发匹配、不读取服务器未复制内容。进入新 Place、实战楼层或等流式加载后，重新绑定独立 run 并分别采集。

## 3. 有地形时按明确范围分块采集

小 probe 为空只证明被测区域；Terrain.MaxExtents/Size/CountCells 都不能证明世界范围。先记录已加载区域证据，再把配置 `terrain.enabled` 设为 true，填测量得到的 `min/maxExclusive/chunkStuds/resolution/captureName`，重新准备新 run。

本适配器支持 resolution=4；边界/分块尺寸必须对齐，单块最多 4,194,304 voxels。使用 `ReadVoxelChannels` 同时保存 SolidMaterial、SolidOccupancy、LiquidOccupancy，接口缺失时失败并记录，不悄悄丢弃液体通道。执行生成的：

```lua
assert(loadstring(readfile("archive_tools_run1/terrain_capture.luau")))()
```

输出 `captureDirectory/terrain/<captureName>`，保留每块索引独立文件、非默认块的无量化 JSON RLE、起止统计与完成记录。索引使用最终 writefile + readfile 回读，避免历史 appendfile 丢索引问题。断线留下原始部分结果，不覆盖旧目录；重采须新 captureName/run。当前分发没有自动合并修复器。

```sh
python scripts/capture/validate_terrain.py --capture /private/xeno/workspace/client_archive_run1/terrain/box-1 --place-id 123 --universe-id 456 --output /private/run/terrain-validation.json
```

验证所有计划块覆盖、坐标、尺寸、顺序、RLE 长度、材料声明、occupancy 数值、重建统计/包围盒、文件集合及 SHA256。仅证明配置中的已读明确范围完整，不证明整个世界；流式加载未复制部分仍可能为空。这个参数化版本做过离线样本测试，尚未在新游戏中实测，必须观察实际采集并重新验收。

## 4. 原件复制与 XML/脚本分离

```sh
python scripts/capture/validate_and_extract.py --capture /private/xeno/workspace/client_archive_run1 --output /private/run/raw-archive --place-id 123 --universe-id 456
```

capture 与 output 必须是互不嵌套的不同目录，output 必须不存在。工具要求诊断写读证据、export_start/export_finish、inventory-complete、类映射记录和双身份 terrain probe；核对版本/身份、输出路径、完成字节数、计数内部一致、Roblox XML 根和解析。按 hash 复制原始 XML/日志/terrain，输出 `snapshot/`、`inventory.json`、`scripts/source/`、`scripts/bytecode/`、索引和 `validation.json`。原始 XML 不改写。已有派生输出也不覆盖。

本次 inventory 同时记录导出范围内与排除引擎树的 classCounts。XML 交叉核对解释排除树、已记录未知类映射及隔离/生成对象差异；未解释的脚本缺失、重大几何丢失或九成以上对象减少会使 `acceptancePassed=false` 并返回非零。其余差异完整列出并标记需人工复核，不把运行中 DataModel 和导出 XML 强制视为完全相等。旧 inventory 没有导出范围计数时按 legacy 基础比较并标明限制；缺生产记录或 probe 双身份时不能直接补“成功”，需重新采集或完成有证据的人工复核。

Source 分类区分可读源码、空、未复制/不可访问、生成说明和反编译占位内容。字节码只从明确 Base64 注释解码成原始 bytes，记录 SHA、头部 hex、首字节版本候选与解码失败；不把首字节当完整结构验收，不解压猜测、不反编译、不执行导出代码。无字节码的服务器脚本不会变成源码。

XML 可解析、RLE 校验或下载 hash 通过，都不能替代 Studio 原生重开/实际显示验收。默认 raw 归档继续补清单与 ZIP 验收；仅在已选择 native 分支时补 `.rbxl` 的 Studio 验收。
