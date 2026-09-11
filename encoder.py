"""Resolve the bundled encoder, unpacking the Windows payload on first use."""

import lzma
import shutil
import sys
import tempfile
import threading
from pathlib import Path

_lock = threading.Lock()
_directory: tempfile.TemporaryDirectory | None = None


def ffmpeg_executable() -> Path:
    global _directory
    archive = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "encoder" / "ffmpeg.exe.xz"
    if not archive.is_file():
        import imageio_ffmpeg

        return Path(imageio_ffmpeg.get_ffmpeg_exe())
    with _lock:
        if _directory is None:
            directory = tempfile.TemporaryDirectory(prefix="eps_encoder_")
            try:
                with lzma.open(archive, "rb") as source, (Path(directory.name) / "ffmpeg.exe").open("wb") as target:
                    shutil.copyfileobj(source, target)
            except Exception:
                directory.cleanup()
                raise
            _directory = directory
        return Path(_directory.name) / "ffmpeg.exe"
