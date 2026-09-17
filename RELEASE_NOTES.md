# EPS Live Viewer 3.1.0

## 3.1.0 中文

- 固定 Settings / 界面语言 Language 入口；菜单置于标签栏上方，以唯一的 Home 图标返回首页，文档标签加宽并突出当前项。
- 首页最近文件改为对齐表格，显示名称、大小、最近打开时间和位置。
- 默认工具栏增加换色、PDF 与 EPS/PS 导出；保留用户已自定义的工具栏。
- EPS 导出保留原页面画布和留白；支持同段中独立定位的旋转文字、单位、上标片段，增加编辑光标提示。
- 备用渲染 DPI 移入设置，减少重复弹窗；原文件及未保存修改保护仍保留。
- README 加入实际产品截图（合成示例）。

## 3.1.0 English

- Stable bilingual language entry, menus above tabs, a single Home icon, and wider highlighted document tabs.
- Recent files use an aligned table with file name, size, last-opened time and location.
- Replace Colors and PDF/EPS/PS export in the default toolbar; existing custom tool choices are retained.
- Preserve EPS page canvas/margins; recognize independently positioned rotated/unit/superscript fragments and show an editing cursor on hover.
- Fallback DPI moves to preferences; retain confirmations that protect originals and unsaved work.
- Compact README product screenshots using synthetic data.

## 3.0.1 中文

- 页面内双击编辑，支持同一文字片段中的局部字符样式；实时显示，保存自动包含当前修改。
- 文字列表默认隐藏；科研符号改为分类工具盒；EPS/PS/PDF 保存顺序与旋转文字选中提示优化。
- 首页最近文件及显示开关、屏幕自适应启动尺寸、可选最大化；关闭最后一个标签返回首页。
- 分类设置菜单统一管理预览、依赖、编辑、导出、视频、比较和工具栏偏好，并同步已打开的窗口/标签页；保留文档独立编辑。
- 调整导出菜单，提供中英文发布介绍草稿；本次不推送或发布 GitHub。

## 3.0.1 English

- Double-click on-page editing with character-range styling inside a recognizable run, live updates and automatic commit on Save.
- Optional text list, categorized symbol toolbox, EPS-first Save As, and improved rotated-text selection feedback.
- Recent files on Home, screen-fitting startup and optional maximization; the final tab returns Home.
- Categorized, synchronized preferences for preview, dependencies, editing, export, video, comparison and toolbar; document edits remain independent.
- Regrouped export menu and bilingual release-copy draft. No GitHub push/publication in this iteration.

## 3.0.0 中文

- 新增可识别文字的独立编辑窗口：内容、系统字体、字号、颜色、粗斜体、旋转、科研符号、撤销/重做和矢量预览。
- 原文件保护及 EPS/PS/PDF 另存为；EPS 当前页，PS/PDF 全部页。源文件变化时提醒快照冲突。
- 未打开文件时显示品牌首页、版本、仓库和作者；重新绘制简约矢量 Logo，生成 Windows/macOS 图标。
- 图标工具栏与悬停说明、彩色色值和文档色板、Ghostscript 下载及路径设置指引。
- 不增加运行依赖或字体包；保留 2.3.1 完整帧和内存优化。
- 边界：只编辑可识别独立文字；旧版 Ghostscript 可能将导出的新文字转为矢量轮廓，建议保留 PDF 以继续编辑。

## 3.0.0 English

- Independent text-editing workspace: content, installed fonts, size, color, bold/italic, rotation, scientific symbols, undo/redo and vector preview.
- Original-file protection and EPS/PS/PDF Save As; EPS exports the current page, PS/PDF all pages. External source changes trigger a snapshot warning.
- Branded home screen with version, repository and author; modern vector logo and Windows/macOS icons.
- Icon toolbar with tooltips, colored replacement values, document palettes and Ghostscript installation guidance.
- No new runtime dependencies or font bundles; retains 2.3.1 preview/memory improvements.
- Scope is recognizable independent runs. Old Ghostscript may outline exported text; retain the edited PDF for subsequent editing.

## 2.3.1 中文

- 预览改为整幅可见区域更新，去除图块接缝和点击重绘时变化的细线。
- 缩放时保留上一幅完整画面，只处理最新视图请求；适应窗口时直接生成高清画面。
- 限制当前高清帧像素量，释放过期缩放缓存和后台标签页高清帧，降低多窗口/多标签页内存占用。
- 增加透明图像、区域采样、点击重绘和缓存释放回归检查；未新增运行依赖。

## 2.3.1 English

- Update the visible preview as a complete frame, eliminating tile seams and thin lines that changed during click-only repaints.
- Retain the previous complete image while zooming and coalesce requests to the latest view. Fitted pages render directly at display quality.
- Bound detail-frame pixels, replace old zoom caches, and release hidden-tab detail frames to reduce memory use.
- Added transparent-region sampling, repaint, and cache-release regressions. No new runtime dependencies.

---

## 2.3.0 中文

