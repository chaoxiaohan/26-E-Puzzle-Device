import math

import cv2
import numpy as np

from layout_constraints import evaluate_layout
from solver_hybrid import solve
from solver_v2 import layout_metrics


def normalize_layout(layout):
    all_points = np.vstack(
        [
            np.asarray(polygon, dtype=np.float64)
            for polygon in layout.values()
        ]
    ).astype(np.float32)
    rectangle = cv2.minAreaRect(all_points)
    box = cv2.boxPoints(rectangle)
    edges = [
        box[(index + 1) % 4] - box[index]
        for index in range(4)
    ]
    longest = max(
        edges,
        key=lambda edge: float(np.dot(edge, edge)),
    )
    angle = math.atan2(longest[1], longest[0])
    cosine = math.cos(-angle)
    sine = math.sin(-angle)
    rotation = np.array(
        [[cosine, -sine], [sine, cosine]],
        dtype=np.float64,
    )
    center = np.array(rectangle[0], dtype=np.float64)
    rotated = {
        piece_id: (
            np.asarray(polygon, dtype=np.float64) - center
        ) @ rotation.T
        for piece_id, polygon in layout.items()
    }
    minimum = np.min(np.vstack(list(rotated.values())), axis=0)
    return {
        piece_id: (polygon - minimum).astype(np.float32)
        for piece_id, polygon in rotated.items()
    }


def solve_camera_rectangle(
    pieces,
    roi,
    time_limit_s=3.0,
    allow_relaxed=False,
):
    if not 2 <= len(pieces) <= 4:
        return None, 0.0, 0, None

    layout, score, nodes, metrics, method = solve(
        pieces,
        time_limit_s=time_limit_s,
        dimension_range="auto",
        allow_relaxed=allow_relaxed,
    )
    if layout is None or metrics is None:
        return None, score, nodes, None

    normalized = normalize_layout(layout)
    normalized_metrics = layout_metrics(normalized)
    constraint_report = evaluate_layout(normalized)
    aspect_ratio = (
        metrics["width"]
        / max(1.0, metrics["height"])
    )
    if (
        metrics["coverage"] < 0.86
        or metrics["overlap"] > 0.015
        or metrics["corners"] < 0.25
        or not 0.98 <= aspect_ratio <= 2.45
    ):
        return None, score, nodes, None
    if not allow_relaxed and not constraint_report["valid"]:
        return None, score, nodes, None

    relaxed = bool(
        metrics["coverage"] < 0.94
        or metrics["corners"] < 0.75
        or not constraint_report["valid"]
    )

    info = {
        "solve_scale": 1.0,
        "width": normalized_metrics["width"],
        "height": normalized_metrics["height"],
        "ratio": (
            normalized_metrics["width"]
            / max(1.0, normalized_metrics["height"])
        ),
        "coverage": metrics["coverage"],
        "overlap": metrics["overlap"],
        "method": method + ("-relaxed" if relaxed else ""),
        "relaxed": relaxed,
        "outer_piece_ratio": constraint_report["outer_piece_ratio"],
        "internal_match": constraint_report["internal_match"],
        "perimeter_error": constraint_report["perimeter_error"],
        "adjacency_count": len(constraint_report["adjacencies"]),
        "rejection_reasons": constraint_report["reasons"],
    }
    return normalized, score, nodes, info
