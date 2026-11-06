"""Compare source startup/working set using a deterministic EPS on Windows.

Run: python tests/profile_open.py [checkout_directory]
This is a manual measurement, not a timing threshold in CI.
"""
import json
import math
import sys
import tempfile
import time
from pathlib import Path

project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(project))
started = time.perf_counter()
import main
imported = time.perf_counter()
from PyQt6.QtCore import QSettings
from config import AppConfig, ConfigManager
from tests.preview_profile import memory_mib
from unittest.mock import patch

app = main.EpsApplication([])
app.setOrganizationName("EPSOpenProfile")
app.setApplicationName("Profile")
with tempfile.TemporaryDirectory() as temporary:
    folder = Path(temporary)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, temporary)
    manager = ConfigManager()
    manager.base_dir, manager.path = folder, folder / "config.json"
    manager.save(AppConfig())
    source = folder / "plot.eps"
    commands = ["%!PS-Adobe-3.0 EPSF-3.0", "%%BoundingBox: 0 0 600 400",
                "0 0 0 setrgbcolor 1 setlinewidth 40 40 moveto 560 40 lineto stroke",
                "40 40 moveto 40 360 lineto stroke",
                "/Helvetica findfont 16 scalefont setfont 180 370 moveto (Spectrum) show",
                "0.1 0.4 0.8 setrgbcolor"]
    for i in range(1600):
        commands.append(f"{40+i*520/1599:.3f} {180+100*math.sin(i/90):.3f} "
                        + ("moveto" if i == 0 else "lineto"))
    commands += ["stroke", "showpage", "%%EOF"]
    source.write_text("\n".join(commands), encoding="ascii")
    controller = main.DesktopController(manager)
    window = controller.new_window()
    app.processEvents()
    empty = memory_mib()
    view = window.tabs.currentWidget()

    def settle(current):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            app.processEvents()
            v = current._view
            if (current._current_pdf is not None and current._preview_thread is None
                    and v.has_document() and not v._page_item._frame.isNull()
                    and not v._in_flight and not v._detail_timer.isActive()):
                return
            time.sleep(.002)
        raise RuntimeError("Preview did not finish")

    try:
        open_start = time.perf_counter()
        view.open_eps(source)
        settle(view)
        opened = time.perf_counter()
        one = memory_mib()
        other = window.add_document(source)
        settle(other)
        two = memory_mib()
        with patch.object(view, "_retranslate_ui", wraps=view._retranslate_ui) as translate:
            switch_start = time.perf_counter()
            for _ in range(20):
                window.tabs.setCurrentWidget(view)
                window.tabs.setCurrentWidget(other)
            switch_elapsed = time.perf_counter() - switch_start
            translations = translate.call_count
        print(json.dumps({
            "import_ms": round((imported-started)*1000, 1),
            "open_eps_ms": round((opened-open_start)*1000, 1),
            "empty": empty, "one_file": one, "two_tabs": two,
            "40_switches_ms": round(switch_elapsed*1000, 1),
            "first_tab_retranslations": translations,
        }))
    finally:
        for i in range(window.tabs.count()):
            window.tabs.widget(i)._discard_on_close = True
        window.close()
        app.processEvents()
