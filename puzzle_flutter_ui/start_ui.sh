#!/bin/bash

set -e
directory="$(cd "$(dirname "$0")" && pwd)"
cd "$directory"
export PUZZLE_BACKEND_DIR="${PUZZLE_BACKEND_DIR:-$(dirname "$directory")/puzzle_card_detector}"
export PUZZLE_PYTHON="${PUZZLE_PYTHON:-$PUZZLE_BACKEND_DIR/.venv/bin/python}"
export DISPLAY="${DISPLAY:-:0}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$UID}"
export FLUTTER_LINUX_RENDERER="${FLUTTER_LINUX_RENDERER:-software}"
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
exec 8>"$XDG_RUNTIME_DIR/puzzle-ui.lock"
flock -n 8 || { echo "Puzzle UI is already running"; exit 0; }
nohup env PUZZLE_HEADLESS=1 bash "$PUZZLE_BACKEND_DIR/start.sh" >>/tmp/puzzle_backend.log 2>&1 </dev/null 8>&- &
exec "$directory/build/linux/arm64/release/bundle/puzzle_flutter_ui"
