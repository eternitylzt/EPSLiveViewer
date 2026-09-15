"""Replace one existing Release checksum, preserving every other asset entry."""

import hashlib
from pathlib import Path
import sys


def update(checksums: Path, asset: Path) -> None:
    lines = checksums.read_text(encoding="utf-8").splitlines(keepends=True)
    matches = []
    for index, line in enumerate(lines):
        parts = line.rstrip("\r\n").split(maxsplit=1)
        if len(parts) == 2 and Path(parts[1].lstrip("*")).name == asset.name:
            matches.append((index, parts[1]))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one checksum for {asset.name}")
    with asset.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    index, name = matches[0]
    lines[index] = f"{digest}  {name}\n"
    checksums.write_text("".join(lines), encoding="utf-8")


if __name__ == "__main__":
    update(Path(sys.argv[1]), Path(sys.argv[2]))
