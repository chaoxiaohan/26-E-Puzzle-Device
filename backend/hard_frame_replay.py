import glob
import json
import os
import sys
import time

from cpp_rectangle_solver import solve
from layout_constraints import evaluate_layout


directory = sys.argv[1] if len(sys.argv) > 1 else "captures"
paths = sorted(glob.glob(os.path.join(directory, "*.json")))
for path in paths:
    with open(path, "r", encoding="utf-8") as capture_file:
        capture = json.load(capture_file)
    pieces = capture.get("pieces", [])
    if not 2 <= len(pieces) <= 4:
        continue

    started = time.perf_counter()
    result = None
    tested = 0
    for fill_ratio, position_step in (
        (0.96, 4),
        (0.88, 4),
        (0.80, 4),
        (0.80, 3),
        (0.76, 3),
        (0.72, 2),
    ):
        layout, score, nodes, info = solve(
            pieces,
            fill_ratio=fill_ratio,
            position_step=position_step,
        )
        tested += nodes
        if layout is None:
            continue
        report = evaluate_layout(layout, edge_tolerance_ratio=0.035)
        if (
            report["corners"] < 0.99
            or report["outer_piece_ratio"] < 0.999
            or report["coverage"] < 0.82
            or report["internal_match"] < 0.42
            or report["boundary_min_coverage"] < 0.88
            or report["boundary_max_gap_ratio"] > 0.12
            or report["boundary_angle_error"] > 7.0
        ):
            continue
        result = (fill_ratio, score, info, report)
        break

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if result is None:
        print(
            "REJECT %-28s pieces=%d nodes=%d time=%.1fms"
            % (os.path.basename(path), len(pieces), tested, elapsed_ms)
        )
        continue
    fill_ratio, score, info, report = result
    print(
        "PASS   %-28s fill=%.2f score=%.3f coverage=%.3f "
        "internal=%.3f side=%.3f gap=%.3f angle=%.2f time=%.1fms"
        % (
            os.path.basename(path),
            fill_ratio,
            score,
            report["coverage"],
            report["internal_match"],
            report["boundary_min_coverage"],
            report["boundary_max_gap_ratio"],
            report["boundary_angle_error"],
            elapsed_ms,
        )
    )
