# -*- coding: utf-8 -*-

import concurrent.futures
import itertools
import json
import math
import multiprocessing
import os
import time

import cv2
import numpy as np
from maix import app, camera, display, image, touchscreen
from layout_constraints import (
    add_adjacency_gap,
    evaluate_layout,
    repair_layout_for_competition,
)
from puzzle_solver import solve_camera_rectangle


def longest_edge(points):
    """返回多边形最长边及其相对图像水平向右方向的角度。"""
    best_start = points[0]
    best_end = points[1]
    best_length = 0.0

    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = dx * dx + dy * dy
        if length > best_length:
            best_start = start
            best_end = end
            best_length = length

    angle = math.degrees(
        math.atan2(best_end[1] - best_start[1], best_end[0] - best_start[0])
    )
    if angle >= 90:
        angle -= 180
    elif angle < -90:
        angle += 180

    return (best_start, best_end), angle


def find_candidates(
    mask,
    offset_x,
    offset_y,
    min_area,
    max_area,
    polygon_epsilon,
):
    """从一张二值图中找出可能属于拼图碎片的多边形。"""
    image_height, image_width = mask.shape
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    candidates = []

    for contour in contours:
        area = abs(cv2.contourArea(contour))
        if area < min_area or area > max_area:
            continue

        x, y, width, height = cv2.boundingRect(contour)
        if x <= 2 or y <= 2:
            continue
        if x + width >= image_width - 2 or y + height >= image_height - 2:
            continue
        if min(width, height) < 10:
            continue
        if max(width, height) / min(width, height) > 8:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter < 50:
            continue

        polygon = cv2.approxPolyDP(
            contour,
            polygon_epsilon * perimeter,
            True,
        )
        if len(polygon) < 3 or len(polygon) > 5:
            continue

        polygon_area = abs(cv2.contourArea(polygon))
        if polygon_area < min_area or area / polygon_area < 0.72:
            continue

        hull_area = abs(cv2.contourArea(cv2.convexHull(contour)))
        if hull_area < 1 or area / hull_area < 0.55:
            continue

        moments = cv2.moments(contour)
        if abs(moments["m00"]) < 1:
            continue

        center_x = int(moments["m10"] / moments["m00"]) + offset_x
        center_y = int(moments["m01"] / moments["m00"]) + offset_y
        points = [
            (
                int(point[0][0]) + offset_x,
                int(point[0][1]) + offset_y,
            )
            for point in polygon
        ]
        piece_longest_edge, angle = longest_edge(points)

        candidates.append(
            {
                "points": points,
                "center": (center_x, center_y),
                "area": area,
                "angle": angle,
                "longest_edge": piece_longest_edge,
                "solidity": area / hull_area,
            }
        )

    candidates.sort(key=lambda item: item["area"], reverse=True)
    return candidates


def candidate_set_score(candidates, max_pieces):
    """优先选择包含较大、完整多边形的阈值极性。"""
    selected = candidates[:max_pieces]
    if not selected:
        return 0.0
    return sum(item["area"] * item["solidity"] for item in selected)


