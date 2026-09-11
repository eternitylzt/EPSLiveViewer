# EPS Live Viewer

[简体中文](README.md) | [English](README_EN.md)

EPS Live Viewer 是面向科研绘图快速迭代的轻量级桌面查看器。它可打开 EPS 和 PostScript（PS）文件；当 IDL、Python、MATLAB、Fortran 等程序重新生成当前文件后，预览会自动更新。Windows 版本保持原有稳定用法，仓库现已具备 Linux 和 macOS 的构建、配置与发布基础。

## 主要功能

- 打开 `.eps`、`.ps` 文件：菜单、命令行、Windows“打开方式”或直接拖入预览区域。
- 自动检测当前文件变化并刷新，支持文件被覆盖、短暂占用或延迟写入的常见工作流。
- 矢量源预览：放大时按当前视野重新绘制路径和文字，而非放大固定 DPI 的截图。
- 自动识别同一文件夹内按文件名排列的 EPS/PS；按左右方向键即可前后翻看比较。
- 多页 EPS/PS 使用上下方向键翻页，状态栏显示当前页码；PNG 导出保存当前页。
- 鼠标滚轮缩放、拖动平移、双击恢复 100%、`Ctrl+0` 适应窗口。
- 滚轮可设置为缩放、切换相邻文件或仅翻页；后两种模式下 `Ctrl+滚轮` 始终用于缩放。
- 窗口顶部工具栏提供打开、刷新、切换文件、翻页、缩放、适应窗口和保存 PNG 按钮。
- 界面支持简体中文与英语，可在设置中即时切换，无需重启。
- 设置透明棋盘格、白色或自定义预览背景。
- 仅导出 PNG；每次导出可选择 72–600 DPI，并可保留透明背景或合成到背景色。
- 将文件夹中的 EPS、PS、PNG、JPG/JPEG 制作成 MP4 或 GIF，可排除文件、调整帧序、分辨率、帧率和背景色，并通过首帧预览框选局部区域。
- 保存最近打开的 10 个文件。

## 平台支持

| 平台 | 发布形式 | 当前状态 |
| --- | --- | --- |
| Windows x64 | 单文件 `EPSLiveViewer.exe` | 主要开发与验证平台，原有用法不变 |
| Linux x64 | 单文件 `EPSLiveViewer` | 可移植基础版本，需桌面环境与系统 Ghostscript |
| macOS Apple Silicon / Intel | `.dmg` 安装镜像，内含 `EPSLiveViewer.app` | 两种架构的可安装版本，当前未使用 Apple Developer 证书签名或公证 |

