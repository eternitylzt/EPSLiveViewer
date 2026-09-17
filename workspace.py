"""Independent document windows/tabs and local desktop-open routing."""

import hashlib
import json
from pathlib import Path

from PyQt6.QtCore import QLockFile, QStandardPaths, Qt, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMainWindow, QTabWidget, QTabBar, QToolButton, QStyle, QStackedWidget, QSizePolicy
from PyQt6.QtGui import QAction, QKeySequence, QIcon

from config import APP_NAME
from i18n import set_language, tr
from viewer import MainWindow
from window_geometry import fit_initial_window
from branding import tool_icon


class WorkspaceWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        fit_initial_window(self,1250,850)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabBarAutoHide(False)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideMiddle)
        self.tabs.setStyleSheet("QTabBar::tab { min-width: 100px; max-width: 210px; padding: 7px 14px; margin: 2px 2px 0 0; border-bottom: 3px solid transparent; } QTabBar::tab:selected { border-bottom: 3px solid #20B8AC; background: palette(base); font-weight: 600; } QTabBar::tab:!selected { background: palette(button); }")
        self.home_button = QToolButton()
        self.home_button.setIcon(tool_icon("home",self.palette().color(self.foregroundRole())))
        self.home_button.setToolTip("Home / 首页")
        self.home_button.setAccessibleName("Home")
        self.home_button.setAutoRaise(True)
        tab_height = self.tabs.tabBar().sizeHint().height()
        self.home_button.setFixedSize(max(34,tab_height),max(30,tab_height))
        self.home_button.clicked.connect(self.show_home)
        self.tabs.setCornerWidget(self.home_button,Qt.Corner.TopLeftCorner)
        self._menu_stack = QStackedWidget()
        self._menu_stack.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
        self.setMenuWidget(self._menu_stack)
        self.tabs.currentChanged.connect(self._activated)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.setCentralWidget(self.tabs)
        close = QAction(self)
        close.setShortcut(QKeySequence("Ctrl+W"))
        close.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))
        self.addAction(close)

    def add_document(self, source=None):
        view = MainWindow(self.controller.config_manager, self.tabs)
        view._host = self
        bar = view.menuBar()
        bar.setParent(self._menu_stack)
        view._shared_menu_bar = bar
        self._menu_stack.addWidget(bar)
        # Scope shortcuts to this document, including its menu actions. Hidden
        # tabs must never consume shortcuts belonging to the visible document.
        for action in view.findChildren(QAction):
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            view.addAction(action)
        view._exit_action.triggered.disconnect()
        view._exit_action.triggered.connect(self.close)
        index = self.tabs.addTab(view, tr("未打开文件"))
        view.caption_changed.connect(lambda: self._caption(view))
        self.tabs.setCurrentIndex(index)
        if source is not None:
            view.open_eps(source)
        self._caption(view)
        # Updating the first visible tab can make Qt reactivate it while a
        # second tab is being populated. Keep the newly opened document active.
        self.tabs.setCurrentWidget(view)
        if source is not None:
            QTimer.singleShot(0,self._align_home_button)
        return view

    def _align_home_button(self):
        height=max(30,self.tabs.tabBar().height(),self.tabs.tabBar().sizeHint().height())
        self.home_button.setFixedSize(height,height)

    def show_home(self):
        for index in range(self.tabs.count()):
            if self.tabs.widget(index)._current_file is None:
                self.tabs.setCurrentIndex(index)
                return self.tabs.widget(index)
        view = self.add_document()
        self.tabs.tabBar().moveTab(self.tabs.indexOf(view),0)
        return view

    def _caption(self, view):
        index = self.tabs.indexOf(view)
        if index < 0:
            return
        title = view._current_file.name if view._current_file else tr("首页")
        title += " *" if view.is_modified() else ""
        self.tabs.setTabText(index, title)
        self.tabs.setTabToolTip(index, str(view._current_file or ""))
        bar = self.tabs.tabBar()
        if view._current_file is None:
            for side in (QTabBar.ButtonPosition.LeftSide,QTabBar.ButtonPosition.RightSide):
                button = bar.tabButton(index,side)
                if button is not None:
                    button.hide()
            self.tabs.tabBar().setTabVisible(index,False)
        else:
            self.tabs.tabBar().setTabVisible(index,True)
            self.tabs.setTabIcon(index,QIcon())
            for side in (QTabBar.ButtonPosition.LeftSide,QTabBar.ButtonPosition.RightSide):
                button = bar.tabButton(index,side)
                if button is not None:
                    button.show()
        if index == self.tabs.currentIndex():
            self.setWindowTitle(f"{APP_NAME} — {title}")

    def _activated(self, index):
        view = self.tabs.widget(index)
        if view is not None:
            self._menu_stack.setCurrentWidget(view.menuBar())
            set_language(view._config.language)
            view._retranslate_ui()
            self._caption(view)
            view._view.setFocus()
        self.controller.active_window = self

    def open_file(self, source, mode="tabs"):
        if mode == "tabs":
            self.add_document(source)
        else:
            self.controller.new_window(source)

    def open_documents(self):
        result = []
        for index in range(self.tabs.count()):
            view = self.tabs.widget(index)
            if view._current_file is not None:
                result.append((self.tabs.tabText(index), view._current_file,
                               view._current_transforms().snapshot(), view._current_page_index))
        return result

    def close_tab(self, index):
        view = self.tabs.widget(index)
        if view is not None and view._current_file is None:
            return
        if view is None or not view.close():
            return
        self.tabs.removeTab(index)
        self._menu_stack.removeWidget(view.menuBar())
        view.menuBar().deleteLater()
        view.deleteLater()
        if not self.tabs.count():
            self.add_document()

    def closeEvent(self, event):
        # Ask about every dirty document before stopping any view's workers.
        views = [self.tabs.widget(i) for i in range(self.tabs.count())]
        for view in views:
            if not view.confirm_save_changes():
                event.ignore()
                return
        for view in views:
            view._discard_on_close = True
            if not view.close():
                view._discard_on_close = False
                event.ignore()
                return
        if self in self.controller.windows:
            self.controller.windows.remove(self)
        if self.controller.active_window is self:
            self.controller.active_window = self.controller.windows[-1] if self.controller.windows else None
        super().closeEvent(event)

    def event(self, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.WindowActivate and hasattr(self, "tabs"):
            # Cocoa activates windows while dispatching menu/button input.
            # Rebuilding menus or forcing focus here can cancel that very click
            # (and invalidate actions in an open Recent Files submenu).
            self.controller.active_window = self
            view = self.tabs.currentWidget()
            if view is not None:
                set_language(view._config.language)
        return super().event(event)


class DesktopController:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.windows = []
        self.active_window = None

    def new_window(self, source=None):
        window = WorkspaceWindow(self)
        self.windows.append(window)
        window.add_document(source)
        if self.config_manager.load().start_maximized:
            window.showMaximized()
        else:
            window.show()
        self.active_window = window
        return window

    def apply_settings(self, config, exclude=None):
        for window in self.windows:
            for index in range(window.tabs.count()):
                view = window.tabs.widget(index)
                if view is not exclude:
                    view._apply_config(config)

    def refresh_recent_files(self):
        for window in self.windows:
            for index in range(window.tabs.count()):
                window.tabs.widget(index)._update_recent_menu()

    def open_files(self, filenames):
        mode = self.config_manager.load().open_mode
        for filename in filenames:
            window = self.active_window
            if window is not None and (mode == "tabs" or window.tabs.currentWidget()._current_file is None):
                current = window.tabs.currentWidget()
                if current._current_file is None:
                    window.add_document(filename)
                else:
                    window.add_document(filename)
                window.showNormal() if window.isMinimized() else window.show()
                window.raise_()
                window.activateWindow()
            else:
                self.new_window(filename)
        if not filenames and not self.windows:
            self.new_window()


class OpenRequestServer:
    """One per-user router; file content never leaves the local computer."""
    def __init__(self, on_files):
        suffix = hashlib.sha256(str(Path.home()).encode()).hexdigest()[:16]
        self.name = "EPSLiveViewer-" + suffix
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._connected)
        self._on_files = on_files
        self._sockets = {}
        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
        self.lock = QLockFile(str(Path(folder) / (self.name + ".lock")))

    def forward(self, files):
        socket = QLocalSocket()
        socket.connectToServer(self.name)
        if not socket.waitForConnected(700):
            return False
        socket.write(json.dumps([str(Path(p).resolve()) for p in files]).encode("utf-8") + b"\n")
        if not socket.waitForBytesWritten(1500):
            socket.abort()
            return False
        acknowledged = socket.waitForReadyRead(5000) and bytes(socket.readAll()).strip() == b"OK"
        socket.disconnectFromServer()
        return acknowledged

    def listen(self):
        if not self.lock.tryLock(0):
            return False
        QLocalServer.removeServer(self.name)
        return self.server.listen(self.name)

    def _connected(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._sockets[socket] = bytearray()
            socket.readyRead.connect(lambda current=socket: self._read(current))
            socket.disconnected.connect(lambda current=socket: self._drop(current))
            self._read(socket)

    def _read(self, socket):
        data = self._sockets.get(socket)
        if data is None:
            return
        data.extend(bytes(socket.readAll()))
        if len(data) > 1024 * 1024:
            socket.abort()
            return
        if b"\n" not in data:
            return
        try:
            files = json.loads(bytes(data).split(b"\n", 1)[0])
            if not isinstance(files, list) or not all(isinstance(p, str) for p in files):
                raise ValueError("Invalid file list")
        except (ValueError, UnicodeError):
            socket.abort()
            return
        self._sockets.pop(socket, None)
        socket.write(b"OK\n")
        socket.flush()
        QTimer.singleShot(0, lambda: self._on_files(files))

    def _drop(self, socket):
        self._sockets.pop(socket, None)
        socket.deleteLater()

    def close(self):
        self.server.close()
        self.lock.unlock()