def detect_pieces(
    frame_rgb,
    roi,
    min_area=500,
    max_area_ratio=0.35,
    max_pieces=4,
    polygon_epsilon=0.018,
    threshold=None,
    polarity_mode="AUTO",
):
    """检测ROI内的拼图碎片。"""
    roi_x, roi_y, roi_width, roi_height = roi
    roi_rgb = frame_rgb[
        roi_y : roi_y + roi_height,
        roi_x : roi_x + roi_width,
    ]

    gray = cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    if threshold is None:
        threshold_value, bright_mask = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        threshold_mode = "OTSU"
    else:
        threshold_value = min(255, max(0, int(threshold)))
        _, bright_mask = cv2.threshold(
            gray,
            threshold_value,
            255,
            cv2.THRESH_BINARY,
        )
        threshold_mode = "MANUAL"

    dark_mask = cv2.bitwise_not(bright_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    bright_mask = cv2.morphologyEx(
        bright_mask,
        cv2.MORPH_OPEN,
        kernel,
        iterations=1,
    )
    bright_mask = cv2.morphologyEx(
        bright_mask,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2,
    )
    dark_mask = cv2.morphologyEx(
        dark_mask,
        cv2.MORPH_OPEN,
        kernel,
        iterations=1,
    )
    dark_mask = cv2.morphologyEx(
        dark_mask,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2,
    )

    max_area = roi_width * roi_height * max_area_ratio
    bright_candidates = find_candidates(
        bright_mask,
        roi_x,
        roi_y,
        min_area,
        max_area,
        polygon_epsilon,
    )
    dark_candidates = find_candidates(
        dark_mask,
        roi_x,
        roi_y,
        min_area,
        max_area,
        polygon_epsilon,
    )

    polarity_mode = polarity_mode.upper()
    if polarity_mode == "LIGHT":
        pieces = bright_candidates[:max_pieces]
        polarity = "LIGHT"
        selected_mask = bright_mask
    elif polarity_mode == "DARK":
        pieces = dark_candidates[:max_pieces]
        polarity = "DARK"
        selected_mask = dark_mask
    elif candidate_set_score(
        bright_candidates,
        max_pieces,
    ) >= candidate_set_score(
        dark_candidates,
        max_pieces,
    ):
        pieces = bright_candidates[:max_pieces]
        polarity = "LIGHT"
        selected_mask = bright_mask
    else:
        pieces = dark_candidates[:max_pieces]
        polarity = "DARK"
        selected_mask = dark_mask

    pieces.sort(key=lambda item: (item["center"][1], item["center"][0]))
    return pieces, {
        "polarity": polarity,
        "polarity_mode": polarity_mode,
        "threshold": int(threshold_value),
        "threshold_mode": threshold_mode,
        "mask": selected_mask,
    }


def polygon_edge_length(polygon, edge_index):
    """计算多边形指定边的长度。"""
    start = polygon[edge_index]
    end = polygon[(edge_index + 1) % len(polygon)]
    return float(np.linalg.norm(end - start))


def normalize_polygon(points):
    """统一多边形顶点方向并把坐标转换为浮点数。"""
    polygon = np.array(points, dtype=np.float32)
    if cv2.contourArea(polygon, oriented=True) < 0:
        polygon = polygon[::-1].copy()
    return polygon


def align_polygon_edge(polygon, edge_index, target_start, target_end):
    """旋转并平移碎片，使指定边与目标边反向贴合。"""
    source_start = polygon[edge_index]
    source_end = polygon[(edge_index + 1) % len(polygon)]
    source_vector = source_end - source_start
    target_vector = target_start - target_end
    source_angle = math.atan2(source_vector[1], source_vector[0])
    target_angle = math.atan2(target_vector[1], target_vector[0])
    angle = target_angle - source_angle

    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotation = np.array(
        [
            [cosine, -sine],
            [sine, cosine],
        ],
        dtype=np.float32,
    )
    source_middle = (source_start + source_end) * 0.5
    target_middle = (target_start + target_end) * 0.5
    return (polygon - source_middle) @ rotation.T + target_middle


def polygon_center(polygon):
    """用顶点平均值计算只用于拼接侧向判断的中心。"""
    return np.mean(polygon, axis=0)


def centers_on_opposite_sides(
    edge_start,
    edge_end,
    first_center,
    second_center,
):
    """公共边两侧必须分别属于两块碎片。"""
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


def polygons_overlap(first, second):
    """栅格化判断两块碎片是否发生了明显面积重叠。"""
    all_points = np.vstack((first, second))
    minimum = np.floor(np.min(all_points, axis=0)).astype(np.int32) - 3
    maximum = np.ceil(np.max(all_points, axis=0)).astype(np.int32) + 3
    width = int(maximum[0] - minimum[0] + 1)
    height = int(maximum[1] - minimum[1] + 1)
    if width <= 0 or height <= 0:
        return True

    first_mask = np.zeros((height, width), dtype=np.uint8)
    second_mask = np.zeros((height, width), dtype=np.uint8)
    first_points = np.rint(first - minimum).astype(np.int32)
    second_points = np.rint(second - minimum).astype(np.int32)
    cv2.fillPoly(first_mask, [first_points], 255)
    cv2.fillPoly(second_mask, [second_points], 255)

    kernel = np.ones((3, 3), dtype=np.uint8)
    first_mask = cv2.erode(first_mask, kernel, iterations=1)
    second_mask = cv2.erode(second_mask, kernel, iterations=1)
    overlap = cv2.countNonZero(cv2.bitwise_and(first_mask, second_mask))
    smaller_area = min(
        cv2.countNonZero(first_mask),
        cv2.countNonZero(second_mask),
    )
    return overlap > max(12, int(smaller_area * 0.008))


def assembly_quality(layout, length_errors):
    """用真实并集面积、矩形四角和目标比例评价完整拼法。"""
    polygons = list(layout.values())
    all_points = np.vstack(polygons).astype(np.float32)
    rectangle = cv2.minAreaRect(all_points)
    rectangle_width, rectangle_height = rectangle[1]
    if min(rectangle_width, rectangle_height) < 1:
        return -1.0, 0.0, 0.0

    minimum = np.floor(np.min(all_points, axis=0)).astype(np.int32) - 4
    maximum = np.ceil(np.max(all_points, axis=0)).astype(np.int32) + 4
    width = int(maximum[0] - minimum[0] + 1)
    height = int(maximum[1] - minimum[1] + 1)
    union_mask = np.zeros((height, width), dtype=np.uint8)
    summed_piece_area = 0
    for polygon in polygons:
        points = np.rint(polygon - minimum).astype(np.int32)
        piece_mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(piece_mask, [points], 255)
        summed_piece_area += cv2.countNonZero(piece_mask)
        cv2.bitwise_or(union_mask, piece_mask, dst=union_mask)

    rectangle_mask = np.zeros((height, width), dtype=np.uint8)
    rectangle_points = np.rint(
        cv2.boxPoints(rectangle) - minimum
    ).astype(np.int32)
    cv2.fillPoly(rectangle_mask, [rectangle_points], 255)
    union_area = cv2.countNonZero(union_mask)
    rectangle_area = cv2.countNonZero(rectangle_mask)
    if rectangle_area < 1:
        return -1.0, 0.0, 0.0

    rectangularity = min(1.0, union_area / rectangle_area)
    overlap_ratio = max(
        0.0,
        (summed_piece_area - union_area) / rectangle_area,
    )

    rectangle_corners = cv2.boxPoints(rectangle)
    corner_tolerance = max(
        5.0,
        math.hypot(rectangle_width, rectangle_height) * 0.035,
    )
    covered_corners = 0
    for corner in rectangle_corners:
        distances = np.linalg.norm(all_points - corner, axis=1)
        if float(np.min(distances)) <= corner_tolerance:
            covered_corners += 1
    corner_score = covered_corners / 4.0

    aspect_ratio = max(rectangle_width, rectangle_height) / min(
        rectangle_width,
        rectangle_height,
    )
    target_ratio = 10.0 / 6.0
    ratio_score = math.exp(
        -abs(math.log(max(0.01, aspect_ratio / target_ratio)))
    )
    mean_length_error = (
        sum(length_errors) / len(length_errors)
        if length_errors
        else 0.0
    )
    score = (
        rectangularity * 0.70
        + corner_score * 0.16
        + ratio_score * 0.14
        - overlap_ratio * 0.35
        - mean_length_error * 0.05
    )
    return score, rectangularity, corner_score


def assembly_score(layout, length_errors):
    """保留单分数接口，便于合成测试和调试。"""
    return assembly_quality(layout, length_errors)[0]


def solve_rectangle(pieces):
    """
    枚举完整公共边和长边分段公共边，返回最佳矩形布局。

    这里只允许旋转和平移碎片，不进行镜像或单块缩放。
    """
    if len(pieces) < 2 or len(pieces) > 4:
        return None, 0.0, 0

    source_polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    best_layout = None
    best_score = -1.0
    best_rectangularity = 0.0
    best_corner_score = 0.0
    total_nodes = 0

    def search(placed, remaining, edge_usage, length_errors):
        nonlocal best_layout
        nonlocal best_score
        nonlocal best_rectangularity
        nonlocal best_corner_score
        nonlocal total_nodes

        if total_nodes >= 12000:
            return
        if (
            best_score >= 0.965
            and best_rectangularity >= 0.94
            and best_corner_score >= 0.99
        ):
            return

        total_nodes += 1
        if not remaining:
            score, rectangularity, corner_score = assembly_quality(
                placed,
                length_errors,
            )
            if score > best_score:
                best_score = score
                best_rectangularity = rectangularity
                best_corner_score = corner_score
                best_layout = {
                    piece_id: polygon.copy()
                    for piece_id, polygon in placed.items()
                }
            return

        branches = []
        generated = set()
        for placed_id, placed_polygon in tuple(placed.items()):
            placed_center = polygon_center(placed_polygon)
            for placed_edge in range(len(placed_polygon)):
                usage = edge_usage.get((placed_id, placed_edge), set())
                if "FULL" in usage or (
                    "START" in usage
                    and "CENTER" in usage
                    and "END" in usage
                ):
                    continue

                target_start = placed_polygon[placed_edge]
                target_end = placed_polygon[
                    (placed_edge + 1) % len(placed_polygon)
                ]
                target_vector = target_end - target_start
                target_length = float(np.linalg.norm(target_vector))
                if target_length < 8:
                    continue
                target_unit = target_vector / target_length

                for new_id in tuple(remaining):
                    source_polygon = source_polygons[new_id]
                    for source_edge in range(len(source_polygon)):
                        source_length = polygon_edge_length(
                            source_polygon,
                            source_edge,
                        )
                        if source_length < 8:
                            continue

                        length_error = abs(
                            source_length - target_length
                        ) / max(source_length, target_length)
                        options = []
                        if not usage and length_error <= 0.16:
                            options.append(
                                (
                                    "FULL",
                                    target_start,
                                    target_end,
                                    length_error,
                                    length_error,
                                )
                            )
                        elif (
                            source_length < target_length * 0.82
                            and source_length > target_length * 0.16
                        ):
                            if "START" not in usage:
                                options.append(
                                    (
                                        "START",
                                        target_start,
                                        target_start
                                        + target_unit * source_length,
                                        0.05,
                                        0.0,
                                    )
                                )
                            if "END" not in usage:
                                options.append(
                                    (
                                        "END",
                                        target_end
                                        - target_unit * source_length,
                                        target_end,
                                        0.05,
                                        0.0,
                                    )
                                )
                            if "CENTER" not in usage:
                                center_offset = (
                                    target_length - source_length
                                ) * 0.5
                                options.append(
                                    (
                                        "CENTER",
                                        target_start
                                        + target_unit * center_offset,
                                        target_start
                                        + target_unit
                                        * (center_offset + source_length),
                                        0.06,
                                        0.0,
                                    )
                                )

                        for (
                            attach_mode,
                            segment_start,
                            segment_end,
                            priority,
                            recorded_error,
                        ) in options:
                            transformed = align_polygon_edge(
                                source_polygon,
                                source_edge,
                                segment_start,
                                segment_end,
                            )
                            transformed_center = polygon_center(transformed)
                            if not centers_on_opposite_sides(
                                segment_start,
                                segment_end,
                                placed_center,
                                transformed_center,
                            ):
                                continue

                            if any(
                                polygons_overlap(transformed, polygon)
                                for polygon in placed.values()
                            ):
                                continue

                            first_edge = transformed[1] - transformed[0]
                            pose_angle = math.degrees(
                                math.atan2(first_edge[1], first_edge[0])
                            )
                            pose_key = (
                                new_id,
                                int(round(transformed_center[0] / 3)),
                                int(round(transformed_center[1] / 3)),
                                int(round(pose_angle / 3)),
                            )
                            if pose_key in generated:
                                continue
                            generated.add(pose_key)
                            branches.append(
                                (
                                    priority,
                                    placed_id,
                                    placed_edge,
                                    new_id,
                                    source_edge,
                                    attach_mode,
                                    transformed,
                                    recorded_error,
                                )
                            )

        branches.sort(key=lambda item: item[0])
        for (
            _,
            placed_id,
            placed_edge,
            new_id,
            source_edge,
            attach_mode,
            transformed,
            recorded_error,
        ) in branches:
            next_placed = dict(placed)
            next_placed[new_id] = transformed
            next_remaining = set(remaining)
            next_remaining.remove(new_id)
            next_usage = {
                key: set(value)
                for key, value in edge_usage.items()
            }
            next_usage.setdefault(
                (placed_id, placed_edge),
                set(),
            ).add(attach_mode)
            next_usage[(new_id, source_edge)] = {"FULL"}
            search(
                next_placed,
                next_remaining,
                next_usage,
                length_errors + [recorded_error],
            )
            if (
                best_score >= 0.965
                and best_rectangularity >= 0.94
                and best_corner_score >= 0.99
            ):
                return

    seed_order = sorted(
        range(len(source_polygons)),
        key=lambda piece_id: (
            0 if len(source_polygons[piece_id]) == 3 else 1,
            -max(
                polygon_edge_length(
                    source_polygons[piece_id],
                    edge_index,
                )
                for edge_index in range(len(source_polygons[piece_id]))
            ),
        ),
    )
    for seed_id in seed_order:
        search(
            {seed_id: source_polygons[seed_id].copy()},
            set(range(len(source_polygons))) - {seed_id},
            {},
            [],
        )
        if (
            best_score >= 0.965
            and best_rectangularity >= 0.94
            and best_corner_score >= 0.99
        ):
            break

    if (
        best_layout is None
        or best_rectangularity < 0.90
        or best_corner_score < 0.75
        or best_score < 0.86
    ):
        return None, 0.0, total_nodes
    return best_layout, best_score, total_nodes


def polygon_mask_bits(polygon, width, height):
    """把候选碎片转换成整数位图，便于快速计算覆盖和重叠。"""
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(
        mask,
        [np.rint(polygon).astype(np.int32)],
        1,
    )
    core_mask = cv2.erode(
        mask,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    )
    packed = np.packbits(mask.reshape(-1))
    packed_core = np.packbits(core_mask.reshape(-1))
    return (
        int.from_bytes(packed.tobytes(), "little"),
        int.from_bytes(packed_core.tobytes(), "little"),
        int(np.sum(mask)),
    )


def count_mask_bits(value):
    """统计整数位图中的有效像素。"""
    return value.bit_count()


def polygons_have_interior_overlap(first, second):
    all_points = np.vstack((first, second))
    minimum = np.floor(np.min(all_points, axis=0)) - 2.0
    maximum = np.ceil(np.max(all_points, axis=0)) + 2.0
    width = int((maximum[0] - minimum[0]) * 4.0) + 1
    height = int((maximum[1] - minimum[1]) * 4.0) + 1
    if width <= 0 or height <= 0:
        return True

    first_mask = np.zeros((height, width), dtype=np.uint8)
    second_mask = np.zeros((height, width), dtype=np.uint8)
    first_points = np.rint(
        (first - minimum) * 4.0
    ).astype(np.int32)
    second_points = np.rint(
        (second - minimum) * 4.0
    ).astype(np.int32)
    cv2.fillPoly(first_mask, [first_points], 1)
    cv2.fillPoly(second_mask, [second_points], 1)

    kernel = np.ones((3, 3), dtype=np.uint8)
    first_core = cv2.erode(
        first_mask,
        kernel,
        iterations=1,
    )
    second_core = cv2.erode(
        second_mask,
        kernel,
        iterations=1,
    )
    return (
        cv2.countNonZero(
            cv2.bitwise_and(first_core, second_mask)
        )
        > 0
        or cv2.countNonZero(
            cv2.bitwise_and(first_mask, second_core)
        )
        > 0
    )


def layout_has_interior_overlap(layout):
    polygons = [
        layout[piece_id]
        for piece_id in sorted(layout)
    ]
    for first_id in range(len(polygons)):
        for second_id in range(first_id + 1, len(polygons)):
            if polygons_have_interior_overlap(
                polygons[first_id],
                polygons[second_id],
            ):
                return True
    return False


def layout_can_be_separated(layout):
    piece_ids = sorted(layout)
    polygons = [
        layout[piece_id]
        for piece_id in piece_ids
    ]
    all_points = np.vstack(polygons)
    target_center = (
        np.min(all_points, axis=0)
        + np.max(all_points, axis=0)
    ) * 0.5
    centers = [
        np.mean(polygon, axis=0)
        for polygon in polygons
    ]

    moved = {
        piece_id: (
            polygon
            + (center - target_center) * 0.6
        )
        for piece_id, polygon, center in zip(
            piece_ids,
            polygons,
            centers,
        )
    }
    return not layout_has_interior_overlap(moved)


def rectangle_result_is_valid(result):
    return (
        result[0] is not None
        and result[2] >= 0.94
        and result[3] <= 0.06
        and layout_can_be_separated(result[0])
    )


def generate_boundary_candidates(
    polygon,
    width,
    height,
    position_step=4,
):
    """
    枚举碎片外边落在目标矩形四条边上的所有候选姿态。

    题目保证每块碎片至少有一条边属于矩形外边，因此不需要在整张
    矩形内部做二维平移搜索，只沿四条边搜索即可。
    """
    candidates = []
    generated = set()
    inside_tolerance = 2.5

    for edge_index in range(len(polygon)):
        edge_length = polygon_edge_length(polygon, edge_index)
        if edge_length < 8:
            continue

        for side in range(4):
            side_length = width if side < 2 else height
            if edge_length > side_length + inside_tolerance:
                continue

            maximum_position = max(0.0, side_length - edge_length)
            positions = list(
                np.arange(
                    0.0,
                    maximum_position + 0.1,
                    position_step,
                )
            )
            positions.extend((0.0, maximum_position))

            for position in positions:
                if side == 0:
                    first = np.array([position, 0.0], dtype=np.float32)
                    second = np.array(
                        [position + edge_length, 0.0],
                        dtype=np.float32,
                    )
                elif side == 1:
                    first = np.array(
                        [position, height - 1.0],
                        dtype=np.float32,
                    )
                    second = np.array(
                        [position + edge_length, height - 1.0],
                        dtype=np.float32,
                    )
                elif side == 2:
                    first = np.array([0.0, position], dtype=np.float32)
                    second = np.array(
                        [0.0, position + edge_length],
                        dtype=np.float32,
                    )
                else:
                    first = np.array(
                        [width - 1.0, position],
                        dtype=np.float32,
                    )
                    second = np.array(
                        [width - 1.0, position + edge_length],
                        dtype=np.float32,
                    )

                for target_start, target_end in (
                    (first, second),
                    (second, first),
                ):
                    transformed = align_polygon_edge(
                        polygon,
                        edge_index,
                        target_start,
                        target_end,
                    )
                    minimum = np.min(transformed, axis=0)
                    maximum = np.max(transformed, axis=0)
                    if (
                        minimum[0] < -inside_tolerance
                        or minimum[1] < -inside_tolerance
                        or maximum[0] > width - 1 + inside_tolerance
                        or maximum[1] > height - 1 + inside_tolerance
                    ):
                        continue

                    transformed[:, 0] = np.clip(
                        transformed[:, 0],
                        0,
                        width - 1,
                    )
                    transformed[:, 1] = np.clip(
                        transformed[:, 1],
                        0,
                        height - 1,
                    )
                    center = polygon_center(transformed)
                    pose_key = (
                        int(round(center[0] / 2)),
                        int(round(center[1] / 2)),
                        edge_index,
                        side,
                    )
                    if pose_key in generated:
                        continue
                    generated.add(pose_key)

                    (
                        mask_bits,
                        core_mask_bits,
                        area,
                    ) = polygon_mask_bits(
                        transformed,
                        width,
                        height,
                    )
                    candidates.append(
                        {
                            "mask": mask_bits,
                            "core_mask": core_mask_bits,
                            "area": area,
                            "polygon": transformed.copy(),
                        }
                    )
    return candidates


def search_rectangle_ratio(
    polygons,
    target_ratio,
    beam_width,
    position_step=4,
    max_piece_overlap_ratio=0.30,
):
    """在一个给定的矩形长宽比下搜索拼片位置。"""
    width = int(round(math.sqrt(6000.0 * target_ratio)))
    height = int(round(6000.0 / width))
    candidate_sets = [
        generate_boundary_candidates(
            polygon,
            width,
            height,
            position_step,
        )
        for polygon in polygons
    ]
    if any(not candidates for candidates in candidate_sets):
        return (
            None,
            0.0,
            0.0,
            0.0,
            sum(len(item) for item in candidate_sets),
            width,
            height,
        )

    piece_order = sorted(
        range(4),
        key=lambda piece_id: len(candidate_sets[piece_id]),
    )
    rectangle_area = width * height
    states = [
        {
            "union": 0,
            "core_union": 0,
            "covered": 0,
            "overlap": 0,
            "layout": {},
        }
    ]
    evaluated = 0

    for piece_id in piece_order:
        next_states = []
        for state in states:
            for candidate in candidate_sets[piece_id]:
                evaluated += 1
                boundary_overlap = count_mask_bits(
                    state["union"] & candidate["mask"]
                )
                candidate_core_overlap = count_mask_bits(
                    state["union"] & candidate["core_mask"]
                )
                placed_core_overlap = count_mask_bits(
                    state["core_union"] & candidate["mask"]
                )
                interior_overlap = max(
                    candidate_core_overlap,
                    placed_core_overlap,
                )
                if interior_overlap > max(
                    6,
                    int(
                        candidate["area"]
                        * max_piece_overlap_ratio
                    ),
                ):
                    continue

                layout = dict(state["layout"])
                layout[piece_id] = candidate["polygon"]
                next_states.append(
                    {
                        "union": state["union"] | candidate["mask"],
                        "core_union": (
                            state["core_union"]
                            | candidate["core_mask"]
                        ),
                        "covered": (
                            state["covered"]
                            + candidate["area"]
                            - boundary_overlap
                        ),
                        "overlap": (
                            state["overlap"]
                            + interior_overlap
                        ),
                        "layout": layout,
                    }
                )

        if not next_states:
            return None, 0.0, 0.0, 0.0, evaluated, width, height

        next_states.sort(
            key=lambda state: (
                state["covered"]
                - state["overlap"] * 8
            ),
            reverse=True,
        )
        states = next_states[:beam_width]

    ranked_states = sorted(
        states,
        key=lambda state: (
            state["covered"]
            - state["overlap"] * 8
        ),
        reverse=True,
    )
    best_state = None
    for state in ranked_states:
        if layout_can_be_separated(state["layout"]):
            best_state = state
            break
    if best_state is None:
        return None, 0.0, 0.0, 0.0, evaluated, width, height
    coverage = best_state["covered"] / rectangle_area
    overlap_ratio = best_state["overlap"] / rectangle_area
    score = coverage - overlap_ratio * 2.0
    return (
        best_state["layout"],
        score,
        coverage,
        overlap_ratio,
        evaluated,
        width,
        height,
    )


def solve_rectangle_by_cover(
    pieces,
    max_piece_overlap_ratio=0.30,
):
    """
    自动搜索允许范围内的目标矩形比例，再用位图束搜索拼接。

    返回的solve_info用于把求解坐标恢复为相机像素坐标。
    """
    if len(pieces) != 4:
        return None, 0.0, 0, None

    polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    total_piece_area = sum(
        abs(cv2.contourArea(polygon))
        for polygon in polygons
    )
    if total_piece_area < 100:
        return None, 0.0, 0, None

    solve_scale = math.sqrt(
        6000.0 * 0.98 / total_piece_area
    )
    polygons = [
        polygon * solve_scale
        for polygon in polygons
    ]

    ratios = [
        10.0 / 6.0,
        1.45,
        1.50,
        1.40,
        1.60,
        1.80,
        2.00,
        1.20,
        2.20,
        1.00,
        2.40,
    ]
    total_evaluated = 0
    best_ratio = ratios[0]
    best_result = None
    refined_ratios = set()

    for index, ratio in enumerate(ratios):
        beam_width = 16
        if index == 0:
            beam_width = 120
        elif index <= 3:
            beam_width = 60
        result = search_rectangle_ratio(
            polygons,
            ratio,
            beam_width,
            max_piece_overlap_ratio=max_piece_overlap_ratio,
        )
        total_evaluated += result[4]
        if (
            result[0] is not None
            and (
                best_result is None
                or result[1] > best_result[1]
            )
        ):
            best_result = result
            best_ratio = ratio

        if rectangle_result_is_valid(result):
            return (
                result[0],
                result[1],
                total_evaluated,
                {
                    "ratio": ratio,
                    "solve_scale": solve_scale,
                    "width": result[5],
                    "height": result[6],
                    "coverage": result[2],
                    "overlap": result[3],
                    "forced": False,
                },
            )
        if (
            index >= 2
            and best_result is not None
            and best_result[1] >= 0.72
            and best_ratio not in refined_ratios
        ):
            refined_result = search_rectangle_ratio(
                polygons,
                best_ratio,
                120,
                max_piece_overlap_ratio=max_piece_overlap_ratio,
            )
            refined_ratios.add(best_ratio)
            total_evaluated += refined_result[4]
            if refined_result[1] > best_result[1]:
                best_result = refined_result
            if rectangle_result_is_valid(refined_result):
                return (
                    refined_result[0],
                    refined_result[1],
                    total_evaluated,
                    {
                        "ratio": best_ratio,
                        "solve_scale": solve_scale,
                        "width": refined_result[5],
                        "height": refined_result[6],
                        "coverage": refined_result[2],
                        "overlap": refined_result[3],
                        "forced": False,
                    },
                )

    if (
        best_result is not None
        and best_ratio not in refined_ratios
    ):
        refined_result = search_rectangle_ratio(
            polygons,
            best_ratio,
            120,
            max_piece_overlap_ratio=max_piece_overlap_ratio,
        )
        total_evaluated += refined_result[4]
        if refined_result[1] > best_result[1]:
            best_result = refined_result
        if rectangle_result_is_valid(refined_result):
            return (
                refined_result[0],
                refined_result[1],
                total_evaluated,
                {
                    "ratio": best_ratio,
                    "solve_scale": solve_scale,
                    "width": refined_result[5],
                    "height": refined_result[6],
                    "coverage": refined_result[2],
                    "overlap": refined_result[3],
                    "forced": False,
                },
            )

    return (
        None,
        best_result[1] if best_result is not None else 0.0,
        total_evaluated,
        None,
    )


def fit_layout_to_box(layout, target_box):
    """把求出的整体拼图旋转、缩放到屏幕下半区显示。"""
    ordered_ids = sorted(layout)
    polygons = [layout[piece_id] for piece_id in ordered_ids]
    all_points = np.vstack(polygons).astype(np.float32)
    rectangle = cv2.minAreaRect(all_points)
    rectangle_points = cv2.boxPoints(rectangle)

    longest_vector = rectangle_points[1] - rectangle_points[0]
    for index in range(1, 4):
        vector = rectangle_points[(index + 1) % 4] - rectangle_points[index]
        if np.dot(vector, vector) > np.dot(longest_vector, longest_vector):
            longest_vector = vector

    angle = -math.atan2(longest_vector[1], longest_vector[0])
    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotation = np.array(
        [
            [cosine, -sine],
            [sine, cosine],
        ],
        dtype=np.float32,
    )
    center = np.mean(all_points, axis=0)
    rotated = [
        (polygon - center) @ rotation.T
        for polygon in polygons
    ]
    rotated_all = np.vstack(rotated)
    minimum = np.min(rotated_all, axis=0)
    maximum = np.max(rotated_all, axis=0)
    size = maximum - minimum

    if size[1] > size[0]:
        quarter_turn = np.array(
            [
                [0.0, -1.0],
                [1.0, 0.0],
            ],
            dtype=np.float32,
        )
        rotated = [polygon @ quarter_turn.T for polygon in rotated]
        rotated_all = np.vstack(rotated)
        minimum = np.min(rotated_all, axis=0)
        maximum = np.max(rotated_all, axis=0)
        size = maximum - minimum

    target_x, target_y, target_width, target_height = target_box
    scale = min(
        target_width / max(1.0, size[0]),
        target_height / max(1.0, size[1]),
    )
    target_center = np.array(
        [
            target_x + target_width * 0.5,
            target_y + target_height * 0.5,
        ],
        dtype=np.float32,
    )
    source_center = (minimum + maximum) * 0.5

    fitted = []
    for piece_id, polygon in zip(ordered_ids, rotated):
        points = np.rint(
            (polygon - source_center) * scale + target_center
        ).astype(np.int32)
        fitted.append(
            {
                "piece_id": piece_id,
                "points": [
                    (int(point[0]), int(point[1]))
                    for point in points
                ],
            }
        )
    return fitted


def point_segment_distance(point, start, end):
    vector = end - start
    length_squared = float(np.dot(vector, vector))
    if length_squared < 1e-6:
        return float(np.linalg.norm(point - start))
    amount = float(
        np.dot(point - start, vector) / length_squared
    )
    amount = min(1.0, max(0.0, amount))
    nearest = start + vector * amount
    return float(np.linalg.norm(point - nearest))


def polygon_distance(first, second):
    if polygons_have_interior_overlap(first, second):
        return -1.0

    best = float("inf")
    for point in first:
        for edge_id, start in enumerate(second):
            end = second[(edge_id + 1) % len(second)]
            best = min(
                best,
                point_segment_distance(point, start, end),
            )
    for point in second:
        for edge_id, start in enumerate(first):
            end = first[(edge_id + 1) % len(first)]
            best = min(
                best,
                point_segment_distance(point, start, end),
            )
    return best


def spread_layout_with_gap(polygons, target_center, gap_pixels):
    centers = [
        np.mean(polygon, axis=0)
        for polygon in polygons
    ]
    best_layout = [polygon.copy() for polygon in polygons]
    best_distance = -1.0

    for step in range(121):
        factor = step * 0.005
        moved = [
            polygon + (center - target_center) * factor
            for polygon, center in zip(polygons, centers)
        ]
        distances = []
        valid = True
        for first_id in range(len(moved)):
            for second_id in range(first_id + 1, len(moved)):
                distance = polygon_distance(
                    moved[first_id],
                    moved[second_id],
                )
                if distance < 0:
                    valid = False
                    break
                distances.append(distance)
            if not valid:
                break
        if not valid:
            continue

        minimum_distance = (
            min(distances)
            if distances
            else gap_pixels
        )
        if minimum_distance > best_distance:
            best_distance = minimum_distance
            best_layout = moved
        if minimum_distance >= gap_pixels:
            return moved

    return best_layout


def place_layout_on_paper(layout, solve_info, roi):
    """把目标矩形放到A4纸下半区，并给相邻拼片留出小缝。"""
    roi_x, roi_y, roi_width, roi_height = roi
    scale = 1.0 / solve_info["solve_scale"]
    target_width = solve_info["width"] * scale
    target_height = solve_info["height"] * scale
    target_left = roi_x + (roi_width - target_width) * 0.5
    lower_top = roi_y + roi_height * 0.5
    target_top = lower_top + (
        roi_height * 0.5 - target_height
    ) * 0.5
    piece_ids = sorted(layout)
    placed_polygons = []
    for piece_id in piece_ids:
        polygon = layout[piece_id]
        points = polygon * scale + np.array(
            [target_left, target_top],
            dtype=np.float32,
        )
        placed_polygons.append(points)

    fitted = []
    for piece_id, points in zip(piece_ids, placed_polygons):
        fitted.append(
            {
                "piece_id": piece_id,
                "points": [
                    (float(point[0]), float(point[1]))
                    for point in points
                ],
            }
        )
    return fitted


def prepare_layout_for_execution(layout, solve_info, roi):
    """把识别误差形成的轻微重叠修正掉，并在相邻边之间保留约1mm缝隙。"""
    strict_report = evaluate_layout(layout)
    gap_pixels = max(1.0, roi[3] / 297.0) * solve_info[
        "solve_scale"
    ]
    if strict_report["valid"]:
        prepared, gap_info = add_adjacency_gap(
            layout,
            gap_pixels,
        )
        mode = "EXACT"
        repair_info = {
            "valid": True,
            "stage": "strict",
            "reasons": [],
            "maximum_move": 0.0,
            "gap": gap_info,
        }
    else:
        prepared, repair_info = repair_layout_for_competition(
            layout,
            gap_pixels=gap_pixels,
        )
        mode = "EXEC"

    if prepared is None or layout_has_interior_overlap(prepared):
        return None, repair_info

    final_report = evaluate_layout(
        prepared,
        edge_tolerance_ratio=0.05,
    )
    solve_info["width"] = final_report["width"]
    solve_info["height"] = final_report["height"]
    solve_info["ratio"] = (
        final_report["width"]
        / max(1.0, final_report["height"])
    )
    solve_info["execution_mode"] = mode
    solve_info["constraint_report"] = {
        "coverage": final_report["coverage"],
        "overlap": final_report["overlap"],
        "outer_piece_ratio": final_report["outer_piece_ratio"],
        "internal_match": final_report["internal_match"],
    }
    solve_info["repair"] = repair_info
    return prepared, repair_info


def build_motion_plan(pieces, fitted_layout):
    """
    计算每块拼片的吸取点、放置点和图像坐标系旋转角。

    目标轮廓由当前轮廓刚体变换得到，顶点顺序保持一致，因此不会产生
    仅依靠最长边判断时常见的180度方向歧义。
    """
    targets = {
        item["piece_id"]: np.array(
            item["points"],
            dtype=np.float32,
        )
        for item in fitted_layout
    }
    plan = []

    for piece_id, piece in enumerate(pieces):
        source = np.array(
            piece["points"],
            dtype=np.float32,
        )
        target = targets[piece_id]

        best_start = 0
        best_end = 1
        best_length = 0.0
        for start in range(len(source)):
            for end in range(start + 1, len(source)):
                vector = source[end] - source[start]
                length = float(np.dot(vector, vector))
                if length > best_length:
                    best_start = start
                    best_end = end
                    best_length = length

        source_vector = (
            source[best_end] - source[best_start]
        )
        target_vector = (
            target[best_end] - target[best_start]
        )
        rotation = math.degrees(
            math.atan2(
                target_vector[1],
                target_vector[0],
            )
            - math.atan2(
                source_vector[1],
                source_vector[0],
            )
        )
        while rotation > 180:
            rotation -= 360
        while rotation <= -180:
            rotation += 360

        radians = math.radians(rotation)
        rotation_matrix = np.array(
            [
                [math.cos(radians), -math.sin(radians)],
                [math.sin(radians), math.cos(radians)],
            ],
            dtype=np.float32,
        )
        translation = (
            target[best_start]
            - rotation_matrix @ source[best_start]
        )
        pick = np.array(
            piece["center"],
            dtype=np.float32,
        )
        place = rotation_matrix @ pick + translation
        plan.append(
            {
                "piece_id": piece_id,
                "pick": (
                    float(pick[0]),
                    float(pick[1]),
                ),
                "place": (
                    float(place[0]),
                    float(place[1]),
                ),
                "rotation": rotation,
            }
        )
    return plan


def print_motion_plan(plan):
    """打印视觉坐标搬运指令，便于后续发送给机械臂控制器。"""
    for move in plan:
        print(
            "MOVE P%d PICK=(%.1f,%.1f) PLACE=(%.1f,%.1f) ROT_IMG=%+.1f"
            % (
                move["piece_id"] + 1,
                move["pick"][0],
                move["pick"][1],
                move["place"][0],
                move["place"][1],
                move["rotation"],
            ),
            flush=True,
        )


def draw_solved_rectangle(
    img,
    fitted_layout,
    target_box,
    score,
    motion_plan,
):
    """在A4纸下半区画出拼接后的矩形及内部接缝。"""
    target_x, target_y, _, _ = target_box
    colors = (
        image.COLOR_GREEN,
        image.COLOR_RED,
        image.COLOR_YELLOW,
        image.COLOR_BLUE,
    )
    rotations = {
        move["piece_id"]: move["rotation"]
        for move in motion_plan
    }
    for item in fitted_layout:
        points = item["points"]
        color = colors[item["piece_id"] % len(colors)]
        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            img.draw_line(
                int(round(start[0])),
                int(round(start[1])),
                int(round(end[0])),
                int(round(end[1])),
                color,
                4,
            )
        center_x = int(
            round(
                sum(point[0] for point in points)
                / len(points)
            )
        )
        center_y = int(
            round(
                sum(point[1] for point in points)
                / len(points)
            )
        )
        img.draw_string(
            center_x - 20,
            center_y - 18,
            "S%d R%+.0f"
            % (
                item["piece_id"] + 1,
                rotations[item["piece_id"]],
            ),
            color,
            scale=1,
        )

    img.draw_string(
        target_x,
        target_y - 36,
        "SOLVED %.3f" % score,
        image.COLOR_WHITE,
        scale=2,
    )


def draw_roi(img, roi):
    """在屏幕上画出当前参与识别的区域。"""
    x, y, width, height = roi
    right = x + width - 1
    bottom = y + height - 1
    img.draw_line(x, y, right, y, image.COLOR_YELLOW, 1)
    img.draw_line(right, y, right, bottom, image.COLOR_YELLOW, 1)
    img.draw_line(right, bottom, x, bottom, image.COLOR_YELLOW, 1)
    img.draw_line(x, bottom, x, y, image.COLOR_YELLOW, 1)


def draw_piece(img, piece, piece_id):
    """画出一块碎片的轮廓、中心、最长边和简洁编号。"""
    points = piece["points"]
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        img.draw_line(
            start[0],
            start[1],
            end[0],
            end[1],
            image.COLOR_GREEN,
            2,
        )

    edge_start, edge_end = piece["longest_edge"]
    img.draw_line(
        edge_start[0],
        edge_start[1],
        edge_end[0],
        edge_end[1],
        image.COLOR_YELLOW,
        3,
    )

    center_x, center_y = piece["center"]
    img.draw_cross(
        center_x,
        center_y,
        image.COLOR_RED,
        size=6,
        thickness=2,
    )
    label = "P%d" % piece_id
    img.draw_string(
        max(0, center_x - 24),
        max(0, center_y - 44),
        label,
        image.COLOR_GREEN,
        scale=2,
    )


def print_detection(pieces, threshold_info):
    """把结果打印到串口终端，之后可直接扩展为机械控制数据。"""
    print(
        "pieces=%d polarity=%s mode=%s threshold=%d"
        % (
            len(pieces),
            threshold_info["polarity"],
            threshold_info["threshold_mode"],
            threshold_info["threshold"],
        ),
        flush=True,
    )
    for index, piece in enumerate(pieces, 1):
        print(
            "  P%d center=(%d,%d) vertices=%d area=%d angle=%.1f"
            % (
                index,
                piece["center"][0],
                piece["center"][1],
                len(piece["points"]),
                int(piece["area"]),
                piece["angle"],
            ),
            flush=True,
        )


def touch_in_box(
    touch_status,
    box,
    image_width,
    image_height,
    display_width,
    display_height,
):
    """把图像上的按钮位置映射到实际屏幕触摸坐标。"""
    if not touch_status[2]:
        return False

    mapped = image.resize_map_pos(
        image_width,
        image_height,
        display_width,
        display_height,
        image.Fit.FIT_CONTAIN,
        box[0],
        box[1],
        box[2],
        box[3],
    )
    return (
        mapped[0] <= touch_status[0] < mapped[0] + mapped[2]
        and mapped[1] <= touch_status[1] < mapped[1] + mapped[3]
    )


def get_button_boxes(image_width, image_height):
    """返回右侧调参按钮在摄像头图像中的位置。"""
    if image_height > image_width:
        return {
            "solve": [20, 760, 330, 70],
            "tune": [370, 760, 330, 70],
            "capture": [20, 840, 680, 70],
            "threshold_down": [20, 810, 330, 70],
            "threshold_up": [370, 810, 330, 70],
            "auto_threshold": [20, 890, 680, 70],
            "polarity": [20, 970, 680, 70],
            "area_down": [20, 1050, 330, 70],
            "area_up": [370, 1050, 330, 70],
            "close": [20, 1190, 680, 70],
        }

    panel_x = image_width - 350
    return {
        "solve": [panel_x + 10, 10, 155, 70],
        "tune": [panel_x + 175, 10, 155, 70],
        "capture": [panel_x + 10, 90, 320, 70],
        "threshold_down": [panel_x + 10, 90, 155, 70],
        "threshold_up": [panel_x + 175, 90, 155, 70],
        "auto_threshold": [panel_x + 10, 170, 320, 70],
        "polarity": [panel_x + 10, 250, 320, 70],
        "area_down": [panel_x + 10, 330, 155, 70],
        "area_up": [panel_x + 175, 330, 155, 70],
        "close": [panel_x + 10, 500, 320, 70],
    }


def draw_button(img, box, text, active=False):
    """绘制适合高分辨率画面缩放显示的触摸按钮。"""
    color = image.COLOR_GREEN if active else image.COLOR_WHITE
    img.draw_rect(
        box[0],
        box[1],
        box[2],
        box[3],
        image.COLOR_BLACK,
        -1,
    )
    img.draw_rect(
        box[0],
        box[1],
        box[2],
        box[3],
        color,
        3,
    )

    text_size = image.string_size(text, scale=2)
    text_width = (
        text_size.width()
        if hasattr(text_size, "width")
        else text_size[0]
    )
    text_height = (
        text_size.height()
        if hasattr(text_size, "height")
        else text_size[1]
    )
    img.draw_string(
        box[0] + (box[2] - text_width) // 2,
        box[1] + (box[3] - text_height) // 2,
        text,
        color,
        scale=2,
    )


def draw_controls(
    img,
    boxes,
    auto_threshold,
    threshold_value,
    polarity_mode,
    min_piece_area,
):
    """显示阈值、极性和最小面积的触摸调参面板。"""
    if img.height() > img.width():
        img.draw_rect(
            0,
            740,
            img.width(),
            img.height() - 740,
            image.COLOR_BLACK,
            -1,
        )
        img.draw_string(
            20,
            755,
            "BINARY TUNE",
            image.COLOR_WHITE,
            scale=2,
        )
    else:
        panel_x = boxes["threshold_down"][0] - 10
        img.draw_rect(
            panel_x,
            0,
            img.width() - panel_x,
            590,
            image.COLOR_BLACK,
            -1,
        )
        img.draw_string(
            panel_x + 10,
            20,
            "BINARY TUNE",
            image.COLOR_WHITE,
            scale=2,
        )
    draw_button(
        img,
        boxes["threshold_down"],
        "TH -5",
    )
    draw_button(
        img,
        boxes["threshold_up"],
        "TH +5",
    )
    draw_button(
        img,
        boxes["auto_threshold"],
        "TH AUTO" if auto_threshold else "TH %d" % threshold_value,
        active=auto_threshold,
    )
    draw_button(
        img,
        boxes["polarity"],
        "POL %s" % polarity_mode,
        active=polarity_mode != "AUTO",
    )
    draw_button(
        img,
        boxes["area_down"],
        "AREA -",
    )
    draw_button(
        img,
        boxes["area_up"],
        "AREA +",
    )
    img.draw_string(
        boxes["area_down"][0],
        boxes["area_down"][1] + boxes["area_down"][3] + 12,
        "MIN AREA %d" % min_piece_area,
        image.COLOR_WHITE,
        scale=2,
    )
    draw_button(
        img,
        boxes["close"],
        "BACK",
    )


def show_binary_preview(frame_rgb, mask, roi):
    """调参页面中把当前参与识别的二值图直接显示出来。"""
    roi_x, roi_y, roi_width, roi_height = roi
    frame_rgb[:, :, :] = 0
    preview = frame_rgb[
        roi_y : roi_y + roi_height,
        roi_x : roi_x + roi_width,
    ]
    preview[:, :, 0] = mask
    preview[:, :, 1] = mask
    preview[:, :, 2] = mask


def save_capture(
    frame_rgb,
    mask,
    pieces,
    threshold_info,
    roi,
    settings,
):
    capture_dir = "/home/pi5/puzzle_card_detector/captures"
    os.makedirs(capture_dir, exist_ok=True)
    timestamp = "%s_%03d" % (
        time.strftime("%Y%m%d_%H%M%S"),
        int(time.time() * 1000) % 1000,
    )
    prefix = os.path.join(capture_dir, timestamp)
    roi_x, roi_y, roi_width, roi_height = roi
    raw_bgr = cv2.cvtColor(
        frame_rgb,
        cv2.COLOR_RGB2BGR,
    )
    roi_bgr = raw_bgr[
        roi_y : roi_y + roi_height,
        roi_x : roi_x + roi_width,
    ]
    if not cv2.imwrite(prefix + "_raw.png", raw_bgr):
        raise RuntimeError("cannot save raw capture")
    if not cv2.imwrite(prefix + "_roi.png", roi_bgr):
        raise RuntimeError("cannot save ROI capture")
    if not cv2.imwrite(prefix + "_binary.png", mask):
        raise RuntimeError("cannot save binary capture")

    metadata = {
        "timestamp": timestamp,
        "raw_file": timestamp + "_raw.png",
        "roi_file": timestamp + "_roi.png",
        "binary_file": timestamp + "_binary.png",
        "image_size": [
            int(frame_rgb.shape[1]),
            int(frame_rgb.shape[0]),
        ],
        "roi": [
            int(roi_x),
            int(roi_y),
            int(roi_width),
            int(roi_height),
        ],
        "threshold": int(threshold_info["threshold"]),
        "threshold_mode": threshold_info["threshold_mode"],
        "polarity": threshold_info["polarity"],
        "settings": settings,
        "pieces": [
            {
                "index": index,
                "points": [
                    [int(point[0]), int(point[1])]
                    for point in piece["points"]
                ],
                "center": [
                    int(piece["center"][0]),
                    int(piece["center"][1]),
                ],
                "area": float(piece["area"]),
                "solidity": float(piece["solidity"]),
                "angle": float(piece["angle"]),
            }
            for index, piece in enumerate(pieces, 1)
        ],
    }
    with open(prefix + ".json", "w", encoding="utf-8") as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )
    print(
        "CAPTURE_SAVED %s pieces=%d"
        % (timestamp, len(pieces)),
        flush=True,
    )
    return timestamp


