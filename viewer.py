"""Main window, background jobs, menus, and live-refresh coordination."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QSettings, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QAction, QDragEnterEvent, QDropEvent, QKeySequence
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
)

from config import (
    APP_NAME,
    AppConfig,
    ConfigManager,
    SUPPORTED_SOURCE_SUFFIXES,
    filename_sort_key,
)
from dialogs import PngExportDialog, SettingsDialog
from eps_renderer import (
    EpsRenderCancelledError,
    EpsRenderError,
    EpsRenderer,
    GhostscriptNotFoundError,
    PdfRenderResult,
)
from file_monitor import EpsFileMonitor
from video_creator import (
    VideoExportCancelled,
    VideoExporter,
    VideoExportRequest,
)
from video_dialog import VideoCreationDialog
from vector_preview import VectorGraphicsView, VectorPreviewError


@dataclass(frozen=True)
class PreviewRequest:
    """Immutable source-generation snapshot for one EPS-to-PDF conversion."""

    source: Path
    generation: int
    automatic: bool
    reset_view: bool


@dataclass(frozen=True)
class PreviewSuccess:
    request: PreviewRequest
    result: PdfRenderResult


@dataclass(frozen=True)
class PreviewFailure:
    request: PreviewRequest
    error: Exception


class PreviewWorker(QObject):
    """Convert one stable EPS file to vector PDF outside the GUI thread."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, renderer: EpsRenderer, request: PreviewRequest) -> None:
        super().__init__()
        self._renderer = renderer
        self._request = request
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @pyqtSlot()
    def run(self) -> None:
        try:
            result = self._renderer.convert_to_pdf(
                self._request.source,
                cancel_event=self._cancel_event,
            )
        except Exception as error:
            self.failed.emit(PreviewFailure(self._request, error))
        else:
            self.succeeded.emit(PreviewSuccess(self._request, result))


@dataclass(frozen=True)
class ExportRequest:
    source: Path
    target: Path
    dpi: int
    background_mode: str
    background_color: str


@dataclass(frozen=True)
class ExportFailure:
    request: ExportRequest
    error: Exception


class ExportWorker(QObject):
    """Render and save one PNG without blocking interaction or live refresh."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, renderer: EpsRenderer, request: ExportRequest) -> None:
        super().__init__()
        self._renderer = renderer
        self._request = request
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @pyqtSlot()
    def run(self) -> None:
        try:
            output = self._renderer.export_png(
                self._request.source,
                self._request.target,
                dpi=self._request.dpi,
                background=self._request.background_mode,
                background_color=self._request.background_color,
                cancel_event=self._cancel_event,
            )
        except Exception as error:
            self.failed.emit(ExportFailure(self._request, error))
        else:
            self.succeeded.emit(output)


class VideoWorker(QObject):
    """Prepare and encode a folder sequence outside the GUI thread."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)
    progress = pyqtSignal(int, int, str)

    def __init__(self, exporter: VideoExporter, request: VideoExportRequest) -> None:
        super().__init__()
        self._exporter = exporter
        self._request = request
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @pyqtSlot()
    def run(self) -> None:
        try:
            output = self._exporter.create(
                self._request,
                self._cancel_event,
                lambda current, total, message: self.progress.emit(
                    current, total, message
                ),
            )
        except Exception as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(output)


