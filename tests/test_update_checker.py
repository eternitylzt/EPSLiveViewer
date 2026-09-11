"""Offline tests for release parsing, comparison, and API error handling."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from update_checker import (
    UpdateCheckError,
    check_latest_release,
    is_newer_version,
    version_tuple,
)


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class UpdateCheckerTests(unittest.TestCase):
    def test_version_comparison_accepts_release_tag(self) -> None:
        self.assertEqual(version_tuple("eps-live-viewer-v1.3.0"), (1, 3, 0, 0))
        self.assertTrue(is_newer_version("v1.3.1", "1.3.0"))
        self.assertFalse(is_newer_version("1.3", "1.3.0"))
        self.assertFalse(is_newer_version("1.2.9", "1.3.0"))

    @patch("update_checker.urlopen")
    def test_valid_release(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _Response(
            json.dumps(
                {
                    "tag_name": "eps-live-viewer-v1.4.0",
                    "html_url": "https://github.com/eternitylzt/EPSLiveViewer/releases/tag/eps-live-viewer-v1.4.0",
                }
            ).encode()
        )
        release = check_latest_release()
        self.assertEqual(release.version, "1.4.0")
        self.assertEqual(release.tag, "eps-live-viewer-v1.4.0")

    @patch("update_checker.urlopen", side_effect=URLError("offline"))
    def test_network_error_is_explicit(self, _mocked_urlopen) -> None:
        with self.assertRaisesRegex(UpdateCheckError, "Could not connect to GitHub"):
            check_latest_release()

    @patch("update_checker.urlopen")
    def test_invalid_or_untrusted_release_is_rejected(self, mocked_urlopen) -> None:
        mocked_urlopen.return_value = _Response(
            b'{"tag_name":"not-a-version","html_url":"https://example.com"}'
        )
        with self.assertRaises(UpdateCheckError):
            check_latest_release()


if __name__ == "__main__":
    unittest.main()
