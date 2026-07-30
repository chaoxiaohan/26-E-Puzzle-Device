# -*- coding: utf-8 -*-

import math
import itertools
import time

import cv2
import numpy as np

from solver_v2 import (
    align_edge_segment,
    edge_length,
    interval_is_free,
    interval_positions,
    layout_metrics,
    normalize_polygon,
    opposite_sides,
    polygon_center,
    polygons_overlap,
    quick_compactness,
    residual_partition_error,
)


def _inward_normal(polygon, edge_id):
    start = polygon[edge_id]
    end = polygon[(edge_id + 1) % len(polygon)]
    vector = end - start
    length = float(np.linalg.norm(vector))
    if length < 1e-6:
        return None

    normal = np.array(
        [-vector[1] / length, vector[0] / length],
        dtype=np.float64,
    )
    middle = (start + end) * 0.5
    contour = polygon.astype(np.float32)
    first_test = middle + normal * 3.0
    if cv2.pointPolygonTest(
        contour,
        (float(first_test[0]), float(first_test[1])),
        False,
    ) < 0:
        normal = -normal
    return normal


def _sample_edge_strip(
    frame_rgb,
    polygon,
    edge_id,
    offset,
    shared_length,
    reverse=False,
):
    start = polygon[edge_id]
    end = polygon[(edge_id + 1) % len(polygon)]
    vector = end - start
    full_length = float(np.linalg.norm(vector))
    normal = _inward_normal(polygon, edge_id)
    if full_length < 1e-6 or normal is None:
        return None

    unit = vector / full_length
    sample_count = max(20, min(56, int(shared_length * 0.65)))
    margin = min(3.0, shared_length * 0.08)
    along = np.linspace(
        offset + margin,
        offset + shared_length - margin,
        sample_count,
        dtype=np.float32,
    )
    if reverse:
        along = along[::-1].copy()

    depths = np.array([2.5, 5.0, 8.5], dtype=np.float32)
    map_x = np.empty((len(depths), sample_count), dtype=np.float32)
    map_y = np.empty_like(map_x)
    valid = np.ones((len(depths), sample_count), dtype=bool)
    contour = polygon.astype(np.float32)

    for depth_id, depth in enumerate(depths):
        points = (
            start[None, :]
            + along[:, None] * unit[None, :]
            + float(depth) * normal[None, :]
        )
        map_x[depth_id] = points[:, 0]
        map_y[depth_id] = points[:, 1]
        for sample_id, point in enumerate(points):
            valid[depth_id, sample_id] = (
                cv2.pointPolygonTest(
                    contour,
                    (float(point[0]), float(point[1])),
                    False,
                )
                >= 0
            )

    sampled = cv2.remap(
        frame_rgb,
        map_x,
        map_y,
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    ).astype(np.float32)
    return sampled, valid


def _profile_features(samples):
    rgb = samples / 255.0
    maximum = np.max(rgb, axis=2)
    minimum = np.min(rgb, axis=2)
    gray = (
        rgb[:, :, 0] * 0.299
        + rgb[:, :, 1] * 0.587
        + rgb[:, :, 2] * 0.114
    )
    darkness = 1.0 - maximum
    saturation = maximum - minimum
    redness = np.maximum(
        0.0,
        rgb[:, :, 0] - np.maximum(rgb[:, :, 1], rgb[:, :, 2]),
    )
    return np.stack(
        (gray, darkness, saturation, redness),
        axis=2,
    )


def _compare_edge_strips(first, second):
    if first is None or second is None:
        return 0.5, 0.0

    first_features = _profile_features(first[0])
    second_features = _profile_features(second[0])
    first_valid = first[1]
    second_valid = second[1]
    best_error = 1.0

    for shift in range(-2, 3):
        if shift < 0:
            first_slice = slice(-shift, None)
            second_slice = slice(None, shift)
        elif shift > 0:
            first_slice = slice(None, -shift)
            second_slice = slice(shift, None)
        else:
            first_slice = slice(None)
            second_slice = slice(None)

        valid = (
            first_valid[:, first_slice]
            & second_valid[:, second_slice]
        )
        if np.count_nonzero(valid) < 18:
            continue
        difference = np.abs(
            first_features[:, first_slice]
            - second_features[:, second_slice]
        )
        feature_error = (
            difference[:, :, 0] * 0.28
            + difference[:, :, 1] * 0.34
            + difference[:, :, 2] * 0.16
            + difference[:, :, 3] * 0.22
        )
        first_ink = np.maximum(
            first_features[:, first_slice, 1],
            first_features[:, first_slice, 2] * 0.75,
        )
        second_ink = np.maximum(
            second_features[:, second_slice, 1],
            second_features[:, second_slice, 2] * 0.75,
        )
        pattern_weight = 0.12 + np.maximum(
            first_ink,
            second_ink,
        )
        best_error = min(
            best_error,
            float(
                np.sum(feature_error[valid] * pattern_weight[valid])
                / np.sum(pattern_weight[valid])
            ),
        )

    combined = np.maximum(
        first_features[:, :, 1],
        second_features[:, :, 1],
    )
    color = np.maximum(
        first_features[:, :, 2],
        second_features[:, :, 2],
    )
    evidence = min(
        1.0,
        float(np.mean(combined) * 2.8 + np.mean(color) * 1.6),
    )
    quality = math.exp(-best_error * 7.0)
    return quality, evidence


