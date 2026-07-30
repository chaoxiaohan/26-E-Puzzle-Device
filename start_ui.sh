#!/bin/bash

set -e
cd /home/pi5/puzzle_flutter_ui

export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/1000

if ! pgrep -f '^python3 /home/pi5/puzzle_card_detector/main.py$' >/dev/null; then
    (
        cd /home/pi5/puzzle_card_detector
        PUZZLE_HEADLESS=1 ./start.sh
    ) >/tmp/puzzle_backend.log 2>&1 &
fi

if pgrep -f '^build/linux/arm64/release/bundle/puzzle_flutter_ui$' >/dev/null; then
    echo "Puzzle UI is already running"
    exit 0
fi

exec build/linux/arm64/release/bundle/puzzle_flutter_ui
