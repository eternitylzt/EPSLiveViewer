"""Interactive normalized crop selection for a sequence reference frame."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from i18n import tr


NormalizedCrop = tuple[float, float, float, float]


class CropPreviewWidget(QWidget):
    """Display one frame and select a rectangular image-relative region."""

    selection_changed = pyqtSignal()

    def __init__(
        self,
        image: QImage,
        selection: NormalizedCrop | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._image = image
        self._selection = QRectF(*(selection or (0.0, 0.0, 1.0, 1.0)))
        self._anchor: QPointF | None = None
        self.setMinimumSize(560, 360)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _image_rect(self) -> QRectF:
        if self._image.isNull() or self.width() <= 0 or self.height() <= 0:
            return QRectF()
        margin = 12.0
        available_width = max(1.0, self.width() - margin * 2)
        available_height = max(1.0, self.height() - margin * 2)
        scale = min(
            available_width / self._image.width(),
            available_height / self._image.height(),
        )
        width = self._image.width() * scale
        height = self._image.height() * scale
        return QRectF(
            (self.width() - width) / 2,
            (self.height() - height) / 2,
            width,
            height,
        )

    def _to_normalized(self, position: QPointF) -> QPointF:
        image_rect = self._image_rect()
        x = (position.x() - image_rect.left()) / image_rect.width()
        y = (position.y() - image_rect.top()) / image_rect.height()
        return QPointF(max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))

    def _selection_on_widget(self) -> QRectF:
        image_rect = self._image_rect()
        return QRectF(
            image_rect.left() + self._selection.left() * image_rect.width(),
            image_rect.top() + self._selection.top() * image_rect.height(),
            self._selection.width() * image_rect.width(),
            self._selection.height() * image_rect.height(),
        )

    def set_full_image(self) -> None:
        self._selection = QRectF(0.0, 0.0, 1.0, 1.0)
        self.selection_changed.emit()
        self.update()

    def normalized_crop(self) -> NormalizedCrop | None:
        values = (
            self._selection.x(),
            self._selection.y(),
            self._selection.width(),
            self._selection.height(),
        )
        if all(
            abs(value - expected) < 1e-6
            for value, expected in zip(values, (0, 0, 1, 1))
        ):
            return None
        return values

    def pixel_crop_size(self) -> tuple[int, int]:
        crop = self.normalized_crop() or (0.0, 0.0, 1.0, 1.0)
        left = math.floor(crop[0] * self._image.width())
        top = math.floor(crop[1] * self._image.height())
        right = math.ceil((crop[0] + crop[2]) * self._image.width())
        bottom = math.ceil((crop[1] + crop[3]) * self._image.height())
        return max(1, right - left), max(1, bottom - top)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#242424"))
        image_rect = self._image_rect()
        if image_rect.isEmpty():
            painter.end()
            return
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(image_rect, self._image)

        selected = self._selection_on_widget()
        shade = QColor(0, 0, 0, 150)
        painter.fillRect(
            QRectF(
                image_rect.left(),
                image_rect.top(),
                image_rect.width(),
                selected.top() - image_rect.top(),
            ),
            shade,
        )
        painter.fillRect(
            QRectF(
                image_rect.left(),
                selected.bottom(),
                image_rect.width(),
                image_rect.bottom() - selected.bottom(),
            ),
            shade,
        )
        painter.fillRect(
            QRectF(
                image_rect.left(),
                selected.top(),
                selected.left() - image_rect.left(),
                selected.height(),
            ),
            shade,
        )
        painter.fillRect(
            QRectF(
                selected.right(),
                selected.top(),
                image_rect.right() - selected.right(),
                selected.height(),
            ),
            shade,
        )
        painter.setPen(QPen(QColor("#42A5F5"), 2.0))
        painter.drawRect(selected)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._image_rect().contains(event.position())
        ):
            self._anchor = self._to_normalized(event.position())
            self._selection = QRectF(self._anchor, self._anchor)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._anchor is None:
            return
        current = self._to_normalized(event.position())
        self._selection = QRectF(self._anchor, current).normalized()
        self.selection_changed.emit()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() != Qt.MouseButton.LeftButton or self._anchor is None:
            return
        current = self._to_normalized(event.position())
        candidate = QRectF(self._anchor, current).normalized()
        self._anchor = None
        if (
            candidate.width() * self._image.width() < 2
            or candidate.height() * self._image.height() < 2
        ):
            self.set_full_image()
            return
        self._selection = candidate
        self.selection_changed.emit()
        self.update()


class CropSelectionDialog(QDialog):
    """Modal preview used to confirm the frame region included in output."""

    def __init__(
        self,
        image: QImage,
        filename: str,
        selection: NormalizedCrop | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("选择视频区域"))
        self.resize(900, 680)
        layout = QVBoxLayout(self)
        intro = QLabel(
            tr(
                "参考帧：{name}　{width} × {height} 像素\n在预览图上按住鼠标左键拖拽；该区域会按相同比例应用到后续每一帧。",
                name=filename,
                width=image.width(),
                height=image.height(),
            )
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._preview = CropPreviewWidget(image, selection, self)
        self._preview.selection_changed.connect(self._update_selection_label)
        layout.addWidget(self._preview, 1)

        controls = QHBoxLayout()
        self._selection_label = QLabel()
        controls.addWidget(self._selection_label)
        controls.addStretch(1)
        full_button = QPushButton(tr("使用完整图像"))
        full_button.clicked.connect(self._preview.set_full_image)
        controls.addWidget(full_button)
        layout.addLayout(controls)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("确认区域"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("取消"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_selection_label()

    def _update_selection_label(self) -> None:
        width, height = self._preview.pixel_crop_size()
        crop = self._preview.normalized_crop()
        if crop is None:
            self._selection_label.setText(
                tr("完整图像：{width} × {height} 像素", width=width, height=height)
            )
        else:
            self._selection_label.setText(
                tr(
                    "选定区域：{width} × {height} 像素　（宽 {width_percent:.1f}%，高 {height_percent:.1f}%）",
                    width=width,
                    height=height,
                    width_percent=crop[2] * 100,
                    height_percent=crop[3] * 100,
                )
            )

    def normalized_crop(self) -> NormalizedCrop | None:
        return self._preview.normalized_crop()

    def pixel_crop_size(self) -> tuple[int, int]:
        return self._preview.pixel_crop_size()
