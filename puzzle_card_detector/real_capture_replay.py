import glob
import json
import os
import sys
import time

from layout_constraints import (
    evaluate_layout,
    repair_layout_for_competition,
)
from puzzle_solver import solve_camera_rectangle


arguments = [
    argument
    for argument in sys.argv[1:]
    if not argument.startswith("--")
]
capture_directory = (
    arguments[0]
    if arguments
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
)
allow_relaxed = "--relaxed" in sys.argv
use_legacy = "--legacy" in sys.argv
competition_mode = "--competition" in sys.argv
repair_mode = "--repair" in sys.argv
safe_cover = "--safe-cover" in sys.argv
safe_cover_ratio = 0.008
for argument in sys.argv:
    if argument.startswith("--safe-cover="):
        safe_cover = True
        safe_cover_ratio = float(argument.split("=", 1)[1])
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
        layout, score, nodes, info = solve_rectangle_by_cover(
            pieces,
            max_piece_overlap_ratio=(
                safe_cover_ratio
                if safe_cover
                else 0.30
            ),
        )
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

    report = evaluate_layout(
        layout,
        edge_tolerance_ratio=(
            0.035
            if competition_mode
            else 0.012
        ),
    )
    repair_info = None
    if repair_mode:
        repaired, repair_info = repair_layout_for_competition(
            layout,
            gap_pixels=1.0,
        )
        if repaired is not None:
            layout = repaired
            report = evaluate_layout(
                layout,
                edge_tolerance_ratio=0.05,
            )
    accepted = (
        repair_info["valid"]
        if repair_mode
        else report["competition_valid"]
        if competition_mode
        else report["valid"]
    )
    if accepted:
        succeeded += 1
    print(
        "%-4s %-30s method=%s score=%.3f coverage=%.3f "
        "overlap=%.4f outer=%.2f internal=%.3f reasons=%s "
        "nodes=%d time=%.1fms%s"
        % (
            "OK" if accepted else "BEST",
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
            (
                report["competition_reasons"]
                if competition_mode
                else report["reasons"]
            ),
            nodes,
            elapsed_ms,
            (
                " repair=%s move=%.2f"
                % (
                    repair_info["reasons"],
                    repair_info.get("maximum_move", 0.0),
                )
                if repair_info is not None
                else ""
            ),
        )
    )

print(
    "SUMMARY success=%d/%d"
    % (succeeded, attempted)
)
