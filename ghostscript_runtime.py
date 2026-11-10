"""Locate the private Ghostscript runtime without starting or loading it.

The bundled interpreter contains its initialization files, standard fonts and
ICC profiles in ROMFS. External installations retain their existing discovery
and environment behavior.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def bundled_ghostscript_path() -> Path | None:
    """Return this platform's bundled console executable, when available."""
    bundle = getattr(sys, "_MEIPASS", None)
    root = (
        Path(bundle) / "ghostscript"
        if bundle is not None
        else Path(__file__).resolve().parent / "vendor" / "ghostscript"
    )
    executable = root / "bin" / ("gswin64c.exe" if sys.platform == "win32" else "gs")
    return executable if executable.is_file() else None


def ghostscript_environment(executable: str | Path) -> dict[str, str] | None:
    """Isolate bundled resource lookup; leave external GS settings untouched.

    Returning None asks subprocess to inherit the current environment. Never
    modify os.environ: preview, export and diagnostics may run concurrently.
    """
    bundled = bundled_ghostscript_path()
    if bundled is None or Path(executable).resolve() != bundled.resolve():
        return None
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith("GS_")
    }
    # The first Init path also establishes GenericResourceDir=%rom%Resource/,
    # including the embedded font resources. ROMICC profiles are found by the
    # interpreter itself; do not disable its normal system-font fallback.
    environment["GS_LIB"] = os.pathsep.join(("%rom%Resource/Init/", "%rom%lib/"))
    return environment
