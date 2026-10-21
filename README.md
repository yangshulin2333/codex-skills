# AI Skills 与工作流

按任务选择一个技能，先读 `SKILL.md`，再按需读取引用资料。可供人类及能读取文件的 AI 使用，不绑定某一种 AI 平台。

## 选技能

| 你要做什么 | 技能入口 | 需要提供 |
|---|---|---|
| Roblox 功能知识点：把刚性物品挂到角色身上、在假人上调整握持，或靠近拾取后穿戴 | [roblox-character-item-mounting](roblox-character-item-mounting/SKILL.md) | 物品与参考 Rig、目标身体挂点；[人类操作卡](roblox-character-item-mounting/references/operation-guide.md) |
| 将教程、文章或多份笔记整理成中文学习笔记 | [learning-notes](learning-notes/SKILL.md) | 可读取的正文、字幕或笔记；不自带视频抓取/转写 |
| 检查、安装或修复 Android Google 服务与 Play 商店 | [android-google-services](android-google-services/SKILL.md) | 设备与系统情况；可用工具或人工操作配合 |
| 下载部署 3x-ui、创建节点、排障和恢复 | [three-x-ui-workflow](three-x-ui-workflow/SKILL.md) | 实际目标、环境与授权；[详细说明](three-x-ui-workflow/README.md) |
| 从下载 Xeno 开始，导出 Roblox 客户端内容、下载资源、校验并生成本地项目和 ZIP | [roblox-client-archive](roblox-client-archive/SKILL.md) | 当前客户端或已验证原始包、本机执行能力；[完整工作流](roblox-client-archive/references/full-workflow.md) |

## 怎么用

1. **支持 Skills 的工具**：按该工具的规则加载所选技能的完整目录，不只复制 `SKILL.md`。
2. **普通聊天 AI**：上传所选目录，或提供它确实能读取的文件；先读入口，再按引用读取所需资料。无法联网时，只贴仓库链接不够。
3. **通用请求**：

   > 请使用【技能目录名】。先读取其中的 SKILL.md，再按我的需求读取必要资料。缺少环境信息先核实，没有执行能力或尚未实测的部分请明确说明。

工作流不是一键安装器。AI 是否能实际操作取决于工具与授权；本地检查通过不等于手机、服务器或代理已验收。不要上传账号、密码、私钥、令牌、订阅链接或个人备份。

## 目录约定

- 每个技能独立放置，`SKILL.md` 是入口；参考资料、脚本和模板按需放在该技能目录内。
- [archives](archives/README.md) 只保留原始分发快照；日常使用以技能目录为准，不自动与 ZIP 同步。
- [scripts/check_repository.py](scripts/check_repository.py) 只检查仓库完整性及已有本地测试，不连接设备或服务器。

## 维护

在仓库根目录运行 `python scripts/check_repository.py`（Python 3.9+，仅标准库；按环境使用 `python3` 或 `py -3`）。

检查入口、首页收录、相对链接、Python 语法、归档摘要和各技能已有单元测试。新增或更新技能见 [CONTRIBUTING.md](CONTRIBUTING.md)。保留现有路径，避免旧链接失效。
