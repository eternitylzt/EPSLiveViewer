"""A partial release must preserve checksums for the untouched packages."""

import hashlib
from pathlib import Path
import tempfile
import unittest

from scripts.update_asset_checksum import update


class AssetChecksumTests(unittest.TestCase):
    def test_only_requested_asset_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            asset = root / "EPSLiveViewer-macOS-arm64.dmg"
            asset.write_bytes(b"replacement DMG")
            checksums = root / "SHA256SUMS.txt"
            other = "a" * 64 + "  release-assets/EPSLiveViewer-Windows-x64.zip\n"
            checksums.write_text(other + "b" * 64 + "  release-assets/" + asset.name + "\n")
            update(checksums, asset)
            self.assertEqual(checksums.read_text(), other + hashlib.sha256(asset.read_bytes()).hexdigest()
                             + "  release-assets/" + asset.name + "\n")

    def test_missing_asset_does_not_rewrite_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            checksums = root / "SHA256SUMS.txt"
            original = "a" * 64 + "  untouched.zip\n"
            checksums.write_text(original)
            with self.assertRaises(ValueError):
                update(checksums, root / "missing.dmg")
            self.assertEqual(checksums.read_text(), original)
