# EPS Live Viewer

[简体中文](README.md) | [English](README_EN.md)

EPS Live Viewer is a lightweight desktop viewer for rapid scientific-plot iteration. It opens EPS and PostScript (PS) files and automatically refreshes the preview when IDL, Python, MATLAB, Fortran, or another program rewrites the current file. The established Windows application remains unchanged, while the repository now provides the foundation for Linux and macOS builds.

## Features

- Open `.eps` and `.ps` files from the menu, command line, OS file association, or drag and drop.
- Detect rewritten, temporarily locked, or slowly written source files and refresh automatically.
- Vector-source preview: paths and text are rerendered at the current zoom instead of enlarging a fixed-DPI screenshot.
- Browse neighboring EPS/PS files in natural filename order with the left and right arrow keys.
- Zoom with the mouse wheel, pan by dragging, restore 100% with a double click, or fit with `Ctrl+0`.
- Use a transparent checkerboard, white, or custom preview background.
- Export PNG at 72–600 DPI with a transparent or composited background.
- Create MP4/GIF sequences from EPS, PS, PNG, JPG, and JPEG files, with filtering, ordering, frame rate, canvas, and background controls.
- Select a crop region interactively on the first frame; the same normalized region is applied to frames with different resolutions.
- Keep the ten most recently opened files.

## Platform support

| Platform | Package | Status |
| --- | --- | --- |
| Windows x64 | Single-file `EPSLiveViewer.exe` | Primary development and validation platform; existing usage is unchanged |
| Linux x64 | Single-file `EPSLiveViewer` | Initial portable build; requires a desktop environment and system Ghostscript |
| macOS Apple Silicon / Intel | `EPSLiveViewer.app` | Initial native builds for both architectures; currently unsigned and not notarized |

Download packages from [GitHub Releases](https://github.com/eternitylzt/EPSLiveViewer/releases). Linux and macOS packages are built on native GitHub-hosted runners and should be considered initial ports. Platform-specific reports are welcome through GitHub Issues.

## Usage

### 1. Requirements

Release packages do not require Python. Ghostscript is required to preview EPS/PS files or use them as video frames. Windows searches for `gswin64c.exe`; Linux and macOS search for `gs`. If detection fails, select the executable under **File → Settings**. Creating a video from PNG/JPG files alone does not require Ghostscript.

### 2. Open and live-preview a file

Use **文件 (File) → 打开 EPS/PS (Open EPS/PS)**, or drag an `.eps`/`.ps` file into the preview. A command-line example is:

```text
EPSLiveViewer path/to/figure.ps
```

After opening an output file, rerun your plotting code. The viewer refreshes after the write becomes stable and tries to preserve the current zoom and pan position.

Files in the same folder are naturally sorted by name. Press `←` or `→` to open the previous or next file. The status bar keeps the current filename and `[position/total]` visible, and the folder is rescanned whenever you navigate.

### 3. Export PNG

Choose **文件 (File) → 另存为 PNG (Save as PNG)**, then select the output path and DPI. Exporting always renders from the source EPS/PS and is independent of the current viewport.

### 4. Create MP4/GIF

Choose **文件 (File) → 制作视频/动图 (Create Video/Animation)**, then select a source folder.

- The left list contains included frames; move unwanted files to the right list.
- Drag items or use the move buttons to change frame order.
- When the first frame is PNG/JPG, its native pixel dimensions become the default canvas size.
- Select **Preview and choose region**, then drag on the first frame to crop the sequence. The crop is stored as relative coordinates, so later frames use the corresponding proportional region even when their resolutions differ.
- Choose MP4 or GIF, canvas size, frame rate, background color, and destination, then start the export.

EPS/PS sources use their first page. Frames preserve aspect ratio and are centered on the selected canvas.

## FAQ

### Ghostscript was not found

Install Ghostscript, then select its command-line executable in Settings. On Windows choose `gswin64c.exe`, not the windowed `gswin64.exe`. On Linux/macOS choose `gs`. Finder-launched macOS applications may not inherit your terminal PATH, so the app also checks common Homebrew locations.

### Where is the configuration stored?

For compatibility, Windows keeps `config.json` beside the EXE. Linux uses `$XDG_CONFIG_HOME/EPSLiveViewer/config.json` (or `~/.config/EPSLiveViewer/config.json` when the variable is unset); macOS uses `~/Library/Application Support/EPSLiveViewer/config.json`.

### The file does not refresh immediately

The viewer waits for writing to stabilize. For network drives or unusually slow writers, increase the detection interval to 800–1000 ms in Settings.

### The preview briefly looks soft while zooming

Visible tiles are rerendered after continuous zooming stops. Photos or bitmaps embedded inside EPS/PS remain limited by their original pixel resolution.

### macOS says the application cannot be verified

The initial macOS package is not signed or notarized. Review the source and release checksum before using it, then follow the security controls provided by your macOS version. A future signed release can replace this provisional distribution.

### Later frames have different resolutions

The crop is not stored as fixed first-frame pixels. Its left, top, width, and height are stored as proportions of the image, then converted to each frame's own pixels before fitting the output canvas.

<details>
<summary>Development and packaging</summary>

Use Python 3.11+ and install dependencies from `requirements.txt`. Ghostscript is also needed to exercise EPS/PS features.

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python main.py
```

Run `build.bat` on Windows to retain the original single-file build. On Linux or macOS run:

```bash
chmod +x build_unix.sh
./build_unix.sh
```

Pushing an `eps-live-viewer-v*` tag runs the [multi-platform release workflow](.github/workflows/eps-live-viewer-release.yml). It builds on native Windows, Ubuntu, macOS Apple Silicon, and macOS Intel runners, publishes archives and SHA-256 checksums, and creates a GitHub Release. PyInstaller does not cross-compile these desktop bundles from one operating system.

This project was developed primarily with the assistance of Codex.

</details>
