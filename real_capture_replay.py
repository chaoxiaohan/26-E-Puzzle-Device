import glob
import json
import os
import sys
import time

from layout_constraints import evaluate_layout
from puzzle_solver import solve_camera_rectangle


arguments = [
    argument
    for argument in sys.argv[1:]
    if not argument.startswith("--")
]
capture_directory = (
    arguments[0]
    if arguments
    else "/home/pi5/puzzle_detector/captures"
)
allow_relaxed = "--relaxed" in sys.argv
use_legacy = "--legacy" in sys.argv
if use_legacy:
    from main import solve_rectangle_by_cover
attempted = 0
succeeded = 0
for path in sorted(glob.glob(os.path.join(capture_directory, "*.json"))):
    with open(path, "r", encoding="utf-8") as capture_file:
        data = json.load(capture_file)
    pieces = data.get("pieces", [])
    if not 2 <= len(pieces) <= 4:
        continue

    attempted += 1
    started = time.perf_counter()
    if use_legacy:
        layout, score, nodes, info = solve_rectangle_by_cover(pieces)
    else:
        layout, score, nodes, info = solve_camera_rectangle(
            pieces,
            data.get("roi", (0, 0, 1, 1)),
            time_limit_s=3.0,
            allow_relaxed=allow_relaxed,
        )
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if layout is None:
        print(
            "FAIL %-30s score=%.3f nodes=%d time=%.1fms"
            % (os.path.basename(path), score, nodes, elapsed_ms)
        )
        continue

    report = evaluate_layout(layout)
    if report["valid"]:
        succeeded += 1
    print(
        "%-4s %-30s method=%s score=%.3f coverage=%.3f "
        "overlap=%.4f outer=%.2f internal=%.3f reasons=%s "
        "nodes=%d time=%.1fms"
        % (
            "OK" if report["valid"] else "BEST",
            os.path.basename(path),
            (
                "legacy"
                if use_legacy
                else info["method"]
            ),
            score,
            report["coverage"],
            report["overlap"],
            report["outer_piece_ratio"],
            report["internal_match"],
            report["reasons"],
            nodes,
            elapsed_ms,
        )
    )

print(
    "SUMMARY success=%d/%d"
    % (succeeded, attempted)
)
