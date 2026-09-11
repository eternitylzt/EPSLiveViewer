# EPS Live Viewer

[中文](README.md) | [English](README_EN.md)

EPS Live Viewer is a lightweight cross-platform desktop viewer for rapid scientific plotting workflows. It live-previews EPS/PS files, opens PNG/JPG directly, and provides neighboring-file comparison, multi-page navigation, rotation, color inversion/replacement, export, and video creation in one interface.

## Main features

- Vector EPS/PS preview: visible content is rerendered for the current zoom, keeping paths and text sharp.
- PNG/JPG viewing: open, zoom, rotate, invert, and replace colors without Ghostscript.
- Live refresh when IDL, Python, MATLAB, Fortran, or another program regenerates the current file.
- Neighbor browsing: EPS, PS, PNG, and JPG/JPEG files in the same folder are naturally sorted; use `Left`/`Right` to compare them.
- Multi-page documents: use `Up`/`Down` for EPS/PS pages. The wheel can zoom, browse files, or change pages; `Ctrl + wheel` always zooms.
- Image adjustments: rotate the current page left/right, invert the whole document, and define up to 16 color replacements.
- Flexible color selection: Qt's dialog supports RGB and HEX, and a screen picker where the operating system provides one. Each mapping has an RGB tolerance. Processing always follows “invert → replace”, so click order does not change the result.
- PNG export at 72–600 DPI. For multi-page EPS/PS, save the current page or export every page into a new folder.
- Document export: save adjusted output as PDF, PS, or EPS. PDF/PS retain all pages; standard EPS saves the current page.
- MP4/GIF creation: every EPS/PS page and every PNG/JPG can be an independent frame. Reorder/exclude frames, inherit the first frame's canvas size, crop proportionally, choose FPS, and apply existing rotation/color adjustments.
- Chinese/English interface, recent files, configurable background, and manual GitHub update checks.

The viewer uses each file's own page/image dimensions and is not limited to A4, so no paper-size setting is needed. PNG/JPG is raster data and remains limited by its original pixels when enlarged.

## Installation

Download the appropriate package from [GitHub Releases](https://github.com/eternitylzt/EPSLiveViewer/releases):

- Windows: extract `EPSLiveViewer-Windows-x64.zip` and run `EPSLiveViewer.exe`.
- macOS Apple Silicon: download `EPSLiveViewer-macOS-arm64.dmg`.
- macOS Intel: download `EPSLiveViewer-macOS-x64.dmg`.
- Linux x64: extract `EPSLiveViewer-Linux-x64.tar.gz`, make the executable runnable, and launch it.

Release packages do not require Python. Ghostscript is required to view or process EPS/PS; the app searches automatically, or you can select it under **File → Settings**. Opening/adjusting PNG/JPG, saving PNG, and creating a video exclusively from raster images do not require Ghostscript. Exporting PNG/JPG to PDF/PS/EPS does.

## Usage

1. Choose **File → Open Image**, drop a supported file into the window, or pass its path on the command line.
2. Scroll to zoom, drag to pan, double-click for 100%, or use the toolbar zoom/fit controls.
3. Use the arrow keys to browse neighboring files and document pages. The status bar shows file position, page number, page size, zoom, and update time.
4. Rotate or invert from the **Image** menu/toolbar. Under **Image → Replace Colors**, choose source/target colors and tolerance.
5. Use **Save as PNG/PDF/EPS/PS** to export the adjusted result. Color replacement stores PDF/PS/EPS pages as raster images at the selected DPI. Without replacements, rotation and inversion of EPS/PS content remain vector-based.
6. Choose **File → Create Video/Animation**, select a folder, and edit the frame list and output options. Multi-page EPS/PS files are expanded into consecutive frames automatically.

Adjustments exist only in the current session and never modify the source. Live refresh retains the current file's adjustment state.

## FAQ

### Why will an EPS/PS file not display?

Install Ghostscript and select its console executable in Settings if automatic detection fails: usually `gswin64c.exe` on Windows and `gs` on Linux/macOS.

### Why does a PNG/JPG become blurry when enlarged?

PNG/JPG is raster data; the app cannot create missing detail. Photographs embedded in EPS/PS are likewise limited by their original resolution.

### Why does an inverted PDF remain vector while arbitrary replacement does not?

Rotation and whole-page inversion can use document graphics operations. Tolerance-based multi-color replacement must inspect pixels, so PDF/PS/EPS receives raster-backed pages at the chosen DPI. PNG and video are always pixel output.

### Why does macOS say the app is unsafe?

Formal signing and notarization require an Apple Developer certificate. If a Release is not notarized, Control-click the app in Finder and choose **Open**, or approve it in **Privacy & Security**. Download only from this project's Releases.

### Why can I not overwrite the current source?

Document export blocks that operation so live refresh and export cannot damage the open source. Choose a new filename.

### How do I check for updates?

Choose **Help → Check for Updates** manually. There is no background check, automatic download, or automatic installation.

<details>
<summary>Development and build information</summary>

The development stack is Python 3.11+, PyQt6, Ghostscript, and PyInstaller. After installing the requirements, run `python main.py example.eps`. Use `build.bat` for a one-file Windows EXE and `build_unix.sh` on Linux/macOS. Pushing an `eps-live-viewer-v*` tag triggers native Windows, Linux, macOS Apple Silicon, and macOS Intel builds and creates a GitHub Release.

Color processing uses only Qt/Python and adds no image or PDF dependency. Ghostscript remains the only EPS/PostScript interpreter.

</details>

Author: Zhentong Li · eternitylzt@gmail.com
