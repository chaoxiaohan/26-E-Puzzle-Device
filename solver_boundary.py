import itertools
import math
import time

import cv2
import numpy as np

try:
    from .solver_v2 import (
        layout_metrics,
        normalize_polygon,
        polygons_overlap,
    )
except ImportError:
    from solver_v2 import (
        layout_metrics,
        normalize_polygon,
        polygons_overlap,
    )


def polygon_area(polygon):
    return abs(cv2.contourArea(polygon.astype(np.float32)))


def edge_length(polygon, edge_id):
    return float(
        np.linalg.norm(
            polygon[(edge_id + 1) % len(polygon)]
            - polygon[edge_id]
        )
    )


def align_edge(polygon, edge_id, target_start, target_end):
    source_start = polygon[edge_id]
    source_end = polygon[(edge_id + 1) % len(polygon)]
    source_vector = source_end - source_start
    target_vector = target_end - target_start
    source_length = float(np.linalg.norm(source_vector))
    target_length = float(np.linalg.norm(target_vector))
    if source_length < 1e-6 or target_length < 1e-6:
        return None

    source_angle = math.atan2(source_vector[1], source_vector[0])
    target_angle = math.atan2(target_vector[1], target_vector[0])
    angle = target_angle - source_angle
    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotation = np.array(
        [[cosine, -sine], [sine, cosine]],
        dtype=np.float64,
    )
    return (polygon - source_start) @ rotation.T + target_start


def subset_sums(lengths, maximum_items):
    values = [0.0]
    for count in range(1, min(maximum_items, len(lengths)) + 1):
        for selected in itertools.combinations(lengths, count):
            values.append(sum(selected))
    return values


def unique_values(values, distance):
    result = []
    for value in sorted(values):
        if not result or abs(value - result[-1]) >= distance:
            result.append(value)
        elif abs(value - round(value)) < abs(result[-1] - round(result[-1])):
            result[-1] = value
    return result


def rectangle_candidates(
    polygons,
    dimension_range=None,
):
    total_area = sum(polygon_area(polygon) for polygon in polygons)
    if dimension_range is None:
        dimension_range = (89.0, 121.0, 49.0, 91.0)
    elif dimension_range == "auto":
        square_side = math.sqrt(max(1.0, total_area))
        dimension_range = (
            square_side * 0.97,
            math.sqrt(total_area * 2.4) * 1.03,
            math.sqrt(total_area / 2.4) * 0.97,
            square_side * 1.03,
        )
    long_min, long_max, short_min, short_max = dimension_range
    lengths = [
        edge_length(polygon, edge_id)
        for polygon in polygons
        for edge_id in range(len(polygon))
    ]
    sums = subset_sums(lengths, len(polygons))
    long_values = [
        value
        for value in sums
        if long_min <= value <= long_max
    ]
    short_sums = [
        value
        for value in sums
        if short_min <= value <= short_max
    ]

    candidates = []
    for width in long_values:
        height = total_area / width
        if not short_min <= height <= short_max:
            continue
        short_error = min(
            abs(value - height)
            for value in short_sums
        ) if short_sums else 99.0
        support = sum(
            min(abs(length - width), abs(length - height)) <= 1.0
            for length in lengths
        )
        candidates.append(
            (
                short_error,
                -support,
                width,
                height,
            )
        )

    candidates.sort()
    result = []
    for _, _, width, height in candidates:
        if any(
            abs(width - old_width) < 0.35
            and abs(height - old_height) < 0.35
            for old_width, old_height in result
        ):
            continue
        result.append((width, height))
        if len(result) >= 36:
            break
    return result, lengths


def boundary_offsets(side_length, edge_size, lengths, piece_count):
    maximum = side_length - edge_size
    if maximum < -1.5:
        return []
    maximum = max(0.0, maximum)
    values = [0.0, maximum]
    for value in subset_sums(lengths, max(1, piece_count - 1)):
        values.extend([value, maximum - value])
    return unique_values(
        [
            min(maximum, max(0.0, value))
            for value in values
            if -1.5 <= value <= maximum + 1.5
        ],
        0.35,
    )


