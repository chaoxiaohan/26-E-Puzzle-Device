#!/bin/bash

set -e
cd "$(dirname "$0")"

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

echo "Built $(pwd)/librectangle_solver.so for $(uname -m)"
