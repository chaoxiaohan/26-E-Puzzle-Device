#!/bin/bash

set -e
cd /home/pi5/puzzle_card_detector

g++ \
    -O3 \
    -march=native \
    -flto \
    -pthread \
    -std=c++17 \
    -fPIC \
    -shared \
    rectangle_solver.cpp \
    -o librectangle_solver.so

echo "built /home/pi5/puzzle_card_detector/librectangle_solver.so"
