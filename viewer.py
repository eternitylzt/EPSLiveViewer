"""Main window, background jobs, menus, and live-refresh coordination."""

from __future__ import annotations

import threading
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import (
    Qt,
    QObject,
    QSettings,
    QThread,
    QTimer,
    QUrl,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenuBar,
    QMessageBox,
    QProgressDialog,
    QStyle,
    QTextBrowser,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QCheckBox,
    QGridLayout,
    QStackedWidget,
)

from config import (
    APP_NAME,
    APP_VERSION,
    PROJECT_URL,
    AppConfig,
    ConfigManager,
    SUPPORTED_SOURCE_SUFFIXES,
    filename_sort_key,
)
from color_dialog import ColorReplacementDialog
from welcome import WelcomePage
from branding import tool_icon
from window_geometry import fit_initial_window
from comparison import ComparisonDialog
from dialogs import PngExportDialog, SettingsDialog
from diagnostics import Diagnostics, DiagnosticsDialog
from eps_renderer import (
    EpsRenderCancelledError,
    EpsRenderError,
    EpsRenderer,
    GhostscriptNotFoundError,
    PdfRenderResult,
)
from file_monitor import EpsFileMonitor
from i18n import set_language, tr, bilingual as L
from image_transforms import DocumentTransforms, TransformSnapshot, TransformHistory
from update_checker import (
    ReleaseInfo,
    check_latest_release,
    is_newer_version,
)
from video_creator import (
    VideoExportCancelled,
    VideoExporter,
    VideoExportRequest,
    VideoFrameSource,
)
from video_dialog import VideoCreationDialog
from vector_preview import VectorGraphicsView, VectorPreviewError
from document_state import load_state, save_state, state_path


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
    page_number: int = 1
    all_pages: bool = False
    page_count: int = 1
    transforms: TransformSnapshot = TransformSnapshot()


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
            if self._request.all_pages:
                output = self._renderer.export_png_pages(
                    self._request.source,
                    self._request.target,
                    self._request.page_count,
                    dpi=self._request.dpi,
                    background=self._request.background_mode,
                    background_color=self._request.background_color,
                    cancel_event=self._cancel_event,
                    transforms=self._request.transforms,
                )
            else:
                output = self._renderer.export_png(
                    self._request.source,
                    self._request.target,
                    dpi=self._request.dpi,
                    background=self._request.background_mode,
                    background_color=self._request.background_color,
                    cancel_event=self._cancel_event,
                    page_number=self._request.page_number,
                    transforms=self._request.transforms,
                )
        except Exception as error:
            self.failed.emit(ExportFailure(self._request, error))
        else:
            self.succeeded.emit(output)


@dataclass(frozen=True)
class PdfExportRequest:
    source: Path
    target: Path
    transforms: TransformSnapshot = TransformSnapshot()
    page_count: int = 1
    current_page: int = 1
    dpi: int = 300
    background_mode: str = "transparent"
    background_color: str = "#FFFFFF"


@dataclass(frozen=True)
class PdfExportFailure:
    request: PdfExportRequest
    error: Exception


