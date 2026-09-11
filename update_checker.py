"""Manual GitHub release lookup using only the Python standard library."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


LATEST_RELEASE_API = (
    "https://api.github.com/repos/eternitylzt/EPSLiveViewer/releases/latest"
)
_RELEASE_URL_PREFIX = "https://github.com/eternitylzt/EPSLiveViewer/releases/"
_MAX_RESPONSE_BYTES = 1_000_000


class UpdateCheckError(RuntimeError):
    """Raised when release information cannot be downloaded or validated."""


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    url: str


def version_tuple(value: str) -> tuple[int, ...]:
    """Extract a comparable dotted numeric version from an app version or tag."""
    match = re.search(r"(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)", value.strip())
    if match is None:
        raise ValueError(f"Invalid version: {value}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * (4 - len(parts))


def is_newer_version(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def check_latest_release(timeout: float = 6.0) -> ReleaseInfo:
    """Return GitHub's latest stable release or raise a user-facing error."""
    request = Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "EPS-Live-Viewer-Update-Check",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
    except HTTPError as error:
        raise UpdateCheckError(f"GitHub API returned HTTP {error.code}.") from error
    except (URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise UpdateCheckError(f"Could not connect to GitHub: {reason}") from error

    if len(payload) > _MAX_RESPONSE_BYTES:
        raise UpdateCheckError("GitHub returned an unexpectedly large response.")
    try:
        data = json.loads(payload.decode("utf-8"))
        tag = str(data["tag_name"]).strip()
        url = str(data["html_url"]).strip()
        version_tuple(tag)
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise UpdateCheckError("GitHub returned invalid release information.") from error
    if not url.startswith(_RELEASE_URL_PREFIX):
        raise UpdateCheckError("GitHub returned an invalid release URL.")

    match = re.search(r"(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)", tag)
    assert match is not None
    return ReleaseInfo(version=match.group(1), tag=tag, url=url)
