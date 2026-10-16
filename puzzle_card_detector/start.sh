#!/bin/bash
set -e
directory="$(cd "$(dirname "$0")" && pwd)"
cd "$directory"
export PUZZLE_PORTRAIT="${PUZZLE_PORTRAIT:-1}"
export PUZZLE_ROTATION="${PUZZLE_ROTATION:-CW}"
export PUZZLE_CAMERA="${PUZZLE_CAMERA:-auto}"
python="${PUZZLE_PYTHON:-$directory/.venv/bin/python}"
if [ ! -x "$python" ]; then
    echo "Python environment missing. Run deploy_pi5.sh on the Pi first." >&2
    exit 1
fi
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/puzzle-backend-$UID.lock"
flock -n 9 || exit 0
if [ ! -f librectangle_solver.so ] || [ rectangle_solver.cpp -nt librectangle_solver.so ]; then
    bash ./build_cpp_solver.sh
fi
exec "$python" "$directory/main.py"
