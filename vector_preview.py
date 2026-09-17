"""Zoom-independent EPS preview backed by a temporary vector PDF.

Ghostscript converts EPS to PDF only when the source changes.  QtPdf then
renders the visible region as a complete frame from that vector document.  The screen is of
course raster, but every zoom level is freshly sampled from vector data instead
of magnifying one fixed-DPI PNG.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import (
    QMarginsF,
    QObject,
    QPointF,
    QRect,
    QRectF,
    QSize,
    QSizeF,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QDragEnterEvent,
    QDragMoveEvent,
    QDropEvent,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
    QWheelEvent,
)
from PyQt6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions, QPdfPageRenderer
from PyQt6.QtWidgets import QApplication, QGraphicsItem, QGraphicsScene, QGraphicsView, QStyleOptionGraphicsItem, QWidget
from PyQt6 import sip

from config import SUPPORTED_SOURCE_SUFFIXES
from background_tasks import TaskRunner
from i18n import tr
from image_transforms import ColorReplacement, adjusted_color, apply_color_adjustments


class VectorPreviewError(RuntimeError):
    """Raised when QtPdf cannot load a generated preview document."""


@dataclass(frozen=True)
class _RenderRequest:
    kind: str
    generation: int
    page_index: int
    full_size: QSize
    clip: QRect


@dataclass
class _DocumentContext:
    generation: int
    path: Path
    document: QPdfDocument
    renderer: QPdfPageRenderer
    pending: dict[int, _RenderRequest]
    active: bool = True


class _PdfPageItem(QGraphicsItem):
    """A small overview and one complete, visible-region detail image."""
    def __init__(self, page_size):
        super().__init__()
        self._page_rect = QRectF(0, 0, page_size.width(), page_size.height())
        self._overview = QPixmap()
        self._frame = QPixmap()
        self._frame_request = None
        self._frame_rect = QRectF()
        self._cache_bytes = 0

    def boundingRect(self):
        return self._page_rect

    def _account_memory(self):
        self._cache_bytes = sum(p.width() * p.height() * 4 for p in (self._overview, self._frame))

    def set_overview(self, pixmap):
        self._overview = pixmap
        self._account_memory()
        self.update()

    def set_frame(self, pixmap, request):
        self._frame = pixmap
        self._frame_request = request
        clip, size = request.clip, request.full_size
        self._frame_rect = QRectF(clip.x() * self._page_rect.width() / size.width(),
                                  clip.y() * self._page_rect.height() / size.height(),
                                  clip.width() * self._page_rect.width() / size.width(),
                                  clip.height() * self._page_rect.height() / size.height())
        self._account_memory()
        self.update()

    def covers(self, full_size, visible_pixels):
        request = self._frame_request
        return (request is not None and request.full_size == full_size
                and request.clip.contains(visible_pixels))

    def release_detail(self):
        self._frame = QPixmap()
        self._frame_request = None
        self._frame_rect = QRectF()
        self._account_memory()
        self.update()

    def clear_cache(self):
        self._overview = QPixmap()
        self.release_detail()

    def paint(self, painter, option, widget=None):
        del option, widget
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        if not self._overview.isNull():
            painter.save()
            if not self._frame.isNull():
                # Avoid double-compositing transparent content. Frame edges
                # normally lie outside the viewport's prefetched margin.
                outside = QPainterPath()
                outside.addRect(self._page_rect)
                inside = QPainterPath()
                inside.addRect(self._frame_rect)
                painter.setClipPath(outside.subtracted(inside), Qt.ClipOperation.IntersectClip)
            painter.drawPixmap(self._page_rect, self._overview, QRectF(self._overview.rect()))
            painter.restore()
        if not self._frame.isNull():
            painter.drawPixmap(self._frame_rect, self._frame, QRectF(self._frame.rect()))


class VectorGraphicsView(QGraphicsView):
    """Interactive vector-source preview with bounded visible-region frames."""

    zoom_changed = pyqtSignal(float)
    image_loaded = pyqtSignal(float, float)
    page_changed = pyqtSignal(int, int)
    render_error = pyqtSignal(str)
    document_released = pyqtSignal(object)
    source_dropped = pyqtSignal(str)
    file_navigation_requested = pyqtSignal(int)
    page_navigation_requested = pyqtSignal(int)
    viewport_changed = pyqtSignal()
    edit_text_requested = pyqtSignal(object)

    MAX_IN_FLIGHT = 1
    MAX_DETAIL_PIXELS = 6_000_000
    OVERVIEW_MAX_EDGE = 960
    DETAIL_DEBOUNCE_MS = 35
    MIN_ZOOM = 0.01
    MAX_ZOOM = 512.0

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._page_item: _PdfPageItem | None = None
        self._active_context: _DocumentContext | None = None
        self._page_index = 0
        self._page_count = 0
        self._text_mode = False
        self.text_edit_enabled = False
        self._text_regions_key = None
        self._text_regions = []
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._selection_start = None
        self._selection = None
        self._contexts: dict[int, _DocumentContext] = {}
        self._queued: deque[_RenderRequest] = deque()
        self._in_flight = 0
        self._wanted_detail = None
        self._fit_mode = True
        self._background_mode = "white"
        self._background_color = QColor("#FFFFFF")
        self._wheel_action = "zoom"
        self._rotation = 0
        self._invert_colors = False
        self._color_replacements: tuple[ColorReplacement, ...] = ()
        self._navigation_wheel_remainder = 0
        self._closed = False
        self._color_runner = TaskRunner(self)
        self._color_jobs = {}
        self._color_revision = 0
        self._sync_suppressed = False

        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )

        self._detail_timer = QTimer(self)
        self._detail_timer.setSingleShot(True)
        self._detail_timer.timeout.connect(self._refresh_visible_frame)
        self.horizontalScrollBar().valueChanged.connect(self._schedule_detail)
        self.verticalScrollBar().valueChanged.connect(self._schedule_detail)
        self.horizontalScrollBar().valueChanged.connect(self._notify_viewport)
        self.verticalScrollBar().valueChanged.connect(self._notify_viewport)

        checker = QPixmap(16, 16)
        checker.fill(QColor("#F8F8F8"))
        checker_painter = QPainter(checker)
        checker_painter.fillRect(0, 0, 8, 8, QColor("#D8D8D8"))
        checker_painter.fillRect(8, 8, 8, 8, QColor("#D8D8D8"))
        checker_painter.end()
        self._checker_brush = QBrush(checker)

    @staticmethod
    def _first_supported_drop_path(event: QDragEnterEvent | QDropEvent) -> str | None:
        """Return the first local EPS/PS path contained in a drag payload."""
        if not event.mimeData().hasUrls():
            return None
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if Path(path).suffix.lower() in SUPPORTED_SOURCE_SUFFIXES:
                return path
        return None

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if self._first_supported_drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # type: ignore[override]
        if self._first_supported_drop_path(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        path = self._first_supported_drop_path(event)
        if path is None:
            event.ignore()
            return
        self.source_dropped.emit(path)
        event.acceptProposedAction()

    def has_document(self) -> bool:
        return self._active_context is not None and self._page_item is not None

    def page_size_points(self) -> tuple[float, float] | None:
        if self._page_item is None:
            return None
        rect = self._page_item.sceneBoundingRect()
        return rect.width(), rect.height()

    def current_page_index(self) -> int:
        return self._page_index

    def page_count(self) -> int:
        return self._page_count

    def set_wheel_action(self, action: str) -> None:
        self._wheel_action = action if action in {"zoom", "files", "pages"} else "zoom"
        self._navigation_wheel_remainder = 0

    def set_page_background(self, mode: str, color: str = "#FFFFFF") -> None:
        if mode not in {"transparent", "white", "custom"}:
            mode = "transparent"
        parsed = QColor(color)
        if not parsed.isValid():
            parsed = QColor("#FFFFFF")
        self._background_mode = mode
        self._background_color = parsed
        self.viewport().update()

    def set_visual_transforms(
        self,
        rotation: int = 0,
        inverted: bool = False,
        replacements: tuple[ColorReplacement, ...] = (),
    ) -> None:
        """Apply session transforms and refresh the viewport from the vector document."""
        rotation = int(rotation) % 360
        if rotation not in {0, 90, 180, 270}:
            rotation = 0
        rotation_changed = rotation != self._rotation
        colors_changed = (
            bool(inverted) != self._invert_colors
            or tuple(replacements) != self._color_replacements
        )
        self._rotation = rotation
        self._invert_colors = bool(inverted)
        self._color_replacements = tuple(replacements)

        if self._page_item is not None and rotation_changed:
            self._apply_item_rotation()
            if self._fit_mode:
                self.fit_to_window()
            else:
                self.centerOn(self._page_item)
                self._emit_zoom()
            size = self.page_size_points()
            if size is not None:
                self.image_loaded.emit(*size)
        if self._page_item is not None and colors_changed:
            self._invalidate_colors()
            self._page_item.clear_cache()
            self._queued.clear()
            context = self._active_context
            if context is not None and context.active:
                page = self._page_item.boundingRect()
                self._request_overview(context, page.width(), page.height())
            self._schedule_detail(immediate=True)

    def _apply_item_rotation(self) -> None:
        item = self._page_item
        if item is None:
            return
        item.setTransformOriginPoint(item.boundingRect().center())
        item.setRotation(self._rotation)
        self._scene.setSceneRect(item.sceneBoundingRect())
        self.viewport().update()

    def _invalidate_colors(self):
        self._color_revision += 1
        self._color_runner.cancel_all()

    def viewport_state(self):
        rect = self._scene.sceneRect()
        if rect.isEmpty():
            return None
        center = self.mapToScene(self.viewport().rect().center())
        return (abs(self.transform().m11()),
                (center.x() - rect.left()) / rect.width(),
                (center.y() - rect.top()) / rect.height())

    def set_viewport_state(self, state):
        if state is None or not self.has_document():
            return
        scale, x, y = state
        self._sync_suppressed = True
        try:
            self._fit_mode = False
            scale = max(self.MIN_ZOOM, min(self.MAX_ZOOM, scale))
            self.setTransform(QTransform().scale(scale, scale))
            rect = self._scene.sceneRect()
            self.centerOn(rect.left() + x * rect.width(), rect.top() + y * rect.height())
            self._emit_zoom()
            self._schedule_detail()
        finally:
            self._sync_suppressed = False

    def _notify_viewport(self, *_args):
        if not self._sync_suppressed:
            self.viewport_changed.emit()

    def load_pdf(
        self,
        filename: str | Path,
        generation: int,
        reset_view: bool = False,
        page_index: int = 0,
    ) -> None:
        """Load and validate a unique PDF cache, then start viewport rendering.

        A newly opened file fits the window.  Live refreshes retain zoom and a
        normalized page center; fit mode remains fit mode even if page geometry
        changes between source generations.
        """
        self._selection = None
        if self._closed:
            raise VectorPreviewError(tr("预览窗口已关闭。"))
        path = Path(filename).resolve()
        if not path.is_file():
            raise VectorPreviewError(tr("找不到预览 PDF：{path}", path=path))

        document = QPdfDocument(self)
        error = document.load(str(path))
        if error != QPdfDocument.Error.None_ or document.status() != QPdfDocument.Status.Ready:
            document.close()
            sip.delete(document)
            raise VectorPreviewError(tr("QtPdf 无法加载预览文档。"))
        if document.pageCount() < 1:
            document.close()
            sip.delete(document)
            raise VectorPreviewError(tr("预览 PDF 不包含可显示的页面。"))
        page_count = document.pageCount()
        page_index = max(0, min(int(page_index), page_count - 1))
        point_size = document.pagePointSize(page_index)
        if not point_size.isValid() or point_size.width() <= 0 or point_size.height() <= 0:
            document.close()
            sip.delete(document)
            raise VectorPreviewError(tr("预览 PDF 的页面尺寸无效。"))

        renderer = QPdfPageRenderer(self)
        renderer.setRenderMode(QPdfPageRenderer.RenderMode.MultiThreaded)
        renderer.setDocument(document)
        context = _DocumentContext(generation, path, document, renderer, {})
        renderer.pageRendered.connect(
            lambda page, size, image, options, request_id, gen=generation: self._on_page_rendered(
                gen, page, size, image, options, request_id
            )
        )

        old_rect = self._scene.sceneRect()
        old_center = self.mapToScene(self.viewport().rect().center())
        normalized_center = QPointF(0.5, 0.5)
        if not old_rect.isEmpty():
            normalized_center = QPointF(
                (old_center.x() - old_rect.left()) / max(old_rect.width(), 1e-9),
                (old_center.y() - old_rect.top()) / max(old_rect.height(), 1e-9),
            )

        self._invalidate_colors()
        old_context = self._active_context
        if old_context is not None:
            old_context.active = False
            # The old page item is removed immediately, so its queued detail
            # work has no remaining visual value.  Cancel it instead of letting
            # rapid live-refresh generations monopolize the active render queue.
            self._dispose_context(old_context, cancel=True)
            self._contexts.pop(old_context.generation, None)
        if self._page_item is not None:
            self._scene.removeItem(self._page_item)
        self._queued.clear()

        self._page_item = _PdfPageItem(point_size)
        self._scene.addItem(self._page_item)
        self._apply_item_rotation()
        self._active_context = context
        self._page_index = page_index
        self._page_count = page_count
        self._contexts[generation] = context

        if reset_view or old_context is None:
            self.fit_to_window()
        elif self._fit_mode:
            self.fit_to_window()
        else:
            new_rect = self._scene.sceneRect()
            self.centerOn(
                new_rect.left() + normalized_center.x() * new_rect.width(),
                new_rect.top() + normalized_center.y() * new_rect.height(),
            )
            self._emit_zoom()

        self.image_loaded.emit(point_size.width(), point_size.height())
        self.page_changed.emit(page_index, page_count)
        self._request_overview(context, point_size.width(), point_size.height())
        self._schedule_detail(immediate=True)

    def set_page(self, page_index: int) -> bool:
        """Display one page from the active vector PDF without reconversion."""
        self._selection = None
        context = self._active_context
        if (
            context is None
            or not context.active
            or not 0 <= page_index < self._page_count
            or page_index == self._page_index
        ):
            return False

        old_rect = self._scene.sceneRect()
        old_center = self.mapToScene(self.viewport().rect().center())
        normalized_center = QPointF(0.5, 0.5)
        if not old_rect.isEmpty():
            normalized_center = QPointF(
                (old_center.x() - old_rect.left()) / max(old_rect.width(), 1e-9),
                (old_center.y() - old_rect.top()) / max(old_rect.height(), 1e-9),
            )

        point_size = context.document.pagePointSize(page_index)
        if not point_size.isValid() or point_size.width() <= 0 or point_size.height() <= 0:
            self.render_error.emit(tr("预览 PDF 的页面尺寸无效。"))
            return False

        self._invalidate_colors()
        self._detail_timer.stop()
        self._queued.clear()
        if self._page_item is not None:
            self._scene.removeItem(self._page_item)
        self._page_item = _PdfPageItem(point_size)
        self._scene.addItem(self._page_item)
        self._apply_item_rotation()
        self._page_index = page_index

        if self._fit_mode:
            self.fit_to_window()
        else:
            new_rect = self._scene.sceneRect()
            self.centerOn(
                new_rect.left() + normalized_center.x() * new_rect.width(),
                new_rect.top() + normalized_center.y() * new_rect.height(),
            )
            self._emit_zoom()

        self.image_loaded.emit(point_size.width(), point_size.height())
        self.page_changed.emit(page_index, self._page_count)
        self._request_overview(context, point_size.width(), point_size.height())
        self._schedule_detail(immediate=True)
        return True

    def fit_to_window(self) -> None:
        if not self.has_document() or self._scene.sceneRect().isEmpty():
            return
        self._fit_mode = True
        margin = 12.0
        target = self._scene.sceneRect().marginsAdded(QMarginsF(margin, margin, margin, margin))
        self.fitInView(target, Qt.AspectRatioMode.KeepAspectRatio)
        self._emit_zoom()
        self._schedule_detail()

    def reset_to_actual_size(self) -> None:
        if not self.has_document():
            return
        self._fit_mode = False
        self.resetTransform()
        self.centerOn(self._page_item)
        self._emit_zoom()
        self._schedule_detail()

    def zoom_by(self, factor: float) -> None:
        if not self.has_document() or factor <= 0:
            return
        current = abs(self.transform().m11())
        target = current * factor
        if target < self.MIN_ZOOM:
            factor = self.MIN_ZOOM / max(current, 1e-12)
        elif target > self.MAX_ZOOM:
            factor = self.MAX_ZOOM / max(current, 1e-12)
        if abs(factor - 1.0) < 1e-9:
            return
        self._fit_mode = False
        self.scale(factor, factor)
        self._emit_zoom()
        self._schedule_detail()

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if not self.has_document() or delta == 0:
            event.ignore()
            return
        control = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if self._wheel_action == "zoom" or control:
            steps = abs(delta) / 120.0
            base = 1.35 if control else 1.15
            factor = base**steps if delta > 0 else (1.0 / base) ** steps
            self.zoom_by(factor)
            self._navigation_wheel_remainder = 0
        else:
            self._navigation_wheel_remainder += delta
            if abs(self._navigation_wheel_remainder) >= 120:
                offset = -1 if self._navigation_wheel_remainder > 0 else 1
                self._navigation_wheel_remainder = 0
                if self._wheel_action == "files":
                    self.file_navigation_requested.emit(offset)
                else:
                    self.page_navigation_requested.emit(offset)
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            if self.text_edit_enabled and self._over_text(event.position()):
                point = self.mapToScene(event.position().toPoint()) - self._page_item.sceneBoundingRect().topLeft()
                self._selection_start = self._selection = None
                self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                QTimer.singleShot(0, lambda: self.edit_text_requested.emit(point))
                event.accept()
                return
            self.reset_to_actual_size()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def set_text_selection_mode(self, enabled):
        self._text_mode = bool(enabled)
        self._selection = None
        self._selection_start = None
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        self.viewport().update()

    def _page_point(self, position):
        return self._page_item.mapFromScene(self.mapToScene(position.toPoint()))

    def _over_text(self, position):
        if not self._text_mode or not self.has_document():
            return False
        point = self._page_point(position)
        if not self._page_item.boundingRect().contains(point):
            return False
        key = (self._active_context.generation, self._page_index)
        if key != self._text_regions_key:
            self._text_regions_key = key
            self._text_regions = [polygon.boundingRect() for polygon in
                                  self._active_context.document.getAllText(self._page_index).bounds()]
        candidates = [rect for rect in self._text_regions if rect.adjusted(-1, -1, 1, 1).contains(point)]
        if not candidates:
            return False
        # At a glyph's upper edge both nearest-character endpoints can be the
        # same index. Accept the visible text region's edge as a drag origin.
        if any(abs(point.y() - rect.top()) < 2 or abs(point.x() - rect.left()) < 2 for rect in candidates):
            return True
        selection = self._active_context.document.getSelection(
            self._page_index, point - QPointF(2, 1), point + QPointF(2, 1))
        return bool(selection.text().strip()) and any(
            polygon.boundingRect().adjusted(-1, -1, 1, 1).contains(point)
            for polygon in selection.bounds())

    def mousePressEvent(self, event):
        if self._over_text(event.position()) and event.button() == Qt.MouseButton.LeftButton:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
            self._selection_start = self._page_point(event.position())
            self._selection = None
            event.accept()
            return
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self._selection = None
        self.viewport().update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._text_mode and self.has_document() and self._selection_start is not None:
            self._selection = self._active_context.document.getSelection(
                self._page_index, self._selection_start, self._page_point(event.position()))
            self.viewport().update()
            event.accept()
            return
        super().mouseMoveEvent(event)
        if event.buttons() == Qt.MouseButton.NoButton:
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor if self._over_text(event.position())
                                      else Qt.CursorShape.OpenHandCursor)

    def mouseReleaseEvent(self, event):
        if self._text_mode and self._selection_start is not None:
            self.mouseMoveEvent(event)
            self._selection_start = None
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def copy_selected_text(self):
        if self._selection is not None and self._selection.text():
            QApplication.clipboard().setText(self._selection.text())

    def hideEvent(self, event):
        # Some native Qt backends can deliver Hide before Python finishes
        # initializing this subclass (notably while reparenting editor views).
        if not hasattr(self, "_detail_timer"):
            super().hideEvent(event)
            return
        self._detail_timer.stop()
        self._queued.clear()
        self._wanted_detail = None
        self._invalidate_colors()
        if self._page_item is not None:
            self._page_item.release_detail()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not hasattr(self, "_detail_timer"):
            return
        if self.has_document():
            if self._page_item._overview.isNull():
                page = self._page_item.boundingRect()
                self._request_overview(self._active_context, page.width(), page.height())
            self._schedule_detail(immediate=True)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if self._fit_mode and self.has_document():
            QTimer.singleShot(0, self.fit_to_window)
        else:
            self._schedule_detail()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # type: ignore[override]
        painter.fillRect(rect, QColor(46, 48, 52))
        if self._page_item is None:
            return
        page = self._page_item.sceneBoundingRect()
        visible_page = rect.intersected(page)
        if visible_page.isEmpty():
            return
        if self._background_mode == "transparent":
            # Keep checker squares a constant screen size at every zoom level.
            # Without the inverse world transform an 8 px square would become
            # enormous when inspecting vector details at 1000%.
            checker = QBrush(self._checker_brush)
            inverse, invertible = painter.worldTransform().inverted()
            if invertible:
                checker.setTransform(inverse)
            painter.fillRect(visible_page, checker)
        elif self._background_mode == "white":
            painter.fillRect(
                visible_page,
                adjusted_color(
                    QColor("#FFFFFF"),
                    self._invert_colors,
                    self._color_replacements,
                ),
            )
        else:
            painter.fillRect(
                visible_page,
                adjusted_color(
                    self._background_color,
                    self._invert_colors,
                    self._color_replacements,
                ),
            )

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:  # type: ignore[override]
        del rect
        if self._page_item is None:
            return
        pen = QPen(QColor(25, 25, 25, 150))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Draw the paper border outside the content so it cannot cover an axis
        # that lies exactly on a tightly cropped EPS page edge.
        margin = 1.0 / max(abs(self.transform().m11()), 0.01)
        painter.drawRect(self._page_item.sceneBoundingRect().adjusted(-margin, -margin, margin, margin))
        if self._selection is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(40, 130, 240, 85))
            for polygon in self._selection.bounds():
                painter.drawPolygon(self._page_item.mapToScene(polygon))

    def clear_document(self) -> None:
        self._selection = None
        self._selection_start = None
        self._text_regions = []
        self._text_regions_key = None
        self._wanted_detail = None
        self._invalidate_colors()
        self._detail_timer.stop()
        self._queued.clear()
        if self._page_item is not None:
            self._scene.removeItem(self._page_item)
            self._page_item = None
        self._scene.setSceneRect(QRectF())
        active = self._active_context
        self._active_context = None
        self._page_index = 0
        self._page_count = 0
        if active is not None:
            active.active = False
        for context in list(self._contexts.values()):
            self._dispose_context(context, cancel=True)
        self._contexts.clear()
        self._in_flight = 0
        self.page_changed.emit(-1, 0)
        self.viewport().update()

    def close(self) -> bool:  # type: ignore[override]
        if not self._color_runner.shutdown():
            return False
        self._closed = True
        self.clear_document()
        return super().close()

    def _emit_zoom(self) -> None:
        self.zoom_changed.emit(abs(self.transform().m11()) * 100.0)
        self._notify_viewport()

    def _schedule_detail(self, _value: int | None = None, immediate: bool = False) -> None:
        if not self.has_document() or self._closed or not self.isVisible():
            return
        self._detail_timer.start(0 if immediate else self.DETAIL_DEBOUNCE_MS)

    def _visible_page_rect(self) -> QRectF:
        if self._page_item is None:
            return QRectF()
        visible_scene = self.mapToScene(self.viewport().rect())
        visible_item = self._page_item.mapFromScene(visible_scene).boundingRect()
        return visible_item.intersected(self._page_item.boundingRect())

    def _refresh_visible_frame(self) -> None:
        """Coalesce pan/zoom requests into one bounded, atomic viewport frame."""
        context, item = self._active_context, self._page_item
        if context is None or item is None or not context.active or not self.isVisible():
            return
        page, visible = item.boundingRect(), self._visible_page_rect()
        if visible.isEmpty():
            return
        effective = abs(self.transform().m11()) * max(1.0, self.viewport().devicePixelRatioF())
        # A short pan margin avoids resampling on every small drag. Limit the
        # visible-region allocation, even at extreme zoom or on large displays.
        margin = 48 / max(effective, .01)
        wanted = visible.adjusted(-margin, -margin, margin, margin).intersected(page)
        scale = min(effective * 2,
                    math.sqrt(self.MAX_DETAIL_PIXELS / max(1, wanted.width() * wanted.height())))
        full_size = QSize(max(1, round(page.width() * scale)), max(1, round(page.height() * scale)))
        sx, sy = full_size.width() / page.width(), full_size.height() / page.height()

        def pixels(rect):
            left, top = math.floor(rect.left() * sx), math.floor(rect.top() * sy)
            right, bottom = math.ceil(rect.right() * sx), math.ceil(rect.bottom() * sy)
            return QRect(left, top, max(1, right - left), max(1, bottom - top)).intersected(
                QRect(0, 0, full_size.width(), full_size.height()))

        if item.covers(full_size, pixels(visible)):
            self._wanted_detail = None
            self._queued.clear()
            return
        request = _RenderRequest("detail", context.generation, self._page_index,
                                 full_size, pixels(wanted))
        self._wanted_detail = request
        self._queued.clear()
        # Keep the last complete image while working; discard stale results
        # and submit only the latest requested viewport next.
        pending = list(context.pending.values()) + [
            req for revision, req in self._color_jobs.values() if revision == self._color_revision]
        if request not in pending:
            self._queued.append(request)
        self._pump_queue()

    def _request_overview(self, context: _DocumentContext, width: float, height: float) -> None:
        if self._fit_mode:
            return  # The first fitted frame is already the complete page.
        scale = min(2.0, self.OVERVIEW_MAX_EDGE / max(width, height, 1.0))
        size = QSize(max(1, int(math.ceil(width * scale))), max(1, int(math.ceil(height * scale))))
        request = _RenderRequest(
            "overview", context.generation, self._page_index, size, QRect()
        )
        options = QPdfDocumentRenderOptions()
        request_id = context.renderer.requestPage(self._page_index, size, options)
        # Qt reuses the ID of an identical request already in its queue.
        # Rapid color changes must not count that same completion twice.
        if request_id not in context.pending:
            self._in_flight += 1
        context.pending[request_id] = request

    def _pump_queue(self) -> None:
        context = self._active_context
        while (
            context is not None
            and context.active
            and self._queued
            and self._in_flight + len(self._color_jobs) < self.MAX_IN_FLIGHT
        ):
            request = self._queued.popleft()
            if request.generation != context.generation:
                continue
            options = QPdfDocumentRenderOptions()
            output_size = request.clip.size()
            if request.clip != QRect(0, 0, request.full_size.width(), request.full_size.height()):
                options.setScaledSize(request.full_size)
                # QtPdf 6.8/6.9 uses inclusive QRect.right()/bottom() in its
                # matrix. Add one to the extent to avoid shrinking each region.
                options.setScaledClipRect(QRect(request.clip.x(), request.clip.y(),
                                                request.clip.width() + 1, request.clip.height() + 1))
            request_id = context.renderer.requestPage(
                request.page_index, output_size, options
            )
            if request_id not in context.pending:
                self._in_flight += 1
            context.pending[request_id] = request

    def _on_page_rendered(
        self,
        generation: int,
        _page: int,
        _size: QSize,
        image,
        _options: QPdfDocumentRenderOptions,
        request_id: int,
    ) -> None:
        context = self._contexts.get(generation)
        if context is None:
            return
        request = context.pending.pop(request_id, None)
        if request is None:
            return
        self._in_flight = max(0, self._in_flight - 1)

        if (
            context.active
            and context is self._active_context
            and self._page_item is not None
            and request.page_index == self._page_index
            and self.isVisible()
            and (request.kind == "overview" or request == self._wanted_detail)
        ):
            if image.isNull():
                self.render_error.emit(tr("QtPdf 无法渲染预览区域。"))
            else:
                if self._invert_colors or self._color_replacements:
                    inverted, replacements = self._invert_colors, self._color_replacements
                    number = self._color_runner.submit(
                        lambda cancel, raw=image: apply_color_adjustments(
                            raw, inverted, replacements, cancel),
                        lambda result, error, cancelled: self._on_colors_ready(
                            number, result, error, cancelled),
                    )
                    self._color_jobs[number] = (self._color_revision, request)
                else:
                    self._install_image(request, image)

        self._finalize_context_if_idle(context)
        # Completion of an obsolete document also frees a global render slot;
        # always give the active document an opportunity to use it.
        self._pump_queue()
        active = self._active_context
        if active is not None and not self._queued and not active.pending:
            # Scrolling may have changed while the previous frame was running.
            self._schedule_detail()

    def _install_image(self, request, image):
        pixmap = QPixmap.fromImage(image)
        if request.kind == "overview":
            self._page_item.set_overview(pixmap)
        elif request == self._wanted_detail:
            self._page_item.set_frame(pixmap, request)
            if self._page_item._overview.isNull():
                if request.clip == QRect(0, 0, request.full_size.width(), request.full_size.height()):
                    self._page_item.set_overview(pixmap.scaled(
                        self.OVERVIEW_MAX_EDGE, self.OVERVIEW_MAX_EDGE,
                        Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
                elif self._active_context is not None:
                    page = self._page_item.boundingRect()
                    self._request_overview(self._active_context, page.width(), page.height())

    def _on_colors_ready(self, number, image, error, cancelled):
        entry = self._color_jobs.pop(number, None)
        if entry is None or self._closed:
            return
        revision, request = entry
        context = self._active_context
        if (not cancelled and revision == self._color_revision and context is not None
                and request.generation == context.generation
                and request.page_index == self._page_index and self._page_item is not None
                and self.isVisible()
                and (request.kind == "overview" or request == self._wanted_detail)):
            if error is not None:
                self.render_error.emit(str(error))
            elif image is not None:
                self._install_image(request, image)
        self._pump_queue()
        self._schedule_detail()

    def _finalize_context_if_idle(self, context: _DocumentContext | None) -> None:
        if context is None or context.active or context.pending:
            return
        self._dispose_context(context, cancel=False)
        self._contexts.pop(context.generation, None)

    def _dispose_context(self, context: _DocumentContext, cancel: bool) -> None:
        context.active = False
        if cancel:
            cancelled_requests = len(context.pending)
            try:
                context.renderer.setDocument(None)
            except (RuntimeError, TypeError):
                pass
            context.pending.clear()
            self._in_flight = max(0, self._in_flight - cancelled_requests)
        try:
            context.document.close()
        except RuntimeError:
            pass
        # deleteLater() is too late during QMainWindow.closeEvent: on Windows the
        # PDF handle can otherwise outlive the cache cleanup call.  QtPdf's
        # renderer destructor cancels/joins its internal jobs, so explicit SIP
        # deletion makes the generated file removable before we emit release.
        if not sip.isdeleted(context.renderer):
            sip.delete(context.renderer)
        if not sip.isdeleted(context.document):
            sip.delete(context.document)
        self.document_released.emit(context.path)
