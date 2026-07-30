import math
import time

import numpy as np

from puzzle_solver import solve_camera_rectangle
from solver_v2 import layout_metrics


def scramble(polygons):
    result = []
    for index, polygon in enumerate(polygons):
        polygon = np.asarray(polygon, dtype=np.float32)
        center = np.mean(polygon, axis=0)
        angle = math.radians((index * 67 + 23) % 180)
        rotation = np.array(
            [
                [math.cos(angle), -math.sin(angle)],
                [math.sin(angle), math.cos(angle)],
            ],
            dtype=np.float32,
        )
        offset = np.array(
            [
                420 + (index % 2) * 250,
                90 + (index // 2) * 210,
            ],
            dtype=np.float32,
        )
        moved = (polygon - center) @ rotation.T + offset
        result.append(
            {
                "points": [
                    (float(point[0]), float(point[1]))
                    for point in moved
                ]
            }
        )
    return result


cases = [
    [
        [(0, 0), (120, 0), (120, 144), (0, 144)],
        [(120, 0), (240, 0), (240, 144), (120, 144)],
    ],
    [
        [(0, 0), (80, 0), (80, 144), (0, 144)],
        [(80, 0), (160, 0), (160, 144), (80, 144)],
        [(160, 0), (240, 0), (240, 144), (160, 144)],
    ],
    [
        [(0, 0), (120, 0), (120, 72), (0, 72)],
        [(120, 0), (240, 0), (240, 72), (120, 72)],
        [(120, 72), (240, 72), (240, 144), (120, 144)],
        [(0, 72), (120, 72), (120, 144), (0, 144)],
    ],
]

for polygons in cases:
    pieces = scramble(polygons)
    started = time.monotonic()
    layout, score, nodes, info = solve_camera_rectangle(
        pieces,
        (380, 10, 520, 700),
        time_limit_s=3.0,
    )
    elapsed_ms = (time.monotonic() - started) * 1000.0
    if layout is None or info is None:
        raise RuntimeError(
            "%d-piece hybrid solve failed"
            % len(polygons)
        )
    metrics = layout_metrics(layout)
    if (
        metrics["coverage"] < 0.985
        or metrics["overlap"] > 0.006
        or metrics["corners"] < 0.99
    ):
        raise RuntimeError(
            "%d-piece result invalid: %s"
            % (len(polygons), metrics)
        )
    print(
        "HYBRID_%d_OK method=%s score=%.3f "
        "coverage=%.3f overlap=%.4f nodes=%d time=%.1fms"
        % (
            len(polygons),
            info["method"],
            score,
            metrics["coverage"],
            metrics["overlap"],
            nodes,
            elapsed_ms,
        )
    )
