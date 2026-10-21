# 3x-ui：从下载到节点验收的通用工作流

这是供人类及 AI 共同使用的操作规程，不是已部署服务，也不是通用一键安装器。主文档为中文，参数键为英文。它不绑定服务器供应商、账号、端口、域名、安装目录、版本或某一种 AI。

## 给任意 AI 的入口

把本目录完整提供给 Claude、DeepSeek、ChatGPT 或其他能读 Markdown 的工具，发送：

> 先阅读 SKILL.md，再按我的实际目标读取相关 references。先只读发现环境并填写参数，说明你的工具能力和缺失信息。没有我的针对性授权，不扩大变更范围；未执行或未实测的内容标为未验证。最终交付可用配置、脱敏验收结果和交接记录，不公开凭据。

- **不支持 Skills**：作为普通文件上传；也可以复制 `SKILL.md` 和本次需要的 reference。只有仓库链接、没有联网/文件读取能力的 AI，仍需操作者提供正文。
- **支持 Skills**：将整个 `three-x-ui-workflow` 目录放入该工具实际支持的技能目录；具体目录、自动发现方式和调用语法查该工具自己的说明，本工作流不作跨产品假设。
- **只有聊天能力**：AI 给出步骤及预期证据，操作者执行并回传脱敏输出；不要虚报远程操作。

## 交付路线

| 任务 | 起点 | 必需结果 |
|---|---|---|
| 从零部署 | 环境发现、选择 release 和部署方式 | 安全管理入口、持久化、服务健康、真实节点测试 |
| 既有部署升级 | 识别安装、变更说明、恢复点 | 兼容性确认、备份、旧节点回归、回退计划 |
| 加新人 | 明确配额/到期/隔离要求 | 独立身份、正确关联、私密配置交付、真实连接 |
| 加另一条线路 | 确认是否复用原身份 | 指定入站、共享/独立计费语义确认、范围回读 |
| 节点不可用 | 保存原配置并构建失败复现 | 单变量定位、最小修复、同一请求前后对照 |
| 换 AI / 暂停 | 保存当前状态 | 使用交接模板，无秘密，无重复执行 |

## 文件

- [SKILL.md](SKILL.md)：所有 AI 共用的决策入口。
- [installation.md](references/installation.md)：下载、原生与 Docker、管理入口和升级门禁。
- [provisioning-and-acceptance.md](references/provisioning-and-acceptance.md)：客户端/入站、API 能力发现及验收。
- [operations-and-recovery.md](references/operations-and-recovery.md)：诊断、备份、恢复和清理。
- [inputs.example.json](templates/inputs.example.json)：无真实环境数据的参数模板。
- [handoff.md](templates/handoff.md)：跨人/跨 AI 的执行记录格式。
- [sources.md](references/sources.md)：官方来源、核对日期与易变化项。

## 可选本地检查

需要 Python 3.9+，仅标准库；执行前先阅读脚本。无需额外包、账号或网络。

```sh
python scripts/validate_manifest.py templates/inputs.example.json
python -m unittest discover -s tests -v
```

有的系统命令为 `python3` 或 `py -3`，按实际环境替换。

原始模板故意含 `null`，检查器应以退出码 **2** 提示缺失输入；填完整且满足本地约束时为 **0**，文件/JSON 错误为 **1**。检查器不能证明远程 OS 受支持、端口可达、证书可信、备份可还原或代理已通，这些须另行实测。

### 参数含义

| 参数 | 填写原则 |
|---|---|
| `operation` | `inspect / install / upgrade / provision / troubleshoot`，不是自动发现后默认重装 |
| `target.access_method` | `ssh / console / browser / api / manual`；只要求所选方式实际需要的连接信息 |
| `target.*` | 由操作者确认的目标与实际发现值；管理监听、服务名、数据目录不设通用默认 |
| `release.*` | 已发现版本与经过选择/核验的下载来源；原生脚本 commit、资产校验证据与 Docker 镜像 digest 区别记录 |
| `node.inbound_action` | `create / reuse`；复用时填写实际 ID，新建时不能猜一个未分配 ID |
| `node.client_strategy` | `independent / shared`；独立身份与独立入站分别决策 |
| `node.quota_gb / expiry / reset_policy` | `null` 表示未知，不自动转无限；额度 0、`expiry="none"` 仅用于已明确确认无限/无到期的情形。按实际面板核对 GB/GiB、时区及重置语义 |
| `node.minimum_client_version` | `null` 表示本工作流不提出兼容覆盖，不表示写空服务端字段；例外要记录实际值及单独批准 |
| `probe.*` | 用户确认的 HTTPS 目标、预期状态、隔离 loopback 代理及时间预算；不预填固定网站/成功码 |
| `scope.*` | 变更范围与证据引用；写 `true` 是记录已取得的授权，不是替用户授予权限 |
| `secret_refs.*` | 只填私密凭据保管位置/引用；不能填密码、私钥、Cookie、UUID 或完整节点链接 |

检查器不是完整远程 schema/安全审计器，不校验每个产品版本的协议组合或全部敏感信息；它只防止常见遗漏、误把未确认值当默认值及明显秘密载荷。不要上传填过的实际 manifest。

## 完成标准与边界

“文档与本地测试通过”和“某台服务器部署验收通过”分开。最终操作者应拿到：实际版本与安装方式、目标身份及影响范围、私密节点配置、真实请求证据、既有节点回归、备份/回滚范围、未验项。

本目录不含服务器密钥、账号、完整连接链接或生产备份。不需要连接任何作者的服务器，也不依赖 Codex、MCP、特定浏览器插件或记忆目录。使用者须确认其操作授权、当地法律和服务商规则。
