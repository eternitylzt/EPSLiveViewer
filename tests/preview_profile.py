"""Manual preview timing/memory comparison using the same file and window size."""
import ctypes
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QSettings
from PyQt6.QtWidgets import QApplication
from config import AppConfig, ConfigManager
from workspace import DesktopController


def memory_mib():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
            "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
            "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    process = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    ctypes.windll.psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
    return {"working_mib": round(counters.WorkingSetSize / 2**20, 2),
            "private_mib": round(counters.PrivateUsage / 2**20, 2)}


def run(source):
    app = QApplication([])
    app.setOrganizationName("EPSPreviewProfile")
    app.setApplicationName("Profile")
    with tempfile.TemporaryDirectory() as directory:
        QSettings.setDefaultFormat(QSettings.Format.IniFormat)
        QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, directory)
        manager = ConfigManager()
        manager.base_dir, manager.path = Path(directory), Path(directory) / "config.json"
        manager.save(AppConfig())
        controller = DesktopController(manager)
        host = controller.new_window()
        rows = []

        def settle(view=None):
            deadline = time.monotonic() + 30
            idle_since = None
            while time.monotonic() < deadline:
                app.processEvents()
                idle = view is None or (view.has_document() and not view._in_flight
                                       and not view._queued and not view._color_jobs
                                       and not view._detail_timer.isActive())
                if idle:
                    idle_since = idle_since or time.monotonic()
                    if time.monotonic() - idle_since > .15:
                        return
                else:
                    idle_since = None
                time.sleep(.002)
            if view is not None:
                print({"pending": view._in_flight, "queued": len(view._queued),
                       "colors": len(view._color_jobs), "timer": view._detail_timer.isActive(),
                       "cache": view._page_item._cache_bytes if view._page_item else None,
                       "has_frame": not view._page_item._frame.isNull() if view._page_item else None,
                       "memory": memory_mib()}, flush=True)
            raise RuntimeError("Preview failed to settle within 30 seconds")

        def record(label, view=None, elapsed=None):
            row = {"stage": label, **memory_mib()}
            if elapsed is not None:
                row["seconds"] = round(elapsed, 3)
            if view is not None:
                row["cache_mib"] = round(view._page_item._cache_bytes / 2**20, 2)
            rows.append(row)
            print(json.dumps(row), flush=True)

        try:
            settle()
            record("empty")
            first = host.tabs.currentWidget()
            start = time.monotonic()
            first.open_eps(source)
            settle(first._view)
            record("one_file", first._view, time.monotonic() - start)
            start = time.monotonic()
            for _ in range(6):
                first._view.zoom_by(1.2)
                settle(first._view)
            record("six_zooms", first._view, time.monotonic() - start)
            second_host = controller.new_window(source)
            second = second_host.tabs.currentWidget()
            settle(second._view)
            record("two_windows", second._view)
            print(json.dumps(rows, indent=2), flush=True)
        finally:
            for window in list(controller.windows):
                for index in range(window.tabs.count()):
                    window.tabs.widget(index)._discard_on_close = True
                window.close()
            app.processEvents()


if __name__ == "__main__":
    run(Path(sys.argv[1]).resolve())