三个平台的安装包可从 [GitHub Releases](https://github.com/eternitylzt/EPSLiveViewer/releases) 下载。Linux/macOS 版本由 GitHub Actions 在对应原生系统上构建，属于初始移植版本；欢迎通过 Issue 反馈平台相关问题。

## 使用方法

### 1. 环境要求

Windows 可直接运行 `EPSLiveViewer.exe`；Linux 为可执行文件 `EPSLiveViewer`。macOS 请按处理器下载 Apple Silicon（M 系列）或 Intel 版 `.dmg`，打开镜像后将 `EPSLiveViewer.app` 拖到 `Applications` 文件夹。安装后可将 `.eps`/`.ps` 设为由本工具默认打开，Finder 的“打开方式”会把文件直接交给已经启动或新启动的应用。

发布包不要求安装 Python。预览 EPS/PS 或将其制作成视频时需要系统 Ghostscript：Windows 自动查找 `gswin64c.exe`，Linux/macOS 自动查找 `gs`；未识别时，请在“文件 → 设置”中手动选择。仅使用 PNG/JPG 制作视频不需要 Ghostscript。

### 2. 打开文件

可使用“文件 → 打开 EPS/PS”，也可将 `.eps` 或 `.ps` 文件拖入中央预览区域。Windows 命令行示例：

```powershell
.\EPSLiveViewer.exe "D:\plots\figure.ps"
```

如需双击打开，可在系统中为 `.eps` 或 `.ps` 文件关联 EPS Live Viewer。Windows 可在“打开方式”中指定 `EPSLiveViewer.exe`。

### 3. 实时查看

打开绘图程序生成的文件后，继续运行绘图代码即可。文件重新写入完成后，EPS Live Viewer 会自动生成新预览，并尽量保持当前缩放与平移位置。

同目录中的 EPS/PS 会按文件名自然排序。按 `←` 打开上一个文件，按 `→` 打开下一个文件；状态栏会保持显示当前文件名和 `[当前位置/总数]`。切换时会重新扫描文件夹，因此新生成的相邻文件也会自动加入序列。

多页 EPS/PS 按 `↑`、`↓` 切换上一页和下一页；单页文件不会响应翻页。滚轮默认缩放，也可在“文件 → 设置”中改为相邻文件或翻页模式。方向键功能不受滚轮设置影响。

### 4. 导出 PNG

选择“文件 → 另存为 PNG”，指定保存位置和本次 DPI。导出直接由源 EPS/PS 文件生成，不受当前窗口缩放或平移影响。

### 5. 制作 MP4/GIF

选择“文件 → 制作视频/动图”，再选择源文件夹。程序会按文件名把该文件夹内支持的文件放入左侧“参与视频”列表：

- 选中左侧文件并点“排除 →”，可移到右侧而不参与输出；点“← 加回”可恢复。
- 左侧列表支持拖动排序，也可用“上移/下移”改变帧序。
- 首帧为 PNG/JPG 时，画布会自动使用它的实际像素尺寸。首帧改变后会重新读取尺寸。
- 点“预览并选择区域”，在首帧上按住鼠标左键拖拽并确认，即可只输出框选部分；点“恢复完整图像”可取消裁剪。
- 设置 MP4 或 GIF、画布分辨率、帧率、背景色及输出路径后，点“开始生成”。

裁剪区域记录为相对于首帧宽高的比例。后续图片即使分辨率不同，也会在各自相同的比例位置裁剪，然后保持长宽比并居中放入统一画布。EPS/PS 取第一页生成帧。MP4/GIF 编码器已包含在发布包中；但预览或处理 EPS/PS 帧时仍需要 Ghostscript。仅使用 PNG/JPG 制作视频则不需要 Ghostscript。

## 常见问题

### 提示“未找到 Ghostscript”

请安装 Ghostscript。Windows 应在设置中选择命令行程序 `gswin64c.exe`，不要选择带窗口的 `gswin64.exe`；Linux/macOS 选择 `gs`。macOS 通过 Finder 启动时可能没有终端的 PATH，程序也会检查 Homebrew 常用位置。

### 配置文件保存在哪里

为保持兼容，Windows 发布版仍使用 EXE 同目录的 `config.json`。Linux 使用 `$XDG_CONFIG_HOME/EPSLiveViewer/config.json`（未设置该变量时为 `~/.config/EPSLiveViewer/config.json`），macOS 使用 `~/Library/Application Support/EPSLiveViewer/config.json`。

### macOS 提示无法验证开发者

若 Release 标注为未公证版本，首次启动时需在 Finder 的“应用程序”中按住 Control 点击 EPS Live Viewer，选择“打开”，再确认一次。彻底消除此提示需要 Apple Developer ID 证书签名和 Apple 公证；仓库发布流程已支持在配置证书后自动签名、公证和装订凭据，但无法用免费临时签名替代 Apple 的信任链。

### 文件刚生成时没有立即刷新

程序会等待文件写入稳定后再刷新。若文件位于网络盘或写入时间较长，可在设置中把检测间隔提高到 800–1000 ms。

### 放大时短暂不够清晰

停止连续缩放后，程序会按当前缩放比例重新绘制可见区域。EPS/PS 中原本嵌入的照片或位图仍受原始像素数量限制。

### 透明背景显示为灰白方格

方格仅用于提示透明区域，不会写入透明 PNG。若其他软件将透明区域显示为白色或黑色，这是该软件的 alpha 通道显示方式。

### PNG 导出较慢或内存占用较高

PNG 是整页位图，像素数量随 DPI 的平方增长。通常建议使用 300 DPI；只有确有需要时再选 600 DPI。程序会拒绝异常大的输出以保护内存。

### PS 文件有多页

预览器支持多页 EPS/PS，可用上下方向键或工具栏翻页，保存 PNG 时会导出当前页。制作视频时，每个 EPS/PS 文件仍取第一页作为一帧。

### MP4/GIF 中的图片大小不一致

所有帧都会按比例缩放并居中到设定画布，空白区域使用视频窗口中选择的背景色。程序不会拉伸原图。

### 后续帧与首帧的分辨率不同，裁剪位置是否会偏移

不会使用首帧的固定像素坐标。程序保存的是裁剪框占整张图的比例，并据此计算每一张后续图片的对应区域。若图片本身的构图或长宽比发生变化，对应区域仍按宽、高方向的百分比确定。

### 视频生成耗时较长

高分辨率、大量帧或包含 EPS/PS 时需要更多渲染和编码时间。生成过程可取消；取消或失败不会留下不完整的目标文件。

<details>
<summary>开发与打包说明</summary>

开发环境需要 Python 3.11+。运行和调试 EPS/PS 功能时还需要 Ghostscript：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Windows 双击 `build.bat` 可继续生成原有单文件 `dist\EPSLiveViewer.exe`。Linux/macOS 可执行：

```bash
chmod +x build_unix.sh
./build_unix.sh
```

推送 `eps-live-viewer-v*` 标签或手动运行[多平台发布工作流](.github/workflows/eps-live-viewer-release.yml)，会在 Windows、Ubuntu、macOS Apple Silicon 和 macOS Intel 原生 runner 上分别构建发行包、生成 SHA-256 校验文件并创建或更新 GitHub Release。macOS 产物为可拖入“应用程序”的 DMG。PyInstaller 不支持从单一操作系统交叉编译所有平台，因此各平台必须独立构建。

如需正式签名和公证 macOS 包，可在仓库 Secrets 中配置 `MACOS_CERTIFICATE`、`MACOS_CERTIFICATE_PASSWORD`、`MACOS_SIGNING_IDENTITY`、`MACOS_NOTARY_APPLE_ID`、`MACOS_NOTARY_TEAM_ID` 和 `MACOS_NOTARY_PASSWORD`。未配置时工作流回退为可构建但未公证的临时签名版本。

附：本项目主要借助 Codex 生成。

</details>
