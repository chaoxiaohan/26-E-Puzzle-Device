import math

import cv2
import numpy as np


def _edges(polygon):
    return [
        (
            polygon[index],
            polygon[(index + 1) % len(polygon)],
        )
        for index in range(len(polygon))
    ]


def _normalize_layout(layout):
    piece_ids = sorted(layout)
    polygons = {
        piece_id: np.asarray(layout[piece_id], dtype=np.float64)
        for piece_id in piece_ids
    }
    all_points = np.vstack(list(polygons.values())).astype(np.float32)
    rectangle = cv2.minAreaRect(all_points)
    box = cv2.boxPoints(rectangle)
    vectors = [
        box[(index + 1) % 4] - box[index]
        for index in range(4)
    ]
    longest = max(vectors, key=lambda value: float(np.dot(value, value)))
    angle = -math.atan2(float(longest[1]), float(longest[0]))
    rotation = np.array(
        [
            [math.cos(angle), -math.sin(angle)],
            [math.sin(angle), math.cos(angle)],
        ],
        dtype=np.float64,
    )
    center = np.asarray(rectangle[0], dtype=np.float64)
    rotated = {
        piece_id: (polygon - center) @ rotation.T
        for piece_id, polygon in polygons.items()
    }
    all_rotated = np.vstack(list(rotated.values()))
    size = np.max(all_rotated, axis=0) - np.min(all_rotated, axis=0)
    if size[1] > size[0]:
        quarter_turn = np.array(
            [[0.0, -1.0], [1.0, 0.0]],
            dtype=np.float64,
        )
        rotated = {
            piece_id: polygon @ quarter_turn.T
            for piece_id, polygon in rotated.items()
        }
        all_rotated = np.vstack(list(rotated.values()))
    minimum = np.min(all_rotated, axis=0)
    return {
        piece_id: polygon - minimum
        for piece_id, polygon in rotated.items()
    }


def _interval_union_length(intervals):
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total = 0.0
    start, end = ordered[0]
    for next_start, next_end in ordered[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _interval_metrics(intervals, side_length, merge_tolerance):
    if side_length <= 1e-6:
        return 0.0, 1.0
    clipped = []
    for start, end in intervals:
        start = max(0.0, min(side_length, float(start)))
        end = max(0.0, min(side_length, float(end)))
        if end < start:
            start, end = end, start
        if end - start > 1e-6:
            clipped.append((start, end))
    if not clipped:
        return 0.0, 1.0

    merged = []
    for start, end in sorted(clipped):
        if merged and start <= merged[-1][1] + merge_tolerance:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))

    covered = sum(end - start for start, end in merged)
    gaps = [merged[0][0], side_length - merged[-1][1]]
    gaps.extend(
        merged[index + 1][0] - merged[index][1]
        for index in range(len(merged) - 1)
    )
    return (
        min(1.0, covered / side_length),
        max(0.0, max(gaps)) / side_length,
    )


def _outer_side(start, end, width, height, tolerance):
    if abs(start[0]) <= tolerance and abs(end[0]) <= tolerance:
        return "left"
    if (
        abs(start[0] - width) <= tolerance
        and abs(end[0] - width) <= tolerance
    ):
        return "right"
    if abs(start[1]) <= tolerance and abs(end[1]) <= tolerance:
        return "top"
    if (
        abs(start[1] - height) <= tolerance
        and abs(end[1] - height) <= tolerance
    ):
        return "bottom"
    return None


