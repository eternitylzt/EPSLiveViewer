"""A lightweight aspect-preserving image surface for auxiliary dialogs."""

from PyQt6.QtCore import QRectF
from PyQt6.QtGui import QBrush, QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QWidget


class ImagePreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._image = QImage()
        self.setMinimumSize(260, 180)
        tile = QPixmap(16, 16)
        tile.fill(QColor("#FAFAFA"))
        painter = QPainter(tile)
        painter.fillRect(0, 0, 8, 8, QColor("#DCDCDC"))
        painter.fillRect(8, 8, 8, 8, QColor("#DCDCDC"))
        painter.end()
        self._checker = QBrush(tile)

    def set_image(self, image):
        self._image = QImage(image)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#303034"))
        if not self._image.isNull():
            scale = min(self.width() / self._image.width(), self.height() / self._image.height())
            width, height = self._image.width() * scale, self._image.height() * scale
            target = QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height)
            painter.fillRect(target, self._checker)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawImage(target, self._image)
        painter.end()
