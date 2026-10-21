# 明确引用资源下载与独立验收

依赖：Python 3.11+ 标准库。二进制 RBXM 的 LZ4 字符串依赖由随包的只读解析器处理；ZSTD 块可选依赖 `zstandard`，缺少时记录扫描限制，不自动安装。资源内容只作为数据检查，不执行。

`../../templates/download.example.json` 是参数表，不会被脚本自动读取。把表中字段映射为以下实际 CLI；ID 必须与本次 inventory 一致，路径来自当前运行配置。示例从技能目录执行：

```sh
python scripts/downloads/download_assets.py --inventory /private/run/raw-archive/inventory.json --output /private/run/raw-archive/assets --place-id 123 --universe-id 456 --workers 4 --requests-per-second 4 --attempts 3 --timeout 30 --max-asset-mib 256 --content-root /actual/Roblox/version/content
```

`--content-root` 可重复，显式绑定真实安装版本的 content/ExtraContent/PlatformContent 路径；不提供则 builtin 引用记为 local_missing，不猜装机路径。`--max-asset-mib 0` 取消单资源上限；限制同时用于收到的数据和 gzip 解码结果。重试次数有限，429/暂时性 HTTP 错误遵循限流并把单次 Retry-After 等待上限设为 300 秒；401/403/404 直接记录结果，不伪造权限。

工具从 inventory.assets 的 `uri`、可选 `id` 与 `references` 开始，只跟随 JSON/XML/二进制模型字符串字段内的明确 URI 依赖，限制文本扫描 32 MiB。允许数值 assetId、rbxassetid、rbxthumb、显式 rbxasset 安装文件及 HTTPS Roblox/rbxcdn 域名；每次重定向继续检查域名。不会使用 Cookie/账户凭据、猜测资源号、扫描进程内存或浏览器/播放器缓存。未知格式保留 `.bin`，magic/扩展名归类不表示完整媒体结构或 Studio 属性支持已验证。

网络和 builtin 安装文件都经过同一内容关口：空体、HTML 错误/登录页、API 错误 JSON、声明的常见格式与 magic 不符都不能算成功。恢复以前成功文件时也重新检查。此检查仍不是完整图片/音频/模型解码器。

输出：

- `inventory-binding.json` 把输出绑定到本次输入 inventory 的身份和 SHA256。
- `objects/<hash前缀>/<完整SHA256>.<格式>` 保存成功文件；同内容去重。
- `download-progress.jsonl` 保存断点结果，恢复成功文件时先检查实际 SHA256。
- `download-manifest.json`、`download-summary.json`、`download-failures.json` 记录请求/依赖/成功/拒绝/缺失与状态；再次运行保留旧报告，生成带时间后缀的新报告。

相同 inventory 可用原命令继续；身份或 inventory 内容变化需新输出目录，不混用大厅/实战。输出锁表示可能有其他下载进程；核对进程已停止后再由操作者处理旧锁。

正常结束会对自身管理且已为空的 `.partial` 执行非递归 `rmdir`，不会清除非空目录。中断遗留的非空 `.partial` 必须保留检查；打包前复制经过审核的干净 staging，并把未完成文件留在证据目录。不能把暂存片段放进最终项目包。

独立核验必须指定本次实际 manifest，不能把旧报告当新结果：

```sh
python scripts/downloads/verify_downloads.py --root /private/run/raw-archive/assets --manifest /private/run/raw-archive/assets/download-manifest.json --inventory /private/run/raw-archive/inventory.json --place-id 123 --universe-id 456 --output /private/run/download-validation.json
```

该工具从显式 `--inventory` 重算真实输入 SHA256 并核对输出 binding，检查身份、重复 key、请求/状态/字节统计、inventory 每个种子与成功文件依赖的结果记录闭合、成功文件根内路径/大小/SHA256、常见格式 magic 与 HTML/API 错误体，并列出失败和拒绝引用。`integrityPassed` 表示这些一致性检查通过；`allRequestsSucceeded` 另要求没有失败或拒绝引用。默认允许有明确记录的权限缺失；需要零失败时加 `--require-all-success`。报告输出使用独占创建，不能覆盖旧报告。

此分发没有自动字节码常量提取、HLS 分段、暂时签名 URL 刷新、其他大厅复用或缓存恢复脚本。这些属于额外补充任务，未提供不得写成已执行。部分权限失败、未加载内容、引擎动态生成资源、非 URI 字符串依赖必须保留在交接缺失清单。