def align_polygon_points(reference, points):
    reference = np.asarray(reference, dtype=np.float64)
    points = np.asarray(points, dtype=np.float64)
    best = points
    best_error = float("inf")
    for candidate in (points, points[::-1]):
        for offset in range(len(candidate)):
            aligned = np.roll(candidate, offset, axis=0)
            error = float(
                np.mean((aligned - reference) ** 2)
            )
            if error < best_error:
                best = aligned
                best_error = error
    return best


def build_stable_piece_set(recent_piece_sets):
    """从最近的连续画面中生成一组中值轮廓，运动中或顶点跳变时不求解。"""
    if not recent_piece_sets:
        return None

    reference = recent_piece_sets[-1][2]
    if not 2 <= len(reference) <= 4:
        return None

    aligned_sets = []
    for _, _, candidate in reversed(recent_piece_sets[-12:]):
        if len(candidate) != len(reference):
            continue
        best_order = None
        best_error = float("inf")
        for order in itertools.permutations(range(len(candidate))):
            distances = []
            valid = True
            for piece_id, candidate_id in enumerate(order):
                if len(candidate[candidate_id]["points"]) != len(
                    reference[piece_id]["points"]
                ):
                    valid = False
                    break
                first = np.asarray(
                    reference[piece_id]["center"],
                    dtype=np.float64,
                )
                second = np.asarray(
                    candidate[candidate_id]["center"],
                    dtype=np.float64,
                )
                distances.append(
                    float(np.linalg.norm(first - second))
                )
            if not valid or max(distances, default=99.0) > 12.0:
                continue
            error = sum(distance * distance for distance in distances)
            if error < best_error:
                best_error = error
                best_order = order
        if best_order is not None:
            aligned_sets.append(
                [candidate[index] for index in best_order]
            )
        if len(aligned_sets) >= 8:
            break

    if len(aligned_sets) < 4:
        return None

    stable_pieces = []
    for piece_id, reference_piece in enumerate(reference):
        reference_points = np.asarray(
            reference_piece["points"],
            dtype=np.float64,
        )
        point_samples = []
        area_samples = []
        solidity_samples = []
        for pieces in aligned_sets:
            piece = pieces[piece_id]
            point_samples.append(
                align_polygon_points(
                    reference_points,
                    piece["points"],
                )
            )
            area_samples.append(float(piece["area"]))
            solidity_samples.append(float(piece["solidity"]))

        points_array = np.asarray(point_samples)
        median_points = np.median(points_array, axis=0)
        point_spread = float(
            np.max(
                np.sqrt(
                    np.mean(
                        (points_array - median_points) ** 2,
                        axis=2,
                    )
                )
            )
        )
        median_area = float(np.median(area_samples))
        area_spread = (
            max(area_samples) - min(area_samples)
        ) / max(1.0, median_area)
        if point_spread > 3.5 or area_spread > 0.08:
            return None

        points = [
            (int(round(point[0])), int(round(point[1])))
            for point in median_points
        ]
        contour = np.asarray(points, dtype=np.float32)
        moments = cv2.moments(contour)
        if abs(moments["m00"]) < 1:
            return None
        center = (
            int(round(moments["m10"] / moments["m00"])),
            int(round(moments["m01"] / moments["m00"])),
        )
        piece_longest_edge, angle = longest_edge(points)
        stable_pieces.append(
            {
                "points": points,
                "center": center,
                "area": median_area,
                "angle": angle,
                "longest_edge": piece_longest_edge,
                "solidity": float(
                    np.median(solidity_samples)
                ),
            }
        )
    return stable_pieces


