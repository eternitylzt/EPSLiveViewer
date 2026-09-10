#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python_command="${PYTHON_COMMAND:-python3}"
if [[ ! -x ".venv/bin/python" ]]; then
    "$python_command" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

common_args=(
    --noconfirm
    --clean
    --windowed
    --name EPSLiveViewer
    --add-data "resources:resources"
    --collect-all imageio_ffmpeg
)

if [[ "$(uname -s)" == "Darwin" ]]; then
    .venv/bin/python -m PyInstaller \
        "${common_args[@]}" \
        --onedir \
        --osx-bundle-identifier com.zhentongli.epsliveviewer \
        main.py
    echo "Built dist/EPSLiveViewer.app"
else
    .venv/bin/python -m PyInstaller "${common_args[@]}" --onefile main.py
    chmod +x dist/EPSLiveViewer
    echo "Built dist/EPSLiveViewer"
fi
