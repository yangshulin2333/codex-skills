# 原始归档打包与独立验收 CLI

`scripts/package_archive.py` 是完整工作流最后的打包步骤。它不负责下载 Xeno、Attach、执行采集、下载在线资源或生成有效场景；前面各步骤完成后，把已人工或 AI 审核的资料目录作为输入。运行环境为 Python 3.10+，只使用标准库，可由任何能运行命令的 AI 或人调用。

输入必须保留真实原始证据，至少包括根目录 `README.md` / `README.txt`、一个 `.rbxlx` / `.rbxl` 场景，以及一个非空 JSON 采集元数据。元数据来自采集步骤，不能用空对象代替。脚本不会静默删除唯一 XML 原件，也不会把 XML 改名为二进制 `.rbxl`。

## 创建 ZIP

```powershell
python scripts/package_archive.py --source $archiveSourceRoot --output $packageZipPath --scene-relative-path "snapshot/scene.rbxlx" --metadata-relative-path "metadata.json"
```

所有相对路径以 `--source` 为根，使用 `/`。未传场景路径时，依次识别的候选集合为 `snapshot/scene.rbxlx`、`snapshot/scene.rbxl`、`scene.rbxlx`、`scene.rbxl`；必须恰好命中一个。未传元数据路径时，候选集合为 `metadata.json`、`snapshot/metadata.json`、`archive-summary.json`、`inventory.json`、`manifest.json`；多个候选同时存在时也必须显式选择。

命令中的 `$archiveSourceRoot`、`$packageZipPath` 与后文 `$verifiedStudioExecutable` 先从本机实际配置绑定；没有预设盘符、用户名或 Studio 版本。

`--output` 和它的父目录必须在源目录外；父目录必须已经存在。已有 ZIP、已有验收 JSON 一律不覆盖。源目录及各级路径不允许符号链接、Windows reparse point、越界路径或大小写冲突。发现 `.git`、`__pycache__`、以 `.lock` / `.partial` / `.tmp` 结尾的项目时直接失败；先审查并另建干净的 staging 目录，不要为了通过检查删除唯一原件。

脚本逐个保留输入文件，在 ZIP 内另生成 `archive-metadata.json` 和 `file-checksums.json`。源目录不能已有这两个保留名或 `启动场景.cmd`；需要保留旧报告时先在 staging 内改用清楚的证据名称，并记录来源。校验清单明确排除自身，包含 ZIP 内其余每个文件的大小和 SHA-256。

成功时，标准输出为单行 JSON，包含 ZIP 绝对路径、真实 ZIP 大小与 SHA-256、外置验收 JSON 路径和 `sourceUnchanged: true`。验收 JSON 默认写到 `<ZIP>.verification.json`，包括源文件逐项哈希、源目录前后指纹、CRC、文件集合、全部文件大小和 SHA-256 检查。可用 `--verification-output` 指定另一个新建的外置 JSON 文件。

## 重新独立验收

```powershell
python scripts/package_archive.py --source $archiveSourceRoot --verify-existing $packageZipPath --scene-relative-path "snapshot/scene.rbxlx" --metadata-relative-path "metadata.json"
```

重新验收不修改 ZIP 或源资料，默认新建 `<ZIP>.reverification.json`；再次验收时用 `--verification-output` 给出新的报告路径。`--verify-existing` 不能与 `--output` 或 `--create-launcher` 同时使用。检查会重新从源资料计算哈希，重新读取所有 ZIP 文件数据，而不是只相信 ZIP 中可被一同修改的清单。报告不是数字签名，不能证明资料所有权或来源真实性。

## 可选便携启动入口

只有已经生成并另外验证过的原生 `.rbxl` 才适合加启动入口；同一包内可同时保留原始 XML：

```powershell
python scripts/package_archive.py --source $archiveSourceRoot --output $packageZipPath --scene-relative-path "snapshot/scene.rbxlx" --native-scene-relative-path "scene.rbxl" --metadata-relative-path "metadata.json" --create-launcher
```

解压后在 Windows 上运行 `启动场景.cmd -CheckOnly`，先检查全部清单文件的大小和 SHA-256，以及 Studio 路径；此模式不启动 Studio。正常运行该 CMD 才调用 Studio 的 EditFile 入口打开包内相对场景路径，不执行 Play。

启动入口优先使用用户显式设置的 `STUDIO_EXE` 绝对 `.exe` 路径；否则查找当前环境的 `%LOCALAPPDATA%\Roblox\Versions`、`%ProgramFiles%\Roblox\Versions` 和 `%ProgramFiles(x86)%\Roblox\Versions`。只有一个候选时才自动选择；零个或多个候选都会失败并要求设置 `STUDIO_EXE`，不会猜测版本。

```powershell
$env:STUDIO_EXE = $verifiedStudioExecutable
& ".\启动场景.cmd" -CheckOnly
```

默认打包过程不启动 UI、没有网络、不执行游戏代码、不改系统设置、不调整安全策略，也不部署 Roblox 内容目录。可选 CMD 的正常启动只请求 Studio 打开文件；是否成功加载、资源权限、玩法、服务器逻辑和完全离线可用性仍需按主工作流另行验证。SHA-256 正确不代表 `.rbxl` 语义有效，也不代表 Roblox 支持某种本地资源 URI。

## 失败和测试

失败返回非零退出码，标准错误包含原因。写出 ZIP 后发现失败时，会尽可能写出 `status: failed` 的外置验收报告，并保留已生成 ZIP 便于诊断；该 ZIP 不得交付为通过版本。输入在运行中发生增删改也会失败。开始扫描前的路径、README、元数据等检查失败时，不一定生成报告。不要让编辑器、Studio 或下载程序同时写入 staging；检查不能防御恶意进程在检查与读取之间反复替换文件。

```powershell
python -B -m unittest discover -s tests -p test_package_archive.py -v
```

离线测试覆盖 XML 原件保留、整包哈希、只读重新验收、内容/清单篡改、CRC 损坏、多余条目、路径越界、源文件变化、污染项、符号链接/reparse 属性、原生场景启动入口。在 Windows 上额外运行真实 CMD 的 `-CheckOnly` 分支，并把测试 Python 路径作为显式 `STUDIO_EXE`；此测试不运行该 EXE，也不证明真实 Studio 加载成功。操作系统若不允许创建符号链接，该特定真实链接测试会标记 skip，不能写成已通过。
