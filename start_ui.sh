#!/bin/bash

set -e
cd /home/pi5/puzzle_flutter_ui

export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/1000

exec build/linux/arm64/release/bundle/puzzle_flutter_ui
