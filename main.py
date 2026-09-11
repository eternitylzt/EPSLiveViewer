"""Program entry point for EPS Live Viewer."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QEvent, pyqtSignal
from PyQt6.QtGui import QFileOpenEvent, QIcon
from PyQt6.QtWidgets import QApplication

from config import APP_VERSION, ConfigManager
from i18n import tr
from viewer import MainWindow


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
    # Qt 6 enables high-DPI pixmaps automatically on supported desktop systems.
    app = EpsApplication(sys.argv)
    app.setApplicationName("EPS Live Viewer")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("EPSLiveViewer")

    icon_path = application_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow(ConfigManager())
    app.file_open_requested.connect(window.open_eps)
    window.show()

    pending_file_opens = app.take_pending_file_opens()
    if pending_file_opens:
        window.open_eps(pending_file_opens[-1])

    # Explorer and a command prompt can pass an EPS or PS path as the first argument.
    startup_arguments = [
        argument for argument in sys.argv[1:] if not argument.startswith("-psn_")
    ]
    if startup_arguments and not pending_file_opens:
        candidate = Path(startup_arguments[0])
        if candidate.is_file():
            window.open_eps(candidate)
        else:
            window.show_nonfatal_error(
                tr("打开失败"), tr("找不到文件：\n{path}", path=candidate)
            )
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
