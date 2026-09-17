# Packaging regression check

## 3.1.0

All 41 source regressions pass on Windows, including menus above the tabs,
non-closable Home and recent-file routing, stable bilingual language entry,
rotated-text hover/double-click, independent positioned fragments within one
BT/ET block, and preserved EPS/PS page size (including page rotation).
The existing three-page EPS preview/export/video smoke check also passes.
All nine text-editing regressions also pass in a separately frozen executable
using the production packaging hooks and native Windows Qt plugin.

With the user's original three-page EPS, conservative recognition increases
from 53 to 125 independently positioned fragments, including previously skipped
rotated units. Replacing a unit label and exporting EPS, PS and PDF retains the
595 × 842 pt canvas; PS/PDF retain all three pages. The source is never changed.

Actual Home, recoloring, text editing and toolbar captures using synthetic data
are in `docs/screenshots`, reproducible with `scripts/capture_product_screenshots.py`.
Production EXE: 55,130,870 bytes (about 52.6 MiB). No new runtime dependencies.
Native macOS/Linux release artifacts were not rebuilt during this Windows update.

## 3.0.1 local candidate

All 38 source tests pass on Windows. New checks cover actual double-clicks on
rotated text in both the main preview and editing workspace, selected-character
size/color/bold styling, keyboard deletion and symbol insertion, rich-text PDF
reopening, Save committing a live edit, and EPS-first save filters. Workspace
checks cover returning to Home on last-tab close, recent-file activation,
1024 × 728 usable desktop bounds, settings round trips and cross-window
synchronization without changing document transforms.

All seven text-editing tests also pass in a separately frozen executable built
with production hooks and the native Windows Qt platform plugin.
The user's three-page EPS also passes the existing preview/export/video smoke
check. Home, categorized Settings, live mixed-style editing and applied output
were visually inspected. Production Windows EXE: 55,124,370 bytes, an increase
of 22,689 bytes (about 0.04%) over the previous local 3.0.0 build. No new runtime
dependency or font package was added. Native macOS/Linux execution has not been
verified for this local candidate; nothing has been pushed or published.

For 3.0.0, `test_text_editing.py` checks real text replacement (not a white
overlay), unchanged source bytes, preserved vector paths/page counts, unsupported
run rejection, vector EPS/PS output without cached glyph bitmaps, PDF text
re-identification, available CJK/Greek glyphs, undo, source overwrite protection,
home-screen metadata and toolbar icons. Fonts are taken from the test host.
The editor deliberately does not promise arbitrary PostScript/PDF text editing.

Windows 3.0.0 local verification: all 33 source tests pass; the four text-editing
tests also pass in a separately frozen executable using production hooks. The
user's three-page EPS passes the existing end-to-end preview/export/video smoke
check; 53 independent text runs are recognized. Home and editing-window captures
were visually inspected. Production EXE: 55,101,681 bytes (52.55 MiB); no runtime
dependencies or font bundles were added. Native macOS/Linux execution has not
been verified for this local 3.0.0 build.

For 2.3.1, `test_preview_rendering.py` compares partially transparent region
renders against whole-page sampling, verifies click-only repaint stability,
checks that zooming retains a complete image, and bounds cache growth/release.
`preview_profile.py path/to/file.eps` measures preview times and Windows process
working/private memory in an isolated configuration (no additional dependency).
With the user's three-page EPS, 1250 x 850 windows, and the same source runtime:

| Stage | 2.3.0 working set (MiB) | 2.3.1 working set (MiB) |
| --- | ---: | ---: |
| Empty window | 68.75 | 69.38 |
| Open one file | 96.34 | 87.73 |
| Six successive zooms | 176.97 | 94.77 |
| Then open a second window | 205.16 | 113.21 |

Measured first-open-to-settled time: 1.375 s → 0.875 s; six zoom-and-settle cycles:
3.063 s → 1.703 s. Each cycle includes a 150 ms idle verification interval.
These are development-machine measurements, not fixed memory or latency promises.

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
