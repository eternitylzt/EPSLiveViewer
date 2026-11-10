# Licenses and corresponding source

EPS Live Viewer — Copyright (C) 2026 Zhentong Li.
The application is distributed under **GNU AGPL version 3 only**; see LICENSE.
It is provided without warranty. Its source, build scripts and tagged releases
are available at https://github.com/eternitylzt/EPSLiveViewer.

## Ghostscript 10.08.0

Copyright Artifex Software, Inc. and the contributors named in its source.
Ghostscript is distributed under GNU AGPLv3, with the included third-party
libraries and fonts under the terms in their respective notices.

- Complete, unmodified corresponding source:
  https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10080/ghostscript-10.08.0.tar.xz
- SHA-256: `c20492bc8ebb96c87fa2e52a0926e1cda8cde95d66145e018ac713fed5da38cf`
- EPS Live Viewer releases that bundle this engine also attach that exact source
  archive. The matching application tag contains `scripts/prepare_ghostscript.py`
  and `scripts/build_ghostscript_unix.sh`, including build configuration.
- Upstream notices and licenses are included inside the application at
  `ghostscript/licenses/`; `ghostscript/SOURCE.txt` and `manifest.json` identify
  the source and runtime files. Windows one-file builds extract these files
  into the private application runtime directory while running.
- Windows uses the official interpreter binaries without modification; Linux
  and macOS compile the unmodified upstream source with only the output devices
  used by the viewer. Standard fonts, CMaps, ICC profiles, PostScript and PDF
  interpretation are retained in the embedded resource filesystem.

Redistributors must provide the matching application/engine source and build
instructions alongside binaries, retain these notices, and comply with the
applicable licenses. The source archive is a separate download, not duplicated
inside each executable.

## Other components

Components retain their own copyright and licenses. The application's license
does not replace their terms.

- PyQt6: GPLv3, Riverbank Computing; https://www.riverbankcomputing.com/software/pyqt/
- Qt: the applicable Qt open-source licenses; https://www.qt.io/licensing/open-source-lgpl-obligations
- Python: PSF license; https://docs.python.org/3/license.html
- Pillow: HPND and its third-party notices; https://github.com/python-pillow/Pillow
- pypdf: BSD-3-Clause; https://github.com/py-pdf/pypdf
- imageio-ffmpeg: BSD-2-Clause wrapper; the bundled FFmpeg binary has its own
  FFmpeg/codec licenses and build configuration; https://github.com/imageio/imageio-ffmpeg
  and https://ffmpeg.org/legal.html
- certifi: MPL-2.0; existing LICENSE/NOTICE in `resources/licenses/certifi/`.
- PyInstaller: GPL with its distribution exception; https://pyinstaller.org/en/stable/license.html
- Microsoft Visual C++ runtime: Microsoft redistributable runtime terms,
  https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files
  (app-local DLLs supplied by the Python/PyQt runtime, not Ghostscript source).

7-Zip is used only to unpack verified build inputs on Windows. It is not
included in EPS Live Viewer and its installers are never installed or executed.
See https://www.7-zip.org/license.txt for its build-tool license.
