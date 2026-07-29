import math
import time

import cv2
import numpy as np


def normalize_polygon(points):
    polygon = np.asarray(points, dtype=np.float64)
    if cv2.contourArea(
        polygon.astype(np.float32),
        oriented=True,
    ) < 0:
        polygon = polygon[::-1].copy()
    return polygon


def edge_length(polygon, edge_id):
    return float(
        np.linalg.norm(
            polygon[(edge_id + 1) % len(polygon)]
            - polygon[edge_id]
        )
    )


def polygon_center(polygon):
    moments = cv2.moments(polygon.astype(np.float32))
    if abs(moments["m00"]) < 1e-9:
        return np.mean(polygon, axis=0)
    return np.array(
        [
            moments["m10"] / moments["m00"],
            moments["m01"] / moments["m00"],
        ],
        dtype=np.float64,
    )


def align_edge_segment(
    polygon,
    edge_id,
    source_offset,
    shared_length,
    target_start,
    target_end,
):
    source_start = polygon[edge_id]
    source_end = polygon[(edge_id + 1) % len(polygon)]
    source_vector = source_end - source_start
    source_length = float(np.linalg.norm(source_vector))
    if source_length < 1e-9:
        return None
    source_unit = source_vector / source_length
    segment_start = source_start + source_unit * source_offset
    segment_end = segment_start + source_unit * shared_length
    source_angle = math.atan2(
        segment_end[1] - segment_start[1],
        segment_end[0] - segment_start[0],
    )
    target_angle = math.atan2(
        target_start[1] - target_end[1],
        target_start[0] - target_end[0],
    )
    angle = target_angle - source_angle
    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotation = np.array(
        [
            [cosine, -sine],
            [sine, cosine],
        ],
        dtype=np.float64,
    )
    source_middle = (segment_start + segment_end) * 0.5
    target_middle = (target_start + target_end) * 0.5
    return (
        (polygon - source_middle) @ rotation.T
        + target_middle
    )


def opposite_sides(
    edge_start,
    edge_end,
    first_center,
    second_center,
):
    edge = edge_end - edge_start
    first_side = (
        edge[0] * (first_center[1] - edge_start[1])
        - edge[1] * (first_center[0] - edge_start[0])
    )
    second_side = (
        edge[0] * (second_center[1] - edge_start[1])
        - edge[1] * (second_center[0] - edge_start[0])
    )
    return first_side * second_side < 0


def polygons_overlap(first, second, tolerance_ratio=0.006):
    all_points = np.vstack((first, second))
    minimum = np.floor(np.min(all_points, axis=0)) - 2.0
    maximum = np.ceil(np.max(all_points, axis=0)) + 2.0
    width = int((maximum[0] - minimum[0]) * 2.0) + 1
    height = int((maximum[1] - minimum[1]) * 2.0) + 1
    if width <= 0 or height <= 0:
        return True

    first_mask = np.zeros((height, width), dtype=np.uint8)
    second_mask = np.zeros((height, width), dtype=np.uint8)
    first_points = np.rint(
        (first - minimum) * 2.0
    ).astype(np.int32)
    second_points = np.rint(
        (second - minimum) * 2.0
    ).astype(np.int32)
    cv2.fillPoly(first_mask, [first_points], 1)
    cv2.fillPoly(second_mask, [second_points], 1)
    kernel = np.ones((3, 3), dtype=np.uint8)
    first_core = cv2.erode(first_mask, kernel, iterations=1)
    second_core = cv2.erode(second_mask, kernel, iterations=1)
    overlap = max(
        cv2.countNonZero(
            cv2.bitwise_and(first_core, second_mask)
        ),
        cv2.countNonZero(
            cv2.bitwise_and(first_mask, second_core)
        ),
    )
    smaller = min(
        cv2.countNonZero(first_mask),
        cv2.countNonZero(second_mask),
    )
    return overlap > max(2, int(smaller * tolerance_ratio))


