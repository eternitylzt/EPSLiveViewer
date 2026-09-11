# Packaging regression check

Run `python tests/package_smoke.py path/to/multipage.eps` in the development environment.
The test copies the source into a temporary directory and uses isolated settings.
It expects at least two pages and an installed Ghostscript.

To verify bundled dependencies on Windows, build the same test with the production hooks:

```powershell
python -m PyInstaller --noconfirm --onefile --console --name PackageSmoke --paths . --additional-hooks-dir hooks --distpath build/smoke --workpath build/smoke-work tests/package_smoke.py
.\build\smoke\PackageSmoke.exe path/to/multipage.eps
```

The test covers multi-page EPS, PS file navigation, drop handling, live refresh,
zoom/wheel modes, backgrounds, PNG page export, multi-page vector PDF export,
atomic PDF failure handling, JPEG input, even/odd-sized MP4,
GIF frame count, proportional cropping, export cancellation, and both languages.
The video outputs are decoded by FFmpeg to verify that encoding produced readable files.
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
