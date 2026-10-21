# 下载、安装与部署

本章只对已经授权的目标给出操作路径。文中变量必须来自环境发现及用户决策；示例不是可直接复制执行的生产配置。默认新装服务端为目标版本支持的 Linux；Windows/macOS 可以是操作端，不表示可直接运行 Linux 原生安装脚本。

## 阶段 A：只读发现

记录操作目标（新装/升级/修复）、连接方式、SSH 用户与端口、可信来源核验的主机指纹、权限提升方式、OS、CPU 架构、磁盘/内存、时钟同步和 DNS。没有 SSH 工具就由操作者执行，不从本地电脑的 OS 推断远程 OS。

POSIX/Linux 只读示例（按系统可用命令选择）：

```sh
uname -s
uname -m
id
if [ -r /etc/os-release ]; then cat /etc/os-release; fi
if [ -r /usr/lib/os-release ]; then cat /usr/lib/os-release; fi
command -v x-ui || true
command -v docker || true
ss -lntup
df -h
```

不要直接发布完整输出。发现已有面板时：识别具体分支（3x-ui、其他 x-ui 分支不能混为一谈）、面板/核心版本、原生服务或容器身份、启动定义、实际持久化位置与管理入口。只做新增节点的任务到此应进入节点工作流，而不是重装。

- 原生：先列出相关服务/进程；再针对发现的 `SERVICE` 读取 `systemctl status "$SERVICE"`、服务定义/工作目录/环境文件。无 systemd 则查实际进程管理器。
- Docker：针对发现的容器读取镜像、网络、端口与 mounts；记录 Compose 项目身份及文件。环境变量可能含 DSN/密码，不将完整 `inspect` 或环境输出写到公开报告。
- 存储：区分 SQLite 与外部数据库。目录和日志受环境变量及工作目录影响，不预填固定数据库路径；面板生成的运行配置不一定是持久化源。
- 网络：记录主机与云侧规则、现有 SSH 入口、管理入口和业务端口；不在只读发现中改变它们。

**通过门禁：**目标唯一、安装方式与实际版本明确、已知冲突和待补信息已列出。未知安装不能按“新服务器”处理。

## 阶段 B：选择并固定来源

