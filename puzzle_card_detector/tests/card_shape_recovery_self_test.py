import numpy as np

from card_face_solver import (
    _best_similarity_pose,
    generate_shape_swap_layouts,
)


quadrilateral = np.asarray(
    [(0, 0), (100, 0), (82, 60), (0, 60)],
    dtype=np.float64,
)
same_shape_with_extra_corner = np.asarray(
    [(0, 0), (50, 0), (100, 0), (82, 60), (0, 60)],
    dtype=np.float64,
)

pose_error = _best_similarity_pose(
    quadrilateral,
    same_shape_with_extra_corner,
)[-1]
if pose_error > 0.03:
    raise RuntimeError(
        "a collinear extra corner changed the recovered shape: "
        f"{pose_error:.4f}"
    )

pieces = [
    {"points": quadrilateral.copy()},
    {"points": same_shape_with_extra_corner + (180, 20)},
]
base_layout = {
    0: quadrilateral + (20, 100),
    1: same_shape_with_extra_corner + (200, 100),
}
assignments = {
    assignment
    for _, assignment in generate_shape_swap_layouts(pieces, base_layout)
}
if (1, 0) not in assignments:
    raise RuntimeError(
        "similar pieces with 4/5 detected corners were not exchanged"
    )

print("CARD_SHAPE_RECOVERY_OK")