class PdfExportWorker(QObject):
    """Convert and save one complete vector PDF outside the GUI thread."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    def __init__(self, renderer: EpsRenderer, request: PdfExportRequest) -> None:
        super().__init__()
        self._renderer = renderer
        self._request = request
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    @pyqtSlot()
    def run(self) -> None:
        try:
            output = self._renderer.export_document(
                self._request.source,
                self._request.target,
                self._request.transforms,
                self._request.page_count,
                self._request.current_page,
                dpi=self._request.dpi,
                background=self._request.background_mode,
                background_color=self._request.background_color,
                cancel_event=self._cancel_event,
            )
        except Exception as error:
            self.failed.emit(PdfExportFailure(self._request, error))
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


class UpdateCheckWorker(QObject):
    """Fetch release metadata after an explicit user request."""

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(object)

    @pyqtSlot()
    def run(self) -> None:
        try:
            release = check_latest_release()
        except Exception as error:
            self.failed.emit(error)
        else:
            self.succeeded.emit(release)


class MainWindow(QMainWindow):
    """Application shell coordinating source monitoring and vector preview."""

    MAX_RECENT_FILES = 10
    document_state_changed = pyqtSignal(object, object, int)
    caption_changed = pyqtSignal()

    def menuBar(self):
        # Hosted documents retain their own actions, but display their menu
        # above the workspace's tab strip, never inside the document page.
        return getattr(self,"_shared_menu_bar",None) or super().menuBar()

    def __init__(self, config_manager: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        if parent is not None:
            # Establish the child widget before Cocoa creates native menus or
            # window handles. Converting a populated top-level window is too late.
            self.setWindowFlags(Qt.WindowType.Widget)
            menu_bar = QMenuBar(self)
            menu_bar.setNativeMenuBar(False)
            self.setMenuBar(menu_bar)
        self._config_manager = config_manager
        self._config: AppConfig = config_manager.load()
        set_language(self._config.language)
        self._renderer = EpsRenderer(self._config.ghostscript_path)
        self._monitor = EpsFileMonitor(self._config.refresh_interval, self)
        self._monitor.file_changed.connect(self._on_source_changed)

        self._current_file: Path | None = None
        self._current_pdf: Path | None = None
        self._generation = 0
        self._automatic_failure_count = 0
        self._last_updated_timestamp = ""
        self._closing = False

        self._preview_thread: QThread | None = None
        self._preview_worker: PreviewWorker | None = None
        self._active_preview_request: PreviewRequest | None = None
        self._pending_preview_request: PreviewRequest | None = None
        self._export_thread: QThread | None = None
        self._export_worker: ExportWorker | None = None
        self._pdf_export_thread: QThread | None = None
        self._pdf_export_worker: PdfExportWorker | None = None
        self._video_thread: QThread | None = None
        self._video_worker: VideoWorker | None = None
        self._video_progress: QProgressDialog | None = None
        self._update_thread: QThread | None = None
        self._update_worker: UpdateCheckWorker | None = None
        self._siblings: list[Path] = []
        self._sibling_index = -1
        self._current_page_index = 0
        self._page_count = 0
        self._document_transforms: dict[Path, DocumentTransforms] = {}
        self._histories: dict[Path, TransformHistory] = {}
        self._diagnostics = Diagnostics()
        self._comparison = None
        self._saved_states = {}
        self._discard_on_close = False
        self._host = None
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
        self._view.set_wheel_action(self._config.wheel_action)
        self._view.zoom_changed.connect(self._update_zoom_status)
        self._view.image_loaded.connect(self._update_page_size_status)
        self._view.page_changed.connect(self._on_page_changed)
        self._view.render_error.connect(self._on_vector_render_error)
        self._view.document_released.connect(self._renderer.cache.release)
        self._view.source_dropped.connect(self.request_open)
        self._view.file_navigation_requested.connect(self._navigate_sibling)
        self._view.page_navigation_requested.connect(self._navigate_page)
        self._view.edit_text_requested.connect(self._show_text_editor)
        self._pages = QStackedWidget()
        self._welcome = WelcomePage(self)
        self._welcome.open_requested.connect(self._choose_file)
        self._welcome.recent_requested.connect(self._open_recent)
        self._pages.addWidget(self._welcome)
        self._pages.addWidget(self._view)
        self.setCentralWidget(self._pages)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_status_bar()
        self._create_document_actions()
        self._retranslate_ui()
        self._monitor.set_enabled(self._config.auto_refresh)
        if parent is None:
            fit_initial_window(self,1200,800)

    # ----- UI construction -------------------------------------------------

    def _create_actions(self) -> None:
        self._open_action = QAction("打开图片(&O)…", self)
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

        self._save_pdf_action = QAction("另存为 PDF(&D)…", self)
        self._save_pdf_action.setEnabled(False)
        self._save_pdf_action.triggered.connect(self._show_pdf_export_dialog)

        self._save_postscript_action = QAction("另存为 EPS/PS(&E)…", self)
        self._save_postscript_action.setEnabled(False)
        self._save_postscript_action.triggered.connect(
            self._show_postscript_export_dialog
        )

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

        self._previous_page_action = QAction("上一页(&U)", self)
        self._previous_page_action.setShortcut(QKeySequence("Up"))
        self._previous_page_action.setEnabled(False)
        self._previous_page_action.triggered.connect(lambda: self._navigate_page(-1))

        self._next_page_action = QAction("下一页(&D)", self)
        self._next_page_action.setShortcut(QKeySequence("Down"))
        self._next_page_action.setEnabled(False)
        self._next_page_action.triggered.connect(lambda: self._navigate_page(1))

        self._rotate_left_action = QAction("向左旋转 90°(&L)", self)
        self._rotate_left_action.setShortcut(QKeySequence("Ctrl+Shift+["))
        self._rotate_left_action.setEnabled(False)
        self._rotate_left_action.triggered.connect(lambda: self._rotate_page(-90))

        self._rotate_right_action = QAction("向右旋转 90°(&R)", self)
        self._rotate_right_action.setShortcut(QKeySequence("Ctrl+Shift+]"))
        self._rotate_right_action.setEnabled(False)
        self._rotate_right_action.triggered.connect(lambda: self._rotate_page(90))

        self._rotation_scope_group = QActionGroup(self)
        self._rotate_current_action = QAction("仅当前页", self)
        self._rotate_all_action = QAction("全部页面", self)
        for action in (self._rotate_current_action, self._rotate_all_action):
            action.setCheckable(True)
            self._rotation_scope_group.addAction(action)
        scope = self._config.rotation_scope
        (self._rotate_all_action if scope == "all" else self._rotate_current_action).setChecked(True)
        self._rotation_scope_group.triggered.connect(self._rotation_scope_changed)

        self._invert_colors_action = QAction("反转颜色(&I)", self)
        self._invert_colors_action.setCheckable(True)
        self._invert_colors_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self._invert_colors_action.setEnabled(False)
        self._invert_colors_action.toggled.connect(self._set_inverted)

        self._replace_colors_action = QAction("替换颜色(&C)…", self)
        self._replace_colors_action.setEnabled(False)
        self._replace_colors_action.triggered.connect(self._show_color_replacements)

        self._reset_transforms_action = QAction("重置图像调整(&T)", self)
        self._reset_transforms_action.setEnabled(False)
        self._reset_transforms_action.triggered.connect(self._reset_transforms)

        self._undo_action = QAction("撤销图像调整", self)
        self._undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self._undo_action.triggered.connect(lambda: self._restore_history(False))
        self._redo_action = QAction("重做图像调整", self)
        self._redo_action.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self._redo_action.triggered.connect(lambda: self._restore_history(True))
        self._undo_action.setEnabled(False)
        self._redo_action.setEnabled(False)

        self._about_action = QAction("关于(&A)", self)
        self._about_action.triggered.connect(self._show_about)

        self._check_updates_action = QAction("检查更新(&U)…", self)
        self._check_updates_action.triggered.connect(self._check_for_updates)
        self._diagnostics_action = QAction("诊断信息…", self)
        self._diagnostics_action.triggered.connect(self._show_diagnostics)
        self._compare_action = QAction("并排比较…", self)
        self._compare_action.setShortcut(QKeySequence("Ctrl+Shift+C"))
        self._compare_action.setEnabled(False)
        self._compare_action.triggered.connect(self._show_comparison)

    def _create_menus(self) -> None:
        menu_bar = self.menuBar()
        self._file_menu = menu_bar.addMenu("文件(&F)")
        self._file_menu.addAction(self._open_action)
        self._file_menu.addAction(self._reload_action)
        self._export_menu = self._file_menu.addMenu("导出")
        self._export_menu.addAction(self._save_postscript_action)
        self._export_menu.addAction(self._save_pdf_action)
        self._export_menu.addAction(self._save_png_action)
        self._file_menu.addAction(self._make_video_action)
        self._file_menu.addSeparator()
        self._recent_menu = self._file_menu.addMenu("最近打开文件")
        self._update_recent_menu()
        self._file_menu.addSeparator()
        self._file_menu.addAction(self._settings_action)
        self._file_menu.addSeparator()
        self._file_menu.addAction(self._exit_action)

        self._view_menu = menu_bar.addMenu("查看(&V)")
        self._view_menu.addAction(self._compare_action)
        self._view_menu.addSeparator()
        self._view_menu.addAction(self._previous_file_action)
        self._view_menu.addAction(self._next_file_action)
        self._view_menu.addSeparator()
        self._view_menu.addAction(self._previous_page_action)
        self._view_menu.addAction(self._next_page_action)
        self._view_menu.addSeparator()
        self._view_menu.addAction(self._zoom_in_action)
        self._view_menu.addAction(self._zoom_out_action)
        self._view_menu.addAction(self._fit_action)
        self._view_menu.addSeparator()
        self._view_menu.addAction(self._auto_refresh_action)

        self._image_menu = menu_bar.addMenu("图像(&I)")
        self._image_menu.addAction(self._undo_action)
        self._image_menu.addAction(self._redo_action)
        self._image_menu.addSeparator()
        self._rotation_scope_menu = self._image_menu.addMenu("旋转范围")
        self._rotation_scope_menu.addAction(self._rotate_current_action)
        self._rotation_scope_menu.addAction(self._rotate_all_action)
        self._image_menu.addAction(self._rotate_left_action)
        self._image_menu.addAction(self._rotate_right_action)
        self._image_menu.addSeparator()
        self._image_menu.addAction(self._invert_colors_action)
        self._image_menu.addAction(self._replace_colors_action)
        self._image_menu.addAction(self._reset_transforms_action)

        self._preferences_menu = menu_bar.addMenu("设置")
        self._preferences_menu.addAction(self._settings_action)
        self._preferences_menu.addSeparator()
        self._settings_sections = []
        for key, zh, en in (("general","常规与预览…","General & View…"),
                            ("runtime","刷新与依赖…","Refresh & Dependencies…"),
                            ("export","导出与视频…","Export & Video…"),
                            ("editing","编辑与工具…","Editing & Tools…"),
                            ("toolbar","工具栏…","Toolbar…")):
            action = self._preferences_menu.addAction(L(zh,en))
            action.triggered.connect(lambda checked=False, section=key: self._show_settings(section))
            self._settings_sections.append((action,zh,en))

        self._help_menu = menu_bar.addMenu("帮助(&H)")
        self._help_menu.addAction(self._check_updates_action)
        self._help_menu.addAction(self._diagnostics_action)
        self._help_menu.addSeparator()
        self._help_menu.addAction(self._about_action)

    def _create_toolbar(self) -> None:
        self._toolbar = QToolBar("快捷工具", self)
        self._toolbar.setObjectName("mainToolbar")
        self._toolbar.setMovable(False)
        self._toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        standard = QStyle.StandardPixmap
        self._open_action.setIcon(self.style().standardIcon(standard.SP_DialogOpenButton))
        self._reload_action.setIcon(self.style().standardIcon(standard.SP_BrowserReload))
        self._save_png_action.setIcon(self.style().standardIcon(standard.SP_DialogSaveButton))
        self._previous_file_action.setIcon(self.style().standardIcon(standard.SP_ArrowLeft))
        self._next_file_action.setIcon(self.style().standardIcon(standard.SP_ArrowRight))
        self._previous_page_action.setIcon(self.style().standardIcon(standard.SP_ArrowUp))
        self._next_page_action.setIcon(self.style().standardIcon(standard.SP_ArrowDown))
        self._rotation_scope_button = QToolButton(self._toolbar)
        self._rotation_scope_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._rotation_scope_button.setMenu(self._rotation_scope_menu)
        self._rotation_toolbar_action = self._toolbar.addWidget(self._rotation_scope_button)
        self._toolbar.removeAction(self._rotation_toolbar_action)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

    def _create_document_actions(self):
        self._edit_text_action = QAction(self)
        self._edit_text_action.setEnabled(False)
        self._edit_text_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self._edit_text_action.triggered.connect(self._show_text_editor)
        self._image_menu.addSeparator()
        self._image_menu.addAction(self._edit_text_action)
        self._save_edits_action = QAction(self)
        self._save_edits_action.setShortcut(QKeySequence.StandardKey.Save)
        self._save_edits_action.setEnabled(False)
        self._save_edits_action.triggered.connect(lambda: self.save_edits())
        self._file_info_action = QAction(self)
        self._file_info_action.setEnabled(False)
        self._file_info_action.triggered.connect(self._show_file_info)
        self._select_text_action = QAction(self)
        self._select_text_action.setCheckable(True)
        self._select_text_action.setEnabled(False)
        self._select_text_action.toggled.connect(self._set_auto_text)
        self._copy_text_action = QAction(self)
        self._copy_text_action.setShortcut(QKeySequence.StandardKey.Copy)
        self._copy_text_action.triggered.connect(self._view.copy_selected_text)
        self._customize_toolbar_action = QAction(self)
        self._customize_toolbar_action.triggered.connect(self._customize_toolbar)
        self._file_menu.insertAction(self._export_menu.menuAction(), self._save_edits_action)
        self._file_menu.insertAction(self._settings_action, self._file_info_action)
        self._view_menu.addAction(self._select_text_action)
        self._view_menu.addAction(self._copy_text_action)
        self._view_menu.addAction(self._customize_toolbar_action)
        self._toolbar.addAction(self._customize_toolbar_action)
        self._toolbar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._toolbar.customContextMenuRequested.connect(lambda _pos: self._customize_toolbar())
        self._toolbar_options = {
            name: getattr(self, "_" + name + "_action")
            for name in ("open", "reload", "previous_file", "next_file", "previous_page",
                         "next_page", "zoom_out", "zoom_in", "fit", "rotate_left",
                         "rotate_right", "invert_colors", "replace_colors", "save_edits",
                         "save_png", "save_pdf", "save_postscript", "make_video", "compare",
                         "file_info", "select_text", "edit_text")
        }
        self._toolbar_options["rotation_scope"] = self._rotation_toolbar_action
        self._set_toolbar_icons()
        self._refresh_toolbar()

    def _set_toolbar_icons(self):
        color = self.palette().color(self.foregroundRole())
        for name, action in self._toolbar_options.items():
            if name != "rotation_scope":
                action.setIcon(tool_icon(name, color))

    def _show_text_editor(self, point=None):
        if self._current_pdf is None or self._current_file is None:
            return
        from text_editor import TextEditorDialog
        dialog = TextEditorDialog(self._current_pdf, self._current_file, self._renderer,
                                  self._current_transforms().snapshot(), self,
                                  page=self._current_page_index,
                                  show_list=self._config.text_list_visible,
                                  initial_point=point if not isinstance(point,bool) else None)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _refresh_toolbar(self):
        # Removing an action here keeps its menu entry and shortcut available.
        for action in self._toolbar.actions():
            self._toolbar.removeAction(action)
        for name in self._config.toolbar_tools:
            if name in self._toolbar_options:
                self._toolbar.addAction(self._toolbar_options[name])

    def _customize_toolbar(self):
        self._show_settings("toolbar")

    def _set_auto_text(self, enabled):
        self._view.set_text_selection_mode(enabled)
        self._config.auto_select_text = enabled
        self._save_config()

    def is_modified(self, source=None):
        source = source or self._current_file
        state = self._document_transforms.get(source)
        return state is not None and state.snapshot() != self._saved_states.get(source, TransformSnapshot())

    def save_edits(self, source=None):
        source = source or self._current_file
        if source is None:
            return True
        snapshot = self._document_transforms[source].snapshot()
        try:
            path = save_state(source, snapshot)
        except OSError as error:
            self.show_nonfatal_error(tr("无法保存编辑记录"), str(error))
            return False
        self._saved_states[source] = snapshot
        self.caption_changed.emit()
        self.statusBar().showMessage(tr("编辑记录已保存：{path}", path=path), 5000)
        return True

    def confirm_save_changes(self):
        for source in self._document_transforms:
            if not self.is_modified(source):
                continue
            answer = QMessageBox.question(
                self, tr("保存更改"),
                tr("是否保存 {name} 的旋转和颜色调整？\n编辑记录保存为旁边的 .epslive.json 文件，下次打开自动恢复。源图像不变。",
                   name=source.name),
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if answer == QMessageBox.StandardButton.Cancel:
                return False
            if answer == QMessageBox.StandardButton.Save and not self.save_edits(source):
                return False
        return True

    def _show_file_info(self):
        if self._current_file is None:
            return
        from datetime import datetime
        from PyQt6.QtGui import QImageReader
        from PyQt6.QtWidgets import QPlainTextEdit
        source = self._current_file
        try:
            stat = source.stat()
        except OSError as error:
            self.show_nonfatal_error(tr("文件信息"), str(error))
            return
        fields = [
            (tr("文件："), source.name), (tr("路径："), str(source)),
            (tr("格式："), source.suffix[1:].upper()),
            (tr("大小："), f"{stat.st_size:,} bytes"),
            (tr("修改时间："), datetime.fromtimestamp(stat.st_mtime).isoformat(sep=" ", timespec="seconds")),
            (tr("页码："), f"{self._current_page_index + 1} / {self._page_count}"),
        ]
        if self._view.has_document():
            size = self._view._active_context.document.pagePointSize(self._current_page_index)
            fields.append((tr("页面尺寸："), f"{size.width():.2f} × {size.height():.2f} pt"))
        if source.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            size = QImageReader(str(source)).size()
            fields.append((tr("像素："), f"{size.width()} × {size.height()}"))
        fields.extend([(tr("当前旋转："), f"{self._current_transforms().rotation_for(self._current_page_index + 1)}°"),
                       (tr("编辑记录："), str(state_path(source)))])
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("文件信息"))
        dialog.resize(640, 390)
        layout = QVBoxLayout(dialog)
        info = QPlainTextEdit()
        info.setReadOnly(True)
        info.setPlainText("\n".join(f"{key} {value}" for key, value in fields))
        layout.addWidget(info)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()
        dialog.deleteLater()

    def _create_status_bar(self) -> None:
        status = self.statusBar()
        self._filename_label = QLabel("未打开文件")
        self._page_size_label = QLabel("页面：—")
        self._page_number_label = QLabel("页码：—")
        self._zoom_label = QLabel("缩放：—")
        self._updated_label = QLabel("更新时间：—")
        self._filename_label.setMinimumWidth(220)
        status.addWidget(self._filename_label, 1)
        status.addPermanentWidget(self._page_number_label)
        status.addPermanentWidget(self._page_size_label)
        status.addPermanentWidget(self._zoom_label)
        status.addPermanentWidget(self._updated_label)

    # ----- File opening and recent files ----------------------------------

    def _choose_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            tr("打开图片文件"),
            str(self._current_file.parent if self._current_file else Path.home()),
            tr(
                "支持的图片 (*.eps *.EPS *.ps *.PS *.pdf *.PDF *.png *.PNG *.jpg *.JPG *.jpeg *.JPEG);;所有文件 (*.*)"
            ),
        )
        if filename:
            self.request_open(filename)

    def request_open(self, filename):
        if self._host is not None and self._current_file is None:
            self._host.add_document(filename)
        elif self._host is not None:
            self._host.open_file(filename, self._config.open_mode)
        else:
            self.open_eps(filename)

    def open_eps(self, filename: str | Path) -> None:
        """Open a supported vector or raster image and queue its preview."""
        source = Path(filename).expanduser().resolve()
        if not source.is_file():
            self.show_nonfatal_error(
                tr("打开失败"), tr("找不到文件：\n{path}", path=source)
            )
            return
        if source.suffix.lower() not in SUPPORTED_SOURCE_SUFFIXES:
            self.show_nonfatal_error(
                tr("打开失败"),
                tr("请选择 EPS、PS、PDF、PNG、JPG 或 JPEG 文件。"),
            )
            return

        is_new_file = self._current_file != source
        if is_new_file:
            if source not in self._document_transforms:
                state = DocumentTransforms()
                try:
                    state.restore(load_state(source))
                except (OSError, ValueError, TypeError, KeyError) as error:
                    self.show_nonfatal_error(tr("无法读取编辑记录"), str(error))
                self._document_transforms[source] = state
                self._saved_states[source] = state.snapshot()
            self._cancel_active_preview()
            self._current_file = source
            self._current_pdf = None
            self._edit_text_action.setEnabled(False)
            self._pages.setCurrentWidget(self._view)
            self._current_page_index = 0
            self._page_count = 0
            self._view.clear_document()
            self._apply_current_transforms()
            self._monitor.set_file(source)
            self._refresh_sibling_navigation()
            self._page_size_label.setText(tr("页面：正在转换"))
            self._page_number_label.setText(tr("页码：—"))
            self._zoom_label.setText(tr("缩放：—"))
            self._updated_label.setText(tr("更新时间：—"))
            self.setWindowTitle(f"{APP_NAME} — {source.name}")
            self._reload_action.setEnabled(True)
            self._save_png_action.setEnabled(True)
            self._save_pdf_action.setEnabled(True)
            self._save_postscript_action.setEnabled(True)
            self._previous_page_action.setEnabled(False)
            self._next_page_action.setEnabled(False)
            self._set_transform_actions_enabled(True)
            self._select_text_action.setEnabled(source.suffix.lower() in {".eps", ".ps", ".pdf"})
            self._view.text_edit_enabled = self._select_text_action.isEnabled()
            self._select_text_action.blockSignals(True)
            self._select_text_action.setChecked(self._select_text_action.isEnabled() and self._config.auto_select_text)
            self._select_text_action.blockSignals(False)
            self._view.set_text_selection_mode(self._select_text_action.isChecked())
            self._file_info_action.setEnabled(True)
            self._save_edits_action.setEnabled(True)
            self.caption_changed.emit()

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
            tr("上一个：{name}", name=self._siblings[self._sibling_index - 1].name)
            if has_previous
            else tr("没有上一个图片文件")
        )
        self._next_file_action.setToolTip(
            tr("下一个：{name}", name=self._siblings[self._sibling_index + 1].name)
            if has_next
            else tr("没有下一个图片文件")
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

    def _navigate_page(self, offset: int) -> None:
        """Move within a multi-page EPS/PS document without reconversion."""
        if self._page_count <= 1:
            return
        if self._view.set_page(self._current_page_index + offset):
            self._apply_current_transforms()

    def _current_transforms(self) -> DocumentTransforms:
        if self._current_file is None:
            return DocumentTransforms()
        return self._document_transforms.setdefault(
            self._current_file, DocumentTransforms()
        )

    def _set_transform_actions_enabled(self, enabled: bool) -> None:
        for action in (
            self._rotate_left_action,
            self._rotate_right_action,
            self._invert_colors_action,
            self._replace_colors_action,
            self._reset_transforms_action,
            self._compare_action,
        ):
            action.setEnabled(enabled)

    def _apply_current_transforms(self) -> None:
        state = self._current_transforms()
        self._invert_colors_action.blockSignals(True)
        self._invert_colors_action.setChecked(state.inverted)
        self._invert_colors_action.blockSignals(False)
        self._view.set_visual_transforms(
            state.rotation_for(self._current_page_index + 1),
            state.inverted,
            state.replacements,
        )
        self._update_history_actions()
        self.caption_changed.emit()
        if self._current_file is not None and self._page_count:
            self.document_state_changed.emit(self._current_file, state.snapshot(), self._current_page_index)

    def _update_history_actions(self):
        history = self._histories.get(self._current_file)
        self._undo_action.setEnabled(bool(history and history.undo_states))
        self._redo_action.setEnabled(bool(history and history.redo_states))

    def _record_adjustment(self, before):
        if self._current_file is not None:
            history = self._histories.setdefault(self._current_file, TransformHistory())
            history.record(before, self._current_transforms().snapshot())
        self._apply_current_transforms()

    def _restore_history(self, redo):
        history = self._histories.get(self._current_file)
        if history is None:
            return
        state = self._current_transforms()
        state.restore((history.redo if redo else history.undo)(state.snapshot()))
        self._apply_current_transforms()

    def _show_comparison(self):
        if self._current_file is None or not self._page_count:
            return
        if self._comparison is not None:
            self._comparison.show()
            self._comparison.raise_()
            self._comparison.activateWindow()
            return
        dialog = ComparisonDialog(
            self._current_file, self._current_transforms().snapshot(), self._current_page_index,
            self._config.ghostscript_path,
            {path: state.snapshot() for path, state in self._document_transforms.items()},
            self._config.background_mode, self._config.background_color, self._config.wheel_action, self,
        )
        dialog.set_candidates(self._host.open_documents() if self._host else [], self._page_count)
        self._comparison = dialog
        self.document_state_changed.connect(dialog.follow_current)
        dialog.error.connect(lambda error: self._diagnostics.record("Comparison", error))
        dialog.finished.connect(lambda _result: self._comparison_finished(dialog))
        dialog.show()

    def _comparison_finished(self, dialog):
        self.document_state_changed.disconnect(dialog.follow_current)
        if self._comparison is dialog:
            self._comparison = None

    def _rotate_page(self, degrees: int) -> None:
        if self._current_file is None or self._page_count < 1:
            return
        state = self._current_transforms()
        before = state.snapshot()
        if self._rotate_all_action.isChecked():
            for page in range(1, self._page_count + 1):
                state.rotate_page(page, degrees)
            message = tr("全部 {count} 页已旋转 {degrees}°", count=self._page_count, degrees=degrees)
        else:
            rotation = state.rotate_page(self._current_page_index + 1, degrees)
            message = tr("当前页已旋转至 {degrees}°", degrees=rotation)
        self._record_adjustment(before)
        self.statusBar().showMessage(message, 2500)

    def _rotation_scope_changed(self, _action: QAction) -> None:
        self._config.rotation_scope = "all" if self._rotate_all_action.isChecked() else "current"
        self._save_config()
        self._update_rotation_scope_button()

    def _update_rotation_scope_button(self) -> None:
        action = self._rotation_scope_group.checkedAction()
        self._rotation_scope_button.setText(action.text())
        self._rotation_scope_button.setToolTip(tr("旋转范围"))

    def _set_inverted(self, inverted: bool) -> None:
        if self._current_file is None:
            return
        state = self._current_transforms()
        before = state.snapshot()
        state.inverted = bool(inverted)
        self._record_adjustment(before)

    def _show_color_replacements(self) -> None:
        if self._current_file is None:
            return
        state = self._current_transforms()
        before = state.snapshot()
        frame = VideoFrameSource(self._current_file, self._current_page_index + 1)
        exporter = VideoExporter(self._renderer)
        from document_palette import vector_palette
        pdf, page_index = self._current_pdf, self._current_page_index
        dialog = ColorReplacementDialog(
            state.replacements, self,
            preview_loader=lambda cancel: exporter.read_original(frame, 72, cancel, 900),
            inverted=state.inverted, rotation=state.rotation_for(frame.page_number),
            background_mode=self._config.background_mode,
            background_color=self._config.background_color,
            palette_loader=(lambda: vector_palette(pdf, page_index)) if pdf else None,
            default_tolerance=self._config.color_tolerance,
        )
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            state.replacements = dialog.replacements()
        finally:
            dialog.close()
            dialog.deleteLater()
        self._record_adjustment(before)

    def _reset_transforms(self) -> None:
        if self._current_file is None:
            return
        before = self._current_transforms().snapshot()
        self._document_transforms[self._current_file] = DocumentTransforms()
        self._record_adjustment(before)
        self.statusBar().showMessage(tr("已重置当前文件的图像调整"), 2500)

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
        try:
            metadata=json.loads(str(self._settings.value("recentFileMetadata","{}")))
            if not isinstance(metadata,dict):metadata={}
        except (TypeError,ValueError,json.JSONDecodeError):
            metadata={}
        try:size=source.stat().st_size
        except OSError:size=None
        metadata[normalized]={"opened":datetime.now().isoformat(timespec="seconds"),"size":size}
        valid=set(files[:self.MAX_RECENT_FILES])
        self._settings.setValue("recentFileMetadata",json.dumps(
            {path:data for path,data in metadata.items() if path in valid},ensure_ascii=False))
        self._update_recent_menu()
        if self._host is not None:
            self._host.controller.refresh_recent_files()

    def _remove_recent_file(self, filename: str) -> None:
        self._settings.setValue(
            "recentFiles", [item for item in self._recent_files() if item != filename]
        )
        try:
            metadata=json.loads(str(self._settings.value("recentFileMetadata","{}")))
        except (TypeError,ValueError,json.JSONDecodeError):
            metadata={}
        if isinstance(metadata,dict):
            metadata.pop(filename,None)
            self._settings.setValue("recentFileMetadata",json.dumps(metadata,ensure_ascii=False))
        self._update_recent_menu()
        if self._host is not None:
            self._host.controller.refresh_recent_files()

    def _update_recent_menu(self) -> None:
        self._recent_menu.clear()
        files = self._recent_files()
        try:
            metadata=json.loads(str(self._settings.value("recentFileMetadata","{}")))
            if not isinstance(metadata,dict):metadata={}
        except (TypeError,ValueError,json.JSONDecodeError):
            metadata={}
        entries=[]
        for filename in files:
            data=metadata.get(filename,{})
            path=Path(filename)
            try:size=path.stat().st_size
            except OSError:size=data.get("size")
            entries.append({"path":filename,"size":size,"opened":data.get("opened","")})
        self._welcome.set_recent_files(entries, self._config.home_recent)
        if not files:
            placeholder = self._recent_menu.addAction(tr("（暂无最近文件）"))
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
            self.show_nonfatal_error(
                tr("最近文件不可用"), tr("文件已不存在：\n{path}", path=filename)
            )
            self._remove_recent_file(filename)
            return
        self.request_open(filename)

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
                page_index=self._current_page_index,
            )
        except VectorPreviewError as error:
            self._renderer.cache.release(result.pdf_path)
            self._handle_preview_error(request, error)
            return
        self._apply_current_transforms()
        self._current_pdf = result.pdf_path
        self._edit_text_action.setEnabled(result.source.suffix.lower() in {".eps", ".ps", ".pdf"})
        self._add_recent_file(result.source)
        self._automatic_failure_count = 0
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._last_updated_timestamp = timestamp
        self._updated_label.setText(tr("更新时间：{timestamp}", timestamp=timestamp))
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
        message = str(error) or tr("发生未知预览错误。")
        self.statusBar().showMessage(message, 6000)
        if isinstance(error, GhostscriptNotFoundError):
            if not request.automatic:
                self.show_nonfatal_error(tr("未找到 Ghostscript"), message)
            return
        if request.automatic:
            self._automatic_failure_count += 1
            if self._automatic_failure_count <= 5:
                QTimer.singleShot(500, lambda req=request: self._retry_preview(req))
            return
        title = (
            tr("文件无法解析")
            if isinstance(error, EpsRenderError)
            else tr("预览失败")
        )
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
        initial_output = self._current_file.with_suffix(".png")
        if self._page_count > 1:
            initial_output = initial_output.with_name(
                f"{initial_output.stem}_page{self._current_page_index + 1}.png"
            )
        dialog = PngExportDialog(
            initial_output,
            self._config.export_dpi,
            page_count=self._page_count,
            parent=self,
            all_pages=self._config.png_all_pages,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        target, dpi, all_pages = dialog.get_values()
        output = (
            target.parent / f"{target.stem}_pages" if all_pages else target
        )
        if output.exists():
            if all_pages:
                self.show_nonfatal_error(
                    tr("PNG 导出失败"),
                    tr("目标文件夹已存在，请更换文件名：\n{path}", path=output),
                )
                return
            answer = QMessageBox.question(
                self,
                tr("覆盖 PNG 文件"),
                tr("文件已存在，是否覆盖？\n{path}", path=output),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_export(
            ExportRequest(
                self._current_file,
                output,
                dpi,
                self._config.background_mode,
                self._config.background_color,
                self._current_page_index + 1,
                all_pages,
                self._page_count,
                self._current_transforms().snapshot(),
            )
        )

    def _start_export(self, request: ExportRequest) -> None:
        if self._export_thread is not None:
            self.statusBar().showMessage(tr("已有 PNG 导出任务正在进行。"), 4000)
            return
        self._save_png_action.setEnabled(False)
        self.statusBar().showMessage(tr("正在导出 {dpi} DPI PNG…", dpi=request.dpi))
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
        self.statusBar().showMessage(tr("PNG 已保存：{path}", path=output), 6000)
        QMessageBox.information(
            self, tr("PNG 导出完成"), tr("已保存：\n{path}", path=output)
        )

    @pyqtSlot(object)
    def _on_export_failed(self, failure: ExportFailure) -> None:
        if self._closing or isinstance(failure.error, EpsRenderCancelledError):
            return
        message = str(failure.error) or tr("PNG 导出失败。")
        self.statusBar().showMessage(message, 6000)
        title = (
            tr("未找到 Ghostscript")
            if isinstance(failure.error, GhostscriptNotFoundError)
            else tr("PNG 导出失败")
        )
        self.show_nonfatal_error(title, message)

    def _on_export_thread_finished(self, thread: QThread) -> None:
        if thread is not self._export_thread:
            return
        self._export_thread = None
        self._export_worker = None
        if not self._closing:
            self._save_png_action.setEnabled(self._current_file is not None)

    # ----- Vector PDF export ----------------------------------------------

    def _show_pdf_export_dialog(self) -> None:
        if self._current_file is None:
            return
        initial_output = self._current_file.with_name(f"{self._current_file.stem}_adjusted.pdf")
        filename, _ = QFileDialog.getSaveFileName(
            self,
            tr("另存为 PDF"),
            str(initial_output),
            tr("PDF 文件 (*.pdf)"),
        )
        if not filename:
            return
        target = Path(filename).expanduser()
        if target.suffix.lower() != ".pdf":
            target = target.with_suffix(".pdf")
        target = target.resolve()
        if target.exists():
            answer = QMessageBox.question(
                self,
                tr("覆盖 PDF 文件"),
                tr("文件已存在，是否覆盖？\n{path}", path=target),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._prepare_document_export(target)

    def _show_postscript_export_dialog(self) -> None:
        if self._current_file is None:
            return
        initial_suffix = (
            self._current_file.suffix
            if self._page_count == 1
            and self._current_file.suffix.lower() in {".eps", ".ps"}
            else ".ps"
        )
        initial_output = self._current_file.with_name(
            f"{self._current_file.stem}_adjusted{initial_suffix}"
        )
        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            tr("另存为 EPS/PS"),
            str(initial_output),
            tr("PostScript 文件 (*.ps);;EPS 文件 (*.eps)"),
        )
        if not filename:
            return
        target = Path(filename).expanduser()
        if target.suffix.lower() not in {".eps", ".ps"}:
            target = target.with_suffix(
                ".eps" if "*.eps" in selected_filter.lower() else ".ps"
            )
        self._prepare_document_export(target.resolve())

    def _prepare_document_export(self, target: Path) -> None:
        if self._current_file is None:
            return
        if target == self._current_file:
            self.show_nonfatal_error(
                tr("无法导出"), tr("输出文件不能覆盖当前打开的源文件。")
            )
            return
        if target.suffix.lower() == ".eps" and self._page_count > 1:
            QMessageBox.information(
                self,
                tr("EPS 仅支持单页"),
                tr("标准 EPS 只能包含一页，因此将导出当前显示的第 {page} 页。", page=self._current_page_index + 1),
            )
        if target.exists():
            answer = QMessageBox.question(
                self,
                tr("覆盖输出文件"),
                tr("文件已存在，是否覆盖？\n{path}", path=target),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        transforms = self._current_transforms().snapshot()
        dpi = self._config.fallback_dpi
        self._start_pdf_export(
            PdfExportRequest(
                self._current_file,
                target,
                transforms,
                self._page_count,
                self._current_page_index + 1,
                dpi,
                self._config.background_mode,
                self._config.background_color,
            )
        )

    def _start_pdf_export(self, request: PdfExportRequest) -> None:
        if self._pdf_export_thread is not None:
            self.statusBar().showMessage(tr("已有文档导出任务正在进行。"), 4000)
            return
        self._save_pdf_action.setEnabled(False)
        self._save_postscript_action.setEnabled(False)
        self.statusBar().showMessage(tr("正在导出文档…"))
        thread = QThread(self)
        worker = PdfExportWorker(self._renderer, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_pdf_export_succeeded)
        worker.failed.connect(self._on_pdf_export_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._on_pdf_export_thread_finished(current)
        )
        thread.finished.connect(thread.deleteLater)
        self._pdf_export_thread = thread
        self._pdf_export_worker = worker
        thread.start()

    @pyqtSlot(object)
    def _on_pdf_export_succeeded(self, output: Path) -> None:
        if self._closing:
            return
        self.statusBar().showMessage(tr("文档已保存：{path}", path=output), 6000)
        QMessageBox.information(
            self, tr("文档导出完成"), tr("已保存：\n{path}", path=output)
        )

    @pyqtSlot(object)
    def _on_pdf_export_failed(self, failure: PdfExportFailure) -> None:
        if self._closing or isinstance(failure.error, EpsRenderCancelledError):
            return
        message = str(failure.error) or tr("文档导出失败。")
        self.statusBar().showMessage(message, 6000)
        title = (
            tr("未找到 Ghostscript")
            if isinstance(failure.error, GhostscriptNotFoundError)
            else tr("文档导出失败")
        )
        self.show_nonfatal_error(title, message)

    def _on_pdf_export_thread_finished(self, thread: QThread) -> None:
        if thread is not self._pdf_export_thread:
            return
        self._pdf_export_thread = None
        self._pdf_export_worker = None
        if not self._closing:
            self._save_pdf_action.setEnabled(self._current_file is not None)
            self._save_postscript_action.setEnabled(self._current_file is not None)

    # ----- Folder sequence video/GIF export ------------------------------

    def _show_video_dialog(self) -> None:
        if self._video_thread is not None:
            self.statusBar().showMessage(tr("已有视频生成任务正在进行。"), 4000)
            return
        saved_folder = self._settings.value("lastVideoFolder", "")
        initial_folder = (
            self._current_file.parent
            if self._current_file is not None
            else Path(str(saved_folder))
            if saved_folder
            else Path.home()
        )
        snapshots = {source: state for _name, source, state, _page in
                     (self._host.open_documents() if self._host else [])}
        snapshots.update({
            path: state.snapshot()
            for path, state in self._document_transforms.items()
        })
        dialog = VideoCreationDialog(
            initial_folder,
            self._renderer,
            transforms_by_source=snapshots,
            parent=self,
            current_file=self._current_file,
        )
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            request = dialog.request()
        finally:
            # Release the frame list and cached image when this modal closes.
            dialog.deleteLater()
        if request.target.exists():
            answer = QMessageBox.question(
                self,
                tr("覆盖输出文件"),
                tr("文件已存在，是否覆盖？\n{path}", path=request.target),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        if request.sources:
            first_source = request.sources[0]
            first_path = getattr(first_source, "path", first_source)
            self._settings.setValue("lastVideoFolder", str(Path(first_path).parent))
        self._start_video_export(request)

    def _start_video_export(self, request: VideoExportRequest) -> None:
        self._make_video_action.setEnabled(False)
        progress = QProgressDialog(
            tr("正在准备视频帧…"),
            tr("取消"),
            0,
            len(request.sources) + 1,
            self,
        )
        progress.setWindowTitle(tr("制作视频"))
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
        self.statusBar().showMessage(tr("正在生成视频…"))
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
        self.statusBar().showMessage(tr("视频已保存：{path}", path=output), 6000)
        QMessageBox.information(
            self, tr("视频生成完成"), tr("已保存：\n{path}", path=output)
        )

    @pyqtSlot(object)
    def _on_video_failed(self, error: Exception) -> None:
        if self._video_progress is not None:
            self._video_progress.close()
        if self._closing or isinstance(error, VideoExportCancelled):
            if not self._closing:
                self.statusBar().showMessage(tr("视频生成已取消。"), 4000)
            return
        message = str(error) or tr("视频生成失败。")
        self.statusBar().showMessage(message, 6000)
        self.show_nonfatal_error(tr("视频生成失败"), message)

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

    def _retranslate_ui(self) -> None:
        self._welcome.retranslate()
        action_texts = (
            (self._edit_text_action, "编辑文字…"),
            (self._save_edits_action, "保存编辑记录"),
            (self._file_info_action, "文件信息"),
            (self._select_text_action, "自动选择文本"),
            (self._copy_text_action, "复制选中文本"),
            (self._customize_toolbar_action, "自定义工具栏"),
            (self._open_action, "打开图片(&O)…"),
            (self._reload_action, "重新加载(&R)"),
            (self._save_png_action, "另存为 PNG(&S)…"),
            (self._save_pdf_action, "另存为 PDF(&D)…"),
            (self._save_postscript_action, "另存为 EPS/PS(&E)…"),
            (self._make_video_action, "制作视频/动图(&V)…"),
            (self._settings_action, "设置(&P)…"),
            (self._exit_action, "退出(&X)"),
            (self._zoom_in_action, "放大(&I)"),
            (self._zoom_out_action, "缩小(&O)"),
            (self._fit_action, "适应窗口(&F)"),
            (self._auto_refresh_action, "自动刷新(&A)"),
            (self._previous_file_action, "上一个文件(&P)"),
            (self._next_file_action, "下一个文件(&N)"),
            (self._previous_page_action, "上一页(&U)"),
            (self._next_page_action, "下一页(&D)"),
            (self._rotate_left_action, "向左旋转 90°(&L)"),
            (self._rotate_right_action, "向右旋转 90°(&R)"),
            (self._rotate_current_action, "仅当前页"),
            (self._rotate_all_action, "全部页面"),
            (self._invert_colors_action, "反转颜色(&I)"),
            (self._replace_colors_action, "替换颜色(&C)…"),
            (self._reset_transforms_action, "重置图像调整(&T)"),
            (self._undo_action, "撤销图像调整"),
            (self._redo_action, "重做图像调整"),
            (self._check_updates_action, "检查更新(&U)…"),
            (self._diagnostics_action, "诊断信息…"),
            (self._compare_action, "并排比较…"),
            (self._about_action, "关于(&A)"),
        )
        for action, source in action_texts:
            action.setText(tr(source))
            action.setToolTip(tr(source).replace("&", ""))
        self._file_menu.setTitle(tr("文件(&F)"))
        self._recent_menu.setTitle(tr("最近打开文件"))
        self._view_menu.setTitle(tr("查看(&V)"))
        self._image_menu.setTitle(tr("图像(&I)"))
        self._export_menu.setTitle(L("导出", "Export"))
        self._preferences_menu.setTitle("Settings")
        self._settings_action.setText("Settings · 设置…")
        for action, zh, en in self._settings_sections:
            action.setText(L(zh,en))
        self._settings_sections[0][0].setText("界面语言 / Language…")
        self._rotation_scope_menu.setTitle(tr("旋转范围"))
        self._update_rotation_scope_button()
        self._help_menu.setTitle(tr("帮助(&H)"))
        self._toolbar.setWindowTitle(tr("快捷工具"))
        self._update_recent_menu()

        if self._current_file is None:
            self._filename_label.setText(tr("未打开文件"))
            self._page_size_label.setText(tr("页面：—"))
            self._page_number_label.setText(tr("页码：—"))
            self._zoom_label.setText(tr("缩放：—"))
            self._updated_label.setText(tr("更新时间：—"))
            self.setWindowTitle(APP_NAME)
        else:
            self._refresh_sibling_navigation()
            page_size = self._view.page_size_points()
            if page_size is not None:
                self._update_page_size_status(*page_size)
            self._on_page_changed(self._current_page_index, self._page_count)
            self._update_zoom_status(abs(self._view.transform().m11()) * 100.0)
            self._updated_label.setText(
                tr("更新时间：{timestamp}", timestamp=self._last_updated_timestamp)
                if self._last_updated_timestamp
                else tr("更新时间：—")
            )
            self.setWindowTitle(f"{APP_NAME} — {self._current_file.name}")

    def _show_settings(self, section=None) -> None:
        dialog = SettingsDialog(self._config, self, self._toolbar_options)
        if isinstance(section,str):
            dialog.select_section(section)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            dialog.deleteLater()
            return
        updated = dialog.get_config()
        if updated.ghostscript_path:
            executable = Path(updated.ghostscript_path).expanduser()
            if not executable.is_file():
                self.show_nonfatal_error(
                    tr("Ghostscript 路径无效"),
                    tr("找不到指定的 Ghostscript 程序：\n{path}", path=executable),
                )
                return

        try:
            self._config_manager.save(updated)
        except OSError as error:
            self.show_nonfatal_error(tr("设置"),str(error))
            return
        if self._host is not None:
            self._host.controller.apply_settings(updated)
        else:
            self._apply_config(updated)
        self.statusBar().showMessage(tr("设置已保存"),2500)
        if dialog.requested_tool:
            action = self._toolbar_options.get(dialog.requested_tool)
            if action is not None and action.isEnabled():
                QTimer.singleShot(0,action.trigger)
        dialog.deleteLater()

    def _apply_config(self, updated):
        previous = self._config
        updated = AppConfig.from_mapping(updated.__dict__)
        ghostscript_changed = updated.ghostscript_path != previous.ghostscript_path
        refresh_just_enabled = updated.auto_refresh and not previous.auto_refresh
        language_changed = updated.language != previous.language
        self._config = updated
        self._renderer.set_ghostscript_path(updated.ghostscript_path)
        self._monitor.set_refresh_interval(updated.refresh_interval)
        self._monitor.set_enabled(updated.auto_refresh)
        self._view.set_page_background(
            updated.background_mode,
            updated.background_color,
        )
        self._view.set_wheel_action(updated.wheel_action)
        if self._comparison is not None:
            for name in ("linked", "locked", "follow"):
                getattr(self._comparison, "_" + name).setChecked(getattr(updated, "compare_" + name))
            for pane in (self._comparison.left, self._comparison.right):
                pane.view.set_page_background(updated.background_mode, updated.background_color)
                pane.view.set_wheel_action(updated.wheel_action)
        self._auto_refresh_action.blockSignals(True)
        self._auto_refresh_action.setChecked(updated.auto_refresh)
        self._auto_refresh_action.blockSignals(False)
        self._select_text_action.blockSignals(True)
        self._select_text_action.setChecked(updated.auto_select_text)
        self._select_text_action.blockSignals(False)
        self._view.set_text_selection_mode(updated.auto_select_text)
        self._rotation_scope_group.blockSignals(True)
        (self._rotate_all_action if updated.rotation_scope == "all" else self._rotate_current_action).setChecked(True)
        self._rotation_scope_group.blockSignals(False)
        self._refresh_toolbar()
        set_language(updated.language)
        self._retranslate_ui()

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
                tr("自动刷新已开启") if enabled else tr("自动刷新已关闭"), 2500
            )
        if enabled and not was_enabled and self._current_file is not None:
            self._generation += 1
            self._queue_preview(
                PreviewRequest(self._current_file, self._generation, True, False)
            )

    def _save_config(self) -> bool:
        try:
            self._config_manager.save(self._config)
            if self._host is not None:
                self._host.controller.apply_settings(self._config,exclude=self)
        except OSError as error:
            self.statusBar().showMessage(
                tr("无法保存 config.json：{error}", error=error), 6000
            )
            return False
        return True

    @pyqtSlot(float)
    def _update_zoom_status(self, percent: float) -> None:
        self._zoom_label.setText(tr("缩放：{percent:.0f}%", percent=percent))

    @pyqtSlot(float, float)
    def _update_page_size_status(self, width: float, height: float) -> None:
        self._page_size_label.setText(
            tr("页面：{width:.1f} × {height:.1f} pt", width=width, height=height)
        )

    @pyqtSlot(int, int)
    def _on_page_changed(self, page_index: int, page_count: int) -> None:
        self._current_page_index = max(0, page_index)
        self._page_count = max(0, page_count)
        if self._page_count <= 0:
            self._page_number_label.setText(tr("页码：—"))
            self._previous_page_action.setEnabled(False)
            self._next_page_action.setEnabled(False)
            return
        self._page_number_label.setText(
            tr(
                "页码：{current}/{total}",
                current=self._current_page_index + 1,
                total=self._page_count,
            )
        )
        self._previous_page_action.setEnabled(self._current_page_index > 0)
        self._next_page_action.setEnabled(
            self._current_page_index < self._page_count - 1
        )

    @pyqtSlot(str)
    def _on_vector_render_error(self, message: str) -> None:
        self._diagnostics.record("Preview", message, self._diagnostic_context())
        self.statusBar().showMessage(message, 6000)

    def _show_about(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle(tr("关于 {app}", app=APP_NAME))
        dialog.setMinimumSize(560, 430)
        root = QVBoxLayout(dialog)
        content = QTextBrowser(dialog)
        content.setOpenExternalLinks(True)
        content.setHtml(
            f"<h2>{APP_NAME}</h2>"
            f"<p><b>{tr('版本 {version}', version=APP_VERSION)}</b></p>"
            f"<p>{tr('用于快速查看 EPS/PS/PDF/PNG/JPG，并实时刷新当前文件。')}</p>"
            f"<h3>{tr('使用要点')}</h3>"
            f"<ul><li>{tr('打开或拖入支持的图片；文件重新生成后会自动刷新。')}</li>"
            f"<li>{tr('左右方向键切换相邻文件，上下方向键切换多页文档。')}</li>"
            f"<li>{tr('滚轮行为可在设置中选择；Ctrl+滚轮始终可缩放。')}</li>"
            f"<li>{tr('可旋转、反转或替换颜色，并将调整结果导出为 PNG/PDF/PS/EPS。')}</li>"
            f"<li>{tr('Ctrl+Z 撤销图像调整；调色窗口提供实时预览和原图对照。')}</li>"
            f"<li>{tr('Ctrl+S 保存旋转和颜色编辑记录；关闭未保存的文件会提示。')}</li>"
            f"<li>{tr('可在设置中选择新窗口或标签页打开；查看菜单支持自定义工具栏和选择文本。')}</li>"
            f"<li>{tr('文字处拖动选择文本，空白处拖动平移；转为路径的文字不支持选择。')}</li>"
            f"<li>{tr('可并排锁定参考图比较；制作视频前可试播并查看预计时长。')}</li>"
            f"<li>{tr('多页文档可逐页导出 PNG，或将所有页面和相邻图片制作成 MP4/GIF。')}</li></ul>"
            f"<h3>{tr('作者')}</h3>"
            "<p>Zhentong Li<br>eternitylzt@gmail.com</p>"
            f"<p><b>{tr('项目主页')}：</b> "
            f"<a href=\"{PROJECT_URL}\">{PROJECT_URL}</a></p>"
        )
        root.addWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button is not None:
            close_button.setText(tr("关闭"))
        buttons.rejected.connect(dialog.reject)
        root.addWidget(buttons)
        dialog.exec()

    def _check_for_updates(self) -> None:
        """Start a single manual GitHub lookup without blocking the interface."""
        if self._update_thread is not None:
            return
        self._check_updates_action.setEnabled(False)
        self.statusBar().showMessage(tr("正在检查更新…"))

        thread = QThread(self)
        worker = UpdateCheckWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_update_check_succeeded)
        worker.failed.connect(self._on_update_check_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(
            lambda current=thread: self._on_update_check_finished(current)
        )
        self._update_thread = thread
        self._update_worker = worker
        thread.start()

    @pyqtSlot(object)
    def _on_update_check_succeeded(self, release: ReleaseInfo) -> None:
        if self._closing:
            return
        self.statusBar().clearMessage()
        if not is_newer_version(release.version, APP_VERSION):
            QMessageBox.information(
                self,
                tr("检查更新"),
                tr("当前已是最新版（{version}）。", version=APP_VERSION),
            )
            return

        message = QMessageBox(self)
        message.setIcon(QMessageBox.Icon.Information)
        message.setWindowTitle(tr("发现新版本"))
        message.setText(
            tr(
                "发现 EPS Live Viewer {latest}。\n当前版本：{current}",
                latest=release.version,
                current=APP_VERSION,
            )
        )
        open_button = message.addButton(
            tr("打开下载页面"), QMessageBox.ButtonRole.AcceptRole
        )
        message.addButton(QMessageBox.StandardButton.Close)
        message.exec()
        if message.clickedButton() is open_button:
            QDesktopServices.openUrl(QUrl(release.url))

    @pyqtSlot(object)
    def _on_update_check_failed(self, error: Exception) -> None:
        if self._closing:
            return
        self.statusBar().clearMessage()
        detail = str(error).strip() or tr("无法连接 GitHub。")
        QMessageBox.warning(
            self,
            tr("检查更新失败"),
            tr("无法检查更新，请检查网络连接后重试。\n\n{error}", error=detail),
        )

    def _on_update_check_finished(self, thread: QThread) -> None:
        if thread is not self._update_thread:
            return
        self._update_thread = None
        self._update_worker = None
        if not self._closing:
            self._check_updates_action.setEnabled(True)

    def show_nonfatal_error(self, title: str, message: str) -> None:
        if "Ghostscript" in title and self._renderer.ghostscript_path is None:
            self._show_ghostscript_help(message)
            return
        context = self._diagnostic_context()
        self._diagnostics.record(title, message, context)
        box = QMessageBox(QMessageBox.Icon.Warning, title, message,
                          QMessageBox.StandardButton.Close, self)
        box.setDetailedText(self._diagnostics.report(context, self._renderer.ghostscript_path))
        box.exec()

    def _show_ghostscript_help(self, message):
        from i18n import bilingual as L
        if self._config.suppress_ghostscript_help:
            QMessageBox.warning(self, tr("未找到 Ghostscript"), message)
            return
        box = QMessageBox(QMessageBox.Icon.Warning, tr("未找到 Ghostscript"), "", parent=self)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(L("EPS/PS 预览及 PostScript 导出需要 Ghostscript。安装后重新打开文件，或在设置中指定路径。",
                      "EPS/PS preview and PostScript export require Ghostscript. Install it and reopen the file, or set its path in Settings.")
                    + '<br><br><a href="https://ghostscript.com/releases/gsdnld.html">Download Ghostscript</a>')
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        for label in box.findChildren(QLabel):
            label.setOpenExternalLinks(True)
        check = QCheckBox(L("不再显示安装指引", "Do not show installation guidance again"))
        box.setCheckBox(check)
        settings = box.addButton(tr("设置(&P)…"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Close)
        box.exec()
        self._config.suppress_ghostscript_help = check.isChecked()
        self._save_config()
        if box.clickedButton() == settings:
            self._show_settings()

    def _diagnostic_context(self):
        state = self._current_transforms().snapshot()
        return {"file": str(self._current_file or ""),
                "page": self._current_page_index + 1, "page_count": self._page_count,
                "preview_generation": self._generation,
                "rotation": state.rotation_for(self._current_page_index + 1),
                "page_rotations": state.page_rotations, "inverted": state.inverted,
                "replacements": [vars(mapping) for mapping in state.replacements],
                "auto_refresh": self._config.auto_refresh,
                "export_dpi": self._config.export_dpi}

    def _show_diagnostics(self):
        dialog = DiagnosticsDialog(self._diagnostics, self._diagnostic_context(),
                                   self._renderer.ghostscript_path, self)
        try:
            dialog.exec()
        finally:
            dialog.close()
            dialog.deleteLater()

    def report_unhandled_exception(self, error):
        self._diagnostics.record("Unhandled exception", error, self._diagnostic_context())
        self.show_nonfatal_error(tr("操作未完成"), str(error))

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
                self.request_open(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if not self._discard_on_close and not self.confirm_save_changes():
            event.ignore()
            return
        if self._comparison is not None and not self._comparison.close():
            event.ignore()
            return
        self._closing = True
        self._monitor.clear()
        self._pending_preview_request = None
        self._cancel_active_preview()
        if self._export_worker is not None:
            self._export_worker.cancel()
        if self._pdf_export_worker is not None:
            self._pdf_export_worker.cancel()
        if self._video_worker is not None:
            self._video_worker.cancel()

        for thread in (
            self._preview_thread,
            self._export_thread,
            self._pdf_export_thread,
            self._video_thread,
            self._update_thread,
        ):
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
                self.statusBar().showMessage(
                    tr("后台任务尚未结束，请稍后再次关闭。"), 5000
                )
                return

        if not self._view.close():
            self._closing = False
            event.ignore()
            return
        self._renderer.cache.release(self._current_pdf)
        self._renderer.cache.cleanup()
        super().closeEvent(event)
