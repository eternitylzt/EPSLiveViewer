"""Folder sequence selection and video export options dialog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config import VIDEO_SOURCE_SUFFIXES, filename_sort_key
from crop_dialog import CropSelectionDialog, NormalizedCrop
from eps_renderer import EpsRenderer
from i18n import tr
from image_transforms import TransformSnapshot
from video_creator import VideoExporter, VideoExportRequest, VideoFrameSource
from animation_preview import AnimationPreviewDialog
from document_state import load_state


@dataclass(frozen=True)
class _ResolutionPreset:
    label: str
    width: int
    height: int


_PRESETS = (
    _ResolutionPreset("Full HD（1920 × 1080）", 1920, 1080),
    _ResolutionPreset("HD（1280 × 720）", 1280, 720),
    _ResolutionPreset("4K UHD（3840 × 2160）", 3840, 2160),
)


class VideoCreationDialog(QDialog):
    """Choose an ordered folder sequence and the MP4/GIF output settings."""

    def __init__(
        self,
        initial_folder: Path,
        renderer: EpsRenderer,
        transforms_by_source: dict[Path, TransformSnapshot] | None = None,
        parent: QWidget | None = None,
        current_file: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("制作视频"))
        self.setMinimumSize(860, 620)
        self._current_file = current_file
        self.resize(980, 700)
        self._renderer = renderer
        self._transforms_by_source = {
            Path(path).resolve(): transforms
            for path, transforms in (transforms_by_source or {}).items()
        }
        self._background_color = QColor("#FFFFFF")
        self._crop_rect: NormalizedCrop | None = None
        self._reference_source: VideoFrameSource | None = None
        self._reference_raster_size: tuple[int, int] | None = None
        self._preview_key: tuple | None = None
        self._reference_preview = QImage()

        root = QVBoxLayout(self)
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel(tr("源文件夹：")))
        self._folder_edit = QLineEdit()
        self._folder_edit.setReadOnly(True)
        folder_row.addWidget(self._folder_edit, 1)
        browse_folder = QPushButton(tr("选择文件夹…"))
        browse_folder.clicked.connect(self._choose_folder)
        folder_row.addWidget(browse_folder)
        root.addLayout(folder_row)
        source_row = QHBoxLayout()
        self._scope_combo = QComboBox()
        self._scope_combo.addItem(tr("文件夹内的图片"), "folder")
        if current_file is not None:
            self._scope_combo.addItem(tr("当前文件的全部页面"), "current")
            if current_file.suffix.lower() in {".eps", ".ps", ".pdf"}:
                self._scope_combo.setCurrentIndex(1)
        source_row.addWidget(self._scope_combo)
        self._format_filter = QComboBox()
        for label, suffixes in (("EPS / PS / PDF / PNG / JPG", (".eps", ".ps", ".pdf", ".png", ".jpg", ".jpeg")),
                                ("EPS / PS", (".eps", ".ps")), ("PNG / JPG", (".png", ".jpg", ".jpeg")),
                                ("EPS", (".eps",)), ("PS", (".ps",)), ("PDF", (".pdf",)), ("PNG", (".png",)), ("JPG", (".jpg", ".jpeg"))):
            self._format_filter.addItem(label, suffixes)
        source_row.addWidget(self._format_filter)
        root.addLayout(source_row)

        hint = QLabel(
            tr(
                "支持 EPS、PS、PDF、PNG、JPG/JPEG；多页文件会逐页展开。左侧帧按显示顺序写入，可将不需要的帧移到右侧。"
            )
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        list_grid = QGridLayout()
        list_grid.addWidget(QLabel(tr("参与视频")), 0, 0)
        list_grid.addWidget(QLabel(tr("已排除")), 0, 2)
        self._included = self._new_list(allow_reorder=True)
        self._excluded = self._new_list(allow_reorder=False)
        self._included.model().rowsMoved.connect(lambda *_args: self._sync_reference())
        self._included.itemDoubleClicked.connect(
            lambda _item: self._move_selected(self._included, self._excluded)
        )
        self._excluded.itemDoubleClicked.connect(
            lambda _item: self._move_selected(self._excluded, self._included)
        )
        list_grid.addWidget(self._included, 1, 0)
        move_buttons = QVBoxLayout()
        move_buttons.addStretch(1)
        exclude_button = QPushButton(tr("排除 →"))
        exclude_button.clicked.connect(
            lambda: self._move_selected(self._included, self._excluded)
        )
        include_button = QPushButton(tr("← 加回"))
        include_button.clicked.connect(
            lambda: self._move_selected(self._excluded, self._included)
        )
        move_buttons.addWidget(exclude_button)
        move_buttons.addWidget(include_button)
        move_buttons.addStretch(1)
        list_grid.addLayout(move_buttons, 1, 1)
        list_grid.addWidget(self._excluded, 1, 2)

        order_row = QHBoxLayout()
        self._count_label = QLabel()
        order_row.addWidget(self._count_label)
        order_row.addStretch(1)
        up_button = QPushButton(tr("上移"))
        down_button = QPushButton(tr("下移"))
        up_button.clicked.connect(lambda: self._move_order(-1))
        down_button.clicked.connect(lambda: self._move_order(1))
        order_row.addWidget(up_button)
        order_row.addWidget(down_button)
        list_grid.addLayout(order_row, 2, 0)
        root.addLayout(list_grid, 1)

        crop_row = QHBoxLayout()
        self._reference_label = QLabel(tr("首帧：—"))
        self._reference_label.setWordWrap(True)
        crop_row.addWidget(self._reference_label, 1)
        self._crop_button = QPushButton(tr("预览并选择区域…"))
        self._crop_button.clicked.connect(self._choose_crop_region)
        self._crop_button.setEnabled(False)
        crop_row.addWidget(self._crop_button)
        self._clear_crop_button = QPushButton(tr("恢复完整图像"))
        self._clear_crop_button.clicked.connect(self._clear_crop)
        self._clear_crop_button.setEnabled(False)
        crop_row.addWidget(self._clear_crop_button)
        self._trial_button = QPushButton(tr("试播…"))
        self._trial_button.clicked.connect(self._show_trial)
        crop_row.addWidget(self._trial_button)
        root.addLayout(crop_row)

        options = QGroupBox(tr("输出参数"))
        form = QFormLayout(options)
        self._format_combo = QComboBox()
        self._format_combo.addItem(tr("MP4 视频"), "mp4")
        self._format_combo.addItem(tr("GIF 动图"), "gif")
        self._format_combo.currentIndexChanged.connect(self._format_changed)
        form.addRow(tr("格式："), self._format_combo)

        self._preset_combo = QComboBox()
        for preset in _PRESETS:
            self._preset_combo.addItem(preset.label, (preset.width, preset.height))
        self._preset_combo.addItem(tr("自定义"), None)
        self._preset_combo.currentIndexChanged.connect(self._preset_changed)
        form.addRow(tr("分辨率："), self._preset_combo)

        dimensions = QHBoxLayout()
        self._width_spin = self._dimension_spin(1920)
        self._height_spin = self._dimension_spin(1080)
        self._width_spin.valueChanged.connect(self._dimensions_changed)
        self._height_spin.valueChanged.connect(self._dimensions_changed)
        dimensions.addWidget(self._width_spin)
        dimensions.addWidget(QLabel("×"))
        dimensions.addWidget(self._height_spin)
        dimensions.addStretch(1)
        form.addRow(tr("画布（像素）："), dimensions)

        self._fps_spin = QSpinBox()
        self._fps_spin.setRange(1, 60)
        self._fps_spin.setValue(10)
        self._fps_spin.setSuffix(" FPS")
        form.addRow(tr("帧率："), self._fps_spin)
        self._duration_label = QLabel()
        self._fps_spin.valueChanged.connect(self._update_timing)
        form.addRow(self._duration_label)

        encoding_note = QLabel(tr(
            "MP4 使用兼容播放器的 H.264 编码；奇数宽高会在右侧或底部补 1 像素。每张图片/每页对应一帧，帧率决定切换速度。"
        ))
        encoding_note.setWordWrap(True)
        form.addRow(encoding_note)

        self._color_button = QPushButton()
        self._color_button.clicked.connect(self._choose_color)
        self._update_color_button()
        form.addRow(tr("背景："), self._color_button)

        output_row = QHBoxLayout()
        self._output_edit = QLineEdit()
        output_row.addWidget(self._output_edit, 1)
        browse_output = QPushButton(tr("浏览…"))
        browse_output.clicked.connect(self._choose_output)
        output_row.addWidget(browse_output)
        form.addRow(tr("输出文件："), output_row)
        root.addWidget(options)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("开始生成"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        folder = Path(initial_folder).expanduser()
        if not folder.is_dir():
            folder = Path.home()
        self._load_folder(folder)
        self._scope_combo.currentIndexChanged.connect(lambda: self._load_folder(Path(self._folder_edit.text())))
        self._format_filter.currentIndexChanged.connect(lambda: self._load_folder(Path(self._folder_edit.text())))

    @staticmethod
    def _new_list(allow_reorder: bool) -> QListWidget:
        widget = QListWidget()
        widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if allow_reorder:
            widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        return widget

    @staticmethod
    def _dimension_spin(value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(2, 30_000)
        spin.setSingleStep(2)
        spin.setValue(value)
        return spin

    def _choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            tr("选择序列文件夹"),
            self._folder_edit.text() or str(Path.home()),
        )
        if chosen:
            self._scope_combo.blockSignals(True)
            self._scope_combo.setCurrentIndex(0)
            self._scope_combo.blockSignals(False)
            self._load_folder(Path(chosen))

    def _load_folder(self, folder: Path) -> None:
        try:
            files = sorted(
                (
                    item.resolve()
                    for item in folder.iterdir()
                    if item.is_file() and item.suffix.lower() in VIDEO_SOURCE_SUFFIXES
                ),
                key=filename_sort_key,
            )
        except OSError as error:
            QMessageBox.warning(self, tr("无法读取文件夹"), str(error))
            return
        self._folder_edit.setText(str(folder.resolve()))
        if self._scope_combo.currentData() == "current":
            files = [Path(self._current_file).resolve()]
        else:
            suffixes = self._format_filter.currentData()
            files = [path for path in files if path.suffix.lower() in suffixes]
        self._included.clear()
        self._excluded.clear()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for path in files:
                transforms = self._transforms_by_source.get(path)
                if transforms is None:
                    try:
                        transforms = load_state(path)
                    except (OSError, ValueError, TypeError, KeyError) as error:
                        QMessageBox.warning(self, tr("无法读取编辑记录"), f"{path.name}\n{error}")
                        transforms = TransformSnapshot()
                page_count = 1
                if path.suffix.lower() in {".eps", ".ps", ".pdf"}:
                    try:
                        page_count = self._renderer.page_count(path)
                    except Exception:
                        # Rendering will provide the full error if export starts.
                        page_count = 1
                for page_number in range(1, page_count + 1):
                    frame = VideoFrameSource(path, page_number, transforms)
                    self._included.addItem(self._file_item(frame, page_count))
        finally:
            QApplication.restoreOverrideCursor()
        self._update_count()
        self._sync_reference(force=True)
        self._output_edit.setText(str(folder.resolve() / "sequence.mp4"))

    @staticmethod
    def _file_item(frame: VideoFrameSource, page_count: int) -> QListWidgetItem:
        label = frame.path.name
        if page_count > 1:
            label = tr(
                "{name} — 第 {page}/{total} 页",
                name=frame.path.name,
                page=frame.page_number,
                total=page_count,
            )
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, frame)
        item.setToolTip(str(frame.path))
        return item

    def _move_selected(self, source: QListWidget, target: QListWidget) -> None:
        selected_rows = sorted(
            (source.row(item) for item in source.selectedItems()), reverse=True
        )
        moved: list[QListWidgetItem] = []
        for row in selected_rows:
            moved.append(source.takeItem(row))
        for item in reversed(moved):
            target.addItem(item)
            item.setSelected(True)
        self._update_count()
        self._sync_reference()

    def _move_order(self, direction: int) -> None:
        row = self._included.currentRow()
        destination = row + direction
        if row < 0 or destination < 0 or destination >= self._included.count():
            return
        item = self._included.takeItem(row)
        self._included.insertItem(destination, item)
        self._included.setCurrentItem(item)
        self._sync_reference()

    def _update_count(self) -> None:
        self._count_label.setText(
            tr(
                "参与 {included} 帧；排除 {excluded} 帧",
                included=self._included.count(),
                excluded=self._excluded.count(),
            )
        )
        self._update_timing()
        self._trial_button.setEnabled(self._included.count() > 0)

    def _update_timing(self):
        count, fps = self._included.count(), self._fps_spin.value()
        self._duration_label.setText(tr("{frames} 帧 · {fps} FPS · 预计 {duration:.2f} 秒",
                                        frames=count, fps=fps, duration=count / fps))

    def _show_trial(self):
        try:
            dialog = AnimationPreviewDialog(self.request(), VideoExporter(self._renderer), self)
        except Exception as error:
            QMessageBox.warning(self, tr("视频试播"), str(error))
            return
        try:
            dialog.exec()
        finally:
            dialog.close()
            dialog.deleteLater()

    def _first_source(self) -> VideoFrameSource | None:
        if self._included.count() == 0:
            return None
        return self._included.item(0).data(Qt.ItemDataRole.UserRole)

    def _set_dimensions(self, width: int, height: int) -> None:
        self._width_spin.blockSignals(True)
        self._height_spin.blockSignals(True)
        self._width_spin.setValue(width)
        self._height_spin.setValue(height)
        self._width_spin.blockSignals(False)
        self._height_spin.blockSignals(False)
        self._dimensions_changed()

    def _remember_raster_size(self, source: VideoFrameSource) -> None:
        self._reference_raster_size = None
        if source.path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            return
        try:
            image = VideoExporter.read_raster(source.path)
        except RuntimeError as error:
            self._reference_label.setText(
                tr("首帧：{name}（{error}）", name=source.display_name, error=error)
            )
            return
        size = image.size()
        if source.transforms.rotation_for(source.page_number) in {90, 270}:
            size.transpose()
        self._reference_raster_size = (size.width(), size.height())
        self._set_dimensions(*self._reference_raster_size)

    def _sync_reference(self, force: bool = False) -> None:
        source = self._first_source()
        if not force and source == self._reference_source:
            return
        self._reference_source = source
        self._crop_rect = None
        self._reference_raster_size = None
        self._clear_crop_button.setEnabled(False)
        self._crop_button.setEnabled(source is not None)
        if source is None:
            self._reference_label.setText(tr("首帧：—"))
            return
        self._reference_label.setText(
            tr("首帧：{name}　使用完整图像", name=source.display_name)
        )
        self._remember_raster_size(source)
        if self._reference_raster_size is not None:
            width, height = self._reference_raster_size
            self._reference_label.setText(
                tr(
                    "首帧：{name}　{width} × {height} 像素　使用完整图像",
                    name=source.display_name,
                    width=width,
                    height=height,
                )
            )

    def _load_reference_preview(self) -> QImage:
        if self._reference_source is None:
            raise RuntimeError(tr("没有可预览的首帧。"))
        stat = self._reference_source.path.stat()
        key = (self._reference_source, stat.st_mtime_ns, stat.st_size,
               self._background_color.name())
        if key == self._preview_key:
            return QImage(self._reference_preview)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._reference_preview = VideoExporter(self._renderer).read_frame(
                self._reference_source, self._background_color.name()
            )
            self._preview_key = key
            return QImage(self._reference_preview)
        finally:
            QApplication.restoreOverrideCursor()

    def _choose_crop_region(self) -> None:
        if self._reference_source is None:
            return
        try:
            image = self._load_reference_preview()
        except Exception as error:
            QMessageBox.warning(self, tr("无法预览首帧"), str(error))
            return
        dialog = CropSelectionDialog(
            image,
            self._reference_source.display_name,
            self._crop_rect,
            self,
        )
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            self._crop_rect = dialog.normalized_crop()
            crop_width, crop_height = dialog.pixel_crop_size()
        finally:
            dialog.deleteLater()
        if self._crop_rect is None:
            if self._reference_raster_size is not None:
                self._set_dimensions(*self._reference_raster_size)
            self._reference_label.setText(
                tr(
                    "首帧：{name}　使用完整图像",
                    name=self._reference_source.display_name,
                )
            )
            self._clear_crop_button.setEnabled(False)
            return
        self._set_dimensions(crop_width, crop_height)
        self._reference_label.setText(
            tr(
                "首帧：{name}　选定区域 {width} × {height} 像素；后续帧按相同比例裁剪",
                name=self._reference_source.display_name,
                width=crop_width,
                height=crop_height,
            )
        )
        self._clear_crop_button.setEnabled(True)

    def _clear_crop(self) -> None:
        self._crop_rect = None
        self._clear_crop_button.setEnabled(False)
        if self._reference_source is None:
            return
        if self._reference_raster_size is not None:
            self._set_dimensions(*self._reference_raster_size)
            width, height = self._reference_raster_size
            self._reference_label.setText(
                tr(
                    "首帧：{name}　{width} × {height} 像素　使用完整图像",
                    name=self._reference_source.display_name,
                    width=width,
                    height=height,
                )
            )
        else:
            self._reference_label.setText(
                tr(
                    "首帧：{name}　使用完整图像",
                    name=self._reference_source.display_name,
                )
            )

    def _preset_changed(self, index: int) -> None:
        dimensions = self._preset_combo.itemData(index)
        if dimensions is None:
            return
        self._width_spin.blockSignals(True)
        self._height_spin.blockSignals(True)
        self._width_spin.setValue(dimensions[0])
        self._height_spin.setValue(dimensions[1])
        self._width_spin.blockSignals(False)
        self._height_spin.blockSignals(False)

    def _dimensions_changed(self) -> None:
        dimensions = (self._width_spin.value(), self._height_spin.value())
        for index in range(len(_PRESETS)):
            if self._preset_combo.itemData(index) == dimensions:
                self._preset_combo.blockSignals(True)
                self._preset_combo.setCurrentIndex(index)
                self._preset_combo.blockSignals(False)
                return
        self._preset_combo.blockSignals(True)
        self._preset_combo.setCurrentIndex(self._preset_combo.count() - 1)
        self._preset_combo.blockSignals(False)

    def _choose_color(self) -> None:
        color = QColorDialog.getColor(
            self._background_color,
            self,
            tr("选择视频背景颜色"),
        )
        if color.isValid():
            self._background_color = color
            self._update_color_button()

    def _update_color_button(self) -> None:
        name = self._background_color.name().upper()
        foreground = "#000000" if self._background_color.lightness() > 128 else "#FFFFFF"
        self._color_button.setText(name)
        self._color_button.setStyleSheet(
            f"background-color: {name}; color: {foreground}; padding: 4px 18px;"
        )

    def _format_changed(self) -> None:
        output_format = self._format_combo.currentData()
        current = Path(self._output_edit.text().strip() or "sequence.mp4")
        self._output_edit.setText(str(current.with_suffix(f".{output_format}")))

    def _choose_output(self) -> None:
        output_format = self._format_combo.currentData()
        file_filter = (
            tr("MP4 视频 (*.mp4)")
            if output_format == "mp4"
            else tr("GIF 动图 (*.gif)")
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            tr("保存视频"),
            self._output_edit.text(),
            file_filter,
        )
        if filename:
            self._output_edit.setText(
                str(Path(filename).with_suffix(f".{output_format}"))
            )

    def _validate_and_accept(self) -> None:
        if self._included.count() == 0:
            QMessageBox.warning(
                self, tr("无法生成视频"), tr("请至少保留一个参与视频的文件。")
            )
            return
        output_format = str(self._format_combo.currentData())
        width = self._width_spin.value()
        height = self._height_spin.value()
        if width * height > 33_177_600:
            QMessageBox.warning(
                self,
                tr("分辨率过大"),
                tr("画布像素总数不能超过 8K UHD（7680 × 4320）。"),
            )
            return
        output_text = self._output_edit.text().strip()
        if not output_text:
            QMessageBox.warning(self, tr("输出路径无效"), tr("请选择输出文件。"))
            return
        target = Path(output_text).expanduser().with_suffix(f".{output_format}")
        if target.resolve() in self.selected_files():
            QMessageBox.warning(
                self, tr("输出路径无效"), tr("输出文件不能覆盖序列源文件。")
            )
            return
        self._output_edit.setText(str(target))
        self.accept()

    def selected_files(self) -> tuple[Path, ...]:
        return tuple(dict.fromkeys(
            self._included.item(index).data(Qt.ItemDataRole.UserRole).path
            for index in range(self._included.count())
        ))

    def selected_frames(self) -> tuple[VideoFrameSource, ...]:
        return tuple(
            self._included.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self._included.count())
        )

    def request(self) -> VideoExportRequest:
        output_format = str(self._format_combo.currentData())
        return VideoExportRequest(
            sources=self.selected_frames(),
            target=Path(self._output_edit.text()).with_suffix(f".{output_format}"),
            output_format=output_format,
            width=self._width_spin.value(),
            height=self._height_spin.value(),
            fps=self._fps_spin.value(),
            background_color=self._background_color.name().upper(),
            crop_rect=self._crop_rect,
        )
