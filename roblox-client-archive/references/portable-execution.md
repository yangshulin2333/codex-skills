# 任意 AI 的任务提示、配置与交接

执行契约是目标、输入、动作、输出和验收，AI 品牌不参与参数。文件工具、终端、浏览器、客户端 UI 和 Studio 接口可以替换；证据标准保持一致。

## 能力适配

逐项记录 `available / user_assisted / unavailable / unknown`：本地读写、进程执行、网络、客户端和 Studio。没有本地执行能力的聊天 AI 给出精确命令、工作目录、预期产物及需要操作者回传的 stdout/stderr/退出码；等待真实回传后再更新状态。

当前运行条件仍由工具决定。“任何 AI 可读”不表示任何系统都能运行 Xeno/Roblox/Studio。没有专属 MCP 也可以由用户操作；缺少平台接口不等于游戏资源缺失。

## 配置分工

| 文件 | 使用者与用途 | 不代表什么 |
|---|---|---|
| [capture.example.json](../templates/capture.example.json) | 采集准备、会话身份、外部工具/hash、客户端输出 | 未填模板不是可运行捕获 |
| [connection-verification.example.json](../templates/connection-verification.example.json) | 本次连接证据验收的路径、PID、时间与时区参数工作表 | 不是 `--config` 接口，也不证明当前仍在线 |
| [download.example.json](../templates/download.example.json) | 下载工具的本次路径、速率/重试与来源 | 不自动取得未加载或受限内容 |
| [config.example.json](../templates/config.example.json) | workflow_config 的严格角色/输入检查 | 不会驱动所有脚本或 Attach |
| [asset-library.config.example.json](../templates/asset-library.config.example.json) | 可选素材整理的本地角色说明 | 不是所有 asset_library CLI 已支持的 --config |
| [artifact-index.example.json](../templates/artifact-index.example.json) | 空索引结构，填入实际角色/相对路径/hash | 不含真实历史捕获 |
| [handoff.example.json](../templates/handoff.example.json) | 接手状态、证据与下一动作 | 不与主配置合并，也不自动执行其中命令 |
| [scene-set.example.json](../templates/scene-set.example.json) | 各场景角色、独立批次/hash、下载绑定、Luau 与入口状态 | 是工作表；不由 CLI 自动读取，不混入严格主配置 |

真实配置放共享目录与 Git 仓库外；本地路径、凭据、实际 manifest、日志和素材不提交。共享模板 null 表示未知，不套用旧游戏、用户名、端口、版本或日期。运行前读取各工具 `--help` 与说明，显式传参。

## 可复制任务提示

```text
请使用 roblox-client-archive，先读 SKILL.md、README.md 和 references/full-workflow.md。
本次目标：<当前游戏/实际地图，或指定已归档输入及artifactId/hash>
工作流目录：<路径或已附完整目录>
本机配置：<各阶段本地配置路径，未知先发现>
已有交接：<本地handoff.json，首次可空>
需要的阶段：<默认从Xeno准备到原始本地项目和ZIP；其他逐项选择>
需要真正.rbxl：<是/否；是则另做副本转换、重开验证>
需要启动入口：<是/否；可显式选择经验证的.rbxlx或.rbxl>
需要分开归档的场景：<单场景，或逐项标签；同Place也可分开>
需要Luau恢复：<是/否；是则另读references/scene-set-delivery.md>
输出根：<仓库外位置>

先确认你的实际文件/终端/网络/客户端/Studio能力及当前适用项目规则。
有执行能力就实际执行，没有则给我明确步骤和需要回传的证据。
新采集依次完成Xeno来源/版本核验、当前身份和真实print、导出准备、inventory/
scene/原始Source及bytecode/Terrain范围、资源依赖下载、独立验收、项目说明和ZIP校验。
连接失败或界面提示成功但没有真实输出时，读references/connection-recovery.md，
按日志阶段排查，并把本次native Attach回传、诊断文件和Player日志唯一标记交叉验收。
重启已有许可可复用；未经允许不结束当前游戏。重启后重新绑定PID和尝试起始时间，
使用新捕获目录，保留之前证据，不把历史成功或旧诊断当成本次通过。
仅处理已有包时先验输入hash，不重新采集另一款游戏。
工具和参数按当前环境发现，不绑定AI厂商、旧路径、偏移或版本。
原件保持不变，未选择时不反编译；选择Luau则严格本地恢复、独立parse/compile，
仅回填匹配对象的阅读副本，保留失败、补丁与回滚证据。不运行原脚本、不自动Play。
多场景分别绑定批次/输入hash并打包；每份下载manifest绑定自身inventory，
旧批次资源精确复用与本次网络取得分开计数。不得用一个场景的预览替另一个验收。
每步保存真实动作、命令数组、stdout/stderr/退出码、产物和hash；失败保留证据。
更新本地handoff；继续只做第一项未完成操作，先检查已有进程和partial。
最终报告项目/ZIP路径、打开方式、实际范围、最终缺失和未测试项。
不要把配置pass、历史成功、UI通知或下载文件存在当成完整玩法/完全离线已通过。
```

