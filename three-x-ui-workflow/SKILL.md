---
name: three-x-ui-workflow
description: Plan and carry out authorized 3x-ui installation, deployment, upgrades, client/inbound provisioning, troubleshooting, acceptance, and recovery. Discover the installed version and capabilities first; works as plain Markdown without any particular AI tool.
---

# 3x-ui 通用工作流

适用：3x-ui（3X-UI）的下载、新装、既有部署升级、创建独立/共享客户端与入站、故障定位、验收、备份和恢复。不是服务器供应商指南，也不是不经确认的一键安装器。

## 先确定执行条件

1. 明确任务是新装、升级、修复、加用户还是加线路；只操作已获授权的目标及范围。
2. 发现实际系统、CPU 架构、安装方式、版本、服务/容器、数据路径和网络规则。未知值保留为 `null`，不从示例或历史会话猜测。
3. 区分**面板版本、服务器 Xray 核心版本、客户端核心版本**；不能用客户端外壳版本替代核心版本。
4. 先检查本 AI 的工具能力。SSH、终端、浏览器和 HTTP API 是可替换适配器，不是必需的专有工具。只有文本能力时，提供待执行步骤并向操作者索取脱敏结果；绝不声称已经部署。
5. 输入可参考 [参数模板](templates/inputs.example.json)，用 [输入检查器](scripts/validate_manifest.py) 检查适用分支。它只做本地检查，不部署、不连接服务器。

## 按任务读取

- 初次使用或交给另一种 AI：[README.md](README.md)。
- 下载、新装、升级前的环境发现、原生/Docker 分流：[安装与部署](references/installation.md)。
- 新建节点、独立/共享账号、版本化 API、实际连接验收：[客户端、入站与验收](references/provisioning-and-acceptance.md)。
- 故障、备份、回滚、迁移和交接：[运维与恢复](references/operations-and-recovery.md)。
- 证据与暂停/换 AI：[交接模板](templates/handoff.md)。
- 判断版本相关命令是否仍适用：[官方来源与版本边界](references/sources.md)。

## 不可省略的运行约束

- 下载与执行分离；固定经核实的 release/commit/镜像 digest。不要默认执行远程 `latest` 脚本。
- 既有部署在升级、加用户、关联或修复写入前建立适当的一致性恢复点；失败就停止写入。用户明确接受本次跳过备份时，记录风险和无法保证的恢复范围。
- 通过面板或该版本的 API 变更；先核对本机 Swagger/OpenAPI。不要把其他版本的 API 请求或数据库 SQL 直接用于当前服务。
- 添加入站后检查**有效客户端身份与关联关系**；启用开关、端口可达、成功通知都不能替代真正的代理请求。
- “新节点”含义不清时，确认是新线路、新用户，还是原用户的另一条线路；独立身份和独立入站不是同一概念。
- 优先升级不兼容的客户端。降低最低版本、放宽管理入口、改变凭据/权限、生产停服或恢复演练，先说明影响并取得针对性确认；只改目标，不批量放宽。
- 接受 SSH 指纹、登录、密钥、验证码和安全警告时遵守操作者及所用工具的交互规则；没有可信指纹或有效证书就暂停核实，不关闭校验。
- 密码、私钥、Cookie、完整 UUID、订阅链接、数据库、证书和原始日志留在受保护的私密位置；公开仓库只放模板及脱敏资料。
- 不默认停防火墙、清路由、禁用 TUN、重装系统、更新全部服务、重启整机或覆盖已有安装。

## 执行闭环

`发现 → 方案及授权 → 基线/备份 → 最小变更 → 实际验收 → 差异检查 → 私密交付/脱敏交接`

按层记录“已验证 / 失败 / 未验证 / 等待操作者”，不要把任一层的成功外推为全流程成功。至少分别报告：配置、运行服务、外部端口、指定代理的 HTTPS、用户实际客户端、既有节点回归、恢复能力。

写操作超时或响应丢失时，先读取目标是否已创建；不要盲目重试并生成重复账号/入站。只在确认可重试后做有界重试。
