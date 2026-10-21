---
name: roblox-client-archive
description: Guide the complete Roblox client-readable archive workflow, from obtaining and verifying Xeno through session checks, scene export, resource downloads, local validation, and ZIP delivery. Includes configurable capture/download helpers and handoff templates; works with any AI or a human operator. Source recovery and preview are separate optional branches.
---

# Roblox 客户端完整归档工作流

用于把**当前客户端已加载、可读取且能取得的内容**保存为有来源、缺失清单和校验记录的本地项目。主线从下载/准备 Xeno 开始，直到场景、资源及 ZIP 验收完成；不是只有素材分类或场景优化。

## 先读什么

1. [README](README.md)：完整主线、文件导航与首次使用。
2. [从下载 Xeno 到本地项目](references/full-workflow.md)：逐步动作、输入、输出和验收。
3. 按当前阶段读取 [采集脚本](scripts/capture/README.md)、[下载脚本](scripts/downloads/README.md)、[打包 CLI](references/package-cli.md)。
4. 换 AI、换电脑或中断续做时读 [通用任务与交接](references/portable-execution.md)。

## 关键决策

- 默认执行 `raw_archive`：保存原始场景、已有 Source、原始 bytecode、可取得资源与 Terrain 读取范围，完成本地项目与 ZIP 后停止。
- 明确要求 Studio 文件时，在副本转换/另存真正的 `.rbxl` 并重开验证，再提供启动入口；原始 XML 继续保留。不要改扩展名冒充转换。
- 素材库、恢复参考源码、清理报错、静态预览、Play 或 Demo，均由用户另外选择，见 [可选派生处理](references/optional-processing.md)。
- AI 品牌不参与运行参数。终端、文件、网络、UI/Studio 接口可替换；只有聊天能力时给操作者明确步骤并等待真实回传，不声称已操作电脑。
- 新采集绑定本次 PlaceId、UniverseId、地图/回合、版本和 captureId。处理已有包则绑定输入 artifactId/hash，不改为采集另一款当前游戏。
- 工具来源、版本、API dump 与编码按当前环境核验；不沿用历史偏移、固定用户名、路径、游戏 ID 或“最新版本”猜测。

## 执行与证据

依次完成：

`任务/环境 → Xeno 下载及来源核验 → 当前会话与真实 print → 导出准备 → inventory/scene/Terrain → 独立解析与脚本原件 → 资源及依赖下载 → 独立下载验收 → 可选 native → 本地项目说明 → ZIP 全量验收 → 交接`

每步记录实际命令/操作、stdout/stderr/退出码、输入/输出 hash 和状态。UI 成功提示、配置通过、下载成功、Studio 可打开、Play 和原玩法恢复分别验收，不能互相替代。仅继续第一项未完成操作；先核对输入、现有进程和 partial，避免重复任务。

## 工具边界

- 本目录提供自有的准备/采集包装、资源下载/验收、配置检查、ZIP 打包与可选素材整理脚本；外部 exporter、匹配的 API dump、Xeno、Studio、Lune 需执行时取得并核验。没有随包附带这些二进制或游戏资产。
- `scripts/workflow_config.py` 是只读检查器，不是调度器；主配置、采集配置、下载配置和交接模板各自独立，不能互相当作已实现的 `--config` 接口。
- 不运行归档游戏脚本；原件只读，修复/恢复/预览另建派生目录。401/403、server-only、未加载地图和不支持的格式如实记录，不尝试绕过权限。
- 第三方工具单独保留其来源、许可和 hash；下载不等于允许执行。公开提交只包含通用文档、空模板和辅助代码，运行配置、凭据、实际 manifest、日志和资产外置。

完成时报告本地项目/ZIP 的实际路径、打开方法、校验结果、保存范围、最终缺失与未测试项。交付包自包含可迁移的相对索引；客户端归档不等于完整服务端工程或离线原玩法。
