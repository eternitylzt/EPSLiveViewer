"""In-memory, user-copied diagnostic reports. No telemetry or background I/O."""

from collections import deque
from datetime import datetime
import json
import platform
import subprocess
import sys
import traceback

from PyQt6.QtCore import PYQT_VERSION_STR, qVersion, QTimer
from PyQt6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from background_tasks import TaskRunner
from config import APP_VERSION
from i18n import tr


class Diagnostics:
    def __init__(self):
        self._events = deque(maxlen=20)

    def record(self, title, error, context=None):
        detail = ("".join(traceback.format_exception(error))
                  if isinstance(error, BaseException) else str(error))
        self._events.append({"time": datetime.now().isoformat(timespec="seconds"),
                             "event": str(title), "context": context or {},
                             "detail": detail[-12000:]})

    def report(self, context, ghostscript=None, probe=False):
        version = tr("未查询")
        if probe and ghostscript:
            try:
                result = subprocess.run(
                    [str(ghostscript), "-version"], capture_output=True, text=True,
                    encoding="utf-8", errors="replace", timeout=4,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                version = (result.stdout or result.stderr).strip()[:1000]
            except (OSError, subprocess.TimeoutExpired) as error:
                version = str(error)
        data = {
            "application": f"EPS Live Viewer {APP_VERSION}",
            # platform.platform() may start an external command on Unix. Keep the
            # non-probing report side-effect free on every supported platform.
            "system": f"{platform.system()} {platform.release()}".strip(),
            "architecture": platform.machine(),
            "python": platform.python_version(), "frozen": bool(getattr(sys, "frozen", False)),
            "PyQt": PYQT_VERSION_STR, "Qt": qVersion(),
            "Ghostscript": {"path": str(ghostscript or ""), "version": version},
            "current": context, "recent_events": list(self._events),
        }
        return json.dumps(data, ensure_ascii=False, indent=2, default=str)


class DiagnosticsDialog(QDialog):
    def __init__(self, diagnostics, context, ghostscript, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("诊断信息"))
        self.resize(760, 540)
        self._runner = TaskRunner(self)
        root = QVBoxLayout(self)
        note = QLabel(tr("仅显示版本、当前设置和最近错误，不读取图片内容或自动上传。报告可能含本地路径，请查看后再复制。"))
        note.setWordWrap(True)
        root.addWidget(note)
        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setPlainText(diagnostics.report(context, ghostscript))
        root.addWidget(self._text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText(tr("关闭"))
        copy = QPushButton(tr("复制诊断报告"))
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self._text.toPlainText()))
        buttons.addButton(copy, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._runner.submit(lambda _cancel: diagnostics.report(context, ghostscript, True), self._ready)

    def _ready(self, report, error, cancelled):
        if not cancelled and error is None:
            self._text.setPlainText(report)

    def done(self, result):
        if not self._runner.shutdown():
            QTimer.singleShot(100, lambda: self.done(result))
            return
        super().done(result)
