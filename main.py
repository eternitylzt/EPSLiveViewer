"""Program entry point for EPS Live Viewer."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, QTimer, pyqtSignal
from PyQt6.QtGui import QFileOpenEvent, QIcon
from PyQt6.QtWidgets import QApplication

from config import APP_VERSION, ConfigManager
from i18n import tr
from workspace import DesktopController, OpenRequestServer


class EpsApplication(QApplication):
    """Receive document-open events sent by Finder to a macOS app bundle."""

    file_open_requested = pyqtSignal(str)

    def __init__(self, arguments: list[str]) -> None:
        super().__init__(arguments)
        self._pending_file_opens: list[str] = []

    def _queue_file_open(self, filename: str) -> None:
        """Keep early Finder requests and notify the window once it exists."""
        if not filename:
            return
        self._pending_file_opens.append(filename)
        self.file_open_requested.emit(filename)

    def event(self, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() == QEvent.Type.FileOpen and isinstance(event, QFileOpenEvent):
            filename = event.file()
            if filename:
                self._queue_file_open(filename)
                return True
        return super().event(event)

    def take_pending_file_opens(self) -> list[str]:
        pending = list(dict.fromkeys(self._pending_file_opens))
        self._pending_file_opens.clear()
        return pending


def application_icon_path() -> Path:
    """Resolve the icon both in source and in a PyInstaller one-file build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "resources" / "icon.ico"


def main() -> int:
    if sys.argv[1:] == ["--verify-update"]:
        from update_checker import check_latest_release
        print(check_latest_release(timeout=20))
        return 0
    # Qt 6 enables high-DPI pixmaps automatically on supported desktop systems.
    app = EpsApplication(sys.argv)
    app.setApplicationName("EPS Live Viewer")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("EPSLiveViewer")

    icon_path = application_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    controller = DesktopController(ConfigManager())
    startup_arguments = [
        str(Path(argument).expanduser().resolve())
        for argument in sys.argv[1:] if not argument.startswith("-psn_")
    ]
    router = OpenRequestServer(controller.open_files)
    if startup_arguments and router.forward(startup_arguments):
        return 0
    if not router.listen() and startup_arguments and router.forward(startup_arguments):
        return 0
    previous_hook = sys.excepthook
    reporting = False

    def exception_hook(kind, error, tb):
        nonlocal reporting
        if reporting or not isinstance(error, Exception):
            previous_hook(kind, error, tb)
            return
        reporting = True

        def report():
            nonlocal reporting
            try:
                active = controller.active_window
                if active is not None:
                    active.tabs.currentWidget().report_unhandled_exception(error.with_traceback(tb))
                else:
                    previous_hook(kind, error, tb)
            finally:
                reporting = False
        QTimer.singleShot(0, report)

    sys.excepthook = exception_hook
    app.file_open_requested.connect(lambda _filename: controller.open_files(app.take_pending_file_opens()))
    controller.open_files(app.take_pending_file_opens() or startup_arguments)
    try:
        return app.exec()
    finally:
        router.close()
        sys.excepthook = previous_hook


if __name__ == "__main__":
    raise SystemExit(main())
