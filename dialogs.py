"""Settings and PNG export dialogs for EPS Live Viewer."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QTabWidget, QScrollArea, QGridLayout,
)

from config import (
    BACKGROUND_MODES,
    MAX_EXPORT_DPI,
    MAX_REFRESH_INTERVAL,
    MIN_EXPORT_DPI,
    MIN_REFRESH_INTERVAL,
    AppConfig,
)
from i18n import tr, bilingual as L
from window_geometry import fit_initial_window


@dataclass(frozen=True)
class PngExportOptions:
    """Validated choices returned by :class:`PngExportDialog`."""

    path: Path
    dpi: int
    all_pages: bool = False


def _joined_row(field: QWidget, button: QPushButton) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(field, 1)
    layout.addWidget(button)
    return container


class SettingsDialog(QDialog):
    """Edit application preferences without mutating the live configuration."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None, toolbar_options=None) -> None:
        super().__init__(parent)
        self._initial = AppConfig.from_mapping(config.__dict__)
        self._custom_color = QColor(self._initial.background_color)
        self._toolbar_options = toolbar_options or {}
        self.requested_tool = None

        self.setWindowTitle("Settings · 设置")
        self.setModal(True)
        self.setMinimumWidth(540)
        self._build_ui()
        self._load_values()
        fit_initial_window(self,680,660)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        note = QLabel(L("这里是统一的偏好设置入口，保存后同步到所有已打开的窗口和标签页。具体文件的文字、配色及裁剪仍由对应工具编辑。",
                        "Preferences saved here synchronize across open windows and tabs. Document text, colors and crop regions remain document-specific."))
        note.setWordWrap(True)
        root.addWidget(note)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs,1)
        self._sections = {}
        def section(key, title):
            body = QWidget()
            content = QVBoxLayout(body)
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setWidget(body)
            self._sections[key] = self.tabs.addTab(area,title)
            return content
        general = section("general",L("常规与预览", "General & View"))
        runtime = section("runtime",L("刷新与依赖", "Refresh & Dependencies"))
        exports = section("export",L("导出与视频", "Export & Video"))
        editing = section("editing",L("编辑与工具", "Editing & Tools"))
        toolbar = section("toolbar",L("工具栏", "Toolbar"))

        runtime_group = QGroupBox(tr("渲染与自动刷新"))
        runtime_form = QFormLayout(runtime_group)

        self._ghostscript_edit = QLineEdit()
        self._ghostscript_edit.setPlaceholderText(tr("留空则自动查找 Ghostscript"))
        self._ghostscript_edit.setClearButtonEnabled(True)
        browse_gs_button = QPushButton(tr("浏览…"))
        browse_gs_button.clicked.connect(self._browse_ghostscript)
        runtime_form.addRow(
            "Ghostscript：", _joined_row(self._ghostscript_edit, browse_gs_button)
        )

        self._auto_refresh_check = QCheckBox(tr("当前文件变化后自动刷新"))
        self._auto_refresh_check.toggled.connect(self._sync_enabled_states)
        runtime_form.addRow("", self._auto_refresh_check)

        self._refresh_interval_spin = QSpinBox()
        self._refresh_interval_spin.setRange(MIN_REFRESH_INTERVAL, MAX_REFRESH_INTERVAL)
        self._refresh_interval_spin.setSingleStep(100)
        self._refresh_interval_spin.setSuffix(" ms")
        runtime_form.addRow(tr("检测间隔："), self._refresh_interval_spin)
        runtime.addWidget(runtime_group)
        self._suppress_help = QCheckBox(L("不再显示 Ghostscript 安装指引（操作错误仍提示）",
                                          "Hide Ghostscript installation guidance (errors still reported)"))
        runtime.addWidget(self._suppress_help)
        download = QLabel('<a href="https://ghostscript.com/releases/gsdnld.html">Ghostscript Downloads</a>')
        download.setOpenExternalLinks(True)
        runtime.addWidget(download)
        runtime.addStretch()

        display_group = QGroupBox(tr("预览与交互"))
        display_form = QFormLayout(display_group)
        self._background_combo = QComboBox()
        self._background_combo.addItem(tr("透明（棋盘格）"), "transparent")
        self._background_combo.addItem(tr("白色"), "white")
        self._background_combo.addItem(tr("自定义颜色"), "custom")
        self._background_combo.currentIndexChanged.connect(self._sync_enabled_states)
        display_form.addRow(tr("背景："), self._background_combo)

        self._color_button = QPushButton()
        self._color_button.clicked.connect(self._choose_background_color)
        display_form.addRow(tr("自定义颜色："), self._color_button)

        self._wheel_action_combo = QComboBox()
        self._wheel_action_combo.addItem(tr("放大或缩小（默认）"), "zoom")
        self._wheel_action_combo.addItem(
            tr("相邻文件查看（Ctrl+滚轮缩放）"), "files"
        )
        self._wheel_action_combo.addItem(
            tr("仅翻页（Ctrl+滚轮缩放）"), "pages"
        )
        display_form.addRow(tr("鼠标滚轮："), self._wheel_action_combo)

        self._open_mode_combo = QComboBox()
        self._open_mode_combo.addItem(tr("新窗口（默认）"), "window")
        self._open_mode_combo.addItem(tr("同一窗口的新标签页"), "tabs")
        display_form.addRow(tr("打开文件："), self._open_mode_combo)

        self._language_combo = QComboBox()
        self._language_combo.addItem("简体中文", "zh_CN")
        self._language_combo.addItem("English", "en")
        display_form.addRow("界面语言 / Language:", self._language_combo)
        language_note = QLabel(tr("语言切换保存后立即生效，无需重启。"))
        language_note.setWordWrap(True)
        display_form.addRow("", language_note)
        self._home_recent = QCheckBox(L("在首页显示最近打开文件", "Show recent files on Home"))
        self._maximized = QCheckBox(L("启动时最大化（否则自动适应屏幕）", "Start maximized (otherwise fit the screen)"))
        display_form.addRow(self._home_recent)
        display_form.addRow(self._maximized)
        general.addWidget(display_group)
        general.addStretch()

        export_group = QGroupBox(tr("PNG 导出"))
        export_form = QFormLayout(export_group)
        self._export_dpi_spin = QSpinBox()
        self._export_dpi_spin.setRange(MIN_EXPORT_DPI, MAX_EXPORT_DPI)
        self._export_dpi_spin.setSingleStep(50)
        self._export_dpi_spin.setSuffix(" DPI")
        export_form.addRow(tr("默认分辨率："), self._export_dpi_spin)
        self._fallback_dpi_spin = QSpinBox()
        self._fallback_dpi_spin.setRange(MIN_EXPORT_DPI,MAX_EXPORT_DPI)
        self._fallback_dpi_spin.setSuffix(" DPI")
        export_form.addRow(L("复杂效果备用分辨率：","Complex-effect fallback:"),self._fallback_dpi_spin)
        fallback_note = QLabel(L("矢量导出优先保留矢量，仅不支持的复杂效果使用此分辨率，不再逐次询问。",
                                "Vector export stays vector where supported; complex effects use this resolution without a repeated prompt."))
        fallback_note.setWordWrap(True)
        export_form.addRow(fallback_note)
        export_note = QLabel(tr("预览清晰度会随缩放自动调整，此 DPI 只用于保存 PNG。"))
        export_note.setWordWrap(True)
        export_form.addRow("", export_note)
        self._png_all = QCheckBox(L("多页文件默认导出所有页面", "Export all pages by default"))
        export_form.addRow(self._png_all)
        exports.addWidget(export_group)
        video = QGroupBox(L("视频默认参数", "Video Defaults"))
        vf = QFormLayout(video)
        self._video_fps = QSpinBox();self._video_fps.setRange(1,60)
        self._video_format = QComboBox()
        self._video_format.addItem("MP4","mp4");self._video_format.addItem("GIF","gif")
        self._video_width = QSpinBox();self._video_width.setRange(16,7680)
        self._video_height = QSpinBox();self._video_height.setRange(16,7680)
        self._video_color = QLineEdit()
        color_pick = QPushButton(L("选择颜色…","Choose Color…"))
        def pick_video():
            color = QColorDialog.getColor(QColor(self._video_color.text()),self)
            if color.isValid(): self._video_color.setText(color.name())
        color_pick.clicked.connect(pick_video)
        for label,widget in [("FPS",self._video_fps),(L("格式","Format"),self._video_format),
                             (L("默认宽度","Default width"),self._video_width),
                             (L("默认高度","Default height"),self._video_height)]:
            vf.addRow(label,widget)
        vf.addRow(L("背景色","Background"),_joined_row(self._video_color,color_pick))
        video_note = QLabel(L("PNG/JPG 序列仍优先采用首帧分辨率。分辨率、帧率和背景可在制作窗口为本次任务调整，不会改写全局默认值。",
                              "PNG/JPG sequences still use the first frame's resolution. Job-specific size, FPS and background overrides do not change these defaults."))
        video_note.setWordWrap(True);vf.addRow(video_note)
        exports.addWidget(video);exports.addStretch()
        self._text_list = QCheckBox(L("文字编辑窗口显示识别列表", "Show recognized text list in editor"))
        self._auto_text = QCheckBox(tr("自动选择文本"))
        self._scope = QComboBox()
        self._scope.addItem(tr("仅当前页"),"current");self._scope.addItem(tr("全部页面"),"all")
        self._tolerance = QSpinBox();self._tolerance.setRange(0,255)
        ef = QFormLayout()
        ef.addRow(self._text_list);ef.addRow(self._auto_text)
        ef.addRow(tr("旋转范围"),self._scope)
        ef.addRow(L("新颜色替换条目的默认容差","Default new color-rule tolerance"),self._tolerance)
        self._compare_boxes = {}
        for name,label in (("compare_linked",tr("联动缩放和平移")),
                           ("compare_locked",tr("锁定左侧参考图")),
                           ("compare_follow",tr("右图跟随主窗口"))):
            box = QCheckBox(label)
            self._compare_boxes[name] = box
            ef.addRow(box)
        editing.addLayout(ef)
        tool_group = QGroupBox(L("当前文档工具", "Current Document Tools"))
        tl = QGridLayout(tool_group)
        for i,(name,label) in enumerate((("edit_text",L("文字编辑…","Edit Text…")),
                ("replace_colors",tr("替换颜色")),("compare",tr("并排比较…")),
                ("make_video",tr("制作视频")),("file_info",tr("文件信息")))):
            button = QPushButton(label)
            action = self._toolbar_options.get(name)
            button.setEnabled(bool(action and action.isEnabled()))
            button.clicked.connect(lambda checked=False,key=name:self._request_tool(key))
            tl.addWidget(button,i//2,i%2)
        editing.addWidget(tool_group);editing.addStretch()
        self._toolbar_boxes = {}
        grid = QGridLayout()
        for i,(name,action) in enumerate(self._toolbar_options.items()):
            box = QCheckBox(tr("旋转范围") if name == "rotation_scope" else action.text().replace("&",""))
            self._toolbar_boxes[name] = box
            grid.addWidget(box,i//2,i%2)
        toolbar.addLayout(grid);toolbar.addStretch()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("确定"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def select_section(self, key):
        self.tabs.setCurrentIndex(self._sections.get(key,0))

    def _request_tool(self, key):
        self.requested_tool = key
        self.accept()

    def accept(self):
        if not QColor(self._video_color.text()).isValid():
            QMessageBox.warning(self,tr("设置"),L("请输入有效的视频背景颜色。","Enter a valid video background color."))
            return
        super().accept()

    def _load_values(self) -> None:
        self._ghostscript_edit.setText(self._initial.ghostscript_path)
        self._auto_refresh_check.setChecked(self._initial.auto_refresh)
        self._refresh_interval_spin.setValue(self._initial.refresh_interval)
        index = self._background_combo.findData(self._initial.background_mode)
        self._background_combo.setCurrentIndex(max(0, index))
        wheel_index = self._wheel_action_combo.findData(self._initial.wheel_action)
        self._wheel_action_combo.setCurrentIndex(max(0, wheel_index))
        language_index = self._language_combo.findData(self._initial.language)
        self._language_combo.setCurrentIndex(max(0, language_index))
        self._export_dpi_spin.setValue(self._initial.export_dpi)
        self._fallback_dpi_spin.setValue(self._initial.fallback_dpi)
        self._open_mode_combo.setCurrentIndex(self._open_mode_combo.findData(self._initial.open_mode))
        for widget,name in ((self._home_recent,"home_recent"),(self._maximized,"start_maximized"),
                (self._text_list,"text_list_visible"),(self._auto_text,"auto_select_text"),
                (self._png_all,"png_all_pages"),(self._suppress_help,"suppress_ghostscript_help")):
            widget.setChecked(getattr(self._initial,name))
        self._scope.setCurrentIndex(self._scope.findData(self._initial.rotation_scope))
        self._tolerance.setValue(self._initial.color_tolerance)
        for widget,name in ((self._video_fps,"video_fps"),(self._video_width,"video_width"),(self._video_height,"video_height")):
            widget.setValue(getattr(self._initial,name))
        self._video_format.setCurrentIndex(self._video_format.findData(self._initial.video_format))
        self._video_color.setText(self._initial.video_background)
        for name,box in self._toolbar_boxes.items():
            box.setChecked(name in self._initial.toolbar_tools)
        for name,box in self._compare_boxes.items():
            box.setChecked(getattr(self._initial,name))
        self._update_color_button()
        self._sync_enabled_states()

    def _browse_ghostscript(self) -> None:
        current = Path(self._ghostscript_edit.text().strip()).expanduser()
        start = str(current.parent if current.is_file() else Path.home())
        executable_filter = (
            "Ghostscript (gswin64c.exe gswin32c.exe gs.exe);;"
            + tr("可执行文件 (*.exe);;所有文件 (*.*)")
            if sys.platform == "win32"
            else f"Ghostscript (gs);;{tr('所有文件 (*)')}"
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            tr("选择 Ghostscript 控制台程序"),
            start,
            executable_filter,
        )
        if filename:
            self._ghostscript_edit.setText(filename)

    def _choose_background_color(self) -> None:
        selected = QColorDialog.getColor(
            self._custom_color,
            self,
            tr("选择预览背景颜色"),
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if selected.isValid():
            self._custom_color = selected
            self._update_color_button()

    def _update_color_button(self) -> None:
        color_name = self._custom_color.name(QColor.NameFormat.HexRgb).upper()
        luminance = (
            0.2126 * self._custom_color.red()
            + 0.7152 * self._custom_color.green()
            + 0.0722 * self._custom_color.blue()
        )
        foreground = "#000000" if luminance >= 140 else "#FFFFFF"
        self._color_button.setText(color_name)
        self._color_button.setStyleSheet(
            f"QPushButton {{ background-color: {color_name}; color: {foreground}; }}"
        )

    def _sync_enabled_states(self) -> None:
        self._refresh_interval_spin.setEnabled(self._auto_refresh_check.isChecked())
        self._color_button.setEnabled(self._background_combo.currentData() == "custom")

    def get_config(self) -> AppConfig:
        """Return a validated configuration reflecting the current controls."""
        mode = str(self._background_combo.currentData())
        if mode not in BACKGROUND_MODES:
            mode = "transparent"
        return AppConfig.from_mapping(
            {
                **self._initial.__dict__,
                "ghostscript_path": self._ghostscript_edit.text().strip(),
                "auto_refresh": self._auto_refresh_check.isChecked(),
                "refresh_interval": self._refresh_interval_spin.value(),
                "background_mode": mode,
                "background_color": self._custom_color.name(
                    QColor.NameFormat.HexRgb
                ).upper(),
                "export_dpi": self._export_dpi_spin.value(),
                "fallback_dpi": self._fallback_dpi_spin.value(),
                "wheel_action": str(self._wheel_action_combo.currentData()),
                "language": str(self._language_combo.currentData()),
                "open_mode": str(self._open_mode_combo.currentData()),
                "toolbar_tools": [name for name,box in self._toolbar_boxes.items() if box.isChecked()]
                    if self._toolbar_boxes else self._initial.toolbar_tools,
                "home_recent":self._home_recent.isChecked(), "start_maximized":self._maximized.isChecked(),
                "text_list_visible":self._text_list.isChecked(), "auto_select_text":self._auto_text.isChecked(),
                "rotation_scope":self._scope.currentData(), "png_all_pages":self._png_all.isChecked(),
                "suppress_ghostscript_help":self._suppress_help.isChecked(),
                "color_tolerance":self._tolerance.value(), "video_fps":self._video_fps.value(),
                "video_format":self._video_format.currentData(), "video_width":self._video_width.value(),
                "video_height":self._video_height.value(), "video_background":QColor(self._video_color.text()).name(),
                **{name:box.isChecked() for name,box in self._compare_boxes.items()},
            }
        )

    def config(self) -> AppConfig:
        """Backward-friendly alias for :meth:`get_config`."""
        return self.get_config()


class PngExportDialog(QDialog):
    """Collect and validate the destination and DPI for one PNG export."""

    def __init__(
        self,
        initial_path: str | Path,
        initial_dpi: int = 300,
        page_count: int = 1,
        parent: QWidget | None = None,
        all_pages: bool = True,
    ) -> None:
        super().__init__(parent)
        self._options: PngExportOptions | None = None

        self.setWindowTitle(tr("保存为 PNG"))
        self.setModal(True)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._path_edit = QLineEdit(str(initial_path))
        self._path_edit.setClearButtonEnabled(True)
        browse_button = QPushButton(tr("浏览…"))
        browse_button.clicked.connect(self._browse_output)
        form.addRow(tr("文件："), _joined_row(self._path_edit, browse_button))

        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(MIN_EXPORT_DPI, MAX_EXPORT_DPI)
        self._dpi_spin.setSingleStep(50)
        self._dpi_spin.setSuffix(" DPI")
        self._dpi_spin.setValue(
            max(MIN_EXPORT_DPI, min(int(initial_dpi), MAX_EXPORT_DPI))
        )
        form.addRow(tr("分辨率："), self._dpi_spin)
        self._all_pages_check = QCheckBox(tr("导出所有页面到新文件夹"))
        self._all_pages_check.setEnabled(page_count > 1)
        self._all_pages_check.setChecked(page_count > 1 and all_pages)
        form.addRow("", self._all_pages_check)
        root.addLayout(form)

        note = QLabel(tr("PNG 是位图格式；DPI 越高，导出细节越丰富，文件也越大。"))
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("保存"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_output(self) -> None:
        current = Path(self._path_edit.text().strip()).expanduser()
        start = str(current if current.name else Path.home() / "figure.png")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            tr("保存 PNG 文件"),
            start,
            tr("PNG 图像 (*.png)"),
            options=QFileDialog.Option.DontConfirmOverwrite,
        )
        if filename:
            self._path_edit.setText(str(self._normalize_png_path(filename)))

    @staticmethod
    def _normalize_png_path(value: str | Path) -> Path:
        path = Path(value).expanduser()
        if path.suffix.lower() != ".png":
            path = path.with_suffix(".png")
        return path.resolve()

    def accept(self) -> None:  # type: ignore[override]
        raw_path = self._path_edit.text().strip()
        if not raw_path:
            QMessageBox.warning(self, tr("无法保存"), tr("请选择 PNG 文件的保存位置。"))
            return
        try:
            path = self._normalize_png_path(raw_path)
        except (OSError, ValueError):
            QMessageBox.warning(self, tr("无法保存"), tr("PNG 文件路径无效。"))
            return
        if not path.parent.is_dir():
            QMessageBox.warning(
                self,
                tr("无法保存"),
                tr("保存目录不存在：\n{path}", path=path.parent),
            )
            return
        if path.exists() and path.is_dir():
            QMessageBox.warning(
                self, tr("无法保存"), tr("所选路径是文件夹，不能保存为 PNG。")
            )
            return

        self._path_edit.setText(str(path))
        self._options = PngExportOptions(
            path=path,
            dpi=self._dpi_spin.value(),
            all_pages=self._all_pages_check.isChecked(),
        )
        super().accept()

    def options(self) -> PngExportOptions:
        """Return validated choices after the dialog has been accepted."""
        if self._options is None:
            raise RuntimeError("PNG export options are available only after acceptance.")
        return self._options

    def get_values(self) -> tuple[Path, int, bool]:
        """Return ``(path, dpi, all_pages)`` after acceptance."""
        options = self.options()
        return options.path, options.dpi, options.all_pages
