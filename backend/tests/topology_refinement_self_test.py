import numpy as np

from layout_constraints import evaluate_layout
from main import refine_card_layout_geometry


layout = {
    0: np.asarray(
        [(0, 0), (46, 0), (46, 26), (0, 26)],
        dtype=np.float64,
    ),
    1: np.asarray(
        [(56, 0), (100, 0), (100, 26), (56, 26)],
        dtype=np.float64,
    ),
    2: np.asarray(
        [(0, 36), (46, 36), (46, 60), (0, 60)],
        dtype=np.float64,
    ),
    3: np.asarray(
        [(56, 36), (100, 36), (100, 60), (56, 60)],
        dtype=np.float64,
    ),
}

before = evaluate_layout(layout, edge_tolerance_ratio=0.07)
refined, after = refine_card_layout_geometry(layout, time_limit_s=1.2)

if after["overlap"] > 0.008:
    raise RuntimeError("topology refinement introduced overlap")
if after["coverage"] < before["coverage"] + 0.10:
    raise RuntimeError(
        "topology refinement did not close the rectangle: %.3f -> %.3f"
        % (before["coverage"], after["coverage"])
    )
if after["internal_match"] < before["internal_match"]:
    raise RuntimeError("topology refinement reduced internal edge matching")

before_centers = {
    piece_id: np.mean(polygon, axis=0)
    for piece_id, polygon in layout.items()
}
after_centers = {
    piece_id: np.mean(polygon, axis=0)
    for piece_id, polygon in refined.items()
}
for first_id in sorted(layout):
    for second_id in sorted(layout):
        if second_id <= first_id:
            continue
        before_vector = before_centers[second_id] - before_centers[first_id]
        after_vector = after_centers[second_id] - after_centers[first_id]
        if np.dot(before_vector, after_vector) <= 0.0:
            raise RuntimeError("topology order changed")

print(
    "TOPOLOGY_REFINEMENT_OK coverage=%.3f->%.3f internal=%.3f->%.3f"
    % (
        before["coverage"],
        after["coverage"],
        before["internal_match"],
        after["internal_match"],
    )
)
