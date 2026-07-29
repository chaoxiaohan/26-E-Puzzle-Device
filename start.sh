#!/bin/bash

set -e
cd /home/pi5/puzzle_detector

export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/1000
export PUZZLE_PORTRAIT=1
export PUZZLE_PORTRAIT_CROP_X=280

exec python3 /home/pi5/puzzle_detector/main.py
