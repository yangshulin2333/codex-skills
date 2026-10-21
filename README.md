# Codex Skills

可复用的 AI Skill。每个 Skill 独立放在同名目录，入口为 `SKILL.md`。

| Skill | 用途 | 入口 |
|---|---|---|
| learning-notes | 学习笔记工作流；具体范围见 Skill 正文 | [SKILL.md](learning-notes/SKILL.md) |
| android-google-services | 让 AI 按设备情况协助检查、安装或修复 Google 服务与 Play 商店（俗称“Google 三件套”） | [SKILL.md](android-google-services/SKILL.md) |
| three-x-ui-workflow | 3x-ui 下载、原生/Docker 部署、独立/共享客户端与入站、真实验收和恢复；不绑定服务器或 AI 平台 | [SKILL.md](three-x-ui-workflow/SKILL.md) |

## 3x-ui 通用工作流

- [使用说明与跨 AI 入口](three-x-ui-workflow/README.md)
- [通用执行规程](three-x-ui-workflow/SKILL.md)
- [无环境绑定的参数模板](three-x-ui-workflow/templates/inputs.example.json)

Claude、DeepSeek 或其他不支持 Skills 的 AI 可直接读取这些 Markdown 文件；
支持 Skills 的工具可按自身规则加载整个目录。无需 Codex、MCP 或特定浏览器插件。
这是有授权边界、版本发现、验收与交接要求的工作流，不是无条件一键安装器。

## 手机 Google 服务 Skill

- [完整 Skill 目录](android-google-services/)
- [原始 ZIP 压缩包](archives/android-google-services.zip)
- 原始 ZIP SHA-256：`dd1e5c4ea7f0f3a3a03f3a49bf16bebf5711d19e816692c865be72c4c9fbe0a9`

将 `android-google-services` 目录放到支持该格式的 AI 工具的 Skills 目录；
也可以让 AI 读取该目录下的 `SKILL.md`。示例请求：

> 使用 android-google-services，先检查我的手机是否支持，再协助安装 Google 服务和 Play 商店。登录、USB 授权和密码由我在手机上完成。

**能力边界：**这是供 AI 使用的安装、诊断和验收工作流，不是独立的一键安装器。
压缩包不含 APK；附带的 Python 脚本只做 ADB 只读预检，不安装组件。
实际执行仍取决于机型与系统支持、可靠安装包来源、网络、AI 可用工具及手机端授权，
不保证所有手机通用。需要账号或密码验证时，由用户在设备上自行完成。

本仓库仅存放通用 Skill；设备序列号、账号、密码、令牌和个人备份不应提交到仓库。
