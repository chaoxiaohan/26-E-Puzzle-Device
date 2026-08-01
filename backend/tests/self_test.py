# -*- coding: utf-8 -*-

import math
import time

import numpy as np

from main import (
    layout_has_interior_overlap,
    place_layout_on_paper,
    polygon_distance,
    solve_rectangle_by_cover,
)


base_pieces = [
    [(0, 0), (100, 0), (50, 30)],
    [(100, 0), (100, 60), (50, 30)],
    [(100, 60), (0, 60), (50, 30)],
    [(0, 60), (0, 0), (50, 30)],
]
angles = [23, -41, 78, 137]
offsets = [
    (300, 80),
    (520, 120),
    (410, 260),
    (650, 290),
]

pieces = []
for points, angle, offset in zip(
    base_pieces,
    angles,
    offsets,
):
    polygon = np.array(points, dtype=np.float32)
    center = np.mean(polygon, axis=0)
    radians = math.radians(angle)
    rotation = np.array(
        [
            [math.cos(radians), -math.sin(radians)],
            [math.sin(radians), math.cos(radians)],
        ],
        dtype=np.float32,
    )
    moved = (
        (polygon - center) @ rotation.T
        + np.array(offset, dtype=np.float32)
    )
    pieces.append(
        {
            "points": [
                (int(round(point[0])), int(round(point[1])))
                for point in moved
            ]
        }
    )

start = time.monotonic()
layout, score, tested, info = solve_rectangle_by_cover(
    pieces
)
elapsed_ms = (time.monotonic() - start) * 1000.0

if layout is None:
    raise RuntimeError("rectangle solver self-test failed")

fitted = place_layout_on_paper(
    layout,
    info,
    (100, 10, 520, 700),
)
placed = {
    item["piece_id"]: np.array(
        item["points"],
        dtype=np.float32,
    )
    for item in fitted
}
if layout_has_interior_overlap(placed):
    raise RuntimeError("placed layout contains overlap")

execution_gap = info.get("execution_gap", {})
if not execution_gap.get("applied", False):
    raise RuntimeError("execution gap was not applied: %s" % execution_gap)
minimum_vertex_gap = (
    execution_gap["minimum_gap"] / info["solve_scale"]
)
maximum_vertex_gap = (
    execution_gap["maximum_gap"] / info["solve_scale"]
)
if minimum_vertex_gap < 47.0 or maximum_vertex_gap > 53.0:
    raise RuntimeError(
        "adjacent vertex gaps are not near 50px: %.2f..%.2f"
        % (minimum_vertex_gap, maximum_vertex_gap)
    )

minimum_gap = min(
    polygon_distance(placed[first], placed[second])
    for first in range(4)
    for second in range(first + 1, 4)
)
if minimum_gap <= 0.0:
    raise RuntimeError(
        "placed polygon clearance is too small: %.2fpx"
        % minimum_gap
    )

print(
    "SELF_TEST_OK score=%.3f ratio=%.3f vertex_gap=%.1f..%.1fpx "
    "clearance=%.1fpx tested=%d time=%.1fms"
    % (
        score,
        info["ratio"],
        minimum_vertex_gap,
        maximum_vertex_gap,
        minimum_gap,
        tested,
        elapsed_ms,
    )
)

rough_detected_pieces = [
    {
        "points": [
            (745, 176),
            (867, 202),
            (904, 303),
            (746, 201),
        ]
    },
    {
        "points": [
            (687, 289),
            (773, 251),
            (832, 426),
            (797, 522),
        ]
    },
    {
        "points": [
            (589, 313),
            (641, 307),
            (660, 422),
            (590, 423),
        ]
    },
    {
        "points": [
            (932, 417),
            (1180, 421),
            (1055, 539),
        ]
    },
]

start = time.monotonic()
layout, score, tested, info = solve_rectangle_by_cover(
    rough_detected_pieces
)
elapsed_ms = (time.monotonic() - start) * 1000.0

if layout is not None:
    raise RuntimeError("low-score layout was not rejected")

print(
    "LOW_SCORE_REJECTED score=%.3f tested=%d time=%.1fms"
    % (
        score,
        tested,
        elapsed_ms,
    )
)
