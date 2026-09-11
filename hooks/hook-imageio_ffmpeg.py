"""Keep FFmpeg intact, but store the Windows executable with XZ compression."""

import lzma
import shutil
import sys
from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_data_files, copy_metadata, get_package_paths

hiddenimports = ["imageio_ffmpeg.binaries"]
if sys.platform == "win32":
    package = Path(get_package_paths("imageio_ffmpeg")[1])
    executables = list((package / "binaries").glob("ffmpeg-win*.exe"))
    if len(executables) != 1:
        raise RuntimeError("Expected exactly one bundled Windows FFmpeg executable")
    output = Path(CONF["workpath"]) / "encoder" / "ffmpeg.exe.xz"
    output.parent.mkdir(parents=True, exist_ok=True)
    with executables[0].open("rb") as source, lzma.open(
        output, "wb",
        filters=[{"id": lzma.FILTER_X86}, {"id": lzma.FILTER_LZMA2, "preset": 6}],
    ) as target:
        shutil.copyfileobj(source, target)
    datas = [(str(output), "encoder"), *copy_metadata("imageio_ffmpeg")]
else:
    # macOS executables must remain visible to signing/notarization tools.
    datas = collect_data_files("imageio_ffmpeg", subdir="binaries")
