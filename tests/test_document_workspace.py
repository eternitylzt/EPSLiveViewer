"""Document persistence, independent tabs, selection, and actual video frames."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch, PropertyMock

from PyQt6 import sip
from PyQt6.QtCore import QEvent, QLockFile, QPointF, QSettings, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPdfWriter
from PyQt6.QtPdf import QPdfDocument
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtTest import QTest

from animation_preview import AnimationPreviewDialog
from config import AppConfig, ConfigManager
from document_state import load_state, save_state, state_path
from image_transforms import TransformSnapshot, apply_page_transforms
from eps_renderer import EpsRenderer
from video_creator import VideoExporter, VideoExportRequest, VideoFrameSource
from video_dialog import VideoCreationDialog
from workspace import DesktopController, OpenRequestServer

APP = QApplication.instance() or QApplication([])


def wait_for(predicate, seconds=20):
    deadline = time.monotonic() + seconds
    while not predicate():
        APP.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for document state")
        time.sleep(.005)
    APP.processEvents()


def digest(image):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return hashlib.sha256(image.constBits().asstring(image.sizeInBytes())).hexdigest()


class DocumentWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eps_workspace_")
        self.root = Path(self.temp.name).resolve()
        APP.setOrganizationName("EPSWorkspaceTests")
        APP.setApplicationName("Test")
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(self.root))
        manager = ConfigManager()
        manager.base_dir, manager.path = self.root, self.root / "config.json"
        manager.save(AppConfig())
        self.controller = DesktopController(manager)
        self.host = self.controller.new_window()
        self.view = self.host.tabs.currentWidget()
        self.png = self.root / "sample.png"
        image = QImage(240, 160, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        self.assertTrue(image.save(str(self.png)))

    def tearDown(self):
        for host in list(self.controller.windows):
            for index in range(host.tabs.count()):
                view = host.tabs.widget(index)
                view._saved_states = {p: s.snapshot() for p, s in view._document_transforms.items()}
            host.close()
        APP.processEvents()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.temp.cleanup()

    def ready(self, view):
        wait_for(lambda: view._current_pdf is not None and view._page_count > 0)

    def test_close_final_tab_returns_home_and_preferences_synchronize(self):
        from dataclasses import replace
        from dialogs import SettingsDialog
        self.view.open_eps(self.png)
        self.ready(self.view)
        other_host = self.controller.new_window(self.png)
        other = other_host.tabs.currentWidget()
        self.ready(other)
        other._rotate_right_action.trigger()
        before = other._current_transforms().snapshot()
        config = replace(self.view._config,home_recent=False,auto_refresh=False,
                         auto_select_text=False,rotation_scope="all",video_fps=7,
                         video_format="gif",text_list_visible=True,toolbar_tools=["open","fit"])
        dialog = SettingsDialog(config,self.view,self.view._toolbar_options)
        self.assertEqual(dialog.get_config(),config)
        self.assertEqual(dialog.tabs.count(),5)
        dialog.reject()
        self.controller.config_manager.save(config)
        self.controller.apply_settings(config)
        for view in (self.view,other):
            self.assertEqual(view._config,config)
            self.assertTrue(view._welcome.recents.isHidden())
            self.assertFalse(view._auto_refresh_action.isChecked())
            self.assertTrue(view._rotate_all_action.isChecked())
            self.assertNotIn(view._zoom_in_action,view._toolbar.actions())
        self.assertEqual(other._current_transforms().snapshot(),before)
        self.host.close_tab(0)
        APP.processEvents()
        self.assertTrue(self.host.isVisible())
        self.assertEqual(self.host.tabs.count(),1)
        home = self.host.tabs.currentWidget()
        self.assertIsNone(home._current_file)
        self.assertIs(home._pages.currentWidget(),home._welcome)
        self.assertEqual(home._config,config)
        self.host.close_tab(0)
        self.assertTrue(self.host.isVisible())

    def test_initial_window_fits_small_desktop_and_recent_activation(self):
        from PyQt6.QtCore import QRect
        from window_geometry import fit_initial_window
        from unittest.mock import Mock
        screen = Mock()
        screen.availableGeometry.return_value = QRect(0,0,1024,728)
        with patch("window_geometry.QGuiApplication.screenAt",return_value=screen):
            fit_initial_window(self.host,1250,850)
        APP.processEvents()
        self.assertLessEqual(self.host.frameGeometry().bottom(),728)
        self.assertLessEqual(self.host.frameGeometry().right(),1024)
        home = self.view._welcome
        home.set_recent_files([str(self.png)])
        self.assertEqual([home.recents.horizontalHeaderItem(i).text() for i in range(4)],
                         ["文件","大小","最近打开时间","文件位置"])
        self.assertEqual(home.recents.item(0,0).text(),"sample.png")
        self.assertIn("B",home.recents.item(0,1).text())
        self.assertEqual(home.recents.item(0,3).text(),str(self.png.parent))
        selected = []
        home.recent_requested.connect(selected.append)
        home.recents.setCurrentCell(0,0)
        home.recents.itemActivated.emit(home.recents.item(0,0))
        opened = self.host.tabs.currentWidget()
        self.ready(opened)
        self.assertEqual(selected,[str(self.png)])
        self.assertEqual(opened._current_file,self.png)
        self.assertIsNone(self.view._current_file)
        self.host.home_button.click()
        self.assertIs(self.host.tabs.currentWidget(),self.view)

    def test_home_has_no_close_and_menu_is_above_tabs(self):
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QTabBar
        self.host.add_document(self.png)
        self.ready(self.host.tabs.currentWidget())
        APP.processEvents()
        bar = self.host.tabs.tabBar()
        self.assertFalse(bar.isTabVisible(0))
        self.assertLessEqual(abs(self.host.home_button.height()-bar.height()),1)
        for side in (QTabBar.ButtonPosition.LeftSide,QTabBar.ButtonPosition.RightSide):
            button = bar.tabButton(0,side)
            self.assertTrue(button is None or not button.isVisible())
        menu_bottom = self.view.menuBar().mapToGlobal(QPoint(0,self.view.menuBar().height())).y()
        self.assertLessEqual(menu_bottom,bar.mapToGlobal(QPoint(0,0)).y())
        self.assertEqual(self.view._preferences_menu.title(),"Settings")
        self.assertEqual(self.view._settings_sections[0][0].text(),"界面语言 / Language…")
        self.host.close_tab(1)
        self.assertEqual(self.host.tabs.count(),1)

    def test_independent_tabs_toolbar_defaults_and_save_cancel(self):
        self.view.open_eps(self.png)
        self.ready(self.view)
        self.host.open_file(self.png, "tabs")
        second = self.host.tabs.currentWidget()
        self.ready(second)
        self.assertEqual(self.host.tabs.count(), 2)
        self.assertEqual(second._config.background_mode, "white")
        self.assertNotIn(second._reload_action, second._toolbar.actions())
        self.assertNotIn(second._rotate_right_action, second._toolbar.actions())
        second._rotate_right_action.trigger()
        self.assertEqual(second._current_transforms().rotation_for(1), 90)
        self.assertEqual(self.view._current_transforms().rotation_for(1), 0)
        self.host.tabs.setCurrentIndex(0)
        QTest.keyClick(self.view._view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        APP.processEvents()
        self.assertEqual(second._current_transforms().rotation_for(1), 90)
        self.host.tabs.setCurrentIndex(1)
        second._view.setFocus()
        self.host.activateWindow()
        APP.processEvents()
        QTest.keyClick(second._view, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
        APP.processEvents()
        self.assertEqual(second._current_transforms().rotation_for(1), 0)
        second._rotate_right_action.trigger()
        second._config.background_mode = "custom"
        second._config.toolbar_tools = ["reload"]
        second._refresh_toolbar()
        self.assertIn(second._reload_action, second._toolbar.actions())
        self.assertEqual(self.view._config.background_mode, "white")
        self.assertNotIn(self.view._reload_action, self.view._toolbar.actions())
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.host.close_tab(1)
        self.assertEqual(self.host.tabs.count(), 2)
        original = self.png.read_bytes()
        self.assertTrue(second.save_edits())
        self.assertFalse(second.is_modified())
        self.assertEqual(original, self.png.read_bytes())
        self.assertEqual(load_state(self.png).rotation_for(1), 90)
        self.host.close_tab(1)
        self.host.open_file(self.png, "tabs")
        third = self.host.tabs.currentWidget()
        self.ready(third)
        self.assertEqual(third._current_transforms().rotation_for(1), 90)
        self.assertEqual(self.view._current_transforms().rotation_for(1), 0)
        self.host.open_file(self.png, "window")
        self.assertEqual(len(self.controller.windows), 2)

    def test_external_process_open_request(self):
        received = []
        router = OpenRequestServer(received.extend)
        router.name += "-" + self.root.name
        router.lock = QLockFile(str(self.root / "open.lock"))
        self.assertTrue(router.listen())
        code = ("from PyQt6.QtWidgets import QApplication; from workspace import OpenRequestServer; "
                "import sys; app=QApplication([]); r=OpenRequestServer(lambda _:None); "
                "r.name=sys.argv[1]; sys.exit(0 if r.forward([sys.argv[2]]) else 2)")
        arguments = ([sys.executable, "--ipc-child", router.name, str(self.png)]
                     if getattr(sys, "frozen", False) else
                     [sys.executable, "-c", code, router.name, str(self.png)])
        process = subprocess.Popen(arguments,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            wait_for(lambda: process.poll() is not None)
            stdout, stderr = process.communicate(timeout=5)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(received, [str(self.png)])
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            router.close()

    def test_pdf_opens_in_independent_tab_without_ghostscript(self):
        source = self.root / "document.pdf"
        writer = QPdfWriter(str(source))
        writer.setResolution(72)
        painter = QPainter(writer)
        painter.drawText(30, 50, "PDF text")
        writer.newPage()
        painter.drawText(30, 50, "Second page")
        painter.end()
        del writer
        with patch.object(EpsRenderer, "ghostscript_path", new_callable=PropertyMock, return_value=None):
            self.view.open_eps(source)
            self.ready(self.view)
            self.assertEqual(self.view._page_count, 2)
            self.assertTrue(self.view._select_text_action.isChecked())
            self.view._next_page_action.trigger()
            self.assertEqual(self.view._current_page_index, 1)
            self.view._invert_colors_action.trigger()
            self.assertTrue(self.view._current_transforms().inverted)
            self.host.open_file(source, "tabs")
            second = self.host.tabs.currentWidget()
            self.ready(second)
            self.assertFalse(second._current_transforms().inverted)
            self.assertEqual(second._current_page_index, 0)

    def test_multipage_video_matches_preview_and_text_selection(self):
        renderer = self.view._renderer
        if renderer.ghostscript_path is None:
            self.skipTest("Ghostscript is required")
        source = self.root / "pages.ps"
        source.write_text("%!PS-Adobe-3.0\n%%Pages: 3\n"
                          "<< /PageSize [240 160] >> setpagedevice\n"
                          + "".join(f"%%Page: {i} {i}\n{color} setrgbcolor 0 0 240 160 rectfill\n"
                                    f"0 setgray /Helvetica findfont 20 scalefont setfont "
                                    f"20 80 moveto (Frame {i}) show showpage\n"
                                    for i, color in enumerate(("1 0 0", "0 1 0", "0 0 1"), 1)),
                          encoding="ascii")
        self.view.open_eps(source)
        self.ready(self.view)
        self.assertEqual(self.view._page_count, 3)
        self.view._show_comparison()
        comparison = self.view._comparison
        wait_for(lambda: comparison.right.view.has_document())
        self.assertTrue(comparison.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint)
        self.assertEqual(comparison.right.view.current_page_index(), 1)
        selection = self.view._view
        selection.set_text_selection_mode(True)
        text_bounds = selection._active_context.document.getAllText(0).bounds()[0].boundingRect()
        start = selection.mapFromScene(selection._page_item.mapToScene(text_bounds.topLeft()))
        end = selection.mapFromScene(selection._page_item.mapToScene(text_bounds.bottomRight()))
        QTest.mousePress(selection.viewport(), Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(selection.viewport(), end)
        QTest.mouseRelease(selection.viewport(), Qt.MouseButton.LeftButton, pos=end)
        self.assertIn("Frame 1", selection._selection.text())
        # The host desktop may deny clipboard ownership (e.g. remote sessions).
        # Verify the actual mouse selection and the text handed to Qt separately.
        with patch.object(APP.clipboard(), "setText") as copy_text:
            selection.copy_selected_text()
            copy_text.assert_called_once_with("Frame 1")
        frames = tuple(VideoFrameSource(source, page) for page in range(1, 4))
        exporter = VideoExporter(renderer)
        document = QPdfDocument(None)
        document.load(str(self.view._current_pdf))
        try:
            for frame in frames:
                expected = exporter._composite_background(document.render(frame.page_number - 1, QSize(240, 160)), "#FFFFFF")
                self.assertEqual(digest(expected), digest(exporter.read_frame(frame, "#FFFFFF", 72)))
            self.assertEqual(len({digest(exporter.read_frame(f, "#FFFFFF", 72)) for f in frames}), 3)
            snapshots = {source: TransformSnapshot(False, (), ((2, 90),))}
            dialog = VideoCreationDialog(self.root, renderer, snapshots, current_file=source)
            self.assertEqual([f.page_number for f in dialog.selected_frames()], [1, 2, 3])
            self.assertEqual(dialog.selected_frames()[1].transforms.rotation_for(2), 90)
            dialog.close()
            snapshot = TransformSnapshot(False, (), ((2, 90),))
            rotated = VideoFrameSource(source, 2, snapshot)
            expected = apply_page_transforms(exporter.read_frame(frames[1], "#FFFFFF", 72), snapshot, 2)
            self.assertEqual(digest(exporter.read_frame(rotated, "#FFFFFF", 72)), digest(expected))
            request = VideoExportRequest(frames, self.root / "video.mp4", "mp4", 240, 160, 2)
            trial = AnimationPreviewDialog(request, exporter)
            trial.show()
            wait_for(lambda: len(trial._paths) == 3)
            trial._play.setChecked(False)
            self.assertEqual(len({digest(QImage(str(path))) for path in trial._paths}), 3)
            # The clock must advance immediately; no preparation-time hold.
            with patch("animation_preview.time.monotonic", return_value=10.0):
                trial._play.setChecked(True)
            with patch("animation_preview.time.monotonic", return_value=10.51):
                trial._tick()
            self.assertEqual(trial._slider.value(), 1)
            trial.close()
            exporter.create(request, threading.Event())
            decoded = subprocess.run([str(exporter._ffmpeg_executable()), "-v", "error", "-i",
                                      str(request.target), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                     capture_output=True, timeout=30,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(decoded.returncode, 0, decoded.stderr)
            length = 240 * 160 * 3
            self.assertEqual(len(decoded.stdout), 3 * length)
            for index in range(3):
                # Background corner is a different RGB primary on each page.
                rgb = decoded.stdout[index * length:index * length + 3]
                self.assertEqual(max(range(3), key=lambda c: rgb[c]), index)
        finally:
            document.close()
            sip.delete(document)
            exporter.close()

    def test_user_eps_pages_have_same_orientation_as_main_preview(self):
        original = Path(r"C:\Users\ztli\Desktop\20241001.eps")
        if not original.is_file() or self.view._renderer.ghostscript_path is None:
            self.skipTest("Local user's EPS/Ghostscript unavailable")
        source = self.root / original.name
        shutil.copyfile(original, source)
        self.view.open_eps(source)
        self.ready(self.view)
        exporter = VideoExporter(self.view._renderer)
        expected_document = self.view._view._active_context.document
        try:
            hashes = []
            for page in range(expected_document.pageCount()):
                points = expected_document.pagePointSize(page)
                size = QSize(round(points.width()), round(points.height()))
                expected = exporter._composite_background(expected_document.render(page, size), "#FFFFFF")
                actual = exporter.read_frame(VideoFrameSource(source, page + 1), "#FFFFFF", 72)
                self.assertEqual(actual.size(), expected.size())
                self.assertEqual(digest(actual), digest(expected))
                hashes.append(digest(actual))
            self.assertGreater(len(set(hashes)), 1)
        finally:
            exporter.close()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--ipc-child":
        router = OpenRequestServer(lambda _: None)
        router.name = sys.argv[2]
        raise SystemExit(0 if router.forward([sys.argv[3]]) else 2)
    unittest.main()
