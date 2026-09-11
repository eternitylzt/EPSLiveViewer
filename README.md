# EPS Live Viewer

[中文](README.md) | [English](README_EN.md)

EPS Live Viewer 是面向科研绘图快速迭代的轻量级跨平台桌面查看器。它能实时查看 EPS/PS，也能直接打开 PNG/JPG，在同一个界面中完成相邻文件比较、多页浏览、旋转、反色、替换颜色、图片导出和视频制作。

## 主要功能

- EPS/PS 矢量预览：放大时按当前视图重新渲染，线条和文字保持清晰。
- PNG/JPG 图片查看：无需 Ghostscript 即可打开、缩放、旋转、反色和替换颜色。
- 实时刷新：当前文件被 IDL、Python、MATLAB、Fortran 等程序重新生成后自动更新。
- 快速比较：自动识别同一文件夹中的 EPS、PS、PNG、JPG/JPEG；`←`、`→` 切换相邻文件。
- 多页文档：`↑`、`↓` 切换 EPS/PS 页面；滚轮行为可设置为缩放、相邻文件或翻页，`Ctrl + 滚轮` 始终缩放。
- 图像调整：工具栏和“图像”菜单支持按页左/右旋转、全文档反转颜色，以及最多 16 组颜色替换。
- 灵活配色：颜色窗口支持 RGB 和 HEX 色值；系统提供时可使用屏幕取色器。可为每组替换设置 RGB 容差。处理顺序固定为“反色 → 颜色替换”，因此点击顺序不会改变结果。
- PNG 导出：可设置 72–600 DPI；多页 EPS/PS 可仅保存当前页，或将全部页面导出到一个新文件夹。
- 文档导出：调整后的结果可保存为 PDF、PS 或 EPS。PDF/PS 保留多页，标准 EPS 保存当前页。
- 视频/动图：文件夹中的每个 EPS/PS 页面和每张 PNG/JPG 都可作为独立帧，支持调整顺序、排除帧、按首帧设置画布、比例裁剪、帧率、MP4/GIF，并应用已设置的旋转与颜色调整。
- 中英文界面、最近文件、背景颜色、手动检查 GitHub 更新。

查看器使用文件自身的页面或图像尺寸，并不限制为 A4，因此无需设置纸张大小。PNG/JPG 本身是位图，放大清晰度仍由原始像素决定。

## 安装

从 [GitHub Releases](https://github.com/eternitylzt/EPSLiveViewer/releases) 下载对应平台：

- Windows：解压 `EPSLiveViewer-Windows-x64.zip`，运行 `EPSLiveViewer.exe`。
- macOS Apple Silicon：下载 `EPSLiveViewer-macOS-arm64.dmg`。
- macOS Intel：下载 `EPSLiveViewer-macOS-x64.dmg`。
- Linux x64：解压 `EPSLiveViewer-Linux-x64.tar.gz`，为程序添加执行权限后运行。

发布包无需 Python。查看或处理 EPS/PS 需要安装 Ghostscript；程序会自动查找，也可在“文件 → 设置”中指定路径。仅打开/调整 PNG/JPG、保存 PNG 或用纯栅格图片制作视频时不需要 Ghostscript；将 PNG/JPG 导出为 PDF/PS/EPS 时需要 Ghostscript。

## 使用方法

1. 选择“文件 → 打开图片”，将文件拖入窗口，或在命令行传入文件路径。
2. 使用滚轮缩放、拖动平移、双击恢复 100%，或点击工具栏的缩放和适应窗口按钮。
3. 用方向键浏览相邻文件和多页文档；状态栏显示文件位置、页码、页面尺寸、缩放和更新时间。
4. 在“图像”菜单或工具栏中旋转、反色；在“图像 → 替换颜色”中添加源颜色、目标颜色和容差。
5. 选择“另存为 PNG/PDF/EPS/PS”导出调整后的结果。颜色替换会把 PDF/PS/EPS 页面以所选 DPI 封装为位图；没有颜色替换时，EPS/PS 的旋转和反色导出仍保持矢量内容。
6. 选择“文件 → 制作视频/动图”，选定文件夹并调整帧列表和输出参数。多页 EPS/PS 会自动展开为连续帧。

调整只保存在当前运行会话中，不会修改源文件。自动刷新也会保留当前文件的调整状态。

## 常见问题

### 为什么 EPS/PS 无法显示？

确认已安装 Ghostscript，并在设置中选择控制台程序：Windows 通常为 `gswin64c.exe`，Linux/macOS 通常为 `gs`。

### 为什么 PNG/JPG 放大后不再清晰？

PNG/JPG 是位图；程序不会凭空增加细节。EPS/PS 中原本嵌入的照片也受原始像素限制。

### 反色后的 PDF 为什么仍是矢量，而任意颜色替换不是？

旋转和整体反色可用文档图形能力保留矢量；任意多色容差替换需要逐像素判断，因此 PDF/PS/EPS 会使用所选 DPI 的位图页面。PNG 和视频始终按像素输出。

### macOS 提示应用不安全怎么办？

正式签名和公证需要 Apple Developer 证书；如果当前 Release 未公证，可在 Finder 中按住 Control 点击应用并选择“打开”，或在“隐私与安全性”中确认打开。请只从本项目 Releases 下载。

### 为什么不能覆盖当前打开的源文件？

文档另存为会阻止覆盖当前源文件，避免自动刷新和导出同时破坏原图。请使用新的文件名。

### 如何检查更新？

手动选择“帮助 → 检查更新”。程序不会后台检查、自动下载或自动安装。

<details>
<summary>开发与构建信息</summary>

开发环境为 Python 3.11+、PyQt6、Ghostscript、PyInstaller。安装依赖后可运行 `python main.py example.eps`。Windows 运行 `build.bat` 生成单文件 EXE；Linux/macOS 使用 `build_unix.sh`。推送 `eps-live-viewer-v*` 标签会触发原生 Windows、Linux、macOS Apple Silicon/Intel 构建并创建 GitHub Release。

颜色处理完全使用 Qt/Python 实现，没有新增图像或 PDF 第三方依赖。Ghostscript 仍是唯一的 EPS/PostScript 解释器。

</details>

作者：Zhentong Li · eternitylzt@gmail.com
