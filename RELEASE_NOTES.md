# EPS Live Viewer 2.2.0

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
