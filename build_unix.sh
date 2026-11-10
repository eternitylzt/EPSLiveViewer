#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python_command="${PYTHON_COMMAND:-python3}"
if [[ ! -x ".venv/bin/python" ]]; then
    "$python_command" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/prepare_ghostscript.py
QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/verify_bundled_ghostscript.py

common_args=(
    --noconfirm
    --clean
    --windowed
    --exclude-module numpy
    --name EPSLiveViewer
    --add-data "resources:resources"
    --additional-hooks-dir hooks
)

if [[ "$(uname -s)" == "Darwin" ]]; then
    .venv/bin/python -m PyInstaller \
        "${common_args[@]}" \
        --onedir \
        --icon resources/icon.icns \
        --osx-bundle-identifier com.zhentongli.epsliveviewer \
        main.py
    app_version="${APP_VERSION:-3.2.0}"
    .venv/bin/python scripts/configure_macos_bundle.py \
        dist/EPSLiveViewer.app/Contents/Info.plist "$app_version"
    codesign --force --deep --sign - dist/EPSLiveViewer.app
    rm -rf dmg-root
    mkdir -p dmg-root
    cp -R dist/EPSLiveViewer.app dmg-root/
    ln -s /Applications dmg-root/Applications
    cp README.md README_EN.md LICENSE THIRD_PARTY_NOTICES.md dmg-root/
    hdiutil create \
        -volname "EPS Live Viewer ${app_version}" \
        -srcfolder dmg-root \
        -format UDZO \
        -ov dist/EPSLiveViewer-macOS.dmg
    echo "Built dist/EPSLiveViewer.app and dist/EPSLiveViewer-macOS.dmg"
else
    .venv/bin/python -m PyInstaller "${common_args[@]}" --onefile main.py
    chmod +x dist/EPSLiveViewer
    echo "Built dist/EPSLiveViewer"
fi
