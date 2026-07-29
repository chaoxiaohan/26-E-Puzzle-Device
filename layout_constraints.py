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
    first_vector = first_end - first_start
    second_vector = second_end - second_start
    first_length = float(np.linalg.norm(first_vector))
    second_length = float(np.linalg.norm(second_vector))
    if min(first_length, second_length) < 1e-6:
        return None

    first_unit = first_vector / first_length
    second_unit = second_vector / second_length
    if abs(float(np.cross(first_unit, second_unit))) > math.sin(
        math.radians(6.0)
    ):
        return None

    normal = np.array([-first_unit[1], first_unit[0]])
    distances = [
        abs(float(np.dot(second_start - first_start, normal))),
        abs(float(np.dot(second_end - first_start, normal))),
    ]
    if max(distances) > tolerance:
        return None

    projected = sorted(
        [
            float(np.dot(second_start - first_start, first_unit)),
            float(np.dot(second_end - first_start, first_unit)),
        ]
    )
    overlap_start = max(0.0, projected[0])
    overlap_end = min(first_length, projected[1])
    overlap = overlap_end - overlap_start
    if overlap < max(tolerance, min(first_length, second_length) * 0.18):
        return None

    second_projected = sorted(
        [
            float(np.dot(first_start - second_start, second_unit)),
            float(np.dot(first_end - second_start, second_unit)),
        ]
    )
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
        "normal": normal,
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


def evaluate_layout(layout):
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
    tolerance = max(1.5, diagonal * 0.012)
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
                tolerance,
            )
            if side is not None and length > tolerance:
                piece_has_outer[piece_id] = True
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
    return {
        "valid": not reasons,
        "reasons": reasons,
        "score": score,
        "coverage": raster["coverage"],
        "overlap": raster["overlap"],
        "corners": corner_score,
        "outer_piece_ratio": outer_piece_ratio,
        "internal_match": internal_match,
        "perimeter_error": raster["perimeter_error"],
        "components": raster["components"],
        "width": float(max(width, height)),
        "height": float(min(width, height)),
        "aspect": float(aspect_ratio),
        "adjacencies": adjacencies,
        "normalized_layout": normalized,
    }


def add_adjacency_gap(layout, gap_pixels):
    report = evaluate_layout(layout)
    if not report["valid"] or gap_pixels <= 0:
        return layout, {
            "applied": False,
            "reason": "invalid-layout" if not report["valid"] else "zero-gap",
        }

    piece_ids = sorted(layout)
    anchor = max(
        piece_ids,
        key=lambda piece_id: abs(
            cv2.contourArea(
                np.asarray(layout[piece_id], dtype=np.float32)
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
    for adjacency in report["adjacencies"]:
        first = adjacency["first_piece"]
        second = adjacency["second_piece"]
        normal = np.asarray(adjacency["normal"], dtype=np.float64)
        if np.dot(normal, centers[second] - centers[first]) < 0:
            normal = -normal
        for axis in range(2):
            row = np.zeros(len(movable) * 2, dtype=np.float64)
            if first != anchor:
                row[variable[first] * 2 + axis] = -1.0
            if second != anchor:
                row[variable[second] * 2 + axis] = 1.0
            rows.append(row)
            values.append(normal[axis] * gap_pixels)

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
            np.asarray(layout[piece_id], dtype=np.float64)
            + translations[piece_id]
        )
        for piece_id in piece_ids
    }
    maximum_error = 0.0
    for adjacency in report["adjacencies"]:
        first = adjacency["first_piece"]
        second = adjacency["second_piece"]
        normal = np.asarray(adjacency["normal"], dtype=np.float64)
        if np.dot(normal, centers[second] - centers[first]) < 0:
            normal = -normal
        separation = float(
            np.dot(
                translations[second] - translations[first],
                normal,
            )
        )
        maximum_error = max(
            maximum_error,
            abs(separation - gap_pixels),
        )
    return moved, {
        "applied": True,
        "anchor": anchor,
        "gap_pixels": float(gap_pixels),
        "maximum_error": maximum_error,
        "translations": {
            piece_id: translations[piece_id].tolist()
            for piece_id in piece_ids
        },
    }
