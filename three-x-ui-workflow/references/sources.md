# 官方来源与版本边界

复核日期：**2026-10-21**。只读核对官方 GitHub release、固定版本源码/文档及 Docker 文档；没有因编写本工作流而新装、升级或重启任何生产服务器。

下表记录的是文档审查时的版本样本，**不是模板默认值，也不是未来版本保证**。执行者必须先发现实际版本，再核对相应版本资料；官方示例也不能替代目标环境与权限验证。以下内容为摘要，不复制官方脚本或整份手册。

| 主题 | 本次核对发现 | 官方依据 |
|---|---|---|
| 发布与安装器 | 当次最新为 v3.10.2；安装器可接收 release tag，按 OS/架构分支；固定脚本与固定软件包是两件事 | [release](https://github.com/MHSanaei/3x-ui/releases/tag/v3.10.2)、[安装器](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/install.sh)、[README](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/README.md) |
| 供应链 | 资产有 checksum/digest；安装器在某些缺失 sidecar 情形可跳过校验。工作流要求记录校验边界而不冒充签名保证 | [安装器](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/install.sh)、[资产](https://github.com/MHSanaei/3x-ui/releases/tag/v3.10.2) |
| Docker | 官方 Compose 与另一安装例的网络模式不同；持久化、端口和 capability 须根据启用功能设计 | [Compose](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docker-compose.yml)、[安装文档](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docs/content/docs/en/guide/installation.mdx) |
| host 网络 | 与宿主共享网络、端口发布参数不生效；Linux Engine 和支持/启用该功能的 Docker Desktop 有不同约束 | [Docker host networking](https://docs.docker.com/engine/network/drivers/host/) |
| 路径与数据库 | 数据/程序/日志目录可配置；当前版可使用 SQLite 或 PostgreSQL，生成的核心配置不能代替持久化源 | [环境变量](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docs/content/docs/en/reference/env-vars.mdx)、[配置实现](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/internal/config/config.go) |
| 身份和 API | 当前客户端为独立实体；共享关联的修改有传播影响；更新请求并不都具有 PATCH 语义 | [客户端 API](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docs/content/docs/en/reference/api/clients.mdx)、[入站 API](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docs/content/docs/en/reference/api/inbounds.mdx) |
| API 发现与认证 | 固定版本文档描述 cookie/CSRF 与管理员 Bearer token；UI/API 文档地址需含本实例 base path，token不能公开 | [认证](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docs/content/docs/en/reference/api/authentication.mdx)、[API 路由](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/internal/web/controller/api.go)、[schema](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docs/public/openapi.json) |
| 旧版 API | 旧版存在不同的客户端路由/载荷；不能将旧示例直接移植到新服务 | [旧版控制器样本](https://github.com/MHSanaei/3x-ui/blob/v2.8.7/web/controller/inbound.go) |
| REALITY | 空最低版本值的行为随 Xray 版本改变，旧构建可能强制默认下限；较新构建和其他握手要求也不同，不能固定一种修复值 | [面板 REALITY 指南](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docs/content/docs/en/config/reality.mdx)、[Xray 核心实现](https://github.com/XTLS/Xray-core/blob/v26.9.30/infra/conf/transport_security.go) |
| REALITY 目标 | 面板示例域名与较新核心的风险警告可能不一致。按实际核心、可达性和政策选择目标，不照抄示例 | [核心实现与校验](https://github.com/XTLS/Xray-core/blob/v26.9.30/infra/conf/transport_security.go) |

### 如何更新这份工作流

更新时核对 release、安装器参数/校验行为、镜像/网络/持久化、API schema/认证、客户端模型及实际核心兼容性。把变更记为有来源的版本差异，不直接把“最新”替换进默认部署参数。发现资料冲突时，保留冲突说明并以目标实际版本/有效配置和可复现实验确认，不猜测。

跨 AI 可移植性指普通 Markdown、JSON 和可选 Python 标准库检查器可读取/执行；并不承诺所有 AI 都有 SSH、浏览器、联网、文件系统或同等执行权限。
