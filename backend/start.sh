#!/bin/bash

set -e
cd /home/pi5/puzzle_card_detector

export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
export XDG_RUNTIME_DIR=/run/user/1000
export PUZZLE_PORTRAIT=1
export PUZZLE_ROTATION=CW

if [ ! -f librectangle_solver.so ] || [ rectangle_solver.cpp -nt librectangle_solver.so ]; then
    ./build_cpp_solver.sh
fi

exec python3 /home/pi5/puzzle_card_detector/main.py
