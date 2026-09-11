# EPS Live Viewer 1.1.1

## 简体中文

- 优化 Windows 单文件打包，实测 EXE 从 68.16 MB 降至 51.92 MB，减少约 23.8%。
- 移除程序未使用的 Qt 软件 OpenGL 回退库；当前界面和矢量预览继续使用 Qt Widgets 的二维绘制。
- 完整保留内置 FFmpeg，通过无损压缩降低发行体积；首次制作视频时解压到临时目录，本次运行期间复用，退出后自动清理。
- 合并视频窗口与视频导出中重复的 PNG/JPG 读取逻辑。
- 保留已有全部功能和离线能力，不要求单独安装 FFmpeg。

已用三页 `20241001.eps` 完成源码及冻结程序回归检查，覆盖多页、缩放、三种滚轮操作、背景、相邻 EPS/PS、拖拽、自动刷新、当前页 PNG 导出、JPG 输入、MP4/GIF、比例裁剪、取消生成和中英文界面。

本次体积优化针对 Windows。Linux 和 macOS 继续使用原有打包方式，功能和安装方法不变。EPS/PS 预览仍需系统 Ghostscript；发布包不要求 Python。

## English

- Optimized the Windows one-file package: the measured EXE decreased from 68.16 MB to 51.92 MB, a reduction of about 23.8%.
- Removed Qt's unused software OpenGL fallback library; the interface and vector preview continue to use Qt Widgets' 2D painting path.
- Kept the complete bundled FFmpeg executable and compressed it losslessly. It is extracted to a temporary directory on first video export, reused for the current session, and cleaned up on exit.
- Consolidated duplicate PNG/JPG loading code shared by the video dialog and exporter.
- Preserved all existing features and offline operation; no separate FFmpeg installation is required.

Source and frozen-package regression checks used the supplied three-page `20241001.eps` and covered multipage navigation, zoom, all wheel modes, backgrounds, neighboring EPS/PS files, drag and drop, live refresh, current-page PNG export, JPEG input, MP4/GIF, proportional cropping, cancellation, and both interface languages.

This size optimization targets Windows. Linux and macOS retain their established packaging, features, and installation method. EPS/PS preview still requires system Ghostscript; Python is not required.
