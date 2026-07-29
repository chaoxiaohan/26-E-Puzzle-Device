import numpy as np

from layout_constraints import add_adjacency_gap, evaluate_layout


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

overlap_layout = {
    0: valid_cases["two"][0],
    1: valid_cases["two"][1] + np.array([-20.0, 0.0]),
}
overlap_report = evaluate_layout(overlap_layout)
if overlap_report["valid"] or "overlap" not in overlap_report["reasons"]:
    raise RuntimeError("overlap accepted: %s" % overlap_report)
print("overlap rejection OK")

l_shape = {
    0: polygon([(0, 0), (120, 0), (120, 72), (0, 72)]),
    1: polygon([(0, 72), (60, 72), (60, 144), (0, 144)]),
}
l_report = evaluate_layout(l_shape)
if l_report["valid"]:
    raise RuntimeError("L shape accepted: %s" % l_report)
print("non-rectangle rejection OK", l_report["reasons"])