class MainWindow(QMainWindow):
    """Application shell coordinating source monitoring and vector preview."""

    MAX_RECENT_FILES = 10

    def __init__(self, config_manager: ConfigManager) -> None:
        super().__init__()
        self._config_manager = config_manager
        self._config: AppConfig = config_manager.load()
        self._renderer = EpsRenderer(self._config.ghostscript_path)
        self._monitor = EpsFileMonitor(self._config.refresh_interval, self)
        self._monitor.file_changed.connect(self._on_source_changed)

        self._current_file: Path | None = None
        self._current_pdf: Path | None = None
        self._generation = 0
        self._automatic_failure_count = 0
        self._closing = False

        self._preview_thread: QThread | None = None
        self._preview_worker: PreviewWorker | None = None
        self._active_preview_request: PreviewRequest | None = None
        self._pending_preview_request: PreviewRequest | None = None
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._video_thread: QThread | None = None
        self._video_worker: VideoWorker | None = None
        self._video_progress: QProgressDialog | None = None
        self._siblings: list[Path] = []
        self._sibling_index = -1
        self._settings = QSettings()

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(640, 480)
        self.resize(1200, 800)
        self.setAcceptDrops(True)

        self._view = VectorGraphicsView(self)
        self._view.set_page_background(
            self._config.background_mode,
            self._config.background_color,
        )
        self._view.zoom_changed.connect(self._update_zoom_status)
        self._view.image_loaded.connect(self._update_page_size_status)
        self._view.render_error.connect(self._on_vector_render_error)
        self._view.document_released.connect(self._renderer.cache.release)
        self._view.source_dropped.connect(self.open_eps)
        self.setCentralWidget(self._view)

        self._create_actions()
        self._create_menus()
        self._create_status_bar()
        self._monitor.set_enabled(self._config.auto_refresh)

    # ----- UI construction -------------------------------------------------

    def _create_actions(self) -> None:
        self._open_action = QAction("打开 EPS/PS(&O)…", self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.triggered.connect(self._choose_file)

        self._reload_action = QAction("重新加载(&R)", self)
        self._reload_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self._reload_action.setEnabled(False)
        self._reload_action.triggered.connect(self._manual_reload)

        self._save_png_action = QAction("另存为 PNG(&S)…", self)
        self._save_png_action.setShortcut(QKeySequence("Ctrl+Shift+S"))
        self._save_png_action.setEnabled(False)
        self._save_png_action.triggered.connect(self._show_export_dialog)

        self._make_video_action = QAction("制作视频/动图(&V)…", self)
        self._make_video_action.setShortcut(QKeySequence("Ctrl+Shift+V"))
        self._make_video_action.triggered.connect(self._show_video_dialog)

        self._settings_action = QAction("设置(&P)…", self)
        self._settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self._settings_action.triggered.connect(self._show_settings)

        self._exit_action = QAction("退出(&X)", self)
        self._exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self._exit_action.triggered.connect(self.close)

        self._zoom_in_action = QAction("放大(&I)", self)
        self._zoom_in_action.setShortcut(QKeySequence("Ctrl++"))
        self._zoom_in_action.triggered.connect(lambda: self._view.zoom_by(1.2))

        self._zoom_out_action = QAction("缩小(&O)", self)
        self._zoom_out_action.setShortcut(QKeySequence("Ctrl+-"))
        self._zoom_out_action.triggered.connect(lambda: self._view.zoom_by(1 / 1.2))

        self._fit_action = QAction("适应窗口(&F)", self)
        self._fit_action.setShortcut(QKeySequence("Ctrl+0"))
        self._fit_action.triggered.connect(self._view.fit_to_window)

        self._auto_refresh_action = QAction("自动刷新(&A)", self)
        self._auto_refresh_action.setCheckable(True)
        self._auto_refresh_action.setChecked(self._config.auto_refresh)
        self._auto_refresh_action.toggled.connect(self._set_auto_refresh)

        self._previous_file_action = QAction("上一个文件(&P)", self)
        self._previous_file_action.setShortcut(QKeySequence("Left"))
        self._previous_file_action.setEnabled(False)
        self._previous_file_action.triggered.connect(lambda: self._navigate_sibling(-1))

        self._next_file_action = QAction("下一个文件(&N)", self)
        self._next_file_action.setShortcut(QKeySequence("Right"))
        self._next_file_action.setEnabled(False)
        self._next_file_action.triggered.connect(lambda: self._navigate_sibling(1))

        self._about_action = QAction("关于(&A)", self)
        self._about_action.triggered.connect(self._show_about)

    def _create_menus(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("文件(&F)")
        file_menu.addAction(self._open_action)
        file_menu.addAction(self._reload_action)
        file_menu.addAction(self._save_png_action)
        file_menu.addAction(self._make_video_action)
        file_menu.addSeparator()
        self._recent_menu = file_menu.addMenu("最近打开文件")
        self._update_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction(self._settings_action)
        file_menu.addSeparator()
        file_menu.addAction(self._exit_action)

        view_menu = menu_bar.addMenu("查看(&V)")
        view_menu.addAction(self._previous_file_action)
        view_menu.addAction(self._next_file_action)
        view_menu.addSeparator()
        view_menu.addAction(self._zoom_in_action)
        view_menu.addAction(self._zoom_out_action)
        view_menu.addAction(self._fit_action)
        view_menu.addSeparator()
        view_menu.addAction(self._auto_refresh_action)

        help_menu = menu_bar.addMenu("帮助(&H)")
        help_menu.addAction(self._about_action)

    def _create_status_bar(self) -> None:
        status = self.statusBar()
        self._filename_label = QLabel("未打开文件")
        self._page_size_label = QLabel("页面：—")
        self._zoom_label = QLabel("缩放：—")
        self._updated_label = QLabel("更新时间：—")
        self._filename_label.setMinimumWidth(220)
        status.addWidget(self._filename_label, 1)
        status.addPermanentWidget(self._page_size_label)
        status.addPermanentWidget(self._zoom_label)
        status.addPermanentWidget(self._updated_label)

    # ----- File opening and recent files ----------------------------------

    def _choose_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "打开 EPS/PS 文件",
            str(self._current_file.parent if self._current_file else Path.home()),
            "EPS / PS 文件 (*.eps *.EPS *.ps *.PS);;所有文件 (*.*)",
        )
        if filename:
            self.open_eps(filename)

    def open_eps(self, filename: str | Path) -> None:
        """Open an EPS or PostScript path and queue a vector conversion."""
        source = Path(filename).expanduser().resolve()
        if not source.is_file():
            self.show_nonfatal_error("打开失败", f"找不到文件：\n{source}")
            return
        if source.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            self.show_nonfatal_error("打开失败", "请选择扩展名为 .eps 或 .ps 的文件。")
            return

        is_new_file = self._current_file != source
        if is_new_file:
            self._cancel_active_preview()
            self._current_file = source
            self._current_pdf = None
            self._view.clear_document()
            self._monitor.set_file(source)
            self._refresh_sibling_navigation()
            self._page_size_label.setText("页面：正在转换")
            self._zoom_label.setText("缩放：—")
            self._updated_label.setText("更新时间：—")
            self.setWindowTitle(f"{APP_NAME} — {source.name}")
            self._reload_action.setEnabled(True)
            self._save_png_action.setEnabled(True)

        self._automatic_failure_count = 0
        self._generation += 1
        self._queue_preview(
            PreviewRequest(source, self._generation, False, is_new_file)
        )

    def _scan_sibling_sources(self) -> list[Path]:
        """Return supported files in the current folder using natural UI order."""
        if self._current_file is None:
            return []
        try:
            return sorted(
                (
                    item.resolve()
                    for item in self._current_file.parent.iterdir()
                    if item.is_file()
                    and item.suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
                ),
                key=filename_sort_key,
            )
        except OSError:
            return []

    def _refresh_sibling_navigation(self) -> None:
        self._siblings = self._scan_sibling_sources()
        try:
            self._sibling_index = self._siblings.index(self._current_file)
        except ValueError:
            self._sibling_index = -1

        has_previous = self._sibling_index > 0
        has_next = 0 <= self._sibling_index < len(self._siblings) - 1
        self._previous_file_action.setEnabled(has_previous)
        self._next_file_action.setEnabled(has_next)
        self._previous_file_action.setToolTip(
            f"上一个：{self._siblings[self._sibling_index - 1].name}"
            if has_previous
            else "没有上一个 EPS/PS 文件"
        )
        self._next_file_action.setToolTip(
            f"下一个：{self._siblings[self._sibling_index + 1].name}"
            if has_next
            else "没有下一个 EPS/PS 文件"
        )
        if self._current_file is not None:
            position = (
                f"  [{self._sibling_index + 1}/{len(self._siblings)}]"
                if self._sibling_index >= 0
                else ""
            )
            self._filename_label.setText(f"{self._current_file.name}{position}")

    def _navigate_sibling(self, offset: int) -> None:
        """Rescan the directory and open the previous/next source file."""
        self._refresh_sibling_navigation()
        target_index = self._sibling_index + offset
        if not 0 <= target_index < len(self._siblings):
            return
        self.open_eps(self._siblings[target_index])

    def _recent_files(self) -> list[str]:
        saved = self._settings.value("recentFiles", [])
        if isinstance(saved, str):
            return [saved]
        if isinstance(saved, (list, tuple)):
            return [str(item) for item in saved if str(item).strip()]
        return []

    def _add_recent_file(self, source: Path) -> None:
        normalized = str(source)
        files = [item for item in self._recent_files() if item.lower() != normalized.lower()]
        files.insert(0, normalized)
        self._settings.setValue("recentFiles", files[: self.MAX_RECENT_FILES])
        self._update_recent_menu()

    def _remove_recent_file(self, filename: str) -> None:
        self._settings.setValue(
            "recentFiles", [item for item in self._recent_files() if item != filename]
        )
        self._update_recent_menu()

    def _update_recent_menu(self) -> None:
        self._recent_menu.clear()
        files = self._recent_files()
        if not files:
            placeholder = self._recent_menu.addAction("（暂无最近文件）")
            placeholder.setEnabled(False)
            return
        for filename in files:
            path = Path(filename)
            action = self._recent_menu.addAction(path.name)
            action.setToolTip(filename)
            action.triggered.connect(
                lambda checked=False, item=filename: self._open_recent(item)
            )

    def _open_recent(self, filename: str) -> None:
        if not Path(filename).is_file():
            self.show_nonfatal_error("最近文件不可用", f"文件已不存在：\n{filename}")
            self._remove_recent_file(filename)
            return
        self.open_eps(filename)

    # ----- EPS-to-vector-preview lifecycle --------------------------------

    def _manual_reload(self) -> None:
        if self._current_file is None:
            return
        self._automatic_failure_count = 0
        self._generation += 1
        self._queue_preview(
            PreviewRequest(self._current_file, self._generation, False, False)
        )

    def _queue_preview(self, request: PreviewRequest) -> None:
        if self._closing or request.source != self._current_file:
            return
        if self._preview_thread is not None:
            self._pending_preview_request = request
            self._cancel_active_preview()
            return
        self._start_preview(request)

    def _start_preview(self, request: PreviewRequest) -> None:
        if self._closing or request.source != self._current_file:
            return
        thread = QThread(self)
        worker = PreviewWorker(self._renderer, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_preview_succeeded)
        worker.failed.connect(self._on_preview_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._on_preview_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        self._preview_thread = thread
        self._preview_worker = worker
        self._active_preview_request = request
        thread.start()

    @pyqtSlot(object)
    def _on_preview_succeeded(self, success: PreviewSuccess) -> None:
        request = success.request
        result = success.result
        if (
            self._closing
            or request.generation != self._generation
            or request.source != self._current_file
        ):
            self._renderer.cache.release(result.pdf_path)
            return
        try:
            self._view.load_pdf(
                result.pdf_path,
                request.generation,
                reset_view=request.reset_view,
            )
        except VectorPreviewError as error:
            self._renderer.cache.release(result.pdf_path)
            self._handle_preview_error(request, error)
            return
        self._current_pdf = result.pdf_path
        self._add_recent_file(result.source)
        self._automatic_failure_count = 0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._updated_label.setText(f"更新时间：{timestamp}")
        # Keep the filename and sibling position visible after a successful
        # refresh instead of replacing them with a transient status message.
        self.statusBar().clearMessage()

    @pyqtSlot(object)
    def _on_preview_failed(self, failure: PreviewFailure) -> None:
        request = failure.request
        if (
            self._closing
            or request.generation != self._generation
            or request.source != self._current_file
        ):
            return
        self._handle_preview_error(request, failure.error)

    def _handle_preview_error(self, request: PreviewRequest, error: Exception) -> None:
        if isinstance(error, EpsRenderCancelledError):
            return
        message = str(error) or "发生未知预览错误。"
        self.statusBar().showMessage(message, 6000)
        if isinstance(error, GhostscriptNotFoundError):
            if not request.automatic:
                self.show_nonfatal_error("未找到 Ghostscript", message)
            return
        if request.automatic:
            self._automatic_failure_count += 1
            if self._automatic_failure_count <= 5:
                QTimer.singleShot(500, lambda req=request: self._retry_preview(req))
            return
        title = "EPS/PS 文件无法解析" if isinstance(error, EpsRenderError) else "预览失败"
        self.show_nonfatal_error(title, message)

    def _retry_preview(self, request: PreviewRequest) -> None:
        if (
            not self._closing
            and request.generation == self._generation
            and request.source == self._current_file
        ):
            self._queue_preview(request)

    def _on_preview_thread_finished(self, thread: QThread) -> None:
        if thread is not self._preview_thread:
            return
        self._preview_thread = None
        self._preview_worker = None
        self._active_preview_request = None
        pending = self._pending_preview_request
        self._pending_preview_request = None
        if pending is not None and not self._closing:
            QTimer.singleShot(0, lambda req=pending: self._queue_preview(req))

    def _cancel_active_preview(self) -> None:
        if self._preview_worker is not None:
            self._preview_worker.cancel()

    @pyqtSlot(str)
    def _on_source_changed(self, filename: str) -> None:
        if self._current_file is None or Path(filename) != self._current_file:
            return
        if not self._config.auto_refresh:
            return
        self._automatic_failure_count = 0
        self._generation += 1
        self._queue_preview(
            PreviewRequest(self._current_file, self._generation, True, False)
        )

    # ----- PNG export ------------------------------------------------------

    def _show_export_dialog(self) -> None:
        if self._current_file is None:
            return
        dialog = PngExportDialog(
            self._current_file.with_suffix(".png"), self._config.export_dpi, self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        target, dpi = dialog.get_values()
        if target.exists():
            answer = QMessageBox.question(
                self,
                "覆盖 PNG 文件",
                f"文件已存在，是否覆盖？\n{target}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_export(
            ExportRequest(
                self._current_file,
                target,
                dpi,
                self._config.background_mode,
                self._config.background_color,
            )
        )

    def _start_export(self, request: ExportRequest) -> None:
        if self._export_thread is not None:
            self.statusBar().showMessage("已有 PNG 导出任务正在进行。", 4000)
            return
        self._save_png_action.setEnabled(False)
        self.statusBar().showMessage(f"正在导出 {request.dpi} DPI PNG…")
        thread = QThread(self)
        worker = ExportWorker(self._renderer, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_export_succeeded)
        worker.failed.connect(self._on_export_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._on_export_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        self._export_thread = thread
        self._export_worker = worker
        thread.start()

    @pyqtSlot(object)
    def _on_export_succeeded(self, output: Path) -> None:
        if self._closing:
            return
        self.statusBar().showMessage(f"PNG 已保存：{output}", 6000)
        QMessageBox.information(self, "PNG 导出完成", f"已保存：\n{output}")

    @pyqtSlot(object)
    def _on_export_failed(self, failure: ExportFailure) -> None:
        if self._closing or isinstance(failure.error, EpsRenderCancelledError):
            return
        message = str(failure.error) or "PNG 导出失败。"
        self.statusBar().showMessage(message, 6000)
        title = (
            "未找到 Ghostscript"
            if isinstance(failure.error, GhostscriptNotFoundError)
            else "PNG 导出失败"
        )
        self.show_nonfatal_error(title, message)

    def _on_export_thread_finished(self, thread: QThread) -> None:
        if thread is not self._export_thread:
            return
        self._export_thread = None
        self._export_worker = None
        if not self._closing:
            self._save_png_action.setEnabled(self._current_file is not None)

    # ----- Folder sequence video/GIF export ------------------------------

    def _show_video_dialog(self) -> None:
        if self._video_thread is not None:
            self.statusBar().showMessage("已有视频生成任务正在进行。", 4000)
            return
        saved_folder = self._settings.value("lastVideoFolder", "")
        initial_folder = (
            self._current_file.parent
            if self._current_file is not None
            else Path(str(saved_folder))
            if saved_folder
            else Path.home()
        )
        dialog = VideoCreationDialog(initial_folder, self._renderer, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        request = dialog.request()
        if request.target.exists():
            answer = QMessageBox.question(
                self,
                "覆盖输出文件",
                f"文件已存在，是否覆盖？\n{request.target}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if request.sources:
            self._settings.setValue("lastVideoFolder", str(request.sources[0].parent))
        self._start_video_export(request)

    def _start_video_export(self, request: VideoExportRequest) -> None:
        self._make_video_action.setEnabled(False)
        progress = QProgressDialog(
            "正在准备视频帧…",
            "取消",
            0,
            len(request.sources) + 1,
            self,
        )
        progress.setWindowTitle("制作视频")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setMinimumDuration(0)

        thread = QThread(self)
        worker = VideoWorker(VideoExporter(self._renderer), request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_video_progress)
        worker.succeeded.connect(self._on_video_succeeded)
        worker.failed.connect(self._on_video_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        progress.canceled.connect(lambda: worker.cancel())
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._on_video_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        self._video_thread = thread
        self._video_worker = worker
        self._video_progress = progress
        self.statusBar().showMessage("正在生成视频…")
        thread.start()

    @pyqtSlot(int, int, str)
    def _on_video_progress(self, current: int, total: int, message: str) -> None:
        if self._video_progress is None:
            return
        self._video_progress.setMaximum(total)
        self._video_progress.setValue(current)
        self._video_progress.setLabelText(message)

    @pyqtSlot(object)
    def _on_video_succeeded(self, output: Path) -> None:
        if self._closing:
            return
        if self._video_progress is not None:
            self._video_progress.setValue(self._video_progress.maximum())
            self._video_progress.close()
        self.statusBar().showMessage(f"视频已保存：{output}", 6000)
        QMessageBox.information(self, "视频生成完成", f"已保存：\n{output}")

    @pyqtSlot(object)
    def _on_video_failed(self, error: Exception) -> None:
        if self._video_progress is not None:
            self._video_progress.close()
        if self._closing or isinstance(error, VideoExportCancelled):
            if not self._closing:
                self.statusBar().showMessage("视频生成已取消。", 4000)
            return
        message = str(error) or "视频生成失败。"
        self.statusBar().showMessage(message, 6000)
        self.show_nonfatal_error("视频生成失败", message)

    def _on_video_thread_finished(self, thread: QThread) -> None:
        if thread is not self._video_thread:
            return
        self._video_thread = None
        self._video_worker = None
        if self._video_progress is not None:
            self._video_progress.deleteLater()
            self._video_progress = None
        if not self._closing:
            self._make_video_action.setEnabled(True)

    # ----- Settings and status --------------------------------------------

    def _show_settings(self) -> None:
        dialog = SettingsDialog(self._config, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        previous = self._config
        updated = dialog.get_config()
        if updated.ghostscript_path:
            executable = Path(updated.ghostscript_path).expanduser()
            if not executable.is_file():
                self.show_nonfatal_error(
                    "Ghostscript 路径无效",
                    f"找不到指定的 Ghostscript 程序：\n{executable}",
                )
                return

        ghostscript_changed = updated.ghostscript_path != previous.ghostscript_path
        refresh_just_enabled = updated.auto_refresh and not previous.auto_refresh
        self._config = updated
        self._renderer.set_ghostscript_path(updated.ghostscript_path)
        self._monitor.set_refresh_interval(updated.refresh_interval)
        self._monitor.set_enabled(updated.auto_refresh)
        self._view.set_page_background(
            updated.background_mode,
            updated.background_color,
        )
        self._auto_refresh_action.blockSignals(True)
        self._auto_refresh_action.setChecked(updated.auto_refresh)
        self._auto_refresh_action.blockSignals(False)
        if self._save_config():
            self.statusBar().showMessage("设置已保存", 2500)

        if (ghostscript_changed or refresh_just_enabled) and self._current_file is not None:
            self._generation += 1
            self._queue_preview(
                PreviewRequest(self._current_file, self._generation, False, False)
            )

    def _set_auto_refresh(self, enabled: bool) -> None:
        was_enabled = self._config.auto_refresh
        self._config.auto_refresh = enabled
        self._monitor.set_enabled(enabled)
        if self._save_config():
            self.statusBar().showMessage(
                "自动刷新已开启" if enabled else "自动刷新已关闭", 2500
            )
        if enabled and not was_enabled and self._current_file is not None:
            self._generation += 1
            self._queue_preview(
                PreviewRequest(self._current_file, self._generation, True, False)
            )

    def _save_config(self) -> bool:
        try:
            self._config_manager.save(self._config)
        except OSError as error:
            self.statusBar().showMessage(f"无法保存 config.json：{error}", 6000)
            return False
        return True

    @pyqtSlot(float)
    def _update_zoom_status(self, percent: float) -> None:
        self._zoom_label.setText(f"缩放：{percent:.0f}%")

    @pyqtSlot(float, float)
    def _update_page_size_status(self, width: float, height: float) -> None:
        self._page_size_label.setText(f"页面：{width:.1f} × {height:.1f} pt")

    @pyqtSlot(str)
    def _on_vector_render_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 6000)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            f"关于 {APP_NAME}",
            "<b>EPS Live Viewer</b><br><br>"
            "用于科研绘图过程中快速查看并实时刷新 EPS/PS 文件。<br><br>"
            "<b>使用要点</b><br>"
            "• 打开或拖入 EPS/PS 文件；文件重新生成后会自动刷新。<br>"
            "• 按左右方向键，可按文件名切换同一文件夹中的上一个或下一个 EPS/PS。<br>"
            "• 使用鼠标滚轮缩放、拖动平移；双击恢复 100%，Ctrl+0 适应窗口。<br>"
            "• 可将文件夹中的 EPS/PS/PNG/JPG 制作成 MP4/GIF，并在首帧预览中框选输出区域。<br>"
            "• 可在“设置”中调整自动刷新、背景与默认 PNG DPI。<br><br>"
            "<b>作者</b><br>"
            "Zhentong Li<br>"
            "eternitylzt@gmail.com",
        )

    def show_nonfatal_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)

    # ----- Drag/drop and shutdown -----------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # type: ignore[override]
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                if (
                    url.isLocalFile()
                    and Path(url.toLocalFile()).suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
                ):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # type: ignore[override]
        for url in event.mimeData().urls():
            if (
                url.isLocalFile()
                and Path(url.toLocalFile()).suffix.lower() in SUPPORTED_SOURCE_SUFFIXES
            ):
                self.open_eps(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._closing = True
        self._monitor.clear()
        self._pending_preview_request = None
        self._cancel_active_preview()
        if self._export_worker is not None:
            self._export_worker.cancel()
        if self._video_worker is not None:
            self._video_worker.cancel()

        for thread in (self._preview_thread, self._export_thread, self._video_thread):
            if thread is not None and thread.isRunning():
                # quit() is thread-safe and lets the event loop finish as soon
                # as the cancellable worker returns.  Calling it before wait()
                # avoids relying on a queued GUI-thread slot while closeEvent
                # itself is blocking in wait().
                thread.requestInterruption()
                thread.quit()
            if thread is not None and thread.isRunning() and not thread.wait(7_000):
                self._closing = False
                event.ignore()
                if self._current_file is not None:
                    self._monitor.set_file(self._current_file)
                    self._monitor.set_enabled(self._config.auto_refresh)
                self.statusBar().showMessage("后台任务尚未结束，请稍后再次关闭。", 5000)
                return

        self._view.clear_document()
        self._renderer.cache.release(self._current_pdf)
        self._renderer.cache.cleanup()
        super().closeEvent(event)
