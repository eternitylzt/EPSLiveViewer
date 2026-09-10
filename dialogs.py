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
)

from config import (
    BACKGROUND_MODES,
    MAX_EXPORT_DPI,
    MAX_REFRESH_INTERVAL,
    MIN_EXPORT_DPI,
    MIN_REFRESH_INTERVAL,
    AppConfig,
)


@dataclass(frozen=True)
class PngExportOptions:
    """Validated choices returned by :class:`PngExportDialog`."""

    path: Path
    dpi: int


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

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._initial = AppConfig.from_mapping(config.__dict__)
        self._custom_color = QColor(self._initial.background_color)

        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(540)
        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        runtime_group = QGroupBox("渲染与自动刷新")
        runtime_form = QFormLayout(runtime_group)

        self._ghostscript_edit = QLineEdit()
        self._ghostscript_edit.setPlaceholderText("留空则自动查找 Ghostscript")
        self._ghostscript_edit.setClearButtonEnabled(True)
        browse_gs_button = QPushButton("浏览…")
        browse_gs_button.clicked.connect(self._browse_ghostscript)
        runtime_form.addRow(
            "Ghostscript：", _joined_row(self._ghostscript_edit, browse_gs_button)
        )

        self._auto_refresh_check = QCheckBox("EPS/PS 文件变化后自动刷新")
        self._auto_refresh_check.toggled.connect(self._sync_enabled_states)
        runtime_form.addRow("", self._auto_refresh_check)

        self._refresh_interval_spin = QSpinBox()
        self._refresh_interval_spin.setRange(MIN_REFRESH_INTERVAL, MAX_REFRESH_INTERVAL)
        self._refresh_interval_spin.setSingleStep(100)
        self._refresh_interval_spin.setSuffix(" ms")
        runtime_form.addRow("检测间隔：", self._refresh_interval_spin)
        root.addWidget(runtime_group)

        display_group = QGroupBox("预览背景")
        display_form = QFormLayout(display_group)
        self._background_combo = QComboBox()
        self._background_combo.addItem("透明（棋盘格）", "transparent")
        self._background_combo.addItem("白色", "white")
        self._background_combo.addItem("自定义颜色", "custom")
        self._background_combo.currentIndexChanged.connect(self._sync_enabled_states)
        display_form.addRow("背景：", self._background_combo)

        self._color_button = QPushButton()
        self._color_button.clicked.connect(self._choose_background_color)
        display_form.addRow("自定义颜色：", self._color_button)
        root.addWidget(display_group)

        export_group = QGroupBox("PNG 导出")
        export_form = QFormLayout(export_group)
        self._export_dpi_spin = QSpinBox()
        self._export_dpi_spin.setRange(MIN_EXPORT_DPI, MAX_EXPORT_DPI)
        self._export_dpi_spin.setSingleStep(50)
        self._export_dpi_spin.setSuffix(" DPI")
        export_form.addRow("默认分辨率：", self._export_dpi_spin)
        export_note = QLabel("预览清晰度会随缩放自动调整，此 DPI 只用于保存 PNG。")
        export_note.setWordWrap(True)
        export_note.setStyleSheet("color: palette(mid);")
        export_form.addRow("", export_note)
        root.addWidget(export_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _load_values(self) -> None:
        self._ghostscript_edit.setText(self._initial.ghostscript_path)
        self._auto_refresh_check.setChecked(self._initial.auto_refresh)
        self._refresh_interval_spin.setValue(self._initial.refresh_interval)
        index = self._background_combo.findData(self._initial.background_mode)
        self._background_combo.setCurrentIndex(max(0, index))
        self._export_dpi_spin.setValue(self._initial.export_dpi)
        self._update_color_button()
        self._sync_enabled_states()

    def _browse_ghostscript(self) -> None:
        current = Path(self._ghostscript_edit.text().strip()).expanduser()
        start = str(current.parent if current.is_file() else Path.home())
        executable_filter = (
            "Ghostscript (gswin64c.exe gswin32c.exe gs.exe);;"
            "可执行文件 (*.exe);;所有文件 (*.*)"
            if sys.platform == "win32"
            else "Ghostscript (gs);;所有文件 (*)"
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "选择 Ghostscript 控制台程序",
            start,
            executable_filter,
        )
        if filename:
            self._ghostscript_edit.setText(filename)

    def _choose_background_color(self) -> None:
        selected = QColorDialog.getColor(
            self._custom_color,
            self,
            "选择预览背景颜色",
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
                "ghostscript_path": self._ghostscript_edit.text().strip(),
                "auto_refresh": self._auto_refresh_check.isChecked(),
                "refresh_interval": self._refresh_interval_spin.value(),
                "background_mode": mode,
                "background_color": self._custom_color.name(
                    QColor.NameFormat.HexRgb
                ).upper(),
                "export_dpi": self._export_dpi_spin.value(),
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
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._options: PngExportOptions | None = None

        self.setWindowTitle("保存为 PNG")
        self.setModal(True)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self._path_edit = QLineEdit(str(initial_path))
        self._path_edit.setClearButtonEnabled(True)
        browse_button = QPushButton("浏览…")
        browse_button.clicked.connect(self._browse_output)
        form.addRow("文件：", _joined_row(self._path_edit, browse_button))

        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(MIN_EXPORT_DPI, MAX_EXPORT_DPI)
        self._dpi_spin.setSingleStep(50)
        self._dpi_spin.setSuffix(" DPI")
        self._dpi_spin.setValue(
            max(MIN_EXPORT_DPI, min(int(initial_dpi), MAX_EXPORT_DPI))
        )
        form.addRow("分辨率：", self._dpi_spin)
        root.addLayout(form)

        note = QLabel("PNG 是位图格式；DPI 越高，导出细节越丰富，文件也越大。")
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        root.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse_output(self) -> None:
        current = Path(self._path_edit.text().strip()).expanduser()
        start = str(current if current.name else Path.home() / "figure.png")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "保存 PNG 文件",
            start,
            "PNG 图像 (*.png)",
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
            QMessageBox.warning(self, "无法保存", "请选择 PNG 文件的保存位置。")
            return
        try:
            path = self._normalize_png_path(raw_path)
        except (OSError, ValueError):
            QMessageBox.warning(self, "无法保存", "PNG 文件路径无效。")
            return
        if not path.parent.is_dir():
            QMessageBox.warning(self, "无法保存", f"保存目录不存在：\n{path.parent}")
            return
        if path.exists() and path.is_dir():
            QMessageBox.warning(self, "无法保存", "所选路径是文件夹，不能保存为 PNG。")
            return

        self._path_edit.setText(str(path))
        self._options = PngExportOptions(path=path, dpi=self._dpi_spin.value())
        super().accept()

    def options(self) -> PngExportOptions:
        """Return validated choices after the dialog has been accepted."""
        if self._options is None:
            raise RuntimeError("PNG export options are available only after acceptance.")
        return self._options

    def get_values(self) -> tuple[Path, int]:
        """Return ``(path, dpi)`` after the dialog has been accepted."""
        options = self.options()
        return options.path, options.dpi
