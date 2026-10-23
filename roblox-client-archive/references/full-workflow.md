# 从下载 Xeno 到成功保存本地项目

适用目标是当前 Roblox 客户端已加载、可读且能取得的内容。每一步都执行“确认输入 → 实际动作 → 保存输出 → 独立验收 → 更新交接”；没有证据就保持未完成。本流程不需要特定 AI，具体命令见目录内脚本说明。

## 0. 绑定任务与运行目录

先确定本次是新采集，还是继续某个已归档包。固定用户要求的游戏/场景、需要的阶段、输出根和交付形式。新采集建立唯一 captureId；已有包先检查 artifactId、大小和 SHA256，再创建 derivedId，不因电脑恰好打开另一款游戏而改变输入。

若需主场景与活动/实战场景分开交付，为每项创建角色标签、独立 captureId/派生目录/ZIP，并保存已经完成包的 hash。角色由用户描述与现场依据共同记录；同一个 PlaceId 内也可以存在不同运行态场景。不要把“活动子场景”标签当作独立技术 Place 的证明。按 [多场景交付参考](scene-set-delivery.md) 填写 [场景工作表](../templates/scene-set.example.json)。

检查执行者是否能读取文件、执行进程、访问网络、操作客户端与 Studio。没有能力时由操作者完成相应步骤，回传真实日志/截图/文件；AI 不应把给出步骤说成已经执行。

运行配置、工具二进制、实际日志、游戏资产和 ZIP 统一放共享目录之外。机器路径来自本次发现，不能从历史用户名、盘符、游戏 ID 或版本推导。复制共享模板后填写本地值，原模板保持为空。

建议分开保存：

```text
<LOCAL_ROOT>/config/                  本机参数、run、handoff
<LOCAL_ROOT>/tools/                   本次已核验工具与许可证
<LOCAL_ROOT>/captures/<CAPTURE_ID>/   原始捕获、资源、索引和证据
<LOCAL_ROOT>/derived/<DERIVED_ID>/    仅已选择的派生结果
<LOCAL_ROOT>/packages/               验收通过的 ZIP 及外置验收记录
```

## 1. 从发布来源取得 Xeno

先确认是否已有完整、可用且与当前客户端兼容的 Xeno。缺失或明确需要更新时再下载：

1. 查证当前维护方的真实发布入口及版本说明，记录来源页面、最终下载链接、时间、版本和包装形式。不要把搜索广告、第三方同名下载站或旧聊天中的“最新版”直接当成来源。
2. 下载到独立工具目录，保留下载原包；完整解压其相对依赖、resources 等目录。先读当前包装随附说明，再处理确实需要的运行库。
3. 计算下载原包及关键文件的 SHA256、大小。发布者提供了校验值时比对；自行计算 hash 只能识别文件，不能独立证明来源可信。
4. 记录实际运行的 Player 版本和 version hash。已安装的最新版不一定是正在运行的版本；以当前进程对应文件和日志为准。
5. 启动工具并确认依赖完整。若来源无法核实、hash 不符或当前客户端不兼容，保留诊断并停在准备阶段，不能声称可以导出。

PowerShell 文件识别示例，变量先绑定实际路径：

```powershell
Get-FileHash -LiteralPath $downloadedXenoFile -Algorithm SHA256
Get-Process RobloxPlayerBeta,RobloxStudioBeta -ErrorAction SilentlyContinue |
  Select-Object Id,ProcessName,Path
```

不要在通用脚本里固化旧偏移或补丁字节，也不要以关闭系统防护来代替兼容性诊断。本仓库不分发 Xeno 二进制，不自动下载并执行第三方程序。

## 2. 进入实际地图，核对当前客户端

让操作者进入要保存的地图并等待加载稳定。大厅和匹配后的实战可能是不同 Place，Streaming 或回合生成还会改变可见内容。

读取并记录当前 `game.PlaceId`、`game.GameId`、`game.PlaceVersion`、地图层级、当前回合/楼层、Streaming 状态与时间。未知楼层保持未知；玩家最高楼层、已解锁关卡和模板名称不能冒充当前地图。

同 Universe 不代表同场景。传送、回合替换、客户端重启或版本变化时，停止旧捕获并建立新编号。需要保存某一层时，必须在该层销毁前完成独立捕获。

## 3. Attach 和真实执行诊断

按第 4 节准备本次诊断所需配置与脚本；准备不等于已经 Attach。记录新的 attemptId、带时区的尝试开始时间、当前 Player PID、Place/Universe 和实际工具身份。Attach 后执行生成的唯一诊断，导出前同时核对三项证据：

