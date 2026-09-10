"""Program entry point for EPS Live Viewer."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from config import ConfigManager
from viewer import MainWindow


def application_icon_path() -> Path:
    """Resolve the icon both in source and in a PyInstaller one-file build."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "resources" / "icon.ico"


def main() -> int:
    # Qt 6 enables high-DPI pixmaps automatically on supported desktop systems.
    app = QApplication(sys.argv)
    app.setApplicationName("EPS Live Viewer")
    app.setOrganizationName("EPSLiveViewer")

    icon_path = application_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow(ConfigManager())
    window.show()

    # Explorer and a command prompt can pass an EPS or PS path as the first argument.
    if len(sys.argv) > 1:
        candidate = Path(sys.argv[1])
        if candidate.is_file():
            window.open_eps(candidate)
        else:
            window.show_nonfatal_error("打开失败", f"找不到文件：{candidate}")
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
