# EPS Live Viewer

[简体中文](README.md) | [English](README_EN.md)

EPS Live Viewer is a lightweight desktop viewer for rapid scientific-plot iteration. It opens EPS and PostScript (PS) files and automatically refreshes the preview when IDL, Python, MATLAB, Fortran, or another program rewrites the current file. The established Windows application remains unchanged, while the repository now provides the foundation for Linux and macOS builds.

## Features

- Open `.eps` and `.ps` files from the menu, command line, OS file association, or drag and drop.
- Detect rewritten, temporarily locked, or slowly written source files and refresh automatically.
- Vector-source preview: paths and text are rerendered at the current zoom instead of enlarging a fixed-DPI screenshot.
- Browse neighboring EPS/PS files in natural filename order with the left and right arrow keys.
- Use Up/Down to move through multi-page EPS/PS files; the status bar shows the current page and PNG export saves that page.
- Zoom with the mouse wheel, pan by dragging, restore 100% with a double click, or fit with `Ctrl+0`.
- Configure the wheel to zoom, browse neighboring files, or change pages. `Ctrl+wheel` always zooms in the latter two modes.
- Use the top toolbar for opening, reloading, file/page navigation, zooming, fitting, and PNG export.
- Switch the complete interface between Simplified Chinese and English immediately in Settings.
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
| macOS Apple Silicon / Intel | `.dmg` installer containing `EPSLiveViewer.app` | Installable builds for both architectures; not signed with an Apple Developer certificate or notarized |

Download packages from [GitHub Releases](https://github.com/eternitylzt/EPSLiveViewer/releases). Linux and macOS packages are built on native GitHub-hosted runners and should be considered initial ports. Platform-specific reports are welcome through GitHub Issues.

## Usage

### 1. Requirements

Release packages do not require Python. On macOS, download the Apple Silicon build for an M-series Mac or the Intel build for an Intel Mac, open the DMG, and drag `EPSLiveViewer.app` into `Applications`. EPS/PS files associated with the app are delivered directly by Finder whether the app is already running or newly launched. Ghostscript is required to preview EPS/PS files or use them as video frames. Windows searches for `gswin64c.exe`; Linux and macOS search for `gs`. If detection fails, select the executable under **File → Settings**. Creating a video from PNG/JPG files alone does not require Ghostscript.

### 2. Open and live-preview a file

Use **文件 (File) → 打开 EPS/PS (Open EPS/PS)**, or drag an `.eps`/`.ps` file into the preview. A command-line example is:

```text
EPSLiveViewer path/to/figure.ps
```

After opening an output file, rerun your plotting code. The viewer refreshes after the write becomes stable and tries to preserve the current zoom and pan position.

Files in the same folder are naturally sorted by name. Press `←` or `→` to open the previous or next file. The status bar keeps the current filename and `[position/total]` visible, and the folder is rescanned whenever you navigate.

For a multi-page document, press `↑` or `↓` for the previous or next page. Single-page files ignore page navigation. The wheel defaults to zooming; choose file or page navigation under **File → Settings** if preferred. Arrow-key behavior is independent of this setting.

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

If a Release is marked as unnotarized, open `Applications` in Finder for the first launch, Control-click EPS Live Viewer, choose **Open**, and confirm once more. Fully removing this warning requires a Developer ID certificate and Apple notarization. The release workflow now signs, notarizes, and staples automatically when credentials are configured; an ad-hoc signature cannot replace Apple's trust chain.

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

Run `build.bat` on Windows to retain the original single-file build.

The Windows build uses `hooks/` to omit the unused software OpenGL library and losslessly compress the complete bundled FFmpeg executable. The encoder is unpacked into a temporary directory on first video export and cleaned up at exit. Viewing needs no encoder extraction; video export needs no download or separate FFmpeg installation. Keep `--additional-hooks-dir hooks` and do not combine it with `--collect-all imageio_ffmpeg`, which would package duplicate files. Preview and video export share image-reading code. File-lock handling, cancellation, memory limits, and atomic output remain in place.

On Linux or macOS run:

```bash
chmod +x build_unix.sh
./build_unix.sh
```

Pushing an `eps-live-viewer-v*` tag or manually running the [multi-platform release workflow](.github/workflows/eps-live-viewer-release.yml) builds on native Windows, Ubuntu, macOS Apple Silicon, and macOS Intel runners. It publishes platform packages, macOS DMGs, and SHA-256 checksums, then creates or updates a GitHub Release. PyInstaller does not cross-compile these desktop bundles from one operating system.

For formal macOS signing and notarization, configure repository secrets named `MACOS_CERTIFICATE`, `MACOS_CERTIFICATE_PASSWORD`, `MACOS_SIGNING_IDENTITY`, `MACOS_NOTARY_APPLE_ID`, `MACOS_NOTARY_TEAM_ID`, and `MACOS_NOTARY_PASSWORD`. Without them, the workflow falls back to an ad-hoc-signed, unnotarized build.

This project was developed primarily with the assistance of Codex.

</details>