def solve_piece_set_worker(pieces, roi):
    """在独立进程中求解，避免搜索期间停止读取摄像头。"""
    cv2.setNumThreads(1)
    started = time.monotonic()
    solved_layout = None
    solved_score = 0.0
    solver_nodes = 0
    solve_info = None

    print(
        "SOLVE_STABLE %s"
        % [piece["points"] for piece in pieces],
        flush=True,
    )
    if len(pieces) == 4:
        (
            candidate_layout,
            candidate_score,
            candidate_nodes,
            candidate_info,
        ) = solve_rectangle_by_cover(pieces)
        solver_nodes += candidate_nodes
        solved_score = max(solved_score, candidate_score)
        if candidate_layout is not None:
            candidate_info = dict(candidate_info)
            candidate_info["method"] = "legacy-cover"
            candidate_layout, repair_info = (
                prepare_layout_for_execution(
                    candidate_layout,
                    candidate_info,
                    roi,
                )
            )
            if candidate_layout is None:
                print(
                    "SOLVE_REJECT legacy %s" % repair_info,
                    flush=True,
                )
            else:
                solved_layout = candidate_layout
                solved_score = candidate_score
                solve_info = candidate_info

    if solved_layout is None:
        (
            candidate_layout,
            candidate_score,
            candidate_nodes,
            candidate_info,
        ) = solve_camera_rectangle(
            pieces,
            roi,
            time_limit_s=2.2,
            allow_relaxed=False,
        )
        solver_nodes += candidate_nodes
        solved_score = max(solved_score, candidate_score)
        if candidate_layout is not None:
            candidate_info = dict(candidate_info)
            candidate_layout, repair_info = (
                prepare_layout_for_execution(
                    candidate_layout,
                    candidate_info,
                    roi,
                )
            )
        if candidate_layout is not None:
            solved_layout = candidate_layout
            solved_score = candidate_score
            solve_info = candidate_info

    return {
        "layout": solved_layout,
        "score": solved_score,
        "nodes": solver_nodes,
        "info": solve_info,
        "pieces": pieces,
        "elapsed_ms": (
            time.monotonic() - started
        ) * 1000.0,
    }