1. 本次开始时间之后、对应当前 PID 的 native Attach 成功记录。
2. 本次输出目录的诊断文件与写读探针 token 一致，目标身份和已加载状态正确。
3. 当前 Player 日志在本次时间窗中出现同 token 的真实执行标记。

先用现场观察或可信工具记录这些输入属于同一 Player 的依据，再用 [verify_connection.py](../scripts/capture/verify_connection.py) 核验记录内容。它不验证输入的 OS 进程归属，`passed` 不能单独放行导出；报告的 `liveConnectionChecked=false` 也表示没有检查现场活连接。具体参数、时区和失败处理见 [连接验证与有条件恢复](connection-recovery.md)。运行导出前仍要确认绑定的进程与场景未变化。

工具界面“成功”“已执行”或按钮状态不构成最终证据。门禁不通过就停止导出、保留日志和续做状态；区分初始化查找、Attach、本地握手及诊断执行阶段，不能把所有失败都归因于旧偏移。若证据支持状态/时序问题，可尝试参考中的受控冷启动；这会结束游戏，应先复用已有授权，没有授权时说明影响并询问。重新进入同一 Place/Universe 后使用新 PID、新时间窗与新诊断，不沿用旧成功状态。冷启动是条件分支，正常连接时无需强制重启。

客户端读取能力受权限与当前复制范围限制。服务端私有逻辑、尚未加载的地图、不可读属性不能因为 Attach 成功就声称已经取得。

## 4. 准备导出器、API dump 和本次脚本

按 [采集目录说明](../scripts/capture/README.md) 取得当前兼容的 exporter、完整 API dump 及所需依赖。它们是运行时输入，需保存来源、许可、版本、hash 和引擎匹配依据，不使用未审查的动态远程代码。

准备脚本在本地核对这些输入，把兼容版本的依赖本地化并生成本次包装。特定第三方代码的补丁必须与已审核结构精确匹配；不匹配时失败停止，不能把旧补丁强套给未知版本。

若实际 Player 的精确 Full API Dump 不能取得，只能在有版本映射依据时评估同引擎分支 schema，并明确记录实际 schema 版本、来源/hash、差异和 `exactPlayerApiMatch=false`。给缓存写入 Player 版本键不能证明 schema 精确匹配；使用替代 schema 后仍须审查类映射、读取错误和独立对象验收，不能隐去这一限制。

填写 [capture.example.json](../templates/capture.example.json) 的本地副本；确认实际 Place/Universe、唯一 captureId、Xeno workspace、输出前缀与工具 hash。脚本的真实 CLI 见采集 README。完整解压后保持相对结构，客户端 writefile 的路径基准与主机绝对路径分别处理。

若使用高级角色配置，先登记本次工具 artifact-index，再运行 [workflow_config.py](../scripts/workflow_config.py) 的只读 validate。它不会代替 prepare、Attach 或 capture，也不应把未填写模板校验为“已就绪”。

## 5. inventory、场景和原始脚本导出

先在当前会话断言身份一致，再依次采集 inventory 和原始场景。保存启动/完成/pipeline 记录、对象数量、class/属性读取错误、未知映射和实际输出文件。

默认保留当前可读 Source 和编译后 bytecode，不做反编译、远程反编译或 LinkedSource 回退。空占位、导出说明、真实空脚本、服务端未复制、读取失败和有效 bytecode 分开分类。错误文本不能计为字节码。

等待生产任务完成并检查 `.partial`、锁或写入进程后，再复制回主机 capture 根。对实际得到的原件计算 hash；复制前后比大小和 hash。不要在同一 raw 目录反复覆盖失败批次。

会话重连、同 Place 重进或换回合仍可能中断导出。只有 `export_start` 不算完成；必须核对完成标记、实际完整 XML 和身份。旧批次已完成的 inventory/下载结果保留，新批次重新通过连接门禁后采集；跨批次复用时分别绑定各自 inventory hash 和时间，不能描述为同一时刻快照。

原始 XML 是可用于未来重建的输入；没有 `.rbxl` 时不能只改后缀。对象计数相近也不能单独证明所有不可读属性完整。

## 6. 独立解析、提取与身份验收

运行采集目录内的原始导出校验/提取工具：