def _texture_summary(seams):
    if not seams:
        return 0.5, 0.0
    total_weight = sum(max(0.05, item[1]) for item in seams)
    raw_score = sum(
        item[0] * max(0.05, item[1])
        for item in seams
    ) / total_weight
    confidence = min(
        1.0,
        sum(item[1] for item in seams) / max(1.0, len(seams) * 0.45),
    )
    return 0.5 + (raw_score - 0.5) * confidence, confidence


def score_layout_texture(frame_rgb, pieces, layout):
    """对一个已闭合矩形的所有真实内部接缝进行扑克牌花纹评分。"""
    source_polygons = [
        np.asarray(piece["points"], dtype=np.float64)
        for piece in pieces
    ]
    target_polygons = {
        piece_id: np.asarray(polygon, dtype=np.float64)
        for piece_id, polygon in layout.items()
    }
    seams = []
    piece_ids = sorted(target_polygons)

    for first_index, first_id in enumerate(piece_ids):
        first_target = target_polygons[first_id]
        first_source = source_polygons[first_id]
        first_center = polygon_center(first_target)
        for second_id in piece_ids[first_index + 1:]:
            second_target = target_polygons[second_id]
            second_source = source_polygons[second_id]
            second_center = polygon_center(second_target)

            for first_edge in range(len(first_target)):
                first_start = first_target[first_edge]
                first_end = first_target[
                    (first_edge + 1) % len(first_target)
                ]
                first_vector = first_end - first_start
                first_length = float(np.linalg.norm(first_vector))
                if first_length < 1e-6:
                    continue
                first_unit = first_vector / first_length

                for second_edge in range(len(second_target)):
                    second_start = second_target[second_edge]
                    second_end = second_target[
                        (second_edge + 1) % len(second_target)
                    ]
                    second_vector = second_end - second_start
                    second_length = float(
                        np.linalg.norm(second_vector)
                    )
                    if second_length < 1e-6:
                        continue
                    second_unit = second_vector / second_length
                    if float(np.dot(first_unit, second_unit)) > -0.94:
                        continue

                    normal = np.array(
                        [-first_unit[1], first_unit[0]],
                        dtype=np.float64,
                    )
                    line_distance = max(
                        abs(float(np.dot(second_start - first_start, normal))),
                        abs(float(np.dot(second_end - first_start, normal))),
                    )
                    if line_distance > max(
                        5.0,
                        min(first_length, second_length) * 0.12,
                    ):
                        continue
                    first_side = float(
                        np.cross(first_vector, first_center - first_start)
                    )
                    second_side = float(
                        np.cross(first_vector, second_center - first_start)
                    )
                    if first_side * second_side >= 0.0:
                        continue

                    second_projection = sorted(
                        (
                            float(
                                np.dot(
                                    second_start - first_start,
                                    first_unit,
                                )
                            ),
                            float(
                                np.dot(
                                    second_end - first_start,
                                    first_unit,
                                )
                            ),
                        )
                    )
                    overlap_start = max(0.0, second_projection[0])
                    overlap_end = min(
                        first_length,
                        second_projection[1],
                    )
                    overlap = overlap_end - overlap_start
                    if overlap < max(
                        3.0,
                        min(first_length, second_length) * 0.18,
                    ):
                        continue

                    physical_start = (
                        first_start + first_unit * overlap_start
                    )
                    physical_end = (
                        first_start + first_unit * overlap_end
                    )
                    second_offsets = (
                        float(
                            np.dot(
                                physical_start - second_start,
                                second_unit,
                            )
                        ),
                        float(
                            np.dot(
                                physical_end - second_start,
                                second_unit,
                            )
                        ),
                    )
                    second_target_offset = max(
                        0.0,
                        min(second_offsets),
                    )
                    first_source_length = edge_length(
                        first_source,
                        first_edge,
                    )
                    second_source_length = edge_length(
                        second_source,
                        second_edge,
                    )
                    first_scale = (
                        first_length / max(1e-6, first_source_length)
                    )
                    second_scale = (
                        second_length / max(1e-6, second_source_length)
                    )
                    shared_source = min(
                        overlap / first_scale,
                        overlap / second_scale,
                    )
                    first_source_offset = overlap_start / first_scale
                    second_source_offset = (
                        second_target_offset / second_scale
                    )
                    first_strip = _sample_edge_strip(
                        frame_rgb,
                        first_source,
                        first_edge,
                        first_source_offset,
                        shared_source,
                    )
                    second_strip = _sample_edge_strip(
                        frame_rgb,
                        second_source,
                        second_edge,
                        second_source_offset,
                        shared_source,
                        reverse=True,
                    )
                    quality, evidence = _compare_edge_strips(
                        first_strip,
                        second_strip,
                    )
                    seams.append(
                        (
                            quality,
                            evidence,
                            first_id,
                            second_id,
                            overlap,
                        )
                    )

    texture_score, confidence = _texture_summary(seams)
    return {
        "score": texture_score,
        "confidence": confidence,
        "seam_count": len(seams),
        "seams": seams,
    }


def _similarity_pose(source, target):
    source_center = np.mean(source, axis=0)
    target_center = np.mean(target, axis=0)
    source_centered = source - source_center
    target_centered = target - target_center
    covariance = source_centered.T @ target_centered
    first, singular_values, second = np.linalg.svd(covariance)
    rotation = second.T @ first.T
    if np.linalg.det(rotation) < 0.0:
        second[-1, :] *= -1.0
        rotation = second.T @ first.T
    scale = float(
        np.sum(singular_values)
        / max(1e-9, np.sum(source_centered * source_centered))
    )
    return target_center, source_center, rotation, scale