def _edge_match(first, second, tolerance):
    first_start, first_end = first
    second_start, second_end = second
    ax, ay = float(first_end[0]-first_start[0]), float(first_end[1]-first_start[1])
    bx, by = float(second_end[0]-second_start[0]), float(second_end[1]-second_start[1])
    first_length = math.sqrt(ax*ax+ay*ay)
    second_length = math.sqrt(bx*bx+by*by)
    if min(first_length, second_length) < 1e-6:
        return None

    ax, ay = ax/first_length, ay/first_length
    bx, by = bx/second_length, by/second_length
    if abs(ax*by-ay*bx) > math.sin(
        math.radians(6.0)
    ):
        return None

    sx, sy = float(second_start[0]-first_start[0]), float(second_start[1]-first_start[1])
    ex, ey = float(second_end[0]-first_start[0]), float(second_end[1]-first_start[1])
    distances = [abs(-sx*ay+sy*ax), abs(-ex*ay+ey*ax)]
    if max(distances) > tolerance:
        return None

    projected = sorted([sx*ax+sy*ay, ex*ax+ey*ay])
    overlap_start = max(0.0, projected[0])
    overlap_end = min(first_length, projected[1])
    overlap = overlap_end - overlap_start
    if overlap < max(tolerance, min(first_length, second_length) * 0.18):
        return None

    dx, dy = float(first_end[0]-second_start[0]), float(first_end[1]-second_start[1])
    second_projected = sorted([-sx*bx-sy*by, dx*bx+dy*by])
    second_overlap_start = max(0.0, second_projected[0])
    second_overlap_end = min(second_length, second_projected[1])
    return {
        "first_interval": (overlap_start, overlap_end),
        "second_interval": (
            second_overlap_start,
            second_overlap_end,
        ),
        "length": min(
            overlap,
            second_overlap_end - second_overlap_start,
        ),
        "normal": np.array([-ay, ax]),
    }