def pose_candidates(
    polygon,
    width,
    height,
    lengths,
    piece_count,
    noise_tolerance,
):
    poses = []
    generated = set()
    for edge_id in range(len(polygon)):
        size = edge_length(polygon, edge_id)
        sides = [
            ("top", width, np.array([1.0, 0.0])),
            ("bottom", width, np.array([1.0, 0.0])),
            ("left", height, np.array([0.0, 1.0])),
            ("right", height, np.array([0.0, 1.0])),
        ]
        for side_name, side_length, direction in sides:
            offsets = boundary_offsets(
                side_length,
                size,
                lengths,
                piece_count,
            )
            for offset in offsets:
                if side_name == "top":
                    start = np.array([offset, 0.0])
                elif side_name == "bottom":
                    start = np.array([offset, height])
                elif side_name == "left":
                    start = np.array([0.0, offset])
                else:
                    start = np.array([width, offset])
                end = start + direction * size

                for first, second in (
                    (start, end),
                    (end, start),
                ):
                    transformed = align_edge(
                        polygon,
                        edge_id,
                        first,
                        second,
                    )
                    if transformed is None:
                        continue
                    minimum = np.min(transformed, axis=0)
                    maximum = np.max(transformed, axis=0)
                    if (
                        minimum[0] < -noise_tolerance
                        or minimum[1] < -noise_tolerance
                        or maximum[0] > width + noise_tolerance
                        or maximum[1] > height + noise_tolerance
                    ):
                        continue

                    center = np.mean(transformed, axis=0)
                    first_vector = transformed[1] - transformed[0]
                    angle = math.degrees(
                        math.atan2(first_vector[1], first_vector[0])
                    )
                    key = (
                        int(round(center[0] * 2.0)),
                        int(round(center[1] * 2.0)),
                        int(round(angle * 2.0)),
                    )
                    if key in generated:
                        continue
                    generated.add(key)

                    corner_distance = min(
                        math.hypot(point[0] - corner[0], point[1] - corner[1])
                        for point in transformed
                        for corner in (
                            (0.0, 0.0),
                            (width, 0.0),
                            (width, height),
                            (0.0, height),
                        )
                    )
                    poses.append((corner_distance, transformed))
    poses.sort(key=lambda item: item[0])
    return [polygon for _, polygon in poses]


def solve(
    pieces,
    node_limit=60000,
    time_limit_s=3.0,
    noise_tolerance=1.6,
    dimension_range=None,
):
    if not 1 <= len(pieces) <= 4:
        return None, 0.0, 0, None

    polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    dimensions, lengths = rectangle_candidates(
        polygons,
        dimension_range,
    )
    started = time.perf_counter()
    nodes = 0
    best_layout = None
    best_metrics = None

    for width, height in dimensions:
        if nodes >= node_limit:
            break
        if time.perf_counter() - started >= time_limit_s:
            break

        candidates = {
            piece_id: pose_candidates(
                polygon,
                width,
                height,
                lengths,
                len(polygons),
                noise_tolerance,
            )
            for piece_id, polygon in enumerate(polygons)
        }
        if any(not poses for poses in candidates.values()):
            continue

        def search(placed, remaining):
            nonlocal nodes
            nonlocal best_layout
            nonlocal best_metrics

            if nodes >= node_limit:
                return False
            if time.perf_counter() - started >= time_limit_s:
                return False
            nodes += 1

            if not remaining:
                metrics = layout_metrics(placed)
                dimension_error = max(
                    abs(metrics["width"] - width) / width,
                    abs(metrics["height"] - height) / height,
                )
                metrics["dimension_error"] = dimension_error
                if (
                    best_metrics is None
                    or metrics["score"] > best_metrics["score"]
                ):
                    best_metrics = metrics
                    best_layout = {
                        piece_id: polygon.copy()
                        for piece_id, polygon in placed.items()
                    }
                return (
                    metrics["coverage"] >= 0.985
                    and metrics["overlap"] <= 0.006
                    and metrics["corners"] >= 0.99
                    and dimension_error <= 0.025
                )

            compatible = {}
            for piece_id in remaining:
                compatible[piece_id] = [
                    pose
                    for pose in candidates[piece_id]
                    if not any(
                        polygons_overlap(
                            pose,
                            old_pose,
                            tolerance_ratio=0.01,
                        )
                        for old_pose in placed.values()
                    )
                ]
                if not compatible[piece_id]:
                    return False

            piece_id = min(
                remaining,
                key=lambda current: len(compatible[current]),
            )
            next_remaining = set(remaining)
            next_remaining.remove(piece_id)
            for pose in compatible[piece_id]:
                next_placed = dict(placed)
                next_placed[piece_id] = pose
                if search(next_placed, next_remaining):
                    return True
            return False

        if search({}, set(range(len(polygons)))):
            break

    if best_metrics is None:
        return None, 0.0, nodes, None
    if (
        best_metrics["coverage"] < 0.94
        or best_metrics["overlap"] > 0.025
        or best_metrics["corners"] < 0.75
    ):
        return None, best_metrics["score"], nodes, best_metrics
    return best_layout, best_metrics["score"], nodes, best_metrics
