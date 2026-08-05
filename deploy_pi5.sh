#!/usr/bin/env bash

set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
backend_dir="$HOME/puzzle_card_detector"
ui_dir="$HOME/puzzle_flutter_ui"
flutter_bin="${FLUTTER_BIN:-$HOME/flutter/bin/flutter}"

if [[ ! -d "$root_dir/backend" || ! -d "$root_dir/flutter_ui" ]]; then
    echo "Run deploy_pi5.sh from the repository root."
    exit 1
fi

if [[ ! -x "$flutter_bin" ]]; then
    echo "ARM64 Flutter was not found: $flutter_bin"
    echo "Install Flutter first, or rerun with FLUTTER_BIN=/path/to/flutter."
    exit 1
fi

echo "[1/5] Installing system dependencies"
sudo apt-get update
sudo apt-get install -y \
    python3 python3-opencv python3-numpy python3-serial \
    g++ make pkg-config rsync v4l-utils \
    libgl1 libgtk-3-0 libgtk-3-dev libusb-1.0-0 \
    clang cmake ninja-build

echo "[2/5] Deploying vision backend to $backend_dir"
mkdir -p "$backend_dir"
rsync -a --delete \
    --exclude='.git/' \
    --exclude='__pycache__/' \
    --exclude='captures/' \
    --exclude='*.pyc' \
    --exclude='*.log' \
    --exclude='librectangle_solver.so' \
    --exclude='vision_settings.json' \
    --exclude='serial_settings.json' \
    --exclude='roi_settings.json' \
    --exclude='templates.json' \
    "$root_dir/backend/" "$backend_dir/"

echo "[3/5] Building C++ solver"
chmod +x "$backend_dir/build_cpp_solver.sh" "$backend_dir/start.sh"
"$backend_dir/build_cpp_solver.sh"

echo "[4/5] Building Flutter UI"
mkdir -p "$ui_dir"
rsync -a --delete \
    --exclude='.git/' \
    --exclude='.dart_tool/' \
    --exclude='build/' \
    --exclude='.flutter-plugins-dependencies' \
    "$root_dir/flutter_ui/" "$ui_dir/"
chmod +x "$ui_dir/start_all.sh" "$ui_dir/start_ui.sh"
cd "$ui_dir"
"$flutter_bin" pub get
"$flutter_bin" build linux --release

echo "[5/5] Starting puzzle device"
exec "$ui_dir/start_all.sh"