def _raster_metrics(layout, width, height):
    all_points = np.vstack(list(layout.values()))
    minimum = np.floor(np.min(all_points, axis=0)) - 3.0
    maximum = np.ceil(np.max(all_points, axis=0)) + 3.0
    mask_width = int((maximum[0] - minimum[0]) * 2.0) + 1
    mask_height = int((maximum[1] - minimum[1]) * 2.0) + 1
    masks = []
    union = np.zeros((mask_height, mask_width), dtype=np.uint8)
    total = np.zeros((mask_height, mask_width), dtype=np.uint8)
    for polygon in layout.values():
        mask = np.zeros_like(union)
        points = np.rint(
            (polygon - minimum) * 2.0
        ).astype(np.int32)
        cv2.fillPoly(mask, [points], 1)
        masks.append(mask)
        cv2.bitwise_or(union, mask, dst=union)
        total += mask

    rectangle = np.zeros_like(union)
    rectangle_points = np.rint(
        (
            np.array(
                [
                    [0.0, 0.0],
                    [width, 0.0],
                    [width, height],
                    [0.0, height],
                ]
            )
            - minimum
        )
        * 2.0
    ).astype(np.int32)
    cv2.fillPoly(rectangle, [rectangle_points], 1)
    rectangle_area = max(1, cv2.countNonZero(rectangle))
    inside = cv2.countNonZero(cv2.bitwise_and(union, rectangle))

    core_overlap = np.zeros_like(union)
    kernel = np.ones((3, 3), dtype=np.uint8)
    cores = [
        cv2.erode(mask, kernel, iterations=1)
        for mask in masks
    ]
    for first_id in range(len(masks)):
        for second_id in range(first_id + 1, len(masks)):
            overlap = cv2.bitwise_or(
                cv2.bitwise_and(cores[first_id], masks[second_id]),
                cv2.bitwise_and(masks[first_id], cores[second_id]),
            )
            cv2.bitwise_or(core_overlap, overlap, dst=core_overlap)

    contour_list, _ = cv2.findContours(
        union,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    perimeter = sum(cv2.arcLength(contour, True) for contour in contour_list)
    expected_perimeter = max(1.0, 4.0 * (width + height))
    components = max(
        0,
        cv2.connectedComponents(union, connectivity=8)[0] - 1,
    )
    return {
        "coverage": min(1.0, inside / rectangle_area),
        "overlap": cv2.countNonZero(core_overlap) / rectangle_area,
        "perimeter_error": abs(perimeter - expected_perimeter)
        / expected_perimeter,
        "components": components,
    }


def evaluate_layout(layout, edge_tolerance_ratio=0.012):
    if not layout:
        return {
            "valid": False,
            "reasons": ["empty"],
        }

    normalized = _normalize_layout(layout)
    all_points = np.vstack(list(normalized.values()))
    minimum = np.min(all_points, axis=0)
    maximum = np.max(all_points, axis=0)
    width, height = maximum - minimum
    if min(width, height) < 1e-6:
        return {
            "valid": False,
            "reasons": ["zero-size"],
        }

    diagonal = math.hypot(float(width), float(height))
    tolerance = max(1.5, diagonal * edge_tolerance_ratio)
    frame_tolerance = max(
        1.5,
        diagonal * min(edge_tolerance_ratio, 0.018),
    )
    boundary_intervals = {
        "left": [],
        "right": [],
        "top": [],
        "bottom": [],
    }
    boundary_angle_error = 0.0
    edge_records = []
    piece_has_outer = {
        piece_id: False
        for piece_id in normalized
    }
    for piece_id, polygon in normalized.items():
        for edge_id, (start, end) in enumerate(_edges(polygon)):
            length = float(np.linalg.norm(end - start))
            side = _outer_side(
                start,
                end,
                float(width),
                float(height),
                frame_tolerance,
            )
            if side is not None and length > tolerance:
                piece_has_outer[piece_id] = True
                if side in ("top", "bottom"):
                    interval = sorted((float(start[0]), float(end[0])))
                    axis_error = abs(float(end[1] - start[1]))
                else:
                    interval = sorted((float(start[1]), float(end[1])))
                    axis_error = abs(float(end[0] - start[0]))
                boundary_intervals[side].append(tuple(interval))
                boundary_angle_error = max(
                    boundary_angle_error,
                    math.degrees(
                        math.asin(
                            min(1.0, axis_error / max(length, 1e-6))
                        )
                    ),
                )
            edge_records.append(
                {
                    "piece_id": piece_id,
                    "edge_id": edge_id,
                    "start": start,
                    "end": end,
                    "length": length,
                    "outer": side,
                    "matched": [],
                }
            )

    adjacencies = []
    for first_id in range(len(edge_records)):
        first = edge_records[first_id]
        if first["outer"] is not None:
            continue
        for second_id in range(first_id + 1, len(edge_records)):
            second = edge_records[second_id]
            if (
                second["outer"] is not None
                or first["piece_id"] == second["piece_id"]
            ):
                continue
            match = _edge_match(
                (first["start"], first["end"]),
                (second["start"], second["end"]),
                tolerance,
            )
            if match is None:
                continue
            first["matched"].append(match["first_interval"])
            second["matched"].append(match["second_interval"])
            adjacencies.append(
                {
                    "first_piece": first["piece_id"],
                    "first_edge": first["edge_id"],
                    "second_piece": second["piece_id"],
                    "second_edge": second["edge_id"],
                    "length": match["length"],
                    "normal": match["normal"],
                }
            )

    internal_total = 0.0
    internal_matched = 0.0
    for edge in edge_records:
        if edge["outer"] is not None:
            continue
        internal_total += edge["length"]
        internal_matched += min(
            edge["length"],
            _interval_union_length(edge["matched"]),
        )
    internal_match = (
        internal_matched / internal_total
        if internal_total > tolerance
        else 1.0
    )

    raster = _raster_metrics(normalized, float(width), float(height))
    corners = np.array(
        [
            [0.0, 0.0],
            [width, 0.0],
            [width, height],
            [0.0, height],
        ]
    )
    corner_score = sum(
        np.min(np.linalg.norm(all_points - corner, axis=1))
        <= tolerance
        for corner in corners
    ) / 4.0
    outer_piece_ratio = sum(piece_has_outer.values()) / len(
        piece_has_outer
    )
    boundary_side_coverage = {}
    boundary_side_gap = {}
    for side in ("left", "right", "top", "bottom"):
        side_length = (
            float(height)
            if side in ("left", "right")
            else float(width)
        )
        coverage, gap_ratio = _interval_metrics(
            boundary_intervals[side],
            side_length,
            frame_tolerance,
        )
        boundary_side_coverage[side] = coverage
        boundary_side_gap[side] = gap_ratio
    boundary_min_coverage = min(boundary_side_coverage.values())
    boundary_max_gap_ratio = max(boundary_side_gap.values())
    aspect_ratio = max(width, height) / max(1.0, min(width, height))

    reasons = []
    if raster["coverage"] < 0.975:
        reasons.append("coverage")
    if raster["overlap"] > 0.005:
        reasons.append("overlap")
    if corner_score < 0.99:
        reasons.append("corners")
    if outer_piece_ratio < 0.999:
        reasons.append("piece-outer-edge")
    if internal_match < 0.82:
        reasons.append("internal-edges")
    if raster["perimeter_error"] > 0.10:
        reasons.append("perimeter")
    if raster["components"] != 1:
        reasons.append("disconnected")
    if (
        boundary_min_coverage < 0.94
        or boundary_max_gap_ratio > 0.06
        or boundary_angle_error > 4.5
    ):
        reasons.append("rectangle-boundary")
    if not 0.98 <= aspect_ratio <= 2.45:
        reasons.append("aspect")

    score = (
        raster["coverage"]
        - raster["overlap"] * 10.0
        + corner_score * 0.04
        + outer_piece_ratio * 0.05
        + internal_match * 0.08
        - raster["perimeter_error"] * 0.20
    )
    competition_reasons = []
    if raster["coverage"] < 0.92:
        competition_reasons.append("coverage")
    if raster["overlap"] > 0.075:
        competition_reasons.append("overlap")
    if corner_score < 0.75:
        competition_reasons.append("corners")
    if outer_piece_ratio < 0.999:
        competition_reasons.append("piece-outer-edge")
    if internal_match < 0.35:
        competition_reasons.append("internal-edges")
    if raster["perimeter_error"] > 0.25:
        competition_reasons.append("perimeter")
    if raster["components"] != 1:
        competition_reasons.append("disconnected")
    if (
        boundary_min_coverage < 0.88
        or boundary_max_gap_ratio > 0.12
        or boundary_angle_error > 7.0
    ):
        competition_reasons.append("rectangle-boundary")
    if not 0.98 <= aspect_ratio <= 2.45:
        competition_reasons.append("aspect")

    return {
        "valid": not reasons,
        "reasons": reasons,
        "competition_valid": not competition_reasons,
        "competition_reasons": competition_reasons,
        "score": score,
        "coverage": raster["coverage"],
        "overlap": raster["overlap"],
        "corners": corner_score,
        "outer_piece_ratio": outer_piece_ratio,
        "internal_match": internal_match,
        "perimeter_error": raster["perimeter_error"],
        "components": raster["components"],
        "boundary_side_coverage": boundary_side_coverage,
        "boundary_side_gap": boundary_side_gap,
        "boundary_min_coverage": boundary_min_coverage,
        "boundary_max_gap_ratio": boundary_max_gap_ratio,
        "boundary_angle_error": boundary_angle_error,
        "width": float(max(width, height)),
        "height": float(min(width, height)),
        "aspect": float(aspect_ratio),
        "adjacencies": adjacencies,
        "normalized_layout": normalized,
    }


def add_adjacency_gap(
    layout,
    gap_pixels,
    edge_tolerance_ratio=0.012,
    align_vertices=False,
):
    report = evaluate_layout(
        layout,
        edge_tolerance_ratio=edge_tolerance_ratio,
    )
    if gap_pixels <= 0:
        return layout, {
            "applied": False,
            "reason": "zero-gap",
        }

    piece_ids = sorted(layout)
    base_layout = report["normalized_layout"]
    anchor = max(
        piece_ids,
        key=lambda piece_id: abs(
            cv2.contourArea(
                np.asarray(base_layout[piece_id], dtype=np.float32)
            )
        ),
    )
    movable = [piece_id for piece_id in piece_ids if piece_id != anchor]
    variable = {
        piece_id: index
        for index, piece_id in enumerate(movable)
    }
    centers = {
        piece_id: np.mean(
            report["normalized_layout"][piece_id],
            axis=0,
        )
        for piece_id in piece_ids
    }
    rows = []
    values = []
    constraints = []
    for adjacency in report["adjacencies"]:
        first = adjacency["first_piece"]
        second = adjacency["second_piece"]
        normal = np.asarray(adjacency["normal"], dtype=np.float64)
        if np.dot(normal, centers[second] - centers[first]) < 0:
            normal = -normal
        first_polygon = np.asarray(base_layout[first], dtype=np.float64)
        second_polygon = np.asarray(base_layout[second], dtype=np.float64)
        first_edge = adjacency["first_edge"]
        second_edge = adjacency["second_edge"]
        first_points = np.asarray(
            [
                first_polygon[first_edge],
                first_polygon[(first_edge + 1) % len(first_polygon)],
            ],
            dtype=np.float64,
        )
        second_points = np.asarray(
            [
                second_polygon[second_edge],
                second_polygon[(second_edge + 1) % len(second_polygon)],
            ],
            dtype=np.float64,
        )
        direct_error = np.linalg.norm(second_points - first_points, axis=1).sum()
        reverse_error = np.linalg.norm(
            second_points[::-1] - first_points,
            axis=1,
        ).sum()
        if reverse_error < direct_error:
            second_points = second_points[::-1]

        first_middle = np.mean(first_points, axis=0)
        second_middle = np.mean(second_points, axis=0)
        current_separation = float(
            np.dot(second_middle - first_middle, normal)
        )
        if align_vertices:
            current_vector = np.mean(second_points - first_points, axis=0)
            required_translation = normal * gap_pixels - current_vector
        else:
            required_translation = normal * (
                gap_pixels - current_separation
            )
        constraints.append(
            (
                first,
                second,
                normal,
                current_separation,
                first_points,
                second_points,
            )
        )
        for axis in range(2):
            row = np.zeros(len(movable) * 2, dtype=np.float64)
            if first != anchor:
                row[variable[first] * 2 + axis] = -1.0
            if second != anchor:
                row[variable[second] * 2 + axis] = 1.0
            rows.append(row)
            values.append(required_translation[axis])

    if not rows:
        return layout, {
            "applied": False,
            "reason": "no-adjacency",
        }
    matrix = np.vstack(rows)
    target = np.asarray(values, dtype=np.float64)
    solution, _, _, _ = np.linalg.lstsq(matrix, target, rcond=None)
    translations = {
        anchor: np.zeros(2, dtype=np.float64)
    }
    for piece_id in movable:
        start = variable[piece_id] * 2
        translations[piece_id] = solution[start:start + 2]

    moved = {
        piece_id: (
            np.asarray(base_layout[piece_id], dtype=np.float64)
            + translations[piece_id]
        )
        for piece_id in piece_ids
    }
    maximum_error = 0.0
    final_gaps = []
    for (
        first,
        second,
        normal,
        current_separation,
        first_points,
        second_points,
    ) in constraints:
        relative_translation = translations[second] - translations[first]
        if align_vertices:
            distances = np.linalg.norm(
                second_points + relative_translation - first_points,
                axis=1,
            )
            final_gaps.extend(float(distance) for distance in distances)
            maximum_error = max(
                maximum_error,
                max(abs(float(distance) - gap_pixels) for distance in distances),
            )
        else:
            separation = current_separation + float(
                np.dot(relative_translation, normal)
            )
            final_gaps.append(separation)
            maximum_error = max(
                maximum_error,
                abs(separation - gap_pixels),
            )
    return moved, {
        "applied": True,
        "anchor": anchor,
        "gap_pixels": float(gap_pixels),
        "metric": "vertex" if align_vertices else "normal",
        "maximum_error": maximum_error,
        "minimum_gap": min(final_gaps),
        "maximum_gap": max(final_gaps),
        "translations": {
            piece_id: translations[piece_id].tolist()
            for piece_id in piece_ids
        },
    }


def _separating_push(first, second):
    first = np.asarray(first, dtype=np.float64)
    second = np.asarray(second, dtype=np.float64)
    if not cv2.isContourConvex(first.astype(np.float32)):
        first = cv2.convexHull(
            first.astype(np.float32)
        ).reshape(-1, 2)
    if not cv2.isContourConvex(second.astype(np.float32)):
        second = cv2.convexHull(
            second.astype(np.float32)
        ).reshape(-1, 2)

    best_axis = None
    best_overlap = float("inf")
    for polygon in (first, second):
        for start, end in _edges(polygon):
            vector = end - start
            length = float(np.linalg.norm(vector))
            if length < 1e-6:
                continue
            axis = np.array(
                [-vector[1], vector[0]],
                dtype=np.float64,
            ) / length
            first_projection = first @ axis
            second_projection = second @ axis
            overlap = min(
                float(np.max(first_projection)),
                float(np.max(second_projection)),
            ) - max(
                float(np.min(first_projection)),
                float(np.min(second_projection)),
            )
            if overlap <= 0:
                return None
            if overlap < best_overlap:
                best_overlap = overlap
                best_axis = axis

    if best_axis is None:
        return None
    if np.dot(
        best_axis,
        np.mean(second, axis=0) - np.mean(first, axis=0),
    ) < 0:
        best_axis = -best_axis
    return best_axis, best_overlap


def repair_layout_for_competition(
    layout,
    gap_pixels=1.0,
    force=False,
):
    report = evaluate_layout(
        layout,
        edge_tolerance_ratio=0.035,
    )
    candidate_reasons = []
    if report["coverage"] < 0.92:
        candidate_reasons.append("coverage")
    if report["overlap"] > 0.075:
        candidate_reasons.append("overlap")
    if report["corners"] < 0.75:
        candidate_reasons.append("corners")
    if report["outer_piece_ratio"] < 0.999:
        candidate_reasons.append("piece-outer-edge")
    if report["internal_match"] < 0.35:
        candidate_reasons.append("internal-edges")
    if report["components"] != 1:
        candidate_reasons.append("disconnected")
    if not 0.98 <= report["aspect"] <= 2.45:
        candidate_reasons.append("aspect")
    if candidate_reasons and not force:
        return None, {
            "valid": False,
            "stage": "candidate",
            "reasons": candidate_reasons,
        }

    moved, gap_info = add_adjacency_gap(
        report["normalized_layout"],
        gap_pixels,
    )
    original = {
        piece_id: polygon.copy()
        for piece_id, polygon in moved.items()
    }
    piece_ids = sorted(moved)
    anchor = max(
        piece_ids,
        key=lambda piece_id: abs(
            cv2.contourArea(
                moved[piece_id].astype(np.float32)
            )
        ),
    )

    for _ in range(24):
        changed = False
        for first_index in range(len(piece_ids)):
            for second_index in range(first_index + 1, len(piece_ids)):
                first_id = piece_ids[first_index]
                second_id = piece_ids[second_index]
                push = _separating_push(
                    moved[first_id],
                    moved[second_id],
                )
                if push is None:
                    continue
                axis, overlap = push
                amount = overlap + max(0.2, gap_pixels * 0.25)
                if first_id == anchor:
                    moved[second_id] += axis * amount
                elif second_id == anchor:
                    moved[first_id] -= axis * amount
                else:
                    moved[first_id] -= axis * amount * 0.5
                    moved[second_id] += axis * amount * 0.5
                changed = True
        if not changed:
            break

    collision_free = True
    for first_index in range(len(piece_ids)):
        for second_index in range(first_index + 1, len(piece_ids)):
            if _separating_push(
                moved[piece_ids[first_index]],
                moved[piece_ids[second_index]],
            ) is not None:
                collision_free = False
                break
        if not collision_free:
            break

    all_points = np.vstack(list(report["normalized_layout"].values()))
    diagonal = float(
        np.linalg.norm(
            np.max(all_points, axis=0)
            - np.min(all_points, axis=0)
        )
    )
    maximum_move = max(
        float(
            np.linalg.norm(
                np.mean(moved[piece_id], axis=0)
                - np.mean(original[piece_id], axis=0)
            )
        )
        for piece_id in piece_ids
    )
    final_report = evaluate_layout(
        moved,
        edge_tolerance_ratio=0.05,
    )
    final_reasons = []
    if not collision_free:
        final_reasons.append("overlap")
    if (
        not force
        and maximum_move > max(6.0, diagonal * 0.10)
    ):
        final_reasons.append("excessive-move")
    if not force and final_report["coverage"] < 0.86:
        final_reasons.append("coverage")
    if not force and final_report["corners"] < 0.50:
        final_reasons.append("corners")
    if not force and final_report["outer_piece_ratio"] < 0.75:
        final_reasons.append("piece-outer-edge")
    if not force and final_report["internal_match"] < 0.30:
        final_reasons.append("internal-edges")
    if (
        not force
        and final_report["components"] > len(piece_ids)
    ):
        final_reasons.append("components")

    return (
        moved if not final_reasons else None,
        {
            "valid": not final_reasons,
            "forced": bool(force),
            "stage": "execution",
            "reasons": final_reasons,
            "maximum_move": maximum_move,
            "gap": gap_info,
            "before": {
                "coverage": report["coverage"],
                "overlap": report["overlap"],
                "internal_match": report["internal_match"],
            },
            "after": {
                "coverage": final_report["coverage"],
                "overlap": final_report["overlap"],
                "internal_match": final_report["internal_match"],
            },
        },
    )
