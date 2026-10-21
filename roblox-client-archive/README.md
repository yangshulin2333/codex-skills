# Roblox 完整客户端归档：从 Xeno 到本地项目

这套目录交付的是完整主线：**下载并准备 Xeno → 连接当前客户端 → 导出场景 → 下载资源和明示依赖 → 校验本地项目 → 生成 ZIP**。明确要求原生文件时，再生成经验证的 `.rbxl` 和便携启动入口。AI 可以是 DeepSeek、Claude、ChatGPT、Codex 或其他助手，不要求专属插件或旧聊天。

从 [SKILL.md](SKILL.md) 或下方主线开始。文档可直接作为普通 Markdown 阅读；上传给聊天 AI 时提供整个目录，不能只给它一个无法访问的仓库链接。

## 完整主线

| 阶段 | 实际要完成的事情 | 资料或工具 |
|---|---|---|
| 1. 下载与准备 | 核对当前 Xeno 发布来源、版本、hash、依赖和当前 Player；缺失才下载 | [完整工作流](references/full-workflow.md) 第 1 节 |
| 2. 当前会话 | 进入要保存的地图，确认 Place/Universe/地图/版本，Attach 后验证真实唯一 print | [采集脚本与顺序](scripts/capture/README.md) |
| 3. 导出准备 | 获得并审核兼容 exporter/API dump，核对 hash，在独立目录准备离线依赖和本次脚本 | [采集配置](templates/capture.example.json) 与 capture 工具 |
| 4. 原始导出 | inventory、scene、已有 Source/bytecode、完成记录、Terrain 实际读取范围 | capture 工具；先保存原件 |
| 5. 原始验收 | XML 解析、身份/完成记录、Source/bytecode 分类与索引 | capture 中的独立解析工具 |
| 6. 资源补全 | 明示资源、已支持且可验证的依赖、有限重试、成功/最终缺失清单 | [下载说明](scripts/downloads/README.md)、[下载配置](templates/download.example.json) |
| 7. 下载验收 | 检查存在性、格式/大小、路径边界与 SHA256 | 下载目录中的独立验收脚本 |
| 8. 可选 native | 对副本转换/Studio 另存 `.rbxl`、重开审计、记录差异 | 完整工作流第 9 节 |
| 9. 项目与 ZIP | 写 README、索引和缺失说明，保留唯一 raw；逐 entry 验证 ZIP | [package_archive.py 使用说明](references/package-cli.md) |
| 10. 交接 | 报告路径、入口、范围、未取得与未测试项，保存下一动作 | [通用任务提示与交接](references/portable-execution.md) |

步骤和验收细节集中在 [references/full-workflow.md](references/full-workflow.md)。导出器/API dump 等外部工具不随本仓库分发，执行前需取得并核验；因此这里是带辅助脚本的完整工作流，不是无需准备的一键下载器。

## 目录和配置

```text
SKILL.md                              AI 发现与执行入口
references/full-workflow.md            从 Xeno 到本地项目的完整主线
references/portable-execution.md        通用任务提示、能力适配和断点交接
references/optional-processing.md      素材库、源码、native 与预览的边界
scripts/capture/                       采集准备、客户端脚本与原始导出验收
scripts/downloads/                     资源下载、依赖与独立验收
scripts/package_archive.py             ZIP、逐文件校验和适用的便携入口
scripts/workflow_config.py             只读配置/角色/索引检查
scripts/asset_library/                 可选素材库整理辅助工具
templates/                            共享空模板；真实配置放目录外
tests/                                离线小样本测试
```

Python 辅助工具以 Python 3.11+ 为基线；命令中的 `python` 要替换为本机确认的 runtime。采集需要兼容的 Roblox/Xeno 环境；只有已选 native/预览才需要 Studio。可选模型解码可能需要经核验的 Lune。每个脚本的实际参数和作用见其所在目录说明及 `--help`，不假设一个配置会自动驱动所有工具。

`templates/config.example.json` 用于严格角色/输入检查；`capture.example.json` 由采集准备器读取；`download.example.json` 是下载参数表，填写后按下载说明显式映射成 CLI 参数，并非下载器的自动 --config 输入。[handoff.example.json](templates/handoff.example.json) 保存接手状态；[artifact-index.example.json](templates/artifact-index.example.json) 是空索引结构，不是已捕获项目。将需要的模板复制到仓库外，填写本机实际值。

## 默认拿到什么

本地项目保留原始 scene、inventory、原始 Source/bytecode 与索引、成功资源/最终缺失、Terrain 读取范围、工具来源和验收记录，另有文件集合/CRC/entry 大小与 SHA256 全量核对的 ZIP。

原生 `.rbxl` 若已取得或选择转换则保留；未生成 native 时，入口是可解析的原始 `.rbxlx` 和 README。仅当 native 通过验收才生成对应启动入口。启动器只打开本地编辑场景；不会自动恢复服务端、播放原玩法或取得其他未加载地图。

素材库、反编译参考源码与预览都在原始包验收后按需处理，原件保持不变。资源下载文件存在不等于场景引用已离线重绑，权限失败也不等于所有对应模型不可用。

## 检查发布目录

在本技能目录运行只读模板检查：

```sh
python -B scripts/workflow_config.py check-template
```

在仓库根运行包含离线测试的完整检查：

```sh
python -B scripts/check_repository.py
```

这些检查不启动 Xeno/Studio、不连接实际游戏，也不证明新机器已完成捕获。实际采集结果必须按完整工作流另行验收。

参数化脚本基于既有导出实践整理，本分发版的验证范围是离线样本、接口和包完整性；尚未重新连接真实游戏复测。导出准备器匹配明确的上游源码结构，不能据此保证当前上游主分支兼容；执行时重新取得、审核并绑定输入 hash，布局不符先停止适配。
