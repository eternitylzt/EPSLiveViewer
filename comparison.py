"""Optional side-by-side vector views with a pinned reference and linked navigation."""

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QSplitter, QVBoxLayout, QWidget,
)

from background_tasks import TaskRunner
from config import SUPPORTED_SOURCE_SUFFIXES, filename_sort_key
from eps_renderer import EpsRenderer
from i18n import tr
from image_transforms import TransformSnapshot
from vector_preview import VectorGraphicsView


class ComparisonPane(QWidget):
    error = pyqtSignal(object)
    open_requested = pyqtSignal(object)

    def __init__(self, renderer, heading, parent=None):
        super().__init__(parent)
        self._renderer = renderer
        self._runner = TaskRunner(self)
        self.source = None
        self.transforms = TransformSnapshot()
        self._stamp = None
        self._ready_signature = None
        self._generation = 0
        self._wanted_page = 0
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        controls.addWidget(QLabel(heading))
        open_button = QPushButton(tr("选图…"))
        open_button.clicked.connect(lambda: self.open_requested.emit(None))
        controls.addWidget(open_button)
        controls.addStretch(1)
        controls.addWidget(QLabel(tr("页码：")))
        self._page = QSpinBox()
        self._page.setRange(1, 1)
        self._page.valueChanged.connect(self._change_page)
        controls.addWidget(self._page)
        root.addLayout(controls)
        self._title = QLabel(tr("未打开文件"))
        self._title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._title.setWordWrap(True)
        root.addWidget(self._title)
        self.view = VectorGraphicsView(self)
        self.view.setMinimumSize(280, 240)
        self.view.document_released.connect(renderer.cache.release)
        self.view.render_error.connect(self._failed)
        self.view.source_dropped.connect(self.open_requested.emit)
        self.view.page_navigation_requested.connect(lambda offset: self._page.setValue(self._page.value() + offset))
        self.view.file_navigation_requested.connect(self._navigate)
        root.addWidget(self.view, 1)
        zoom = QHBoxLayout()
        for text, action in (("缩小", lambda: self.view.zoom_by(1 / 1.2)),
                             ("适应窗口", self.view.fit_to_window),
                             ("放大", lambda: self.view.zoom_by(1.2))):
            button = QPushButton(tr(text))
            button.clicked.connect(action)
            zoom.addWidget(button)
        self._zoom_label = QLabel()
        self.view.zoom_changed.connect(lambda percent: self._zoom_label.setText(f"{percent:.0f}%"))
        zoom.addWidget(self._zoom_label)
        root.addLayout(zoom)

    def set_source(self, source, transforms=TransformSnapshot(), page=0):
        source = Path(source).resolve()
        try:
            stat = source.stat()
        except OSError as error:
            self._failed(error)
            return
        stamp = stat.st_mtime_ns, stat.st_size
        self.transforms = transforms
        self._wanted_page = page
        if self._ready_signature == (source, stamp) and self.view.has_document():
            self._page.setValue(max(1, min(page + 1, self._page.maximum())))
            self._apply_transforms()
            return
        if self.source == source and self._stamp == stamp and self._runner.pending_count:
            return
        self._generation += 1
        generation = self._generation
        self._runner.cancel_all()
        self.source, self._stamp = source, stamp
        self._page.setEnabled(False)
        self._title.setText(tr("正在打开：{name}", name=source.name))
        self._title.setToolTip(str(source))
        renderer = self._renderer
        self._runner.submit(
            lambda cancel: renderer.convert_to_pdf(source, cancel),
            lambda result, error, cancelled: self._loaded(generation, result, error, cancelled),
        )

    def _loaded(self, generation, result, error, cancelled):
        if cancelled or generation != self._generation:
            if result is not None:
                self._renderer.cache.release(result.pdf_path)
            return
        if error is not None:
            self._stamp = None
            self._failed(error)
            return
        try:
            self.view.load_pdf(result.pdf_path, generation, True, self._wanted_page)
            self._ready_signature = (self.source, self._stamp)
            self._page.blockSignals(True)
            self._page.setRange(1, self.view.page_count())
            self._page.setValue(self.view.current_page_index() + 1)
            self._page.blockSignals(False)
            self._page.setEnabled(True)
            self._apply_transforms()
            self._title.setText(self.source.name)
        except Exception as caught:
            self._renderer.cache.release(result.pdf_path)
            self._stamp = None
            self._failed(caught)

    def _change_page(self, number):
        self._wanted_page = number - 1
        self.view.set_page(number - 1)
        self._apply_transforms()

    def _apply_transforms(self):
        self.view.set_visual_transforms(self.transforms.rotation_for(self._page.value()),
                                        self.transforms.inverted, self.transforms.replacements)

    def _failed(self, error):
        self._title.setText(tr("预览失败：{error}", error=error))
        self.error.emit(error)

    def _navigate(self, offset):
        if self.source is None:
            return
        try:
            files = sorted((p for p in self.source.parent.iterdir()
                            if p.is_file() and p.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES),
                           key=filename_sort_key)
            index = files.index(self.source) + offset
            if 0 <= index < len(files):
                self.open_requested.emit(str(files[index]))
        except (OSError, ValueError) as error:
            self._failed(error)

    def shutdown(self):
        return self._runner.shutdown() and self.view.close()


