"""Small, atomic sidecars for non-destructive document edits."""

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from image_transforms import ColorReplacement, TransformSnapshot


def state_path(source):
    return Path(str(source) + ".epslive.json")


def load_state(source):
    path = state_path(source)
    if not path.exists():
        return TransformSnapshot()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1:
        raise ValueError("Unsupported EPS Live Viewer edit format")
    data = data["transforms"]
    rotations = tuple(sorted((int(page), int(angle) % 360)
                            for page, angle in data.get("page_rotations", [])
                            if int(page) > 0 and int(angle) % 360))
    if any(angle not in {90, 180, 270} for _, angle in rotations):
        raise ValueError("Invalid saved rotation")
    replacements = tuple(ColorReplacement(**entry) for entry in data.get("replacements", []))
    if len(replacements) > 16:
        raise ValueError("Too many replacement colors")
    return TransformSnapshot(bool(data.get("inverted", False)), replacements, rotations)


def save_state(source, snapshot):
    path = state_path(source)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".epslive_", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump({"schema": 1, "transforms": asdict(snapshot)}, handle,
                      ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path
