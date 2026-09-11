# EPS Live Viewer 1.1.0

## 简体中文

- 支持多页 EPS/PS：上下方向键翻页，状态栏显示页码，PNG 导出保存当前页。
- 鼠标滚轮可设置为缩放、切换相邻文件或仅翻页；`Ctrl+滚轮` 始终可缩放。
- 新增顶部快捷工具栏。
- 新增简体中文/英语即时切换。
- “关于”窗口新增版本号、GitHub 链接，并支持选择、复制文字。
- 修复 macOS 从 Finder 或默认文件关联启动时只打开应用、不显示 EPS/PS 的问题。
- macOS 应用清单注册 EPS/PS 文档类型；发布流程支持可选的 Developer ID 签名与 Apple 公证。

macOS Apple Silicon 和 Intel 分别提供 DMG。当前仓库未配置 Apple Developer 凭据时，产物仍为临时签名、未公证版本，首次启动需在 Finder 中按住 Control 点击应用并选择“打开”。EPS/PS 功能仍需系统 Ghostscript；发布包不要求 Python。

## English

- Added multi-page EPS/PS support: Up/Down changes pages, the status bar shows page position, and PNG export saves the current page.
- The mouse wheel can zoom, browse neighboring files, or change pages; `Ctrl+wheel` always zooms.
- Added a top quick-access toolbar.
- Added immediate Simplified Chinese/English switching.
- The copyable About dialog now shows the version and GitHub project link.
- Fixed macOS Finder/default-app launches opening the application without displaying the requested EPS/PS file.
- Registered EPS/PS document types in the macOS bundle and added optional Developer ID signing and Apple notarization to the release workflow.

Separate DMGs are provided for Apple Silicon and Intel. Without Apple Developer credentials configured in this repository, builds remain ad-hoc signed and unnotarized; Control-click the app in Finder and choose **Open** for the first launch. EPS/PS features still require system Ghostscript; Python is not required.
