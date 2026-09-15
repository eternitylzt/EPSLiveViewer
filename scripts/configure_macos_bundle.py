"""Set version and supported-image associations in a macOS app Info.plist."""

from __future__ import annotations

import argparse
import plistlib
from pathlib import Path


def configure(info_plist: Path, version: str) -> None:
    with info_plist.open("rb") as stream:
        info = plistlib.load(stream)

    info["CFBundleDisplayName"] = "EPS Live Viewer"
    info["CFBundleName"] = "EPS Live Viewer"
    info["CFBundleShortVersionString"] = version
    info["CFBundleVersion"] = version
    info["CFBundleDocumentTypes"] = [
        {
            "CFBundleTypeName": "PDF Document",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "CFBundleTypeExtensions": ["pdf"],
            "LSItemContentTypes": ["com.adobe.pdf"],
        },
        {
            "CFBundleTypeName": "EPS/PostScript Document",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "CFBundleTypeExtensions": ["eps", "ps"],
            "LSItemContentTypes": [
                "com.adobe.encapsulated-postscript",
                "com.adobe.postscript",
            ],
        },
        {
            "CFBundleTypeName": "PNG/JPEG Image",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "CFBundleTypeExtensions": ["png", "jpg", "jpeg"],
            "LSItemContentTypes": ["public.png", "public.jpeg"],
        },
    ]

    with info_plist.open("wb") as stream:
        plistlib.dump(info, stream, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("info_plist", type=Path)
    parser.add_argument("version")
    arguments = parser.parse_args()
    configure(arguments.info_plist, arguments.version)


if __name__ == "__main__":
    main()
