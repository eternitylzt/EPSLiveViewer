"""Prepare a pinned, relocatable Ghostscript runtime without installing it.

Only build machines download archives. End users receive the complete runtime.
Windows uses Artifex's official release binaries and app-local VC runtime files;
Unix builds the required output devices from the matching complete source tarball.
The source tarball remains a separate release asset, never inside the application.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import signal
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
VERSION = "10.08.0"
SOURCE_NAME = f"ghostscript-{VERSION}.tar.xz"
SOURCE_SHA256 = "c20492bc8ebb96c87fa2e52a0926e1cda8cde95d66145e018ac713fed5da38cf"
INSTALLER_NAME = "gs10080w64.exe"
INSTALLER_SHA256 = "52a91b8bf09298788d7a57b9206127026c23eacd75405f0a131e26dc381dce50"
RELEASE_URL = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/"
SEVENZIP_URL = "https://github.com/ip7z/7zip/releases/download/26.06/"
SEVENZIP_FILES = {
    "7zr.exe": "e80db2dad715a6c5adabe292d31ed54e11f4e9b99ca349827b50573b175891bc",
    "7z2606-x64.exe": "9b697f65ecc2d9b0152f5ee96d72dde522a7827690349d9307935dacf40f42ec",
}
REQUIRED_DEVICES = {"pngalpha", "pdfwrite", "ps2write", "eps2write", "nullpage"}
VC_FILES = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(name: str, digest: str, base_url: str, directory: Path) -> Path:
    """Verify cached files too; interrupted downloads never become valid cache entries."""
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    if destination.is_file():
        if sha256(destination) != digest:
            raise RuntimeError(f"Checksum mismatch: {destination}. Remove this cached file and retry.")
        return destination
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(base_url + name, headers={"User-Agent": "EPSLiveViewer-build"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output, 1024 * 1024)
        if sha256(temporary) != digest:
            raise RuntimeError(f"Checksum mismatch for {name}")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Verified {name}", flush=True)
    return destination


def run(command: list[str], timeout_seconds: float = 1800, **kwargs) -> subprocess.CompletedProcess:
    """Bound build commands, including every compiler spawned by Unix make."""
    if os.name == "nt":
        return subprocess.run(command, check=True, timeout=timeout_seconds,
                              creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)
    if kwargs.pop("capture_output", False):
        if "stdout" in kwargs or "stderr" in kwargs:
            raise ValueError("capture_output cannot be combined with stdout or stderr")
        kwargs["stdout"] = subprocess.PIPE
        kwargs["stderr"] = subprocess.PIPE
    # A separate session gives this command a private process group. Terminating
    # only bash on timeout would leave make and compiler children running.
    with subprocess.Popen(command, start_new_session=True, **kwargs) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            finally:
                # The leader may have exited while a child ignored SIGTERM.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            stdout, stderr = process.communicate()
            raise subprocess.TimeoutExpired(command, timeout_seconds, stdout, stderr) from None
        except BaseException:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.communicate()
            raise
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def sevenzip(cache: Path, supplied: str | None) -> Path:
    if supplied:
        executable = Path(supplied).expanduser().resolve()
        if not executable.is_file():
            raise RuntimeError(f"7-Zip executable does not exist: {executable}")
        return executable
    installed = shutil.which("7z")
    if installed:
        return Path(installed)
    executable = cache / "7zip" / "7z.exe"
    if executable.is_file() and executable.with_name("7z.dll").is_file():
        return executable
    downloads = cache / "downloads"
    paths = {name: download(name, digest, SEVENZIP_URL, downloads)
             for name, digest in SEVENZIP_FILES.items()}
    # 7zr only unpacks the official 7-Zip installer; neither installer is run.
    run([str(paths["7zr.exe"]), "x", "-y", "-bso0", "-bsp0",
         f"-o{executable.parent}", str(paths["7z2606-x64.exe"]), "7z.exe", "7z.dll"])
    if not executable.is_file() or not executable.with_name("7z.dll").is_file():
        raise RuntimeError("Could not extract the portable 7-Zip build tool")
    return executable


def source_tree(archive: Path, cache: Path) -> Path:
    destination = cache / f"ghostscript-{VERSION}"
    marker = destination / ".eps-source.sha256"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == SOURCE_SHA256:
        return destination
    cache.mkdir(parents=True, exist_ok=True)
    # Windows's long-path prefix avoids source-tree paths exceeding MAX_PATH.
    extraction_root = str(cache.resolve())
    if os.name == "nt":
        extraction_root = "\\\\?\\" + extraction_root
    with tarfile.open(archive, "r:xz") as bundle:
        for member in bundle:
            relative = PurePosixPath(member.name)
            if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != destination.name:
                raise RuntimeError(f"Unsafe source archive path: {member.name}")
            # This pinned source release contains only directories and ordinary files.
            if not member.isdir() and not member.isfile():
                raise RuntimeError(f"Unexpected source archive entry: {member.name}")
            bundle.extract(member, extraction_root, filter="data")
    marker.write_text(SOURCE_SHA256 + "\n", encoding="ascii")
    return destination


def copy_licenses(archive: Path, destination: Path) -> None:
    """Retain upstream and included-library notices without duplicating source code."""
    with tarfile.open(archive, "r:xz") as bundle:
        for member in bundle:
            if not member.isfile():
                continue
            relative = PurePosixPath(member.name)
            basename = relative.name.lower()
            if not (any(word in basename for word in ("copying", "license", "notice"))
                    or basename in {"ftl.txt", "gplv2.txt"}):
                continue
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"Unsafe license path: {member.name}")
            target = destination / "licenses" / Path(*relative.parts[1:])
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    (destination / "SOURCE.txt").write_text(
        f"Ghostscript {VERSION}, Artifex Software, Inc.\n"
        "License: GNU Affero General Public License version 3.\n"
        f"Complete corresponding source: {SOURCE_NAME}\n"
        f"Upstream source: {RELEASE_URL}{SOURCE_NAME}\n"
        f"SHA-256: {SOURCE_SHA256}\n"
        "EPS Live Viewer releases also provide this source archive and the build scripts.\n"
        "Windows binaries are unmodified official Artifex release binaries.\n"
        "Unix binaries use the unmodified upstream source with a reduced device selection.\n"
        "Windows VC runtime files originate from the application's PyQt6/Python dependencies.\n",
        encoding="utf-8",
    )


def prepare_windows(cache: Path, destination: Path, supplied_7z: str | None) -> None:
    if platform.machine().lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("The pinned Windows runtime is x64; build with x64 Python on Windows")
    installer = download(INSTALLER_NAME, INSTALLER_SHA256, RELEASE_URL, cache / "downloads")
    unpacker = sevenzip(cache, supplied_7z)
    with tempfile.TemporaryDirectory(prefix="extract-", dir=cache) as temporary:
        extracted = Path(temporary)
        run([str(unpacker), "x", "-y", "-bso0", "-bsp0", f"-o{extracted}",
             str(installer), "bin/gswin64c.exe", "bin/gsdll64.dll"])
        output_bin = destination / "bin"
        output_bin.mkdir(parents=True, exist_ok=True)
        for name in ("gswin64c.exe", "gsdll64.dll"):
            shutil.copy2(extracted / "bin" / name, output_bin / name)
    import PyQt6
    qt_bin = Path(PyQt6.__file__).resolve().parent / "Qt6" / "bin"
    for name in VC_FILES:
        source = qt_bin / name
        if not source.is_file():
            source = Path(sys.executable).resolve().parent / name
        if not source.is_file():
            raise RuntimeError(f"Required app-local VC runtime file is missing: {name}")
        shutil.copy2(source, destination / "bin" / name)


def verify_runtime(destination: Path) -> None:
    executable = destination / "bin" / ("gswin64c.exe" if os.name == "nt" else "gs")
    environment = {key: value for key, value in os.environ.items() if not key.upper().startswith("GS_")}
    environment["GS_LIB"] = os.pathsep.join(("%rom%Resource/Init/", "%rom%lib/"))
    result = run([str(executable), "-h"], env=environment, capture_output=True, text=True)
    if not REQUIRED_DEVICES.issubset(set(result.stdout.split())):
        raise RuntimeError("Prepared Ghostscript lacks a required output device")
    if VERSION not in result.stdout or "%rom%Resource/Init/" not in result.stdout:
        raise RuntimeError("Prepared Ghostscript does not have the pinned version and embedded resources")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "vendor" / "ghostscript")
    parser.add_argument("--cache", type=Path, default=ROOT / "build" / "ghostscript")
    parser.add_argument("--source-only", action="store_true", help="Download, verify and unpack source only")
    parser.add_argument("--sevenzip", help="Optional existing 7z executable (Windows build tool)")
    args = parser.parse_args()
    cache, destination = args.cache.resolve(), args.destination.resolve()
    archive = download(SOURCE_NAME, SOURCE_SHA256, RELEASE_URL, cache / "downloads")
    if args.source_only:
        print(source_tree(archive, cache))
        return 0
    destination.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        prepare_windows(cache, destination, args.sevenzip)
    elif sys.platform in {"linux", "darwin"}:
        source = source_tree(archive, cache)
        run(["bash", str(ROOT / "scripts" / "build_ghostscript_unix.sh"), str(source), str(destination)])
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
    copy_licenses(archive, destination)
    verify_runtime(destination)
    manifest = {
        "version": VERSION,
        "source_url": RELEASE_URL + SOURCE_NAME,
        "source_sha256": SOURCE_SHA256,
        "platform": sys.platform,
        "architecture": platform.machine(),
        "required_devices": sorted(REQUIRED_DEVICES),
        "files": {path.relative_to(destination).as_posix(): sha256(path)
                  for path in sorted(destination.rglob("*"))
                  if path.is_file() and path.name != "manifest.json"},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    size = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    print(f"Prepared Ghostscript {VERSION}: {destination} ({size / 1024**2:.2f} MiB)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit(f"Ghostscript preparation failed: {error}") from error
