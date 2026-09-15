# EPS Live Viewer

[中文](README.md) | [English](README_EN.md)

Current version: **2.2.1**.

Version 2.2.1 fixes menu bar and toolbar clicks that could be ignored on Apple Silicon Macs. Affected users should download the new `EPSLiveViewer-macOS-arm64.dmg` and replace the old app.

EPS Live Viewer is a lightweight cross-platform desktop viewer for rapid scientific plotting workflows. It live-previews EPS/PS files, opens PNG/JPG directly, and provides neighboring-file comparison, multi-page navigation, rotation, color inversion/replacement, export, and video creation in one interface.

## Main features

- Customizable toolbar: reload and rotation are hidden by default. Use View → Customize Toolbar or right-click the toolbar. New configurations default to a white background; existing preferences are retained.
- Independent tabs: Settings offers new windows (default) or tabs, including files opened by double-click. Each tab keeps its own view, edits, preferences, monitoring, and export jobs.
- Save edits: Ctrl+S saves rotation and color adjustments. Closing unsaved edits prompts to save, discard, or cancel.
- File information and text selection: inspect file/page details and select/copy text preserved in EPS/PS documents.

- Vector EPS/PS preview: visible content is rerendered for the current zoom, keeping paths and text sharp.
- PNG/JPG viewing: open, zoom, rotate, invert, and replace colors without Ghostscript.
- Live refresh when IDL, Python, MATLAB, Fortran, or another program regenerates the current file.
- Neighbor browsing: EPS, PS, PNG, and JPG/JPEG files in the same folder are naturally sorted; use `Left`/`Right` to compare them.
- Multi-page documents: use `Up`/`Down` for EPS/PS pages. The wheel can zoom, browse files, or change pages; `Ctrl + wheel` always zooms.
- Image adjustments: rotate left/right with a choice of current page or all pages, invert the whole document, and define up to 16 color replacements.
- Flexible color selection: Qt's dialog supports RGB and HEX, and a screen picker where the operating system provides one. Each mapping has an RGB tolerance. Processing always follows “invert → replace”, so click order does not change the result.
- Undo/redo: `Ctrl+Z` undoes adjustments; `Ctrl+Y` or `Ctrl+Shift+Z` redoes them. Each file keeps up to 50 operations, including across live refreshes.
- Live color preview: edits run in the background; hold View Original to compare original colors. OK applies the draft and Cancel preserves existing adjustments.
- Side-by-side comparison: pin the left reference and choose an independent right image/page or follow the main window, with linked zoom and pan.
- PNG export at 72–600 DPI. For multi-page EPS/PS, save the current page or export every page into a new folder.
- Document export: save adjusted output as PDF, PS, or EPS. PDF/PS retain all pages; standard EPS saves the current page.
- MP4/GIF creation: every EPS/PS page and every PNG/JPG can be an independent frame. Reorder/exclude frames, inherit the first frame's canvas size, crop proportionally, choose FPS, and apply existing rotation/color adjustments.
- Video rehearsal: see estimated duration and play, pause, seek, or loop a low-resolution preview before exporting. The output video is not overwritten.
- Manual diagnostics: view and copy versions, current page and adjustments, and recent errors. Reports are never uploaded automatically.
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
4. Choose **Current Page Only** or **All Pages** under **Image → Rotation Scope**, then rotate left/right. You can add these tools to the toolbar. Under **Image → Replace Colors**, choose source/target colors and tolerance; drag the divider to resize the editor and preview.
5. Use **Save as PNG/PDF/EPS/PS** to export the adjusted result. Color replacement stores PDF/PS/EPS pages as raster images at the selected DPI. Without replacements, rotation and inversion of EPS/PS content remain vector-based.
6. Choose **File → Create Video/Animation**. EPS/PS defaults to all pages of the current document; you can switch to a folder and filter formats. Edit the frame list and output options. Rehearsal identifies each file/page and uses the same pages and rotations as the main preview.

New workflow controls:

- **Image → Undo/Redo Image Adjustment** handles rotation, inversion, replacements, and resets. Rotating All Pages is one undoable operation.
- **Image → Replace Colors**: add a mapping, edit its color values, use Choose for RGB input, or change tolerance. The right-hand preview updates automatically. Hold View Original temporarily shows original colors while retaining page rotation.
- The video dialog shows frame count, FPS, and estimated duration. Preview uses the selected frames, order, crop, and colors. It is an approximate low-resolution rehearsal; the final export uses the selected canvas resolution.
- **View → Compare Side by Side** (`Ctrl+Shift+C`): the left reference is locked by default. Choose a right-hand image or let it follow the main window. Disable Link Zoom and Pan for independent navigation. Linked views use the same zoom percentage and relative page position. Choosing comparison images does not change the main window's source.
- **Help → Diagnostics** shows a report you can inspect and copy. Error dialogs also provide details. Diagnostics are kept for the current session only and may include local paths; review before sharing.

**File → Save Edits** (Ctrl+S) stores rotations, inversion, and color replacements in a neighboring `original-filename.epslive.json` file, restored automatically when you reopen the image. Move the record together with the source. Use Save as PNG/PDF/EPS/PS for a standalone adjusted image. Live refresh retains current edits.

**File → Settings → Open files in** chooses windows or tabs. Tabs have independent edits and settings, including when opening the same file twice. Changing settings does not change other existing tabs. Ctrl+W closes the current tab.

Side-by-side comparison supports maximization. For multi-page documents the right pane initially shows the next page; the dropdown also offers other pages, open tabs, and Browse.

**View → Select Text** enables drag selection; press Ctrl+C or use Copy Selected Text. Selection follows rotated pages. Disable the mode to resume drag-to-pan. Outlined glyphs and scanned images contain no selectable text; OCR is not included.

Video crop previews and exported frames use the same rotation/color pipeline. Reopening the creation window does not rotate an existing preview again. MP4 uses H.264 Main / YUV420; odd dimensions are padded by just 1 pixel on the right or bottom, preserving the complete crop. GIF dimensions are unchanged.

## FAQ

### Why will an EPS/PS file not display?

Install Ghostscript and select its console executable in Settings if automatic detection fails: usually `gswin64c.exe` on Windows and `gs` on Linux/macOS.

### Why does a PNG/JPG become blurry when enlarged?

PNG/JPG is raster data; the app cannot create missing detail. Photographs embedded in EPS/PS are likewise limited by their original resolution.

### Why does the video switch images like a slideshow?

Each image or page is one frame; duration is frame count divided by FPS. Distinct steps at low FPS are expected; raise FPS for faster switching. Version 2.0.1 improves MP4 player compatibility; re-export videos made with an older version.

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

Video rehearsal uses Qt timers and temporary PNG frames, not QtMultimedia. At most eight preview frames are held in memory; closing the dialog removes its temporary files. Color work is cancellable and obsolete results are discarded. Undo history stores small adjustment snapshots, not copies of source documents.

</details>

Author: Zhentong Li · eternitylzt@gmail.com