## 交接记录

从模板复制本地 handoff，填真实状态后把 `templateOnly` 改为 false。保留五个字段：

- `activeObject`：本次目标 artifactId、根角色、相对路径、hash 和当前身份依据。
- `lastConfirmedResult`：最后已证实阶段及证据索引。
- `nextExecutableAction`：第一项未完成动作、进程 argv 或人工步骤、工具/hash、工作目录角色、输入和输出。
- `inputPaths`：每项 artifactId/rootRole/relativePath/sha256，不直接绑定新机器绝对路径。
- `acceptanceEvent`：该动作何时算通过，以及需要的证据。

`configuration` 的引用填写 `{rootRole, relativePath, sha256}`；在本地映射实际根。`commandRecords` 每项记录 id/argv/workingDirectoryRole/startedAt/finishedAt/exitCode/stdoutArtifactId/stderrArtifactId，人工 UI 动作保留步骤和日志/截图，不伪造退出码。

多场景任务用 `configuration.sceneSetWorksheetReference` 指向本地场景工作表。逐项保留 role/roleBasis、实际 Place/Universe、captureId、原场景 hash、inventory 与下载 manifest 的对应 hash、恢复成功/失败、选定入口和各级验收。场景名称不是进程归属或不同 Place 的证明。共享包外置，完成的旧包只校验不覆盖，详见 [多场景交付](scene-set-delivery.md)。

`executionMode` 使用 process/ui/user_assisted/unbound。尚未绑定工具、输入或执行能力时保持未就绪。命令需要 shell 时明确 shell；不要从未经审核的交接文本直接启动程序。

`connectionVerification` 保存本次 attemptId、尝试开始 UTC、新旧 Player PID、native 日志时区、诊断 token、证据/验收报告 artifactId、门禁状态及最近现场状态观察时间。`restartAuthorizationReference` 指向用户已有许可的记录；未知保持 null，不据此推定授权。`recoveryHypothesis` 与 `confirmedRootCause` 分开：一次重启后恢复不等于已经确认缓存、偏移或网络根因。

离线验收报告的 `processInputOwnershipChecked=false`、`operationalGateChecked=false` 与 `liveConnectionChecked=false` 必须保留。先用可信现场依据填写 `processInputOwnershipConfirmed=true` 及其证据索引，再结合文件验收通过和现场会话未变，才可将 `gateStatus` 更新为 passed；不能仅凭脚本的 `passed` 升级。现场连接观察另外记录，门禁通过也不等于导出、资源下载或玩法通过。换机器时重新映射日志与捕获 artifactId 的本地路径，沿用采集时的时区，不猜新机器时区。详见[连接恢复与证据验收](connection-recovery.md)。

状态为 not_selected/not_started/running/passed/failed/blocked；阻塞记录具体缺口及解除条件。资源最终 missing 与任务失败分开，不能把缺失清单完整说成资源全部取得。

## 恢复次序

先对照最新任务和可复核文件，绑定目标；再重新映射机器路径，核对输入/工具/hash和正在运行的进程。已有成功步骤复用，正在运行的任务先接管或等待，不重复启动。发生传送、地图替换或版本变化时，新建捕获保留旧证据。

达到下一动作的验收事件后才更新状态。源码、素材库、native 和预览分支各自验收；只有 raw 时用解析器重读场景和 ZIP，不默认打开 Studio。