1. 查 [官方发布](https://github.com/MHSanaei/3x-ui/releases) 和当前→目标的迁移说明。选择适合系统及架构的版本，不把本工作流复核时的版本当默认安装目标。
2. 记录 release tag、核验后的 commit、资产名称/URL、架构、安装脚本 hash、软件包 hash 或 OCI image digest 及其证据来源。
3. 下载和执行分开。固定脚本 commit 只固定该脚本；它调用的包源、依赖和远程资源仍可能变化，审查时需检查这一点。
4. SHA-256 可检出错包/损坏，但同源 checksum 不是独立签名认证。无法取得可信校验材料时暂停并让操作者决定，不悄悄跳过。

原生脚本下载示例，**此段不安装**：

```sh
: "${UPSTREAM_COMMIT:?先核验官方commit}"
: "${DOWNLOAD_DIR:?选择受保护的下载目录}"
: "${INSTALLER_SHA256:?记录预期脚本hash及来源}"
mkdir -p "$DOWNLOAD_DIR"
INSTALLER_URL="https://raw.githubusercontent.com/MHSanaei/3x-ui/${UPSTREAM_COMMIT}/install.sh"
curl --fail --show-error --location --proto '=https' --tlsv1.2 \
  --output "$DOWNLOAD_DIR/install.sh" "$INSTALLER_URL"
printf '%s  %s\n' "$INSTALLER_SHA256" "$DOWNLOAD_DIR/install.sh" | sha256sum -c -
```

`sha256sum` 不可用时使用系统等价工具；检查退出码，再阅读脚本及确认后续资产校验方式。不要直接 `curl | bash`，也不要在不可信 URL 中嵌入凭据。官方脚本的某些版本在 checksum sidecar 不存在时会警告并跳过，必须自行核实实际下载资产的校验结果。

## 阶段 C1：原生安装

适用系统和架构以**选定版本**的官方安装脚本为准，不只列举 Debian 或只使用 `apt`。审查依赖安装、服务创建、数据库迁移与旧文件覆盖的影响。

既有部署先走 [备份/升级门禁](operations-and-recovery.md)；首次部署先确认端口与目录不占用、不覆盖其他服务。不要将日志中的历史“用户同意不备份”延续到本次。

官方脚本首个参数接受 release tag 的版本，完成审查/授权后可按实际权限方式执行：

```sh
: "${PANEL_RELEASE:?已选择的release tag}"
: "${DOWNLOAD_DIR:?已校验安装脚本所在目录}"
# 管理员 shell：
bash "$DOWNLOAD_DIR/install.sh" "$PANEL_RELEASE"
# 非管理员：先确认 sudo 是否可用及授权；使用 sudo 执行上面的同一命令。
```

这不是适用于所有历史版本的参数保证；先核对下载的脚本。捕获私密安装日志、退出码和产生的实际设置，阻止并发安装；不要把初始凭据直接复制到交接或公开截图。

**通过门禁：**版本符合选择、实际服务定义存在、进程/监听健康、数据库与配置可持续保存。安装器退出 0 只是其中一个证据。

## 阶段 C2：Docker / Compose

先检查已有 Docker 与 Compose 及目标 OS 支持；未授权时不安装 Docker、不迁移宿主网络。以选定版本 [官方 Compose](https://github.com/MHSanaei/3x-ui/blob/v3.10.2/docker-compose.yml) 为设计参照，不直接复制它的示例身份、端口或数据库密码。

1. 在用户选择的专用目录准备 Compose；固定已确认的 image digest，记录镜像平台。不要用可变 `latest` 当已固定版本。
2. 持久化实际数据库、配置、证书与所用签发工具状态；若数据库为外部服务，备份方法、依赖与数据卷单独确认。
3. **选择网络模式，不拼接示例：**
   - bridge：明确面板与每条入站所需 TCP/UDP 的宿主发布/绑定；只发布管理端口不会让全部节点可用。限制管理端口暴露来源。
   - host：共享宿主网络，`ports/-p` 不生效，检查宿主冲突和 OS 支持；不是跨平台等价行为。
4. 容器所需路径、内部端口与变量按实际镜像文档确定。不要因为示例有 `NET_ADMIN`、`NET_RAW` 或 Docker socket 就默认授予；根据启用的功能单独评估，避免不必要的 `privileged`。
5. `COMPOSE_FILE`、项目身份与 `PANEL_SERVICE` 都来自本次部署；不要在另一个目录误启动重复栈。

示例操作：

```sh
: "${COMPOSE_FILE:?已审查的compose文件}"
docker compose -f "$COMPOSE_FILE" config --quiet
docker compose -f "$COMPOSE_FILE" pull
# 仅新建且已授权整套依赖时：
docker compose -f "$COMPOSE_FILE" up -d
# 既有栈只更新目标服务，且依赖已验证就绪时，才使用：
# docker compose -f "$COMPOSE_FILE" up -d --no-deps "$PANEL_SERVICE"
```

`config` 非 quiet 输出可能展开秘密。pull/up 属于真实变更，不在发现阶段执行。启动后验证容器状态、挂载与写入持久性；重建/重启持久性测试先确认影响，不能让生产多用户连接被无授权中断。

## 阶段 D：管理入口安全初始化

- 在用户指定的保密交互中设置唯一强凭据；遵守执行工具对凭据、验证码、证书警告的人工接管要求。
- 管理入口用有效 HTTPS 并验证证书；若只使用经核验 SSH 隧道，则管理监听限制为 loopback/受限网络，隧道终点与真实监听必须匹配。
- 不将面板随机路径当认证替代，不默认公开管理端口，不以 `-k` 或关闭主机指纹校验完成验收。
- 云/主机防火墙按实际端口/协议及允许来源最小开放，保留管理 SSH 通道和带外恢复方式。管理面板端口与代理入站端口分别核验。
- 有外部反向代理/CDN时先核对协议是否受支持；不能把管理 UI 可代理推导为任意代理协议可过该层。
- 记录证书续期与实际恢复机制；不在此通用文档中安排未经用户要求的定时任务。

完成本章后进入 [客户端与入站](provisioning-and-acceptance.md)，直到实际终端/代理请求验收。不要停在“窗口已打开”“服务进程存在”或“面板登录成功”。