- 独立解析 XML，记录原 XML 的大小与 SHA256，不在解析时覆盖唯一原件。
- 比对本次身份、inventory、启动/完成记录和实际对象集合；差异分类、解释，不能仅信 exporter 的完成计数。
- 按 referent/fullPath/class 建立脚本索引，保留原始可读 Source、bytecode 原字节/hash、编码/版本及失败状态。
- 验证 bytecode 容器，不把 placeholder、Base64 文本或错误响应当成恢复后的 Lua。
- 对未知 class、导出器限制、缺字段与 decoder 缺口明确记录；解析失败就保留 raw 与错误，先修复再继续。

该步骤仅证明已取得原始数据的结构和来源，不证明原游戏逻辑能在新项目运行。未来恢复源码需要另选派生阶段。

## 7. 资源、依赖与最终缺失

按 [下载目录说明](../scripts/downloads/README.md) 使用本次 inventory 及明确输入，不混用其他游戏 manifest。把 [download.example.json](../templates/download.example.json) 的本地参数表逐项映射成该 CLI 接受的参数；该表不会被下载器自动读取。

规范化请求键：asset ID、内置 URI、thumbnail、明确 HTTP URL 分别处理。assetdelivery/thumbnail 使用对应官方接口；`rbxasset://` 从当前确认的安装 content 根查找；thumbnail 的 ID 不一定是普通资源 ID。

下载器按配置限制并发/速率/超时/尝试次数，流式写临时文件，完成后按内容 magic/MIME 识别类型并计算 hash。错误 JSON、HTML 错误页和未完成文件不能计为成功。429 尊重 Retry-After，网络/5xx 有界退避；明确的 401/403/404 记录最终不可取，不绕过权限或借用凭据。

从已取得容器中的明示 ID/URI 枚举所支持的依赖；新依赖去重后增量下载。未知容器版本和不支持的依赖扫描要记录范围，不能宣称已经发现所有隐藏资源。bytecode 静态线索、缓存关联和 HLS 是有条件的扩展步骤，不因为脚本未实现就填“通过”。

补下载还要检查已完成 XML 中真实的 Content/ContentId/Font 等资源属性，与最新 inventory 引用取并集，再扣除主下载所有已处理请求键（含最终失败）。需要重试失败时另建有界重试记录，不让补充扫描隐式无限重试。当前安装资源、当前公开下载、既有归档精确复用分别计数；历史复用必须有同请求键、原文件 hash、原 manifest/库存绑定与复制后校验，不能计为本次网络取得。不同下载器/本地适配器的 manifest 先按真实 schema 验收，不改名冒充兼容。操作细节见多场景参考。

每个请求最终归为 success 或 missing，并保存尝试历史。success 必须有实际文件、bytes/hash/类型；最终失败与早期曾失败但已补成功的记录分开。统计区分请求条数、引用数、物理文件数和唯一 hash 数量。

动画按实际容器 class/通道分类，资源 ID 或文件名含 animation 不足以证明可播放。HLS 取得 master 清单不等于取得 segment 和离线视频；受限分支停止并记录。缓存仅在 URI/ID/长度等精确关联成立时补充，不按时间或外观猜归属。

随后运行独立下载验收工具，检查根边界、存在性、大小、SHA256、文件格式与清单闭合。任何假成功或 hash 不符先修复，不能带着未解释错误交付。

## 8. Terrain 的实际范围

先保存 Terrain 属性、CountCells、Streaming 状态和玩家/相机附近的明确小探针，记录读取方法。局部空探针不证明全世界为空。

发现非空地形或任务要求完整的指定区域时，定义与网格对齐的 bounds、resolution、chunkSize，按三通道 SolidMaterial/SolidOccupancy/LiquidOccupancy 分块采集。若只能用旧 API，明确 liquid 通道没有独立取得。

每块必须有 index、origin、尺寸、状态、hash；空块也保留索引。独立核对计划/实际集合、缺失/重复、尺寸、RLE 总长度、数值和 material mapping。生产端说“全部完成”不能代替索引集合检查。

缺块独立重读后合并到新的 complete 派生目录，保存两次时间、来源 hash 与重叠比较。只能宣称指定扫描框完整；没有充分证据不得宣称整个世界完整。对应采集能力未具备时记录未覆盖，不把 metadata 或 probe 当成全量地形。

默认保存与验证 raw 通道即可；明确选择 native 地形恢复时再在副本 Edit 场景写回、保存并重开逐通道验证。CountCells 的近似变化不能单独判定数据损失。

## 9. 按需恢复 Luau、提供入口或生成真正的 .rbxl

用户只要 raw 时不强制反编译或打开 Studio。明确选择 Luau 时，在独立派生目录按 [多场景参考](scene-set-delivery.md) 执行严格本地恢复与独立 parse/compile，保留失败和原始 bytecode；按 referent 与原 bytecode hash 回填 `ProtectedString.Source` 的阅读副本，验证差异可重构与回滚。该副本可用 `snapshot/scene_with_luau.rbxlx`，无需先生成 `.rbxl`。

