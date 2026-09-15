# Packaging regression check

For 2.3.0, `test_pdf_color_export.py` checks 600 DPI A4 recolored PNG export,
alpha/tolerance/non-cascading replacement semantics, PDF input and multiple video
frames, preserved vector paths and text in recolored PDFs without Ghostscript,
and actual rendered thin axes at seven zoom levels. Qt viewport mouse events
check automatic text selection and blank-space panning. Clipboard writes are
checked separately from system clipboard ownership (unavailable on some hosts).

Windows 2.3.0 local verification (Python 3.12.10 / PyInstaller 6.22.2):

- The full source suite and user-provided three-page EPS package smoke check pass.
- A separately frozen `PdfColorSmoke.exe`, built with production hooks, passes
  the four PDF/color/600-DPI/viewport regressions. Its A4 600 DPI color export took
  approximately one second on the development machine; performance varies.
- Production EXE: 58,682,093 bytes; previous local build: 56,099,038 bytes.
  Increase: 2,583,055 bytes (4.6%). PDF reading reuses QtPdf; only lightweight
  recoloring dependencies were added. Full PDF object editing is not included.
- Linux/macOS build hooks were updated, but this local update has not yet been
  built or interactively tested on those operating systems.

For 2.2.1, `test_document_workspace.py` checks independent tab edits and
shortcuts, external-process open requests, sidecar round trips, close cancellation,
multi-page comparison, text extraction, and actual decoded MP4 frame colors.
When available it compares all pages of the user's `20241001.eps` against the
main PDF preview pixel-for-pixel. Temporary copies protect the original.

For the local 2.1.0 upgrade, `test_upgrade_workflows.py` verifies per-file bounded
undo/redo and live-refresh history, responsive color previews and cancellation,
discarding obsolete tile color jobs, video rehearsal order/seeking/duration/cache
cleanup, pinned and linked comparison panes, and manual diagnostic reports.
It uses generated PNG fixtures and isolated settings and does not need Ghostscript.
The existing EPS smoke test also checks undo/redo of an all-page rotation.

Run `python tests/package_smoke.py path/to/multipage.eps` in the development environment.
The test copies the source into a temporary directory and uses isolated settings.
It expects at least two pages and an installed Ghostscript.

To verify bundled dependencies on Windows, build the same test with the production hooks:

```powershell
python -m PyInstaller --noconfirm --onefile --console --name PackageSmoke --paths . --additional-hooks-dir hooks --distpath build/smoke --workpath build/smoke-work tests/package_smoke.py
.\build\smoke\PackageSmoke.exe path/to/multipage.eps
```

The test covers multi-page EPS/PS preview and navigation, drop handling, live refresh,
zoom/wheel modes, backgrounds, per-page rotation, inversion, color replacement,
current/all-page PNG export, transformed PDF/PS/EPS export, direct PNG/JPG opening,
multi-page video frames, even/odd-sized MP4, GIF frame count, proportional cropping,
export cancellation, both languages, and the manual update-check menu.
`test_update_checker.py` verifies version comparison and GitHub response/error
handling offline, without making a network request.
The video outputs are decoded by FFmpeg to verify that encoding produced readable files.
Run `python -m unittest discover -s tests -p 'test_*.py' -v` for color-dialog
add/edit/reopen checks, repeated rotated previews/exports, MP4 YUV420/Main format,
decoded frame order, and timestamps at 1/7/30/60 FPS. Ghostscript-specific checks
are skipped when Ghostscript is unavailable; other checks run in release CI.
On Windows, `python tests/windows_media_playback.py` additionally plays a generated
odd-sized MP4 through Windows Media Foundation and checks delivered frames and duration.
QtMultimedia is used only by that source-level test, not added to the app payload.
It is a developer test executable and is not included in the application.

Measured with Python 3.12.10, PyInstaller 6.22.2 and imageio-ffmpeg 0.6.0:

| Windows one-file build | Bytes | Decimal MB |
| --- | ---: | ---: |
| Original packaging, same environment | 68,164,643 | 68.16 |
| Optimized packaging | 51,924,694 | 51.92 |

Reduction: 23.82%. The encoder is identical after decompression (SHA-256 checked).
The 50 DLL/PYD files in the delivered executable match the frozen regression build.
The regression test passed using the supplied three-page `20241001.eps`, including
the native Windows Qt platform plugin. First encoder extraction took about 1.7 seconds
on the development machine; subsequent calls reuse it until application exit.

The changes target Windows packaging. Existing macOS/Linux packaging is retained;
these platforms were not rebuilt for this optimization. Passing this check does not
replace testing on every supported OS and graphics-driver combination.
# macOS 2.2.1 interaction fix

`tests/test_desktop_controls.py` uses mouse clicks on toolbar buttons, menus,
recent files and tabs; it also opens/closes File Information and checks subsequent
input. The activation regression fails against the original 2.2.0 workspace and
passes with the fix. Windows source regression checks passed (20 tests).

For macOS, the release workflow runs the checks using `QT_QPA_PLATFORM=cocoa`
and `EPS_REQUIRE_COCOA=1`, both from source and a packaged test executable.
Offscreen runs alone do not validate macOS menu interaction. Screenshots are
saved as workflow artifacts. Passing automated Cocoa checks still needs user
confirmation on the affected Mac/macOS combination.

User check after replacing the app: open an EPS from Finder; click Zoom and
Invert; open Settings and File Information; switch tabs and open Recent Files;
switch to another app and back, then repeat. If any control fails, report the
macOS version, Mac chip, language and whether the failure follows a dialog or tab
switch. The same-version repair replaces only the arm64 DMG and its checksum.
