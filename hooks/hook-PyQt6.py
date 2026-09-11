"""Use upstream Qt discovery; omit the unused Windows OpenGL rasterizer."""

import runpy
import sys
from pathlib import Path

import PyInstaller

upstream = runpy.run_path(str(Path(PyInstaller.__file__).parent / "hooks" / "hook-PyQt6.py"))
hiddenimports = upstream.get("hiddenimports", [])
binaries = upstream.get("binaries", [])
datas = upstream.get("datas", [])
if sys.platform == "win32":
    # All views use QWidget/QImage raster painting, never QOpenGLWidget.
    binaries = [item for item in binaries if Path(item[0]).name.lower() != "opengl32sw.dll"]