class ComparisonDialog(QDialog):
    error = pyqtSignal(object)

    def __init__(self, source, transforms, page, ghostscript_path, snapshots,
                 background_mode, background_color, wheel_action, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle(tr("并排比较"))
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, True)
        self.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint, True)
        self.resize(1200, 760)
        self._renderer = EpsRenderer(ghostscript_path)
        self._snapshots = dict(snapshots)
        self._syncing = False
        root = QVBoxLayout(self)
        controls = QHBoxLayout()
        self._linked = QCheckBox(tr("联动缩放和平移"))
        self._linked.setChecked(True)
        self._locked = QCheckBox(tr("锁定左侧参考图"))
        self._locked.setChecked(True)
        self._locked.setToolTip(tr("锁定后，左图不随主窗口刷新或调色。重新选图可更换参考图。"))
        self._follow = QCheckBox(tr("右图跟随主窗口"))
        self._follow.setChecked(True)
        for checkbox in (self._linked, self._locked, self._follow):
            controls.addWidget(checkbox)
        controls.addStretch(1)
        root.addLayout(controls)
        self._candidates = QComboBox()
        self._candidates.addItem(tr("右侧对比：选择已打开的图片或浏览文件"), None)
        self._candidates.activated.connect(self._candidate_chosen)
        root.addWidget(self._candidates)
        hint = QLabel(tr("选择右侧图片，或在主窗口切换文件；左侧保留参考图。"))
        hint.setWordWrap(True)
        root.addWidget(hint)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.left = ComparisonPane(self._renderer, tr("参考图"))
        self.right = ComparisonPane(self._renderer, tr("对比图"))
        for pane in (self.left, self.right):
            pane.view.set_page_background(background_mode, background_color)
            pane.view.set_wheel_action(wheel_action)
            pane.error.connect(self.error.emit)
            pane.open_requested.connect(lambda path, target=pane: self._choose(target, path))
            splitter.addWidget(pane)
        splitter.setSizes([600, 600])
        root.addWidget(splitter, 1)
        self.left.view.viewport_changed.connect(lambda: self._sync(self.left, self.right))
        self.right.view.viewport_changed.connect(lambda: self._sync(self.right, self.left))
        self._linked.toggled.connect(lambda checked: self._sync(self.left, self.right) if checked else None)
        self.left.set_source(source, transforms, page)
        self.right.set_source(source, transforms, page)

    def set_candidates(self, documents, page_count):
        self._candidates.clear()
        self._candidates.addItem(tr("右侧对比：选择已打开的图片或浏览文件"), None)
        if page_count > 1:
            source, transforms = self.left.source, self.left.transforms
            for page in range(page_count):
                self._candidates.addItem(tr("{name}（第 {page} 页）", name=source.name, page=page + 1),
                                         (source, transforms, page))
            other = (self.left._wanted_page + 1) % page_count
            self._follow.setChecked(False)
            self.right.set_source(source, transforms, other)
            self._candidates.setCurrentIndex(other + 1)
        for name, source, transforms, page in documents:
            self._candidates.addItem(name, (source, transforms, page))
        self._candidates.addItem(tr("浏览…"), "browse")

    def _candidate_chosen(self, index):
        selected = self._candidates.itemData(index)
        if selected is None:
            return
        self._follow.setChecked(False)
        if selected == "browse":
            self._choose(self.right)
        else:
            self.right.set_source(*selected)

    def _choose(self, pane, path=None):
        if path is None:
            path, _filter = QFileDialog.getOpenFileName(
                self, tr("打开图片文件"), str(pane.source.parent if pane.source else Path.home()),
                tr("支持的图片 (*.eps *.EPS *.ps *.PS *.pdf *.PDF *.png *.PNG *.jpg *.JPG *.jpeg *.JPEG);;所有文件 (*.*)"))
        if path:
            if pane is self.right:
                self._follow.setChecked(False)
            source = Path(path).resolve()
            pane.set_source(source, self._snapshots.get(source, TransformSnapshot()))

    def follow_current(self, source, transforms, page):
        if source is None:
            return
        source = Path(source).resolve()
        self._snapshots[source] = transforms
        if self._follow.isChecked():
            self.right.set_source(source, transforms, page)
        if not self._locked.isChecked() and self.left.source == source:
            self.left.set_source(source, transforms, page)

    def _sync(self, source, target):
        if self._syncing or not self._linked.isChecked():
            return
        if not source.view.has_document() or not target.view.has_document():
            return
        self._syncing = True
        try:
            target.view.set_viewport_state(source.view.viewport_state())
        finally:
            self._syncing = False

    def closeEvent(self, event):
        if not (self.left.shutdown() and self.right.shutdown()):
            event.ignore()
            return
        self._renderer.cache.cleanup()
        super().closeEvent(event)

    def done(self, result):
        # Escape/reject can bypass closeEvent on QDialog.
        if not (self.left.shutdown() and self.right.shutdown()):
            QTimer.singleShot(100, lambda: self.done(result))
            return
        self._renderer.cache.cleanup()
        super().done(result)
