# EPS Live Viewer multi-platform release

## 简体中文

这是 EPS Live Viewer 的首个多平台发布版本。

- Windows x64：原有稳定单文件 EXE，用法保持不变。
- Linux x64：初始移植版单文件程序。
- macOS Apple Silicon / Intel：对应架构的初始 `.app` 移植版，尚未签名或公证。
- 所有包均支持 EPS/PS 矢量预览、自动刷新、相邻文件浏览、PNG 导出及 MP4/GIF 序列制作。
- 运行 EPS/PS 功能仍需安装系统 Ghostscript；发布包不要求安装 Python。

请根据平台下载对应压缩包，并可使用 `SHA256SUMS.txt` 校验文件完整性。Linux/macOS 为初始移植版本，如遇平台特有问题请提交 Issue。

## English

This is the first multi-platform release of EPS Live Viewer.

- Windows x64: the established single-file EXE with unchanged usage.
- Linux x64: an initial portable single-file build.
- macOS Apple Silicon / Intel: initial native `.app` builds; currently unsigned and not notarized.
- Every package supports EPS/PS vector preview, automatic refresh, neighboring-file navigation, PNG export, and MP4/GIF sequence creation.
- EPS/PS features still require system Ghostscript; Python is not required for release packages.

Download the archive matching your platform and use `SHA256SUMS.txt` to verify it. Linux and macOS are initial ports; please report platform-specific issues through GitHub Issues.
