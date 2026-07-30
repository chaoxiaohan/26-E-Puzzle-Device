import math

import numpy as np

from layout_constraints import (
    add_adjacency_gap,
    evaluate_layout,
    repair_layout_for_competition,
)


def polygon(points):
    return np.asarray(points, dtype=np.float64)


valid_cases = {
    "two": {
        0: polygon([(0, 0), (120, 0), (120, 144), (0, 144)]),
        1: polygon([(120, 0), (240, 0), (240, 144), (120, 144)]),
    },
    "three_t": {
        0: polygon([(0, 0), (240, 0), (240, 72), (0, 72)]),
        1: polygon([(0, 72), (120, 72), (120, 144), (0, 144)]),
        2: polygon(
            [(120, 72), (240, 72), (240, 144), (120, 144)]
        ),
    },
    "four_grid": {
        0: polygon([(0, 0), (120, 0), (120, 72), (0, 72)]),
        1: polygon([(120, 0), (240, 0), (240, 72), (120, 72)]),
        2: polygon([(0, 72), (120, 72), (120, 144), (0, 144)]),
        3: polygon(
            [(120, 72), (240, 72), (240, 144), (120, 144)]
        ),
    },
}

for name, layout in valid_cases.items():
    report = evaluate_layout(layout)
    if not report["valid"]:
        raise RuntimeError("%s rejected: %s" % (name, report))
    print(
        "%s OK coverage=%.3f overlap=%.4f outer=%.2f "
        "internal=%.3f perimeter=%.3f"
        % (
            name,
            report["coverage"],
            report["overlap"],
            report["outer_piece_ratio"],
            report["internal_match"],
            report["perimeter_error"],
        )
    )

gapped, gap_info = add_adjacency_gap(valid_cases["two"], 1.0)
if not gap_info["applied"] or gap_info["maximum_error"] > 1e-6:
    raise RuntimeError("gap failed: %s" % gap_info)
left_x = float(np.max(gapped[0][:, 0]))
right_x = float(np.min(gapped[1][:, 0]))
if not 0.99 <= right_x - left_x <= 1.01:
    raise RuntimeError(
        "wrong gap: %.3f" % (right_x - left_x)
    )
print("one-pixel adjacency gap OK")

angle = math.radians(37.0)
rotation = np.array(
    [
        [math.cos(angle), -math.sin(angle)],
        [math.sin(angle), math.cos(angle)],
    ],
    dtype=np.float64,
)
rotated = {
    piece_id: points @ rotation.T + np.array([35.0, 80.0])
    for piece_id, points in valid_cases["two"].items()
}
rotated_gapped, rotated_gap_info = add_adjacency_gap(rotated, 1.0)
if (
    not rotated_gap_info["applied"]
    or rotated_gap_info["maximum_error"] > 1e-6
):
    raise RuntimeError(
        "rotated gap failed: %s" % rotated_gap_info
    )
rotated_centers = {
    piece_id: np.mean(points, axis=0)
    for piece_id, points in rotated_gapped.items()
}
if np.linalg.norm(rotated_centers[1] - rotated_centers[0]) <= 120.9:
    raise RuntimeError("rotated pieces did not separate")
print("rotated adjacency gap OK")

overlap_layout = {
    0: valid_cases["two"][0],
    1: valid_cases["two"][1] + np.array([-20.0, 0.0]),
}
overlap_report = evaluate_layout(overlap_layout)
if overlap_report["valid"] or "overlap" not in overlap_report["reasons"]:
    raise RuntimeError("overlap accepted: %s" % overlap_report)
print("overlap rejection OK")

small_overlap_layout = {
    0: valid_cases["two"][0],
    1: valid_cases["two"][1] + np.array([-6.0, 0.0]),
}
repaired, repair_info = repair_layout_for_competition(
    small_overlap_layout,
    gap_pixels=1.0,
)
if repaired is None:
    raise RuntimeError(
        "competition repair failed: %s" % repair_info
    )
repaired_report = evaluate_layout(
    repaired,
    edge_tolerance_ratio=0.05,
)
if repaired_report["overlap"] > 0.001:
    raise RuntimeError(
        "competition repair kept overlap: %s"
        % repaired_report
    )
print(
    "competition repair OK move=%.2f"
    % repair_info["maximum_move"]
)

forced, forced_info = repair_layout_for_competition(
    overlap_layout,
    gap_pixels=1.0,
    force=True,
)
if forced is None or not forced_info["forced"]:
    raise RuntimeError("forced repair failed: %s" % forced_info)
forced_report = evaluate_layout(
    forced,
    edge_tolerance_ratio=0.05,
)
if forced_report["overlap"] > 0.001:
    raise RuntimeError(
        "forced repair kept overlap: %s" % forced_report
    )
print(
    "guaranteed-input repair OK move=%.2f"
    % forced_info["maximum_move"]
)

l_shape = {
    0: polygon([(0, 0), (120, 0), (120, 72), (0, 72)]),
    1: polygon([(0, 72), (60, 72), (60, 144), (0, 144)]),
}
l_report = evaluate_layout(l_shape)
if l_report["valid"]:
    raise RuntimeError("L shape accepted: %s" % l_report)
print("non-rectangle rejection OK", l_report["reasons"])

four_corners_with_broken_sides = {
    0: polygon([(0, 0), (100, 0), (70, 30), (0, 20)]),
    1: polygon([(100, 0), (200, 0), (200, 50), (170, 30)]),
    2: polygon([(200, 50), (200, 100), (100, 100), (140, 70)]),
    3: polygon([(0, 50), (60, 70), (100, 100), (0, 100)]),
}
broken_report = evaluate_layout(four_corners_with_broken_sides)
if broken_report["corners"] < 0.99:
    raise RuntimeError("broken-side fixture does not cover four corners")
if broken_report["outer_piece_ratio"] < 0.999:
    raise RuntimeError("broken-side fixture lacks outer-edge pieces")
if "rectangle-boundary" not in broken_report["reasons"]:
    raise RuntimeError("broken rectangle boundary accepted: %s" % broken_report)
print(
    "broken four-corner frame rejected coverage=%.3f gap=%.3f"
    % (
        broken_report["boundary_min_coverage"],
        broken_report["boundary_max_gap_ratio"],
    )
)
