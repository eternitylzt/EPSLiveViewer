# Packaging regression check

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
