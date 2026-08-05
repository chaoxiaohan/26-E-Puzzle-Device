# -*- coding: utf-8 -*-

import numpy as np

from main import place_layout_on_paper, polygon_distance


layout = {
    0: np.asarray([(0, 0), (240, 0), (240, 72), (0, 72)], dtype=np.float64),
    1: np.asarray([(0, 72), (120, 72), (120, 144), (0, 144)], dtype=np.float64),
    2: np.asarray([(120, 72), (240, 72), (240, 144), (120, 144)], dtype=np.float64),
}
info = {
    "solve_scale": 1.0,
    "repair": {},
}
fitted = place_layout_on_paper(
    layout,
    info,
    (10, 100, 700, 900),
    50,
)
placed = {
    item["piece_id"]: np.asarray(item["points"], dtype=np.float64)
    for item in fitted
}
piece_ids = sorted(placed)
clearances = [
    polygon_distance(placed[piece_ids[first]], placed[piece_ids[second]])
    for first in range(len(piece_ids))
    for second in range(first + 1, len(piece_ids))
]
assert min(clearances) >= 49.5, clearances
assert info["execution_gap"]["minimum_clearance"] >= 49.5
print("execution gap OK min=%.2f" % min(clearances))
