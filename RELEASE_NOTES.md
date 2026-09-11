# EPS Live Viewer 1.3.0

## 简体中文

- 在“帮助”菜单新增“检查更新”。
- 仅在用户手动点击后访问 `eternitylzt/EPSLiveViewer` 的 GitHub Releases API；启动和后台运行时不会检查网络。
- 将 latest release 与当前程序版本比较。发现新版时显示版本号并可打开对应 Release 下载页面；已是最新版时给出明确提示。
- 网络不可用、GitHub API 出错或响应无效时显示清晰错误，不影响本地功能。
- 不包含自动下载或自动安装，也未增加第三方依赖。

本次更新保留 EPS/PS 矢量预览、多页查看、自动刷新、相邻文件浏览、PNG/多页矢量 PDF 导出及 MP4/GIF 制作等全部已有功能。Windows、Linux、macOS Apple Silicon 和 macOS Intel 继续使用现有跨平台发布流程。

## English

- Added **Help → Check for Updates**.
- The app contacts the GitHub Releases API for `eternitylzt/EPSLiveViewer` only after an explicit click. It performs no startup or background checks.
- The latest release is compared with the running app version. A newer version displays its number and can open the matching Release download page; an up-to-date installation receives a clear confirmation.
- Network, GitHub API, and malformed-response failures are reported clearly without affecting local features.
- There is no automatic download or installation and no new third-party dependency.

All existing EPS/PS vector preview, multi-page navigation, live refresh, neighboring-file browsing, PNG/multi-page vector PDF export, and MP4/GIF creation features remain available. The existing release workflow continues to build Windows, Linux, macOS Apple Silicon, and macOS Intel packages.
