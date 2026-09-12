# EPS Live Viewer 2.0.1

## 中文

- 修复颜色替换在确认源颜色、目标颜色和容差后闪退的问题；中英文界面均可正常添加、编辑和重新打开替换列表。
- 修复快速反色、替换颜色时重复渲染计数导致预览停止更新的问题。
- 统一视频裁剪预览和导出帧的读取流程：从原文件应用一次旋转和颜色变换，复用同一首帧预览；关闭重开制作窗口保持一致。
- 禁用预览 PDF 转换时额外的自动转向，避免与手动旋转产生方向差异。
- 新增“旋转范围”：在“图像”菜单或工具栏下拉按钮中选择“仅当前页”或“全部页面”，再使用左/右旋转按钮。全部页面在各自原方向上旋转相同角度。
- 改进 MP4 播放兼容性：统一 H.264 Main / YUV420、固定帧率和明确时间戳；奇数宽高在右侧或底部补 1 像素，避免切换为 YUV444。GIF 尺寸不变。旧 MP4 请重新导出。
- 新增颜色编辑、重复视频预览、MP4 帧顺序/时间戳回归检查，并通过 Windows Media Foundation 实际播放验证；更新中英文说明。
- 未新增运行依赖；继续提供 Windows、Linux、macOS Apple Silicon / Intel 发布包。

## English

- Fixed the crash after confirming replacement colors and tolerance; adding, editing, and reopening mappings now work in both languages.
- Fixed preview stalls caused by counting duplicate render requests during rapid color changes.
- Unified crop preview and video frame loading: apply rotation/colors once to the original source and reuse the reference preview. Closing and reopening the creation dialog produces consistent previews.
- Disabled extra automatic orientation in preview PDF conversion to keep it aligned with manual rotation.
- Added Rotation Scope to the Image menu and toolbar: Current Page Only or All Pages. All Pages rotates every page relative to its own orientation.
- Improved MP4 compatibility with H.264 Main / YUV420, constant frame rate, and explicit timestamps. Odd dimensions receive 1 pixel of right/bottom padding instead of YUV444 output. GIF dimensions are unchanged. Re-export older MP4 files to use the fix.
- Added color-editor, repeated-preview, and decoded-frame/timestamp regression checks; verified actual playback with Windows Media Foundation and updated bilingual documentation.
- No additional runtime dependency. Windows, Linux, macOS Apple Silicon, and macOS Intel packages remain available.
