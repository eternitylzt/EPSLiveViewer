"""Mouse-driven workspace regression checks; run with Cocoa on a real Mac runner.

These tests deliberately click widgets rather than calling QAction.trigger().
EPS_CONTROL_SCREENSHOTS optionally preserves the tested window for inspection.
"""

import os
from pathlib import Path
import tempfile
import time
import unittest

from PyQt6.QtCore import QEvent, QSettings, Qt, QTimer
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog

from config import AppConfig, ConfigManager
from workspace import DesktopController

APP = QApplication.instance() or QApplication([])


def wait_for(predicate, seconds=10):
    deadline = time.monotonic() + seconds
    while not predicate():
        APP.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for desktop interaction")
        QTest.qWait(10)
    APP.processEvents()


class DesktopControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="eps_controls_")
        self.root = Path(self.temp.name).resolve()
        APP.setOrganizationName("EPSDesktopControlTests")
        APP.setApplicationName("Controls")
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(self.root))
        manager = ConfigManager()
        manager.base_dir, manager.path = self.root, self.root / "config.json"
        manager.save(AppConfig(toolbar_tools=["open", "zoom_in", "zoom_out", "invert_colors", "save_png"]))
        self.source = self.root / "controls.png"
        image = QImage(300, 200, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(str(self.source)))
        self.controller = DesktopController(manager)
        self.host = self.controller.new_window(self.source)
        self.view = self.host.tabs.currentWidget()
        self.host.raise_()
        self.host.activateWindow()
        wait_for(lambda: self.view._view.has_document())
        QTest.qWait(150)

    def tearDown(self):
        if APP.activePopupWidget() is not None:
            APP.activePopupWidget().close()
        if APP.activeModalWidget() is not None:
            APP.activeModalWidget().close()
        for host in list(self.controller.windows):
            for i in range(host.tabs.count()):
                view = host.tabs.widget(i)
                view._saved_states = {p: s.snapshot() for p, s in view._document_transforms.items()}
            host.close()
        APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        APP.processEvents()
        self.temp.cleanup()

    def click_toolbar(self, view, action):
        button = view._toolbar.widgetForAction(action)
        self.assertIsNotNone(button)
        self.assertTrue(button.isVisible())
        self.assertTrue(button.isEnabled())
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        APP.processEvents()

    def open_menu(self, view, menu):
        bar = view.menuBar()
        self.assertTrue(bar.isVisible())
        QTest.mouseClick(bar, Qt.MouseButton.LeftButton,
                         pos=bar.actionGeometry(menu.menuAction()).center())
        wait_for(menu.isVisible)

    def test_toolbar_and_menu_mouse_input_across_tabs(self):
        zoom_before = self.view._view.transform().m11()
        self.click_toolbar(self.view, self.view._zoom_in_action)
        self.assertGreater(self.view._view.transform().m11(), zoom_before)
        self.click_toolbar(self.view, self.view._invert_colors_action)
        self.assertTrue(self.view._current_transforms().snapshot().inverted)
        self.open_menu(self.view, self.view._image_menu)
        menu = self.view._image_menu
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton,
                         pos=menu.actionGeometry(self.view._rotate_right_action).center())
        self.assertEqual(self.view._current_transforms().rotation_for(1), 90)
        self.host.add_document(self.source)
        second = self.host.tabs.currentWidget()
        wait_for(lambda: second._view.has_document())
        self.click_toolbar(second, second._invert_colors_action)
        self.click_toolbar(second, second._invert_colors_action)
        self.assertFalse(second._current_transforms().snapshot().inverted)
        self.assertEqual(second._current_transforms().rotation_for(1), 0)
        QTest.mouseClick(self.host.tabs.tabBar(), Qt.MouseButton.LeftButton,
                         pos=self.host.tabs.tabBar().tabRect(0).center())
        self.assertIs(self.host.tabs.currentWidget(), self.view)
        self.click_toolbar(self.view, self.view._invert_colors_action)
        self.assertFalse(self.view._current_transforms().snapshot().inverted)
        screenshots = os.environ.get("EPS_CONTROL_SCREENSHOTS")
        if screenshots:
            folder = Path(screenshots)
            folder.mkdir(parents=True, exist_ok=True)
            self.host.grab().save(str(folder / "desktop-controls.png"))

    def test_window_activation_preserves_open_menu_and_action(self):
        self.open_menu(self.view, self.view._file_menu)
        recent = self.view._recent_menu
        recent.popup(self.view._file_menu.mapToGlobal(
            self.view._file_menu.actionGeometry(recent.menuAction()).topRight()))
        wait_for(recent.isVisible)
        action = recent.actions()[0]
        triggered = []
        action.triggered.connect(lambda: triggered.append(True))
        # macOS can send WindowActivate while a menu is tracking mouse input.
        APP.sendEvent(self.host, QEvent(QEvent.Type.WindowActivate))
        self.assertIn(action, recent.actions(), "Activation replaced an open menu's actions")
        self.assertTrue(recent.isVisible())
        QTest.mouseClick(recent, Qt.MouseButton.LeftButton,
                         pos=recent.actionGeometry(action).center())
        self.assertEqual(triggered, [True])

    def test_file_info_dialog_opens_and_toolbar_works_after_close(self):
        seen = []
        timer = QTimer()
        timer.setInterval(20)

        def close_dialog():
            dialog = APP.activeModalWidget()
            if isinstance(dialog, QDialog):
                seen.append(dialog.windowTitle())
                dialog.reject()

        timer.timeout.connect(close_dialog)
        timer.start()
        # Bound a broken menu/modal path so CI cannot wait indefinitely.
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(lambda: APP.activePopupWidget().close()
                                   if APP.activePopupWidget() else None)
        watchdog.start(5000)
        try:
            self.open_menu(self.view, self.view._file_menu)
            QTest.mouseClick(self.view._file_menu, Qt.MouseButton.LeftButton,
                             pos=self.view._file_menu.actionGeometry(self.view._file_info_action).center())
            self.assertEqual(len(seen), 1)
            self.click_toolbar(self.view, self.view._invert_colors_action)
            self.assertTrue(self.view._current_transforms().snapshot().inverted)
        finally:
            timer.stop()
            watchdog.stop()


if __name__ == "__main__":
    print("Qt platform:", APP.platformName(), flush=True)
    if os.environ.get("EPS_REQUIRE_COCOA") == "1" and APP.platformName() != "cocoa":
        raise SystemExit("Native macOS Cocoa testing is required; offscreen is not accepted")
    unittest.main()
