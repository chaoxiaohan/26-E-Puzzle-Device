#!/bin/bash

set -e
directory="$(cd "$(dirname "$0")" && pwd)"
cd "$directory"
export PUZZLE_BACKEND_DIR="${PUZZLE_BACKEND_DIR:-$(dirname "$directory")/puzzle_card_detector}"
export PUZZLE_PYTHON="${PUZZLE_PYTHON:-$PUZZLE_BACKEND_DIR/.venv/bin/python}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$UID}"
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    for socket in "$XDG_RUNTIME_DIR"/wayland-*; do
        if [ -S "$socket" ]; then
            export WAYLAND_DISPLAY="$(basename "$socket")"
            break
        fi
    done
    if [ -z "${WAYLAND_DISPLAY:-}" ] && [ -S /tmp/.X11-unix/X0 ]; then
        export DISPLAY=:0
    fi
fi
if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
    echo "No desktop session found. Start from the Pi desktop, or pass its DISPLAY/WAYLAND_DISPLAY." >&2
    exit 1
fi
# Inherit the Pi desktop's Wayland/X11 session and native renderer.
# Explicit FLUTTER_LINUX_RENDERER overrides remain available for diagnostics.
binary="$directory/build/linux/arm64/release/bundle/puzzle_flutter_ui"
if [ ! -x "$binary" ] || [ ! -x "$PUZZLE_PYTHON" ]; then
    echo "Pi 5 release is incomplete. Run deploy_pi5.sh on the Pi first." >&2
    exit 1
fi
if [ -z "$DBUS_SESSION_BUS_ADDRESS" ] && [ -S "$XDG_RUNTIME_DIR/bus" ]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
fi
exec 8>"$XDG_RUNTIME_DIR/puzzle-ui.lock"
flock -n 8 || { echo "Puzzle UI is already running"; exit 0; }
nohup env PUZZLE_HEADLESS=1 bash "$PUZZLE_BACKEND_DIR/start.sh" >>/tmp/puzzle_backend.log 2>&1 </dev/null 8>&- &
exec "$binary"