def layout_metrics(layout):
    polygons = list(layout.values())
    all_points = np.vstack(polygons).astype(np.float32)
    rectangle = cv2.minAreaRect(all_points)
    rectangle_width, rectangle_height = rectangle[1]
    if min(rectangle_width, rectangle_height) < 1e-6:
        return {
            "score": -1.0,
            "coverage": 0.0,
            "overlap": 1.0,
            "corners": 0.0,
            "width": 0.0,
            "height": 0.0,
        }

    minimum = np.floor(np.min(all_points, axis=0)) - 3.0
    maximum = np.ceil(np.max(all_points, axis=0)) + 3.0
    width = int((maximum[0] - minimum[0]) * 2.0) + 1
    height = int((maximum[1] - minimum[1]) * 2.0) + 1
    union_mask = np.zeros((height, width), dtype=np.uint8)
    piece_masks = []
    for polygon in polygons:
        mask = np.zeros((height, width), dtype=np.uint8)
        points = np.rint(
            (polygon - minimum) * 2.0
        ).astype(np.int32)
        cv2.fillPoly(mask, [points], 1)
        piece_masks.append(mask)
        cv2.bitwise_or(union_mask, mask, dst=union_mask)

    rectangle_mask = np.zeros((height, width), dtype=np.uint8)
    rectangle_points = np.rint(
        (cv2.boxPoints(rectangle) - minimum) * 2.0
    ).astype(np.int32)
    cv2.fillPoly(rectangle_mask, [rectangle_points], 1)
    rectangle_area = cv2.countNonZero(rectangle_mask)
    union_area = cv2.countNonZero(union_mask)
    if rectangle_area < 1:
        return {
            "score": -1.0,
            "coverage": 0.0,
            "overlap": 1.0,
            "corners": 0.0,
            "width": 0.0,
            "height": 0.0,
        }

    coverage = min(1.0, union_area / rectangle_area)
    overlap_mask = np.zeros((height, width), dtype=np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    cores = [
        cv2.erode(mask, kernel, iterations=1)
        for mask in piece_masks
    ]
    for first_id in range(len(piece_masks)):
        for second_id in range(first_id + 1, len(piece_masks)):
            first_overlap = cv2.bitwise_and(
                cores[first_id],
                piece_masks[second_id],
            )
            second_overlap = cv2.bitwise_and(
                piece_masks[first_id],
                cores[second_id],
            )
            cv2.bitwise_or(
                overlap_mask,
                first_overlap,
                dst=overlap_mask,
            )
            cv2.bitwise_or(
                overlap_mask,
                second_overlap,
                dst=overlap_mask,
            )
    overlap = (
        cv2.countNonZero(overlap_mask)
        / rectangle_area
    )
    corners = cv2.boxPoints(rectangle)
    tolerance = max(
        1.5,
        math.hypot(rectangle_width, rectangle_height) * 0.025,
    )
    corner_count = sum(
        float(
            np.min(np.linalg.norm(all_points - corner, axis=1))
        )
        <= tolerance
        for corner in corners
    )
    corner_score = corner_count / 4.0
    score = (
        coverage
        - overlap * 5.0
        + corner_score * 0.03
    )
    return {
        "score": score,
        "coverage": coverage,
        "overlap": overlap,
        "corners": corner_score,
        "width": max(rectangle_width, rectangle_height),
        "height": min(rectangle_width, rectangle_height),
    }


def interval_is_free(intervals, start, end, tolerance):
    for used_start, used_end in intervals:
        if min(end, used_end) - max(start, used_start) > tolerance:
            return False
    return True


def interval_positions(
    length,
    shared,
    intervals,
    reference_lengths=None,
):
    maximum = max(0.0, length - shared)
    values = [0.0, maximum]
    for start, end in intervals:
        values.extend(
            [
                start,
                end,
                start - shared,
                end - shared,
            ]
        )
    if maximum >= 15.0 and reference_lengths:
        for reference in reference_lengths:
            values.extend(
                [
                    reference,
                    maximum - reference,
                ]
            )
    result = []
    for value in values:
        value = min(maximum, max(0.0, value))
        if not any(abs(value - old) < 0.25 for old in result):
            result.append(value)
    return result


def quick_compactness(polygons):
    all_points = np.vstack(polygons)
    size = np.max(all_points, axis=0) - np.min(all_points, axis=0)
    area = max(1.0, float(size[0] * size[1]))
    piece_area = sum(
        abs(cv2.contourArea(polygon.astype(np.float32)))
        for polygon in polygons
    )
    return area / max(1.0, piece_area)


def residual_partition_error(
    first_length,
    second_length,
    reference_lengths,
):
    residual = abs(first_length - second_length)
    if residual < 1.0:
        return 0.0

    candidates = [
        length
        for length in reference_lengths
        if length <= max(first_length, second_length) + 1.0
    ]
    best = residual
    for length in candidates:
        best = min(best, abs(residual - length))
    for first_id, first in enumerate(candidates):
        for second in candidates[first_id + 1:]:
            best = min(best, abs(residual - first - second))
    return best / residual


def solve(
    pieces,
    node_limit=50000,
    time_limit_s=5.0,
    edge_tolerance=0.14,
    overlap_tolerance_ratio=0.015,
    return_best=False,
):
    if not 1 <= len(pieces) <= 4:
        return None, 0.0, 0, None

    polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    reference_lengths = [
        edge_length(polygon, edge_id)
        for polygon in polygons
        for edge_id in range(len(polygon))
    ]
    if len(polygons) == 1:
        metrics = layout_metrics({0: polygons[0]})
        if (
            metrics["coverage"] >= 0.98
            and metrics["overlap"] <= 0.005
            and metrics["corners"] >= 0.99
        ):
            return {0: polygons[0]}, metrics["score"], 1, metrics
        return None, 0.0, 1, metrics

    best_layout = None
    best_metrics = None
    nodes = 0
    started = time.perf_counter()

    def search(placed, remaining, usage):
        nonlocal best_layout
        nonlocal best_metrics
        nonlocal nodes

        if nodes >= node_limit:
            return
        if time.perf_counter() - started >= time_limit_s:
            return
        if (
            best_metrics is not None
            and best_metrics["coverage"] >= 0.995
            and best_metrics["overlap"] <= 0.003
            and best_metrics["corners"] >= 0.99
        ):
            return

        nodes += 1
        if not remaining:
            metrics = layout_metrics(placed)
            if (
                best_metrics is None
                or metrics["score"] > best_metrics["score"]
            ):
                best_metrics = metrics
                best_layout = {
                    piece_id: polygon.copy()
                    for piece_id, polygon in placed.items()
                }
            return

        branches = []
        generated = set()
        for placed_id, target_polygon in placed.items():
            target_center = polygon_center(target_polygon)
            for target_edge in range(len(target_polygon)):
                target_start = target_polygon[target_edge]
                target_end = target_polygon[
                    (target_edge + 1) % len(target_polygon)
                ]
                target_vector = target_end - target_start
                target_length = float(np.linalg.norm(target_vector))
                if target_length < 1e-6:
                    continue
                target_unit = target_vector / target_length
                target_intervals = usage.get(
                    (placed_id, target_edge),
                    [],
                )

                for source_id in remaining:
                    source_polygon = polygons[source_id]
                    for source_edge in range(len(source_polygon)):
                        source_length = edge_length(
                            source_polygon,
                            source_edge,
                        )
                        if source_length < 1e-6:
                            continue
                        shared = min(target_length, source_length)
                        ratio = shared / max(
                            target_length,
                            source_length,
                        )
                        if ratio < 0.15:
                            continue
                        relative_error = abs(
                            target_length - source_length
                        ) / max(target_length, source_length)
                        if relative_error <= edge_tolerance:
                            shared = (
                                target_length + source_length
                            ) * 0.5
                            shared = min(
                                shared,
                                target_length,
                                source_length,
                            )

                        target_positions = interval_positions(
                            target_length,
                            shared,
                            target_intervals,
                            reference_lengths,
                        )
                        source_positions = interval_positions(
                            source_length,
                            shared,
                            [],
                            reference_lengths,
                        )
                        for target_offset in target_positions:
                            if not interval_is_free(
                                target_intervals,
                                target_offset,
                                target_offset + shared,
                                max(0.5, shared * 0.025),
                            ):
                                continue
                            segment_start = (
                                target_start
                                + target_unit * target_offset
                            )
                            segment_end = (
                                segment_start
                                + target_unit * shared
                            )
                            for source_offset in source_positions:
                                transformed = align_edge_segment(
                                    source_polygon,
                                    source_edge,
                                    source_offset,
                                    shared,
                                    segment_start,
                                    segment_end,
                                )
                                if transformed is None:
                                    continue
                                transformed_center = polygon_center(
                                    transformed
                                )
                                if not opposite_sides(
                                    segment_start,
                                    segment_end,
                                    target_center,
                                    transformed_center,
                                ):
                                    continue
                                if any(
                                    polygons_overlap(
                                        transformed,
                                        old_polygon,
                                        tolerance_ratio=overlap_tolerance_ratio,
                                    )
                                    for old_polygon in placed.values()
                                ):
                                    continue

                                first_edge = (
                                    transformed[1] - transformed[0]
                                )
                                angle = math.degrees(
                                    math.atan2(
                                        first_edge[1],
                                        first_edge[0],
                                    )
                                )
                                pose_key = (
                                    source_id,
                                    int(round(transformed_center[0] * 2.0)),
                                    int(round(transformed_center[1] * 2.0)),
                                    int(round(angle * 2.0)),
                                )
                                if pose_key in generated:
                                    continue
                                generated.add(pose_key)

                                partition_error = (
                                    residual_partition_error(
                                        target_length,
                                        source_length,
                                        reference_lengths,
                                    )
                                )
                                if relative_error <= 0.04:
                                    match_class = 0
                                elif (
                                    relative_error > edge_tolerance
                                    and partition_error <= 0.04
                                ):
                                    match_class = 1
                                elif relative_error <= edge_tolerance:
                                    match_class = 2
                                else:
                                    match_class = 3
                                compactness = quick_compactness(
                                    list(placed.values())
                                    + [transformed]
                                )
                                branches.append(
                                    (
                                        (
                                            match_class,
                                            (
                                                partition_error
                                                if match_class == 1
                                                else relative_error
                                            ),
                                            compactness,
                                        ),
                                        placed_id,
                                        target_edge,
                                        target_offset,
                                        source_id,
                                        source_edge,
                                        source_offset,
                                        shared,
                                        transformed,
                                    )
                                )

        branches.sort(key=lambda item: item[0])
        for (
            _,
            placed_id,
            target_edge,
            target_offset,
            source_id,
            source_edge,
            source_offset,
            shared,
            transformed,
        ) in branches:
            next_placed = dict(placed)
            next_placed[source_id] = transformed
            next_remaining = set(remaining)
            next_remaining.remove(source_id)
            next_usage = {
                key: list(intervals)
                for key, intervals in usage.items()
            }
            next_usage.setdefault(
                (placed_id, target_edge),
                [],
            ).append(
                (
                    target_offset,
                    target_offset + shared,
                )
            )
            next_usage[(source_id, source_edge)] = [
                (
                    source_offset,
                    source_offset + shared,
                )
            ]
            search(
                next_placed,
                next_remaining,
                next_usage,
            )
            if (
                best_metrics is not None
                and best_metrics["coverage"] >= 0.995
                and best_metrics["overlap"] <= 0.003
                and best_metrics["corners"] >= 0.99
            ):
                return

    def matching_edge_count(piece_id):
        count = 0
        polygon = polygons[piece_id]
        for edge_id in range(len(polygon)):
            length = edge_length(polygon, edge_id)
            matched = False
            for other_id, other in enumerate(polygons):
                if other_id == piece_id:
                    continue
                for other_edge in range(len(other)):
                    other_length = edge_length(other, other_edge)
                    error = abs(length - other_length) / max(
                        length,
                        other_length,
                    )
                    if error <= 0.04:
                        matched = True
                        break
                if matched:
                    break
            if matched:
                count += 1
        return count

    seed_order = sorted(
        range(len(polygons)),
        key=lambda piece_id: (
            -matching_edge_count(piece_id),
            len(polygons[piece_id]),
            -max(
                edge_length(polygons[piece_id], edge_id)
                for edge_id in range(len(polygons[piece_id]))
            ),
        ),
    )
    for seed_id in seed_order:
        search(
            {seed_id: polygons[seed_id].copy()},
            set(range(len(polygons))) - {seed_id},
            {},
        )
        if (
            best_metrics is not None
            and best_metrics["coverage"] >= 0.995
            and best_metrics["overlap"] <= 0.003
            and best_metrics["corners"] >= 0.99
        ):
            break

    if best_metrics is None:
        return None, 0.0, nodes, None
    if (
        best_metrics["coverage"] < 0.94
        or best_metrics["overlap"] > 0.025
        or best_metrics["corners"] < 0.75
    ):
        if return_best:
            return (
                best_layout,
                best_metrics["score"],
                nodes,
                best_metrics,
            )
        return None, best_metrics["score"], nodes, best_metrics
    return best_layout, best_metrics["score"], nodes, best_metrics
