"""Editable replacement mappings with cancellable, low-resolution live preview."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import (
    QColorDialog, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)

from background_tasks import TaskRunner
from i18n import tr
from image_transforms import ColorReplacement, apply_color_adjustments, rotate_image
from preview_widgets import ImagePreview


class ColorReplacementDialog(QDialog):
    MAX_REPLACEMENTS = 16

    def __init__(self, replacements, parent: QWidget | None = None, *,
                 preview_loader=None, inverted=False, rotation=0):
        super().__init__(parent)
        self.setWindowTitle(tr("替换颜色"))
        self.resize(960 if preview_loader else 620, 560)
        self._runner = TaskRunner(self)
        self._loader = preview_loader
        self._inverted, self._rotation = inverted, rotation
        self._raw = QImage()
        self._adjusted = QImage()
        self._revision = 0
        self._updating = False
        self._finished = False
        root = QVBoxLayout(self)
        note = QLabel(tr("选择列表中的颜色即可编辑；更改会实时预览，确定后应用，取消则保留原设置。颜色替换在反色之后执行。"))
        note.setWordWrap(True)
        root.addWidget(note)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._selection_changed)
        left.addWidget(self._list, 1)
        controls = QHBoxLayout()
        self._add_button = QPushButton(tr("添加…"))
        remove = QPushButton(tr("移除"))
        clear = QPushButton(tr("全部清除"))
        self._add_button.clicked.connect(self._add)
        remove.clicked.connect(self._remove_selected)
        clear.clicked.connect(self._clear)
        for button in (self._add_button, remove, clear):
            controls.addWidget(button)
        left.addLayout(controls)
        form = QFormLayout()
        self._source_edit = QLineEdit()
        self._target_edit = QLineEdit()
        for label, field in (("源颜色：", self._source_edit), ("目标颜色：", self._target_edit)):
            row = QHBoxLayout()
            field.setPlaceholderText("#RRGGBB")
            field.textChanged.connect(self._update_mapping)
            row.addWidget(field)
            button = QPushButton(tr("选色…"))
            button.clicked.connect(lambda _checked=False, edit=field: self._choose_field(edit))
            row.addWidget(button)
            form.addRow(tr(label), row)
        self._tolerance = QSpinBox()
        self._tolerance.setRange(0, 255)
        self._tolerance.setToolTip(tr("RGB 各通道允许的差值（0 为精确匹配）："))
        self._tolerance.valueChanged.connect(self._update_mapping)
        form.addRow(tr("颜色容差"), self._tolerance)
        left.addLayout(form)
        body.addLayout(left, 1)

        right = QVBoxLayout()
        self._image_preview = ImagePreview()
        right.addWidget(self._image_preview, 1)
        self._original_button = QPushButton(tr("按住查看原图"))
        self._original_button.setToolTip(tr("显示原始配色，保留当前页面旋转。"))
        self._original_button.pressed.connect(lambda: self._image_preview.set_image(self._raw))
        self._original_button.released.connect(lambda: self._image_preview.set_image(self._adjusted))
        right.addWidget(self._original_button)
        if preview_loader is not None:
            body.addLayout(right, 1)
        else:
            self._image_preview.hide()
            self._original_button.hide()
        root.addLayout(body, 1)
        self._status = QLabel()
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("确定"))
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render_preview)
        for replacement in replacements:
            self._list.addItem(self._item(replacement))
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._selection_changed(None)
        if preview_loader is not None:
            QTimer.singleShot(0, self._load_preview)

    @staticmethod
    def _item(replacement):
        item = QListWidgetItem()
        ColorReplacementDialog._set_item(item, replacement)
        return item

    @staticmethod
    def _set_item(item, replacement):
        item.setText(tr("{source} → {target}　容差 ±{tolerance}", source=replacement.source,
                        target=replacement.target, tolerance=replacement.tolerance))
        item.setData(Qt.ItemDataRole.UserRole, replacement)

    def _selection_changed(self, item, _previous=None):
        self._updating = True
        enabled = item is not None
        for field in (self._source_edit, self._target_edit, self._tolerance):
            field.setEnabled(enabled)
        if enabled:
            mapping = item.data(Qt.ItemDataRole.UserRole)
            self._source_edit.setText(mapping.source)
            self._target_edit.setText(mapping.target)
            self._tolerance.setValue(mapping.tolerance)
        else:
            self._source_edit.clear()
            self._target_edit.clear()
        self._updating = False
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(True)
        self._add_button.setEnabled(self._list.count() < self.MAX_REPLACEMENTS)

    def _update_mapping(self, *_args):
        if self._updating:
            return
        item = self._list.currentItem()
        if item is None:
            return
        source, target = QColor(self._source_edit.text()), QColor(self._target_edit.text())
        valid = source.isValid() and target.isValid()
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(valid)
        if not valid:
            self._revision += 1
            self._timer.stop()
            if not self._raw.isNull():
                self._runner.cancel_all()
            self._status.setText(tr("请输入有效颜色，例如 #FFFFFF，或点击选色。"))
            return
        self._set_item(item, ColorReplacement(source.name(), target.name(), self._tolerance.value()))
        self._queue_preview()

    def _choose_field(self, field):
        if not field.isEnabled():
            return
        previous = field.text()
        picker = QColorDialog(QColor(previous), self)
        picker.setOption(QColorDialog.ColorDialogOption.DontUseNativeDialog, True)
        picker.currentColorChanged.connect(lambda color: field.setText(color.name()))
        try:
            if picker.exec() != QDialog.DialogCode.Accepted:
                field.setText(previous)
        finally:
            picker.deleteLater()

    def _add(self):
        if self._list.count() >= self.MAX_REPLACEMENTS:
            return
        self._list.addItem(self._item(ColorReplacement("#000000", "#FFFFFF", 8)))
        self._list.setCurrentRow(self._list.count() - 1)
        self._queue_preview()

    def _remove_selected(self):
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))
        self._selection_changed(self._list.currentItem())
        self._queue_preview()

    def _clear(self):
        self._list.clear()
        self._selection_changed(None)
        self._queue_preview()

    def replacements(self):
        return tuple(self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count()))

    def _load_preview(self):
        if self._finished:
            return
        self._status.setText(tr("正在准备预览…"))
        loader, rotation = self._loader, self._rotation
        self._runner.submit(
            lambda cancel: rotate_image(loader(cancel), rotation), self._preview_loaded)

    def _preview_loaded(self, image, error, cancelled):
        if cancelled or self._finished:
            return
        if error is not None:
            self._status.setText(tr("预览失败：{error}", error=error))
            return
        self._raw = image
        self._queue_preview()

    def _queue_preview(self):
        self._revision += 1
        if self._loader is not None and not self._raw.isNull():
            self._runner.cancel_all()
            self._timer.start(150)

    def _render_preview(self):
        if self._finished or self._raw.isNull():
            return
        revision = self._revision
        raw, inverted, mappings = self._raw, self._inverted, self.replacements()
        self._status.setText(tr("正在更新预览…"))
        self._runner.submit(
            lambda cancel: apply_color_adjustments(raw, inverted, mappings, cancel),
            lambda image, error, cancelled: self._preview_ready(revision, image, error, cancelled),
        )

    def _preview_ready(self, revision, image, error, cancelled):
        if cancelled or self._finished or revision != self._revision:
            return
        if error is not None:
            self._status.setText(tr("预览失败：{error}", error=error))
            return
        self._adjusted = image
        if not self._original_button.isDown():
            self._image_preview.set_image(image)
        self._status.setText(tr("预览已更新；确定后应用到当前文件。"))

    def done(self, result):
        self._timer.stop()
        if not self._runner.shutdown():
            QTimer.singleShot(100, lambda: self.done(result))
            return
        self._finished = True
        super().done(result)