def main():
    portrait_mode = os.environ.get("PUZZLE_PORTRAIT", "0") == "1"
    capture_width = 1280
    capture_height = 720
    camera_width = 720 if portrait_mode else capture_width
    camera_height = 1280 if portrait_mode else capture_height
    portrait_crop_x = (
        int(os.environ.get("PUZZLE_PORTRAIT_CROP_X", "280"))
        if portrait_mode
        else 0
    )

    # 黄色框必须落在A4纸内部，不能包含纸张外部背景。
    # 安装好相机后，只需要调整这里的四个数。
    roi_x = 380 - portrait_crop_x if portrait_mode else 380
    roi_y = 10
    roi_width = 520
    roi_height = 700

    min_piece_area = 1500
    max_piece_area_ratio = 0.35
    max_piece_count = 4
    polygon_epsilon = 0.022

    cam = camera.Camera(
        capture_width,
        capture_height,
        image.Format.FMT_RGB888,
        fps=30,
        buff_num=3,
    )
    disp = display.Display()
    touch = touchscreen.TouchScreen()

    fps = 0.0
    fps_frames = 0
    fps_start = time.monotonic()
    last_print_time = 0.0
    touch_was_pressed = False
    auto_threshold = True
    manual_threshold = 128
    current_threshold = 128
    polarity_mode = "AUTO"
    tuning_open = False
    solve_requested = False
    solved_display = None
    solved_score = 0.0
    solved_ratio = 0.0
    motion_plan = []
    solver_message = ""
    solver_nodes = 0
    solver_ms = 0.0
    recent_piece_sets = []
    solver_executor = concurrent.futures.ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    )
    solver_future = None
    solve_started_at = 0.0
    pending_solve_until = 0.0
    last_capture_name = ""
    last_capture_time = 0.0
    button_boxes = get_button_boxes(
        camera_width,
        camera_height,
    )
    solution_box = (
        roi_x + 40,
        roi_y + roi_height // 2 + 65,
        roi_width - 80,
        roi_height // 2 - 105,
    )
    print("Puzzle detector started", flush=True)

    while not app.need_exit():
        solve_requested = False
        capture_requested = False
        img = cam.read()
        frame_rgb = image.image2cv(
            img,
            ensure_bgr=False,
            copy=False,
        )
        if os.path.exists("/tmp/puzzle_capture_once"):
            os.remove("/tmp/puzzle_capture_once")
            cv2.imwrite(
                "/tmp/puzzle_frame.png",
                cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR),
            )

        touch_status = touch.read()
        touch_clicked = touch_status[2] and not touch_was_pressed
        if touch_clicked:
            touch_args = (
                camera_width,
                camera_height,
                disp.width(),
                disp.height(),
            )
            if not tuning_open:
                if touch_in_box(
                    touch_status,
                    button_boxes["solve"],
                    *touch_args,
                ):
                    solve_requested = True
                elif touch_in_box(
                    touch_status,
                    button_boxes["tune"],
                    *touch_args,
                ):
                    tuning_open = True
                elif touch_in_box(
                    touch_status,
                    button_boxes["capture"],
                    *touch_args,
                ):
                    capture_requested = True
            elif touch_in_box(
                touch_status,
                button_boxes["close"],
                *touch_args,
            ):
                tuning_open = False
            elif touch_in_box(
                touch_status,
                button_boxes["threshold_down"],
                *touch_args,
            ):
                if auto_threshold:
                    manual_threshold = current_threshold
                manual_threshold = max(0, manual_threshold - 5)
                auto_threshold = False
            elif touch_in_box(
                touch_status,
                button_boxes["threshold_up"],
                *touch_args,
            ):
                if auto_threshold:
                    manual_threshold = current_threshold
                manual_threshold = min(255, manual_threshold + 5)
                auto_threshold = False
            elif touch_in_box(
                touch_status,
                button_boxes["auto_threshold"],
                *touch_args,
            ):
                auto_threshold = True
            elif touch_in_box(
                touch_status,
                button_boxes["polarity"],
                *touch_args,
            ):
                if polarity_mode == "AUTO":
                    polarity_mode = "LIGHT"
                elif polarity_mode == "LIGHT":
                    polarity_mode = "DARK"
                else:
                    polarity_mode = "AUTO"
            elif touch_in_box(
                touch_status,
                button_boxes["area_down"],
                *touch_args,
            ):
                min_piece_area = max(100, min_piece_area - 250)
            elif touch_in_box(
                touch_status,
                button_boxes["area_up"],
                *touch_args,
            ):
                min_piece_area = min(50000, min_piece_area + 250)
        touch_was_pressed = touch_status[2]
        if os.path.exists("/tmp/puzzle_solve_once"):
            os.remove("/tmp/puzzle_solve_once")
            solve_requested = True
        if os.path.exists("/tmp/puzzle_dataset_capture_once"):
            os.remove("/tmp/puzzle_dataset_capture_once")
            capture_requested = True

        pieces, threshold_info = detect_pieces(
            frame_rgb,
            (roi_x, roi_y, roi_width, roi_height),
            min_area=min_piece_area,
            max_area_ratio=max_piece_area_ratio,
            max_pieces=max_piece_count,
            polygon_epsilon=polygon_epsilon,
            threshold=None if auto_threshold else manual_threshold,
            polarity_mode=polarity_mode,
        )
        current_threshold = threshold_info["threshold"]
        if capture_requested:
            last_capture_name = save_capture(
                frame_rgb,
                threshold_info["mask"],
                pieces,
                threshold_info,
                (roi_x, roi_y, roi_width, roi_height),
                {
                    "auto_threshold": bool(auto_threshold),
                    "manual_threshold": int(manual_threshold),
                    "polarity_mode": polarity_mode,
                    "min_piece_area": int(min_piece_area),
                    "max_piece_area_ratio": float(
                        max_piece_area_ratio
                    ),
                    "polygon_epsilon": float(polygon_epsilon),
                    "portrait_crop_x": int(portrait_crop_x),
                },
            )
            last_capture_time = time.monotonic()
        frame_time = time.monotonic()
        recent_piece_sets = [
            item
            for item in recent_piece_sets
            if frame_time - item[0] <= 0.8
        ]
        if 2 <= len(pieces) <= 4:
            recent_piece_sets.append(
                (
                    frame_time,
                    sum(
                        piece["area"] * piece["solidity"]
                        for piece in pieces
                    ),
                    pieces,
                )
            )

        if solve_requested:
            if solver_future is not None:
                solver_message = "SOLVING"
            else:
                pending_solve_until = time.monotonic() + 2.0
                solver_message = "HOLD STILL"
                solver_ms = 0.0

        if (
            pending_solve_until > 0
            and solver_future is None
        ):
            stable_pieces = build_stable_piece_set(
                recent_piece_sets
            )
            if stable_pieces is not None:
                pending_solve_until = 0.0
                solved_display = None
                motion_plan = []
                solved_score = 0.0
                solved_ratio = 0.0
                solver_nodes = 0
                solver_message = "SOLVING"
                solve_started_at = time.monotonic()
                solver_future = solver_executor.submit(
                    solve_piece_set_worker,
                    stable_pieces,
                    (
                        roi_x,
                        roi_y,
                        roi_width,
                        roi_height,
                    ),
                )
            elif time.monotonic() >= pending_solve_until:
                pending_solve_until = 0.0
                solver_message = "NO STABLE"

        if solver_future is not None and not solver_future.done():
            solver_ms = (
                time.monotonic() - solve_started_at
            ) * 1000.0

        if solver_future is not None and solver_future.done():
            try:
                result = solver_future.result()
            except Exception as error:
                print(
                    "SOLVE_ERROR %r" % error,
                    flush=True,
                )
                result = None
            solver_future = None

            if result is None:
                solved_display = None
                solved_ratio = 0.0
                motion_plan = []
                solver_message = "SOLVE ERROR"
            else:
                solved_layout = result["layout"]
                solved_score = result["score"]
                solver_nodes = result["nodes"]
                solver_ms = result["elapsed_ms"]
                solve_info = result["info"]
                solve_pieces = result["pieces"]
                if solved_layout is None:
                    solved_display = None
                    solved_ratio = 0.0
                    motion_plan = []
                    solver_message = "NO RECT"
                else:
                    solved_display = place_layout_on_paper(
                        solved_layout,
                        solve_info,
                        (
                            roi_x,
                            roi_y,
                            roi_width,
                            roi_height,
                        ),
                    )
                    solved_ratio = solve_info["ratio"]
                    safe_layout = {
                        item["piece_id"]: np.array(
                            item["points"],
                            dtype=np.float32,
                        )
                        for item in solved_display
                    }
                    if layout_has_interior_overlap(safe_layout):
                        solved_display = None
                        solved_ratio = 0.0
                        motion_plan = []
                        solver_message = "NO SAFE"
                    else:
                        motion_plan = build_motion_plan(
                            solve_pieces,
                            solved_display,
                        )
                        if portrait_mode:
                            for move in motion_plan:
                                move["pick"] = (
                                    move["pick"][0]
                                    + portrait_crop_x,
                                    move["pick"][1],
                                )
                                move["place"] = (
                                    move["place"][0]
                                    + portrait_crop_x,
                                    move["place"][1],
                                )
                        solver_message = (
                            "SOLVE COVER G1.0"
                            if solve_info["method"]
                            == "legacy-cover"
                            else "SOLVE HYB G1.0"
                        )
                        print_motion_plan(motion_plan)
                print(
                    "%s score=%.3f ratio=%.3f tested=%d "
                    "time=%.1fms method=%s"
                    % (
                        solver_message,
                        solved_score,
                        solved_ratio,
                        solver_nodes,
                        solver_ms,
                        (
                            solve_info["method"]
                            if solve_info is not None
                            else "-"
                        ),
                    ),
                    flush=True,
                )

        if tuning_open:
            show_binary_preview(
                frame_rgb,
                threshold_info["mask"],
                (roi_x, roi_y, roi_width, roi_height),
            )

        draw_roi(
            img,
            (roi_x, roi_y, roi_width, roi_height),
        )
        for index, piece in enumerate(pieces, 1):
            draw_piece(img, piece, index)

        if not tuning_open and solved_display is not None:
            draw_solved_rectangle(
                img,
                solved_display,
                solution_box,
                solved_score,
                motion_plan,
            )

        img.draw_string(
            4,
            4,
            "PIECES %d  %s  T%d"
            % (
                len(pieces),
                threshold_info["polarity"],
                threshold_info["threshold"],
            ),
            image.COLOR_WHITE,
            scale=2,
        )
        if not tuning_open and solver_message:
            img.draw_string(
                4,
                42,
                "%s %.3f R%.2f %.0fms"
                % (
                    solver_message,
                    solved_score,
                    solved_ratio,
                    solver_ms,
                ),
                image.COLOR_GREEN
                if solver_message.startswith("SOLVE")
                else image.COLOR_YELLOW,
                scale=2,
            )
        if tuning_open:
            draw_controls(
                img,
                button_boxes,
                auto_threshold,
                manual_threshold,
                polarity_mode,
                min_piece_area,
            )
        else:
            draw_button(
                img,
                button_boxes["solve"],
                "SOLVE",
                active=solved_display is not None,
            )
            draw_button(
                img,
                button_boxes["tune"],
                "TUNE",
            )
            draw_button(
                img,
                button_boxes["capture"],
                "CAPTURE",
            )
            if (
                last_capture_name
                and time.monotonic() - last_capture_time < 2.5
            ):
                img.draw_string(
                    20,
                    920 if img.height() > img.width() else 175,
                    "SAVED %s" % last_capture_name[-10:],
                    image.COLOR_GREEN,
                    scale=2,
                )

        now = time.monotonic()
        fps_frames += 1
        elapsed = now - fps_start
        if elapsed >= 1:
            fps = fps_frames / elapsed
            fps_frames = 0
            fps_start = now
        img.draw_string(
            4,
            camera_height - 38,
            "FPS %.1f" % fps,
            image.COLOR_WHITE,
            scale=2,
        )

        if now - last_print_time >= 1:
            print_detection(pieces, threshold_info)
            last_print_time = now

        disp.show(img)

    solver_executor.shutdown(
        wait=False,
        cancel_futures=True,
    )


if __name__ == "__main__":
    main()