只要求启动入口时，可显式选择已验证的 `.rbxlx` 或 `.rbxl`，见 [打包 CLI](package-cli.md)。只有明确要求二进制原生文件时才做以下转换：

1. 绑定输入 scene/hash、独立 derivedId、输出、转换工具/Studio 角色和版本；只操作副本。
2. 用真实转换工具或 Studio Edit 另存 `.rbxl`，保留原 XML 和保存/转换记录。不启动原游戏脚本或自动 Play。
3. 回读并比较主要服务树、地图、class、Source/脚本对象、关键引用和重要属性；默认项/缓存变化与意外丢失分开。
4. 再次打开最终文件，记录其 hash 和实际编辑模式结果；地形恢复另有通道回读证据。工具解码不了的属性写审计缺口。
5. 只有验收通过的 native 才作为二进制结果交付。XML 启动入口使用独立显式参数，不伪装成 native。下载资源文件不等于场景 URI 已离线重绑；原始玩法恢复单独说明。

已有包仅做 native 时使用独立派生参数，不为通过主配置 validate 而伪选重新采集、源码恢复或预览。

## 10. 形成完整的本地项目

本地项目至少保留：

```text
README.txt / README.md               身份、场景、范围、打开方法、缺失与未测试
snapshot/scene.rbxlx                 原始场景；实际已有native也原样保留
inventory.json                      本次实例、脚本与明示引用
scripts/                            原始Source、bytecode及索引
assets/                             成功文件、依赖、manifest与最终缺失
terrain/                            实际探针/扫描框、通道、索引和验收
tools/ provenance/ diagnostics/      本次工具/许可/hash、执行与会话依据
validation/                         独立解析、复制与下载验证
artifact-index.json                 artifactId、角色、包内相对路径、bytes/hash
snapshot/scene_with_luau.rbxlx        仅选择并验收了 Luau 回填时提供
source-conversion/                   可重构补丁、基线/修改/回滚与失败记录
scene.rbxl                           仅在真正转换并验收后提供
启动场景.cmd                          按需指向显式选择的 .rbxlx 或 .rbxl
```

实际布局可由本次脚本输出适配，必须用相对索引明确说明。README 不能把服务端逻辑、未加载地图、受限资源、未恢复脚本或未测试玩法写成已取得。多个 Place/楼层/回合保持独立快照，不合并覆盖场景树；同资源仅按已验证键/hash复用。

## 11. ZIP 全量验证与交付

运行 [打包脚本](package-cli.md)。打包前确认采集已结束；锁、partial、缓存及符号链接问题先处理，不静默丢掉唯一 raw 或有用失败证据。原件保持不变。

验收包括文件集合、逐文件复制/读回 hash、CRC、每个 ZIP entry 的未压缩大小与 SHA256、整个 ZIP 的 bytes/hash。校验清单排除自身的规则要说明。哈希不符、缺文件、多文件或 CRC 失败均不能交付为通过。

带入口时在完整解压后的包根测试 CheckOnly：验证场景及包内清单、本机 Studio 发现，不启动 GUI。普通启动只请求打开编辑文件；跨机器重新发现 Studio 和依赖。需要实际预览时，完整复制/解压到一次性目录，比较入口和场景 hash 后启动，逐项记录启动、场景加载、渲染预览和 Play 状态。这样 Studio 产生的锁/日志不会污染冻结的 staging。停在登录页只算启动，不能报场景加载通过；一个场景的预览不能替另一个场景验收。

最终报告本地项目和 ZIP 路径、实际场景、入口、范围、最终缺失与未测试项，保留外置验收记录。多场景各自验收并确认旧 ZIP 的 hash 未变。仅选择原始归档时完成后停止；已选择的 Luau、入口或预览在对应派生目录完成独立验收后交付。

## 12. 中断、换 AI 与下一次

将 [handoff.example.json](../templates/handoff.example.json) 的本地副本更新为真实状态，绑定当前对象、最后确认结果、下一动作、输入和验收事件。命令、日志与产物通过 artifactId/hash索引，机器路径只在本机映射。

恢复前检查输入/身份/工具/hash和仍运行的任务；仅继续第一项未完成操作。断网下载先验已成功清单，再补缺失增量；换场景、版本或输入则建立新编号。具体任务提示与状态填写见 [portable-execution.md](portable-execution.md)。
