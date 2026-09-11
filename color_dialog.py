"""Small multi-color replacement editor using Qt's built-in color chooser."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from i18n import tr
from image_transforms import ColorReplacement


class ColorReplacementDialog(QDialog):
    """Edit an ordered list of post-inversion RGB replacements."""

    MAX_REPLACEMENTS = 16

    def __init__(
        self,
        replacements: tuple[ColorReplacement, ...],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("替换颜色"))
        self.setMinimumSize(620, 420)
        root = QVBoxLayout(self)
        note = QLabel(
            tr(
                "颜色替换在反转颜色之后执行。Qt 颜色窗口支持 RGB、HEX 色值；系统支持时也可使用屏幕取色器。"
            )
        )
        note.setWordWrap(True)
        root.addWidget(note)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _item: self._edit_selected())
        root.addWidget(self._list, 1)

        controls = QHBoxLayout()
        add_button = QPushButton(tr("添加…"))
        edit_button = QPushButton(tr("编辑…"))
        remove_button = QPushButton(tr("移除"))
        clear_button = QPushButton(tr("全部清除"))
        add_button.clicked.connect(self._add)
        edit_button.clicked.connect(self._edit_selected)
        remove_button.clicked.connect(self._remove_selected)
        clear_button.clicked.connect(self._list.clear)
        controls.addWidget(add_button)
        controls.addWidget(edit_button)
        controls.addWidget(remove_button)
        controls.addWidget(clear_button)
        controls.addStretch(1)
        root.addLayout(controls)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("确定"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        for replacement in replacements:
            self._list.addItem(self._item(replacement))

    @staticmethod
    def _item(replacement: ColorReplacement) -> QListWidgetItem:
        item = QListWidgetItem(
            tr(
                "{source} → {target}　容差 ±{tolerance}",
                source=replacement.source,
                target=replacement.target,
                tolerance=replacement.tolerance,
            )
        )
        item.setData(Qt.ItemDataRole.UserRole, replacement)
        return item

    def _choose_replacement(
        self, initial: ColorReplacement | None = None
    ) -> ColorReplacement | None:
        source = QColorDialog.getColor(
            QColor(initial.source if initial else "#000000"),
            self,
            tr("选择要替换的颜色"),
        )
        if not source.isValid():
            return None
        target = QColorDialog.getColor(
            QColor(initial.target if initial else "#FFFFFF"),
            self,
            tr("选择替换后的颜色"),
        )
        if not target.isValid():
            return None
        tolerance, accepted = QInputDialog.getInt(
            self,
            tr("颜色容差"),
            tr("RGB 各通道允许的差值（0 为精确匹配）："),
            initial.tolerance if initial else 8,
            0,
            255,
        )
        if not accepted:
            return None
        return ColorReplacement(source.name(), target.name(), tolerance)

    def _add(self) -> None:
        if self._list.count() >= self.MAX_REPLACEMENTS:
            QMessageBox.information(
                self,
                tr("替换颜色"),
                tr("最多可以添加 {count} 组颜色替换。", count=self.MAX_REPLACEMENTS),
            )
            return
        replacement = self._choose_replacement()
        if replacement is not None:
            self._list.addItem(self._item(replacement))

    def _edit_selected(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        replacement = self._choose_replacement(item.data(Qt.ItemDataRole.UserRole))
        if replacement is None:
            return
        row = self._list.row(item)
        self._list.takeItem(row)
        self._list.insertItem(row, self._item(replacement))
        self._list.setCurrentRow(row)

    def _remove_selected(self) -> None:
        for item in self._list.selectedItems():
            self._list.takeItem(self._list.row(item))

    def replacements(self) -> tuple[ColorReplacement, ...]:
        return tuple(
            self._list.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self._list.count())
        )
