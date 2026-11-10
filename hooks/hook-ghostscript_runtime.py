"""Bundle the verified private interpreter, never a machine's Ghostscript install."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import platform
import sys


root = Path(__file__).resolve().parents[1] / "vendor" / "ghostscript"
manifest_path = root / "manifest.json"
if not manifest_path.is_file():
    raise RuntimeError("Run python scripts/prepare_ghostscript.py before packaging")
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if manifest.get("platform") != sys.platform:
    raise RuntimeError("Ghostscript was prepared for a different platform; prepare it again")
normalize_arch = lambda value: {"amd64": "x86_64", "aarch64": "arm64"}.get(value.lower(), value.lower())
if normalize_arch(manifest.get("architecture", "")) != normalize_arch(platform.machine()):
    raise RuntimeError("Ghostscript was prepared for a different architecture; prepare it again")

datas = []
binaries = []
for relative, digest in manifest["files"].items():
    relative_path = PurePosixPath(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts or "\\" in relative or ":" in relative:
        raise RuntimeError(f"Invalid Ghostscript manifest path: {relative}")
    source = root / relative
    if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"Bundled Ghostscript file is missing or changed: {relative}")
    target = str(Path("ghostscript") / Path(relative).parent)
    # Windows files need no relocation. Treating them as data avoids duplicate
    # DLL dependency collection; the VC runtime DLLs are already app-local.
    # Unix executables remain binaries for permissions, relocation and macOS signing.
    collection = binaries if sys.platform != "win32" and relative.startswith("bin/") else datas
    collection.append((str(source), target))
datas.append((str(manifest_path), "ghostscript"))
for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
    notice = root.parents[1] / name
    if not notice.is_file():
        raise RuntimeError(f"Required redistribution notice is missing: {name}")
    datas.append((str(notice), "resources/licenses/EPSLiveViewer"))
