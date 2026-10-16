#!/usr/bin/env bash
set -euo pipefail
directory="$(cd "$(dirname "$0")" && pwd)"
exec "${PUZZLE_SETUP_PYTHON:-python3}" "$directory/tools/pi5_deploy.py" "$@"