def close_card_pattern_layout(layout, solve_info):
    """撤销机械臂安全缝，只用于牌面花纹评分和预览。"""
    closed = {
        int(piece_id): np.asarray(
            polygon,
            dtype=np.float64,
        ).copy()
        for piece_id, polygon in layout.items()
    }
    translations = (
        solve_info.get("repair", {})
        .get("gap", {})
        .get("translations", {})
    )
    for piece_id, translation in translations.items():
        piece_id = int(piece_id)
        if piece_id in closed:
            closed[piece_id] -= np.asarray(
                translation,
                dtype=np.float64,
            )
    return closed


def render_layout_preview(
    frame_rgb,
    pieces,
    layout,
    long_side=640,
    fill_rectangle=False,
):
    """将原图中的碎片纹理按求解结果重建成一张便于检查的牌面图。"""
    if not layout:
        return None

    targets = {
        int(piece_id): np.asarray(polygon, dtype=np.float64)
        for piece_id, polygon in layout.items()
    }
    all_points = np.vstack(list(targets.values()))
    minimum = np.min(all_points, axis=0)
    maximum = np.max(all_points, axis=0)
    size = maximum - minimum
    if min(size) < 1.0:
        return None

    margin = 24
    render_scale = max(
        1.0,
        (float(long_side) - margin * 2.0) / max(size),
    )
    canvas_size = np.ceil(
        size * render_scale + margin * 2.0
    ).astype(int)
    preview = np.full(
        (canvas_size[1], canvas_size[0], 3),
        48,
        dtype=np.uint8,
    )
    if fill_rectangle:
        destination_points = (
            (all_points - minimum) * render_scale + margin
        ).astype(np.float32)
        rectangle = cv2.minAreaRect(destination_points)
        cv2.fillPoly(
            preview,
            [
                np.rint(
                    cv2.boxPoints(rectangle)
                ).astype(np.int32)
            ],
            (245, 245, 245),
        )

    for piece_id, target in targets.items():
        if piece_id < 0 or piece_id >= len(pieces):
            return None
        source = np.asarray(
            pieces[piece_id]["points"],
            dtype=np.float64,
        )
        destination = (
            (target - minimum) * render_scale + margin
        )
        (
            target_center,
            source_center,
            rotation,
            scale,
        ) = _similarity_pose(source, destination)
        matrix = np.zeros((2, 3), dtype=np.float64)
        matrix[:, :2] = rotation * scale
        matrix[:, 2] = (
            target_center
            - rotation @ source_center * scale
        )

        source_mask = np.zeros(
            frame_rgb.shape[:2],
            dtype=np.uint8,
        )
        cv2.fillPoly(
            source_mask,
            [np.rint(source).astype(np.int32)],
            255,
        )
        warped = cv2.warpAffine(
            frame_rgb,
            matrix,
            (preview.shape[1], preview.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(48, 48, 48),
        )
        warped_mask = cv2.warpAffine(
            source_mask,
            matrix,
            (preview.shape[1], preview.shape[0]),
            flags=cv2.INTER_NEAREST,
        )
        preview[warped_mask > 0] = warped[warped_mask > 0]

    return preview


def score_layout_global_pattern(frame_rgb, pieces, layout):
    """
    比较完整牌面与旋转180度后的相似度。

    常规数字牌、A、J/Q/K 的点数和角标通常具有双向阅读布局，这个软
    约束能区分“几何能闭合，但两个角标被放在同一侧”的错误排列。
    """
    targets = {
        piece_id: np.asarray(polygon, dtype=np.float64)
        for piece_id, polygon in layout.items()
    }
    all_points = np.vstack(list(targets.values()))
    minimum = np.min(all_points, axis=0)
    maximum = np.max(all_points, axis=0)
    size = maximum - minimum
    if min(size) < 1.0:
        return {"score": 0.5, "confidence": 0.0}

    render_scale = 280.0 / max(size)
    canvas_size = np.ceil(size * render_scale + 16.0).astype(int)
    canvas = np.full(
        (canvas_size[1], canvas_size[0], 3),
        245,
        dtype=np.uint8,
    )
    valid_mask = np.zeros(canvas.shape[:2], dtype=np.uint8)

    for piece_id, target in targets.items():
        source = np.asarray(
            pieces[piece_id]["points"],
            dtype=np.float64,
        )
        destination = (
            (target - minimum) * render_scale + 8.0
        )
        (
            target_center,
            source_center,
            rotation,
            scale,
        ) = _similarity_pose(source, destination)
        matrix = np.zeros((2, 3), dtype=np.float64)
        matrix[:, :2] = rotation * scale
        matrix[:, 2] = (
            target_center
            - rotation @ source_center * scale
        )
        source_mask = np.zeros(frame_rgb.shape[:2], dtype=np.uint8)
        cv2.fillPoly(
            source_mask,
            [np.rint(source).astype(np.int32)],
            255,
        )
        warped = cv2.warpAffine(
            frame_rgb,
            matrix,
            (canvas.shape[1], canvas.shape[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=(245, 245, 245),
        )
        warped_mask = cv2.warpAffine(
            source_mask,
            matrix,
            (canvas.shape[1], canvas.shape[0]),
            flags=cv2.INTER_NEAREST,
        )
        canvas[warped_mask > 0] = warped[warped_mask > 0]
        cv2.bitwise_or(
            valid_mask,
            warped_mask,
            dst=valid_mask,
        )

    valid_mask = cv2.erode(
        valid_mask,
        np.ones((5, 5), dtype=np.uint8),
        iterations=1,
    )
    rotated_canvas = cv2.rotate(canvas, cv2.ROTATE_180)
    rotated_mask = cv2.rotate(valid_mask, cv2.ROTATE_180)
    valid = (valid_mask > 0) & (rotated_mask > 0)
    if np.count_nonzero(valid) < 100:
        return {"score": 0.5, "confidence": 0.0}

    first_features = _profile_features(canvas.astype(np.float32))
    second_features = _profile_features(
        rotated_canvas.astype(np.float32)
    )
    difference = np.abs(first_features - second_features)
    feature_error = (
        difference[:, :, 0] * 0.24
        + difference[:, :, 1] * 0.34
        + difference[:, :, 2] * 0.18
        + difference[:, :, 3] * 0.24
    )
    first_ink = np.maximum(
        first_features[:, :, 1],
        first_features[:, :, 2] * 0.75,
    )
    second_ink = np.maximum(
        second_features[:, :, 1],
        second_features[:, :, 2] * 0.75,
    )
    ink = np.maximum(first_ink, second_ink)
    y_grid, x_grid = np.indices(ink.shape, dtype=np.float32)
    x_distance = np.minimum(
        x_grid,
        ink.shape[1] - 1.0 - x_grid,
    ) / max(1.0, ink.shape[1] * 0.28)
    y_distance = np.minimum(
        y_grid,
        ink.shape[0] - 1.0 - y_grid,
    ) / max(1.0, ink.shape[0] * 0.28)
    corner_weight = np.exp(
        -(x_distance * x_distance + y_distance * y_distance)
    )
    weight = (0.08 + ink) * (0.25 + corner_weight * 3.0)
    error = float(
        np.sum(feature_error[valid] * weight[valid])
        / np.sum(weight[valid])
    )
    evidence = min(1.0, float(np.mean(ink[valid]) * 4.0))
    exact_score = math.exp(-error * 6.0)

    patch_height = max(12, int(ink.shape[0] * 0.38))
    patch_width = max(12, int(ink.shape[1] * 0.24))
    corner_patches = (
        first_ink[:patch_height, :patch_width],
        first_ink[:patch_height, -patch_width:],
        first_ink[-patch_height:, :patch_width],
        first_ink[-patch_height:, -patch_width:],
    )

    def corner_detail(patch):
        binary = (patch > 0.24).astype(np.uint8)
        component_count, _, statistics, _ = (
            cv2.connectedComponentsWithStats(binary, 8)
        )
        components = sum(
            int(statistics[index, cv2.CC_STAT_AREA])
            >= max(6, int(patch.size * 0.002))
            for index in range(1, component_count)
        )
        horizontal = cv2.Sobel(
            patch,
            cv2.CV_32F,
            1,
            0,
            ksize=3,
        )
        vertical = cv2.Sobel(
            patch,
            cv2.CV_32F,
            0,
            1,
            ksize=3,
        )
        edge_density = float(
            np.mean(np.hypot(horizontal, vertical))
        )
        return (
            float(np.mean(patch)),
            float(np.std(patch)),
            components,
            edge_density,
        )

    corner_details = [
        corner_detail(patch)
        for patch in corner_patches
    ]

    def corner_pair_score(first_patch, second_patch):
        second_patch = cv2.rotate(
            second_patch,
            cv2.ROTATE_180,
        )
        first_patch = cv2.GaussianBlur(
            first_patch.astype(np.float32),
            (5, 5),
            0,
        )
        second_patch = cv2.GaussianBlur(
            second_patch.astype(np.float32),
            (5, 5),
            0,
        )
        patch_evidence = min(
            1.0,
            (
                max(
                    float(np.mean(first_patch)),
                    float(np.mean(second_patch)),
                )
                * 4.0
                + max(
                    float(np.std(first_patch)),
                    float(np.std(second_patch)),
                )
                * 2.5
            ),
        )
        margin = max(
            4,
            int(min(patch_height, patch_width) * 0.10),
        )
        padded = cv2.copyMakeBorder(
            second_patch,
            margin,
            margin,
            margin,
            margin,
            cv2.BORDER_CONSTANT,
            value=0.0,
        )
        correlation = cv2.matchTemplate(
            padded,
            first_patch,
            cv2.TM_CCOEFF_NORMED,
        )
        best = float(np.max(correlation))
        best = max(0.0, min(1.0, (best + 1.0) * 0.5))
        density_score = math.exp(
            -abs(
                float(np.mean(first_patch))
                - float(np.mean(second_patch))
            )
            * 5.0
        )
        return best * 0.75 + density_score * 0.25, patch_evidence

    first_corner = corner_pair_score(
        corner_patches[0],
        corner_patches[3],
    )
    second_corner = corner_pair_score(
        corner_patches[1],
        corner_patches[2],
    )
    corner_weight_sum = max(
        0.1,
        first_corner[1] + second_corner[1],
    )
    corner_average = (
        first_corner[0] * max(0.05, first_corner[1])
        + second_corner[0] * max(0.05, second_corner[1])
    ) / corner_weight_sum
    diagonal_floor = min(
        first_corner[0],
        second_corner[0],
    )
    diagonal_balance = math.exp(
        -abs(first_corner[0] - second_corner[0]) * 2.5
    )
    diagonal_score = (
        diagonal_floor * 0.75
        + diagonal_balance * 0.25
    )
    corner_score = (
        corner_average * 0.35
        + diagonal_score * 0.65
    )
    corner_confidence = min(
        1.0,
        (first_corner[1] + second_corner[1]) * 0.65,
    )
    component_values = [
        float(detail[2])
        for detail in corner_details
    ]
    component_error = (
        abs(component_values[0] - component_values[3])
        + abs(component_values[1] - component_values[2])
    ) / max(2.0, sum(component_values))
    component_score = math.exp(-component_error * 3.2)
    edge_values = [
        float(detail[3])
        for detail in corner_details
    ]
    edge_error = (
        abs(edge_values[0] - edge_values[3])
        + abs(edge_values[1] - edge_values[2])
    ) / max(0.05, sum(edge_values))
    edge_score = math.exp(-edge_error * 3.0)
    structure_score = (
        component_score * 0.70
        + edge_score * 0.30
    )
    combined_confidence = max(evidence, corner_confidence)
    score = (
        exact_score * 0.20
        + corner_score * 0.35
        + structure_score * 0.45
    )
    return {
        "score": (
            0.5
            + (score - 0.5) * combined_confidence
        ),
        "confidence": combined_confidence,
        "exact": exact_score,
        "corners": corner_score,
        "diagonal": diagonal_score,
        "structure": structure_score,
        "corner_details": corner_details,
    }


def score_rank_index_diagonal(frame_rgb, pieces, layout):
    """
    检查扑克牌的数字或字母角标是否出现在一对对角角区。

    这里不做牌面模板匹配，也不尝试识别具体是 5、K 还是大小王。普通牌的
    角标由较小的数字/字母和花色组成，而中央花色通常更大、更靠近牌面中心。
    只有同时找到两组清晰的小角标时才形成强约束；证据不足时返回中性分，
    让几何与拼缝纹理继续决定结果，避免人物牌、大小王或反光造成误拒绝。
    """
    preview = render_layout_preview(
        frame_rgb,
        pieces,
        layout,
        long_side=420,
        fill_rectangle=True,
    )
    if preview is None or min(preview.shape[:2]) <= 52:
        return {
            "score": 0.5,
            "confidence": 0.0,
            "valid": None,
            "corners": (0.0, 0.0, 0.0, 0.0),
            "pair": (),
        }

    card = preview[24:-24, 24:-24]
    height, width = card.shape[:2]
    card_area = height * width
    if min(height, width) < 40:
        return {
            "score": 0.5,
            "confidence": 0.0,
            "valid": None,
            "corners": (0.0, 0.0, 0.0, 0.0),
            "pair": (),
        }

    hsv = cv2.cvtColor(card, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(card, cv2.COLOR_RGB2GRAY)
    ink = (
        ((hsv[:, :, 1] > 38) & (hsv[:, :, 2] < 252))
        | (gray < 105)
    ).astype(np.uint8)
    ink[:3, :] = 0
    ink[-3:, :] = 0
    ink[:, :3] = 0
    ink[:, -3:] = 0

    count, labels, statistics, centers = (
        cv2.connectedComponentsWithStats(ink, 8)
    )
    components = []
    minimum_area = max(12, int(card_area * 0.00012))
    maximum_area = max(minimum_area + 1, int(card_area * 0.009))
    for component_id in range(1, count):
        x, y, item_width, item_height, area = (
            int(value)
            for value in statistics[component_id]
        )
        center_x, center_y = centers[component_id]
        if area < minimum_area or area > maximum_area:
            continue
        if item_width > width * 0.18 or item_height > height * 0.19:
            continue
        if min(item_width, item_height) < 3:
            continue
        fill_ratio = area / float(item_width * item_height)
        if fill_ratio < 0.10:
            continue
        side_distance = min(
            center_x / width,
            1.0 - center_x / width,
        )
        if side_distance > 0.31:
            continue

        corner_id = (
            (0 if center_y < height * 0.5 else 2)
            + (0 if center_x < width * 0.5 else 1)
        )
        size_score = min(
            1.0,
            area / max(1.0, card_area * 0.0015),
        ) * min(
            1.0,
            card_area * 0.007 / max(1.0, area),
        )
        quality = (
            (1.0 - side_distance / 0.31) * 0.45
            + min(1.0, fill_ratio / 0.35) * 0.25
            + size_score * 0.30
        )
        components.append(
            {
                "id": component_id,
                "area": area,
                "center": (float(center_x), float(center_y)),
                "corner": corner_id,
                "quality": quality,
            }
        )

    corner_scores = []
    corner_pairs = []
    corner_component_pairs = []
    for corner_id in range(4):
        items = [
            item
            for item in components
            if item["corner"] == corner_id
        ]
        best_score = 0.0
        best_pair = ()
        for first_id in range(len(items)):
            for second_id in range(first_id + 1, len(items)):
                first = items[first_id]
                second = items[second_id]
                distance = math.hypot(
                    (
                        first["center"][0]
                        - second["center"][0]
                    ) / max(1.0, width * 0.24),
                    (
                        first["center"][1]
                        - second["center"][1]
                    ) / max(1.0, height * 0.24),
                )
                if distance > 1.25:
                    continue
                area_ratio = max(
                    first["area"],
                    second["area"],
                ) / max(
                    1.0,
                    min(first["area"], second["area"]),
                )
                balance = math.exp(
                    -abs(math.log(area_ratio)) * 0.35
                )
                pair_score = (
                    (
                        first["quality"]
                        + second["quality"]
                    )
                    * 0.5
                    * (0.65 + balance * 0.35)
                    * math.exp(
                        -max(0.0, distance - 0.25) * 0.22
                    )
                )
                if pair_score > best_score:
                    best_score = pair_score
                    best_pair = (first, second)
        corner_scores.append(float(best_score))
        corner_component_pairs.append(best_pair)
        corner_pairs.append(
            tuple(
                item["center"]
                for item in best_pair
            )
        )

    ordered = sorted(
        range(4),
        key=lambda corner_id: corner_scores[corner_id],
        reverse=True,
    )
    strongest = corner_scores[ordered[0]]
    second = corner_scores[ordered[1]]
    third = corner_scores[ordered[2]]
    strength = max(
        0.0,
        min(1.0, (second - 0.45) / 0.25),
    )
    separation = max(
        0.0,
        min(1.0, (second - third) / 0.25),
    )
    confidence = float(
        strength * 0.65 + separation * 0.35
    )
    if strongest < 0.52 or second < 0.52:
        confidence = 0.0

    pair = tuple(sorted(ordered[:2]))
    position_valid = None
    orientation_valid = None
    orientation_confidence = 0.0
    orientation_rotation = None
    rotation_scores = ()
    score = 0.5
    if confidence >= 0.55:
        position_valid = pair in ((0, 3), (1, 2))

        def cluster_mask(corner_id):
            seeds = corner_component_pairs[corner_id]
            if len(seeds) != 2:
                return None
            selected = []
            for item in components:
                if item["corner"] != corner_id:
                    continue
                distance = min(
                    math.hypot(
                        (
                            item["center"][0]
                            - seed["center"][0]
                        ) / max(1.0, width * 0.24),
                        (
                            item["center"][1]
                            - seed["center"][1]
                        ) / max(1.0, height * 0.24),
                    )
                    for seed in seeds
                )
                if distance <= 0.90:
                    selected.append(item["id"])
            if len(selected) < 2:
                return None

            selected_mask = np.isin(
                labels,
                selected,
            )
            rows, columns = np.where(selected_mask)
            if len(rows) < 12:
                return None
            crop = selected_mask[
                np.min(rows):np.max(rows) + 1,
                np.min(columns):np.max(columns) + 1,
            ].astype(np.uint8)
            normalized = np.zeros((96, 96), dtype=np.uint8)
            scale = min(
                72.0 / crop.shape[1],
                72.0 / crop.shape[0],
            )
            target_width = max(
                1,
                int(round(crop.shape[1] * scale)),
            )
            target_height = max(
                1,
                int(round(crop.shape[0] * scale)),
            )
            resized = cv2.resize(
                crop,
                (target_width, target_height),
                interpolation=cv2.INTER_AREA,
            )
            offset_x = (96 - target_width) // 2
            offset_y = (96 - target_height) // 2
            normalized[
                offset_y:offset_y + target_height,
                offset_x:offset_x + target_width,
            ] = resized
            return normalized

        def cluster_similarity(first, second):
            first = cv2.GaussianBlur(
                first.astype(np.float32),
                (5, 5),
                0,
            )
            second = cv2.GaussianBlur(
                second.astype(np.float32),
                (5, 5),
                0,
            )
            padded = cv2.copyMakeBorder(
                second,
                8,
                8,
                8,
                8,
                cv2.BORDER_CONSTANT,
                value=0.0,
            )
            correlation = cv2.matchTemplate(
                padded,
                first,
                cv2.TM_CCOEFF_NORMED,
            )
            return float(np.max(correlation))

        first_mask = cluster_mask(ordered[0])
        second_mask = cluster_mask(ordered[1])
        if first_mask is not None and second_mask is not None:
            rotated_masks = (
                second_mask,
                cv2.rotate(
                    second_mask,
                    cv2.ROTATE_90_CLOCKWISE,
                ),
                cv2.rotate(
                    second_mask,
                    cv2.ROTATE_180,
                ),
                cv2.rotate(
                    second_mask,
                    cv2.ROTATE_90_COUNTERCLOCKWISE,
                ),
            )
            rotation_scores = tuple(
                cluster_similarity(
                    first_mask,
                    rotated,
                )
                for rotated in rotated_masks
            )
            best_rotation_id = int(
                np.argmax(rotation_scores)
            )
            orientation_rotation = (
                0,
                90,
                180,
                270,
            )[best_rotation_id]
            rotated_score = rotation_scores[2]
            best_other = max(
                rotation_scores[0],
                rotation_scores[1],
                rotation_scores[3],
            )
            if best_rotation_id == 2:
                best_score = rotated_score
                margin = rotated_score - best_other
            else:
                best_score = best_other
                margin = best_other - rotated_score
            strength = max(
                0.0,
                min(1.0, (best_score - 0.42) / 0.22),
            )
            separation = max(
                0.0,
                min(1.0, margin / 0.15),
            )
            orientation_confidence = (
                strength * 0.55
                + separation * 0.45
            )
            if orientation_confidence >= 0.55:
                orientation_valid = best_rotation_id == 2

        valid = position_valid
        if orientation_valid is not None:
            valid = position_valid and orientation_valid
        effective_confidence = max(
            confidence,
            orientation_confidence,
        )
        direction = 1.0 if valid else -1.0
        score = float(
            0.5 + direction * effective_confidence * 0.48
        )
    else:
        valid = None

    return {
        "score": score,
        "confidence": confidence,
        "valid": valid,
        "position_valid": position_valid,
        "orientation_valid": orientation_valid,
        "orientation_confidence": orientation_confidence,
        "orientation_rotation": orientation_rotation,
        "rotation_scores": rotation_scores,
        "corners": tuple(corner_scores),
        "pair": pair,
        "component_count": len(components),
        "corner_pairs": tuple(corner_pairs),
    }


def generate_shape_swap_layouts(pieces, base_layout):
    """
    在外形近似的碎片之间交换目标槽位。

    C++ 几何求解器只返回一个最优排列；扑克牌模式需要保留这些几何
    近似等价的排列，再用花纹连续性决定最终顺序。
    """
    source_polygons = [
        np.asarray(piece["points"], dtype=np.float64)
        for piece in pieces
    ]
    target_polygons = {
        piece_id: np.asarray(polygon, dtype=np.float64)
        for piece_id, polygon in base_layout.items()
    }

    def shape_signature(polygon):
        area = max(
            1.0,
            abs(float(cv2.contourArea(polygon.astype(np.float32)))),
        )
        lengths = sorted(
            edge_length(polygon, edge_id) / math.sqrt(area)
            for edge_id in range(len(polygon))
        )
        return area, np.asarray(lengths, dtype=np.float64)

    signatures = [
        shape_signature(polygon)
        for polygon in source_polygons
    ]

    def shapes_are_similar(first_id, second_id):
        first = source_polygons[first_id]
        second = source_polygons[second_id]
        if len(first) != len(second):
            return False
        first_area, first_lengths = signatures[first_id]
        second_area, second_lengths = signatures[second_id]
        area_ratio = min(first_area, second_area) / max(
            first_area,
            second_area,
        )
        if area_ratio < 0.68:
            return False
        length_error = float(
            np.mean(
                np.abs(first_lengths - second_lengths)
                / np.maximum(first_lengths, second_lengths)
            )
        )
        return length_error <= 0.18

    slot_poses = {}
    for piece_id, source in enumerate(source_polygons):
        target = target_polygons[piece_id]
        (
            target_center,
            _,
            rotation,
            scale,
        ) = _similarity_pose(source, target)
        slot_poses[piece_id] = (
            target_center,
            rotation,
            scale,
        )

    layouts = []
    piece_ids = tuple(range(len(pieces)))
    for assignment in itertools.permutations(piece_ids):
        if any(
            not shapes_are_similar(slot_id, source_id)
            for slot_id, source_id in enumerate(assignment)
        ):
            continue
        layout = {}
        for slot_id, source_id in enumerate(assignment):
            source = source_polygons[source_id]
            source_center = np.mean(source, axis=0)
            target_center, rotation, scale = slot_poses[slot_id]
            layout[source_id] = (
                (source - source_center) @ rotation.T * scale
                + target_center
            )
        layouts.append((layout, assignment))
    return layouts


def solve_card_face(
    frame_rgb,
    pieces,
    node_limit=90000,
    time_limit_s=5.0,
):
    """
    只依靠未知扑克牌自身的连续花纹求解，不使用任何牌面模板。

    搜索阶段先用边长、无重叠和矩形四角约束生成候选，再比较公共边
    两侧的黑/红/白纹理带。这样 A-10、J/Q/K 和大小王都使用同一算法。
    """
    started = time.perf_counter()
    if not 2 <= len(pieces) <= 4:
        return {
            "layout": None,
            "score": 0.0,
            "nodes": 0,
            "info": None,
            "pieces": pieces,
            "mode": "CARD",
            "elapsed_ms": 0.0,
        }

    polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    reference_lengths = [
        edge_length(polygon, edge_id)
        for polygon in polygons
        for edge_id in range(len(polygon))
    ]
    texture_cache = {}
    strip_cache = {}
    best_layout = None
    best_metrics = None
    best_score = -1.0
    best_texture = 0.5
    best_confidence = 0.0
    best_seams = []
    best_at_node = 0
    nodes = 0

    def cached_texture(
        first_id,
        first_edge,
        first_offset,
        second_id,
        second_edge,
        second_offset,
        shared,
    ):
        key = (
            first_id,
            first_edge,
            int(round(first_offset * 2.0)),
            second_id,
            second_edge,
            int(round(second_offset * 2.0)),
            int(round(shared * 2.0)),
        )
        value = texture_cache.get(key)
        if value is None:
            first_key = (
                first_id,
                first_edge,
                int(round(first_offset * 2.0)),
                int(round(shared * 2.0)),
                False,
            )
            second_key = (
                second_id,
                second_edge,
                int(round(second_offset * 2.0)),
                int(round(shared * 2.0)),
                True,
            )
            first_strip = strip_cache.get(first_key)
            if first_strip is None:
                first_strip = _sample_edge_strip(
                    frame_rgb,
                    polygons[first_id],
                    first_edge,
                    first_offset,
                    shared,
                )
                strip_cache[first_key] = first_strip
            second_strip = strip_cache.get(second_key)
            if second_strip is None:
                second_strip = _sample_edge_strip(
                    frame_rgb,
                    polygons[second_id],
                    second_edge,
                    second_offset,
                    shared,
                    reverse=True,
                )
                strip_cache[second_key] = second_strip
            value = _compare_edge_strips(
                first_strip,
                second_strip,
            )
            texture_cache[key] = value
        return value

    def solution_is_strong():
        return (
            best_metrics is not None
            and best_metrics["coverage"] >= 0.97
            and best_metrics["corners"] >= 0.99
            and best_confidence >= 0.55
            and (
                (
                    best_score >= 0.93
                    and best_texture >= 0.82
                )
                or nodes - best_at_node >= 1200
            )
        )

    def search(placed, remaining, usage, seams):
        nonlocal best_layout
        nonlocal best_metrics
        nonlocal best_score
        nonlocal best_texture
        nonlocal best_confidence
        nonlocal best_seams
        nonlocal best_at_node
        nonlocal nodes

        if nodes >= node_limit:
            return
        if time.perf_counter() - started >= time_limit_s:
            return
        if solution_is_strong():
            return
        nodes += 1

        if not remaining:
            metrics = layout_metrics(placed)
            if (
                metrics["coverage"] < 0.80
                or metrics["overlap"] > 0.015
                or metrics["corners"] < 0.75
                or metrics["height"] < 1.0
            ):
                return
            ratio = metrics["width"] / metrics["height"]
            if ratio > 2.45:
                return

            texture_score, texture_confidence = _texture_summary(
                seams
            )
            score = (
                metrics["coverage"] * 0.55
                + metrics["corners"] * 0.10
                + texture_score * 0.35
                - metrics["overlap"] * 8.0
            )
            if score > best_score:
                best_layout = {
                    piece_id: polygon.copy()
                    for piece_id, polygon in placed.items()
                }
                best_metrics = metrics
                best_score = score
                best_texture = texture_score
                best_confidence = texture_confidence
                best_seams = list(seams)
                best_at_node = nodes
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
                        relative_error = abs(
                            target_length - source_length
                        ) / max(target_length, source_length)
                        partition_error = residual_partition_error(
                            target_length,
                            source_length,
                            reference_lengths,
                        )
                        if (
                            relative_error > 0.14
                            and partition_error > 0.12
                        ):
                            continue
                        if relative_error <= 0.14:
                            shared = min(
                                (target_length + source_length) * 0.5,
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
                                        tolerance_ratio=0.012,
                                    )
                                    for old_polygon in placed.values()
                                ):
                                    continue

                                first_vector = (
                                    transformed[1] - transformed[0]
                                )
                                angle = math.degrees(
                                    math.atan2(
                                        first_vector[1],
                                        first_vector[0],
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

                                texture = cached_texture(
                                    placed_id,
                                    target_edge,
                                    target_offset,
                                    source_id,
                                    source_edge,
                                    source_offset,
                                    shared,
                                )
                                if relative_error <= 0.04:
                                    match_class = 0
                                elif (
                                    relative_error > 0.14
                                    and partition_error <= 0.04
                                ):
                                    match_class = 1
                                elif relative_error <= 0.14:
                                    match_class = 2
                                else:
                                    match_class = 3
                                geometry_error = (
                                    partition_error
                                    if match_class == 1
                                    else relative_error
                                )
                                texture_penalty = (
                                    1.0 - texture[0]
                                ) * texture[1]
                                compactness = quick_compactness(
                                    list(placed.values())
                                    + [transformed]
                                )
                                branches.append(
                                    (
                                        (
                                            match_class,
                                            geometry_error * 0.45
                                            + texture_penalty * 0.55,
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
                                        texture,
                                    )
                                )

        branches.sort(key=lambda item: item[0])
        for branch in branches[:90]:
            (
                _,
                placed_id,
                target_edge,
                target_offset,
                source_id,
                source_edge,
                source_offset,
                shared,
                transformed,
                texture,
            ) = branch
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
            next_seams = list(seams)
            next_seams.append(
                (
                    texture[0],
                    texture[1],
                    placed_id,
                    source_id,
                )
            )
            search(
                next_placed,
                next_remaining,
                next_usage,
                next_seams,
            )
            if nodes >= node_limit:
                return
            if time.perf_counter() - started >= time_limit_s:
                return
            if solution_is_strong():
                return

    def matching_edge_count(piece_id):
        count = 0
        polygon = polygons[piece_id]
        for edge_id in range(len(polygon)):
            length = edge_length(polygon, edge_id)
            matched = any(
                abs(length - edge_length(other, other_edge))
                / max(length, edge_length(other, other_edge))
                <= 0.05
                for other_id, other in enumerate(polygons)
                if other_id != piece_id
                for other_edge in range(len(other))
            )
            count += int(matched)
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
            [],
        )
        if nodes >= node_limit:
            break
        if time.perf_counter() - started >= time_limit_s:
            break
        if solution_is_strong():
            break

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if best_layout is None:
        return {
            "layout": None,
            "score": 0.0,
            "nodes": nodes,
            "info": None,
            "pieces": pieces,
            "mode": "CARD",
            "elapsed_ms": elapsed_ms,
        }

    return {
        "layout": best_layout,
        "score": best_score,
        "nodes": nodes,
        "info": {
            "solve_scale": 1.0,
            "width": best_metrics["width"],
            "height": best_metrics["height"],
            "ratio": (
                best_metrics["width"]
                / max(1.0, best_metrics["height"])
            ),
            "coverage": best_metrics["coverage"],
            "overlap": best_metrics["overlap"],
            "texture_score": best_texture,
            "texture_confidence": best_confidence,
            "seam_count": len(best_seams),
            "best_at_node": best_at_node,
            "method": "card-face",
            "execution_mode": "RECT",
            "forced": False,
        },
        "pieces": pieces,
        "mode": "CARD",
        "elapsed_ms": elapsed_ms,
    }