- 支持直接阅读 PDF，提供多页浏览、旋转、反色、替换颜色、PNG/PDF/EPS/PS 导出与视频/动图制作。
- 常见科研图表在反色或替换颜色后可导出保留文字和路径的矢量 PDF/EPS/PS；渐变、特殊色彩空间等复杂内容使用所选 DPI 的兼容位图导出。
- 修复高 DPI 调色 PNG 导出卡顿；改进线条和文字边缘抗锯齿，以及部分缩放比例下细坐标轴难以看清的问题。
- EPS/PS/PDF 默认在文字上拖选复制，空白处拖动平移。更新中英文说明与跨平台构建检查。
- 本版未加入 PDF 文字或图形对象编辑。EPS/PS 仍需单独安装 Ghostscript。

## 2.3.0 English

- Read PDFs directly, including multi-page navigation, rotation, inversion, color replacement, PNG/PDF/EPS/PS export, and MP4/GIF creation.
- Export recolored PDF/EPS/PS scientific plots with vector text and paths when supported. Complex gradients, special color spaces, and effects use a compatible raster fallback at the selected DPI.
- Fixed stalled high-DPI recolored PNG export. Improved antialiasing and thin-axis visibility at varying zoom levels.
- EPS/PS/PDF select text when dragging over text and pan when dragging blank space. Updated bilingual documentation and cross-platform packaging checks.
- PDF text/graphics object editing is not included. EPS/PS still requires a separate Ghostscript installation.

---

Previous 2.2.1 fixes:

## 2.2.1 中文

## 2.2.1 中文

- 修复 Apple Silicon Mac 上标签页窗口激活时，菜单栏与工具栏点击可能失效的问题。
- 调整标签页内文档窗口和菜单栏的创建顺序，避免 macOS Cocoa 建立错误的窗口/菜单归属。
- 增加 macOS Cocoa 原生鼠标交互检查，覆盖工具栏、菜单、最近文件、标签页及弹窗关闭后的继续操作。

## 2.2.1 English

- Fixed menu bar and toolbar clicks that could stop responding when a tabbed window was activated on Apple Silicon Macs.
- Established embedded document windows and their menu bars before Cocoa creates native window/menu ownership.
- Added native macOS Cocoa mouse interaction checks for toolbars, menus, recent files, tabs, and controls after closing dialogs.

---

Previous 2.2.0 improvements:

## 2.2.0 中文

- 工具栏可自定义；默认隐藏重新加载与旋转，默认背景改为白色。
- 替换颜色窗口默认缩窄编辑区，支持拖动分隔栏。
- 并排比较支持最大化、选择已打开标签页，以及默认比较当前多页文档的另一页。
- 视频、裁剪与试播统一使用主预览的文档页面，修复多页 EPS 输出重复首帧和方向不一致；支持仅当前文件或筛选文件夹格式。
- 保存编辑记录及关闭时保存提示；记录为源文件旁的 .epslive.json，源图像保持不变。
- 新增文件信息、矢量文本拖选复制，以及可选的独立标签页和双击文件路由。
- 未增加第三方运行依赖。

## 2.2.0 English

- Customizable toolbar; reload/rotation hidden by default and white default background.
- Resizable color-editor split with a narrower initial editor pane.
- Maximizable comparison with open-tab choices and another-page default for multi-page documents.
- Video, crop, and rehearsal use the same document pages as the main preview, fixing repeated EPS frames and orientation mismatches. Current-document and filtered-folder input choices are available.
- Save edits and prompt on close. Neighboring .epslive.json records preserve the source image.
- File information, vector text selection/copying, optional independent tabs, and desktop double-click routing.
- No new third-party runtime dependencies.

---

Previous 2.1.0 improvements:

## 中文

- 新增每个文件独立的撤销／重做，支持旋转、反色、颜色替换和重置；保留最近 50 次操作，全部页旋转作为一次操作撤销。
- 调色窗口支持直接编辑色值、RGB 选色和容差，并实时显示低分辨率预览；按住按钮可对照原始配色。确定应用、取消保留原设置。
- 主窗口及比较窗口的颜色处理移到可取消的后台任务；快速编辑或切换页面时丢弃过时结果。
- 视频窗口显示帧数、FPS 和预计时长，新增正式导出前的低分辨率试播，支持暂停、拖动进度和循环播放，应用当前裁剪、顺序与图像调整。
- 新增并排比较：左侧参考图默认锁定，右侧可选其他文件/页面或跟随主窗口，并支持联动缩放和平移。
- 帮助菜单新增本地诊断报告，可查看并复制版本、当前图像调整和最近错误。不会自动上传；报告可能含本地路径。
- 更新中英文说明与帮助；新增回归检查。没有新增运行依赖或视频播放框架。

## English

- Added independent undo/redo per file for rotation, inversion, replacements, and resets. Keeps up to 50 operations; All Pages rotation is a single operation.
- Added editable color values, RGB selection, tolerance, and live low-resolution preview. Hold a button to compare original colors. OK applies changes; Cancel preserves prior settings.
- Moved main/comparison view color processing to cancellable background tasks and discard obsolete results after rapid edits or page changes.
- Added frame/FPS/duration estimates and low-resolution video rehearsal before export, with pause, seek, loop, current crop, frame order, and adjustments.
- Added side-by-side comparison with a locked left reference, an independently selected or main-window-following right view, and linked zoom/pan.
- Added manually viewed/copied local diagnostics for versions, current adjustments, and recent errors. No automatic uploads; reports may contain local paths.
- Updated bilingual documentation/help and regression coverage. No new runtime dependency or media framework.
