#!/bin/bash
set -e
directory="$(cd "$(dirname "$0")" && pwd)"
backend="$directory/puzzle_card_detector"
ui="$directory/puzzle_flutter_ui"
sudo apt-get -y --no-install-recommends install libgtk-3-dev g++ pkg-config python3-venv git libgl1 libglib2.0-0 v4l-utils fake-hwclock
mkdir -p "$directory/.tools"
if [ ! -x "$directory/.tools/uv" ]; then
    python3 -m venv "$directory/.bootstrap"
    "$directory/.bootstrap/bin/python" -m pip install --upgrade pip==25.0.1
    "$directory/.bootstrap/bin/python" -m pip install uv==0.13.0
    cp "$directory/.bootstrap/bin/uv" "$directory/.tools/uv"
fi
uv="$directory/.tools/uv"
python="$directory/.python/cpython-3.13.5-linux-aarch64-gnu/bin/python3.13"
if [ ! -x "$python" ]; then
    "$uv" python install 3.13.5 --no-bin --install-dir "$directory/.python"
fi
if [ -x "$backend/.venv/bin/python" ] && ! "$backend/.venv/bin/python" -c 'import sys; assert sys.version_info[:2] == (3, 13)' 2>/dev/null; then
    mv "$backend/.venv" "$backend/.venv-previous-$(date +%Y%m%d-%H%M%S)"
fi
if [ ! -x "$backend/.venv/bin/python" ]; then
    "$uv" venv --python "$python" "$backend/.venv"
fi
if [ -d "$directory/wheelhouse" ]; then
    "$uv" pip install --python "$backend/.venv/bin/python" --no-index --find-links "$directory/wheelhouse" pip==25.0.1 -r "$backend/requirements-lubancat.txt"
else
    "$uv" pip install --python "$backend/.venv/bin/python" --only-binary :all: -r "$backend/requirements-lubancat.txt"
fi
bash "$backend/build_cpp_solver.sh"
bash "$ui/build_lubancat_runner.sh"
sudo install -m 0644 "$backend/99-puzzle-ch340.rules" /etc/udev/rules.d/99-puzzle-ch340.rules
sudo usermod -aG dialout,video,render "$USER"
sudo udevadm control --reload-rules
sudo fake-hwclock save
sudo systemctl enable fake-hwclock.service
mkdir -p "$HOME/.local/share/applications" "$HOME/.config/autostart"
cat >"$HOME/.local/share/applications/puzzle-device.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Puzzle Device
Name[zh_CN]=拼图装置
Comment=Puzzle vision and motion control
Exec=bash "$ui/start_ui.sh"
Path=$ui
Icon=applications-engineering
Terminal=false
StartupNotify=false
X-GNOME-Autostart-enabled=true
EOF
cp "$HOME/.local/share/applications/puzzle-device.desktop" "$HOME/.config/autostart/puzzle-device.desktop"
echo "SETUP_OK"
