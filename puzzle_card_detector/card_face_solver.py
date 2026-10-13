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
    polygon_mask=None,
):
    start = polygon[edge_id]
    end = polygon[(edge_id + 1) % len(polygon)]
    vector = end - start
    full_length = float(np.linalg.norm(vector))
    normal = _inward_normal(polygon, edge_id)
    if full_length < 1e-6 or normal is None:
        return None

    unit = vector / full_length
    # 固定长度方向采样，使不同候选的同一条接缝可以直接比较。
    sample_count = 96
    margin = min(2.5, shared_length * 0.05)
    along = np.linspace(
        offset + margin,
        offset + shared_length - margin,
        sample_count,
        dtype=np.float32,
    )
    if reverse:
        along = along[::-1].copy()

    # 六层宽带兼顾紧邻切口的连续性和更深处的花纹上下文。
    depths = np.array(
        [1.5, 3.0, 5.5, 8.5, 12.0, 16.0],
        dtype=np.float32,
    )
    map_x = np.empty((len(depths), sample_count), dtype=np.float32)
    map_y = np.empty_like(map_x)

    for depth_id, depth in enumerate(depths):
        points = (
            start[None, :]
            + along[:, None] * unit[None, :]
            + float(depth) * normal[None, :]
        )
        map_x[depth_id] = points[:, 0]
        map_y[depth_id] = points[:, 1]

    sampled = cv2.remap(
        frame_rgb,
        map_x,
        map_y,
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    ).astype(np.float32)
    if polygon_mask is None:
        valid = np.ones((len(depths), sample_count), dtype=bool)
    else:
        valid = cv2.remap(
            polygon_mask,
            map_x,
            map_y,
            cv2.INTER_NEAREST,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0,
        ) > 0
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
    # 略暗的白纸不算黑色印刷，避免空白拼缝获得虚假的信息量。
    blackness = np.maximum(0.0, darkness - 0.08) * np.maximum(0.0, 1.0 - saturation * 1.5)
    along_gradient = np.abs(np.gradient(gray, axis=1))
    return np.stack(
        (
            gray,
            darkness,
            saturation,
            redness,
            blackness,
            along_gradient,
        ),
        axis=2,
    )


def _compare_edge_strips(first, second):
    """一次比较七个沿边偏移；深层只估计变化，不直接比较深处图案。"""
    if first is None or second is None:
        return 0.5, 0.0
    a, b = _profile_features(first[0])[:2], _profile_features(second[0])[:2]
    count = min(a.shape[1], b.shape[1])
    if count < 24:
        return 0.5, 0.0
    indices = np.arange(3, count - 3)
    shifted = indices[None, :] + np.arange(-3, 4)[:, None]
    first_near, first_deep = a[0, indices][None, :], a[1, indices][None, :]
    second_near, second_deep = b[0, shifted], b[1, shifted]
    valid = first[1][0, indices][None, :] & second[1][0, shifted]
    first_rgb = first[0][0, indices][None, :] / 255.0
    second_rgb = second[0][0, shifted] / 255.0
    for rgb in (first_rgb, second_rgb):
        green = (rgb[..., 1] > 0.28) & (rgb[..., 1] > rgb[..., 0] * 1.15) & (rgb[..., 1] > rgb[..., 2] * 1.08)
        valid &= ~green
    weights = np.array([0.22, 0.24, 0.13, 0.18, 0.11, 0.12], dtype=np.float32)
    boundary = np.sum(np.abs(first_near - second_near) * weights, axis=2)
    first_slope, second_slope = first_near - first_deep, second_deep - second_near
    slope = np.minimum(boundary, np.sum(np.abs(first_slope - second_slope) * weights, axis=2))
    change = np.sum((np.abs(first_slope) + np.abs(second_slope)) * weights, axis=2)
    discontinuity = np.maximum(0.0, boundary - change * 1.15)
    detail = np.maximum(np.maximum(first_near[..., 5], second_near[..., 5]),
                        np.maximum(np.mean(np.abs(first_slope), axis=2), np.mean(np.abs(second_slope), axis=2)))
    first_ink = np.maximum(np.maximum(first_near[..., 3] * 1.15, first_near[..., 4]), first_near[..., 2] * 0.45)
    second_ink = np.maximum(np.maximum(second_near[..., 3] * 1.15, second_near[..., 4]), second_near[..., 2] * 0.45)
    both = np.minimum(first_ink, second_ink)
    mismatch = np.abs(first_ink - second_ink)
    importance = detail * (0.20 + both) + both * 0.08 + mismatch * 0.90
    pattern_weight = importance * valid
    total = pattern_weight.sum(axis=1)
    error = boundary * 0.58 + slope * 0.22 + discontinuity * 0.20 + mismatch * 0.55
    errors = (error * pattern_weight).sum(axis=1) / np.maximum(1e-6, total)
    errors[(valid.sum(axis=1) < 18) | (total < 1e-5)] = np.inf
    best = int(np.argmin(errors))
    if not np.isfinite(errors[best]):
        return 0.5, 0.0
    evidence = min(1.0, float(importance[best, valid[best]].mean()) * 8.0)
    return math.exp(-float(errors[best]) * 6.5), evidence


def _texture_summary(seams):
    if not seams:
        return 0.5, 0.0
    total_weight = sum(max(0.01, item[1]) for item in seams)
    raw_score = sum(
        item[0] * max(0.01, item[1])
        for item in seams
    ) / total_weight
    confidence = min(
        1.0,
        sum(item[1] for item in seams) / max(1.0, len(seams) * 0.45),
    )
    return 0.5 + (raw_score - 0.5) * confidence, confidence


def score_layout_texture(frame_rgb, pieces, layout, cache=None):
    """对一个已闭合矩形的所有真实内部接缝进行扑克牌花纹评分。"""
    source_polygons = [
        np.asarray(piece["points"], dtype=np.float64)
        for piece in pieces
    ]
    target_polygons = {
        piece_id: np.asarray(polygon, dtype=np.float64)
        for piece_id, polygon in layout.items()
    }
    # 同时反向源和目标，保留牌面对应关系并统一公共边的遍历方向。
    for piece_id, polygon in enumerate(source_polygons):
        if cv2.contourArea(polygon.astype(np.float32), oriented=True) < 0:
            source_polygons[piece_id] = polygon[::-1].copy()
            if piece_id in target_polygons:
                target_polygons[piece_id] = target_polygons[piece_id][::-1].copy()
    seams = []
    if cache is None:
        cache = {}
    strip_cache = cache.setdefault("strips", {})
    pair_cache = cache.setdefault("pairs", {})
    pair_keys = []
    masks = cache.get("masks")
    if masks is None:
        masks = []
        for polygon in source_polygons:
            mask = np.zeros(frame_rgb.shape[:2], dtype=np.uint8)
            cv2.fillPoly(
                mask,
                [np.rint(polygon).astype(np.int32)],
                255,
            )
            mask = cv2.erode(mask, np.ones((3, 3), dtype=np.uint8))
            masks.append(mask)
        cache["masks"] = masks
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
                    first_key = (
                        first_id,
                        first_edge,
                        int(round(first_source_offset * 2.0)),
                        int(round(shared_source * 2.0)),
                        False,
                    )
                    second_key = (
                        second_id,
                        second_edge,
                        int(round(second_source_offset * 2.0)),
                        int(round(shared_source * 2.0)),
                        True,
                    )
                    pair_key = (first_key, second_key)
                    pair_keys.append(pair_key)
                    if pair_key in pair_cache:
                        quality, evidence = pair_cache[pair_key]
                        seams.append((quality, evidence, first_id, second_id, overlap))
                        continue
                    first_strip = strip_cache.get(first_key)
                    if first_strip is None:
                        first_strip = _sample_edge_strip(
                            frame_rgb,
                            first_source,
                            first_edge,
                            first_source_offset,
                            shared_source,
                            polygon_mask=masks[first_id],
                        )
                        strip_cache[first_key] = first_strip
                    second_strip = strip_cache.get(second_key)
                    if second_strip is None:
                        second_strip = _sample_edge_strip(
                            frame_rgb,
                            second_source,
                            second_edge,
                            second_source_offset,
                            shared_source,
                            reverse=True,
                            polygon_mask=masks[second_id],
                        )
                        strip_cache[second_key] = second_strip
                    quality, evidence = _compare_edge_strips(
                        first_strip,
                        second_strip,
                    )
                    pair_cache[pair_key] = (quality, evidence)
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
        "pair_keys": pair_keys,
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


def _resample_polygon_boundary(polygon, sample_count=48):
    polygon = np.asarray(polygon, dtype=np.float64)
    vectors = np.roll(polygon, -1, axis=0) - polygon
    lengths = np.linalg.norm(vectors, axis=1)
    perimeter = float(np.sum(lengths))
    if perimeter < 1e-9:
        return np.repeat(polygon[:1], sample_count, axis=0)
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    distances = np.arange(sample_count, dtype=np.float64) * (
        perimeter / sample_count
    )
    edge_ids = np.searchsorted(cumulative[1:], distances, side="right")
    edge_ids = np.minimum(edge_ids, len(polygon) - 1)
    offsets = distances - cumulative[edge_ids]
    ratios = offsets / np.maximum(lengths[edge_ids], 1e-9)
    return polygon[edge_ids] + vectors[edge_ids] * ratios[:, None]


def _best_similarity_pose(source, target):
    """枚举顶点循环对应关系，避免相似多边形因起点不同而转错方向。"""
    source = np.asarray(source, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if len(source) < 3 or len(target) < 3:
        return np.mean(target, axis=0), np.mean(source, axis=0), np.eye(2), 1.0, 1.0

    if len(source) != len(target):
        source = _resample_polygon_boundary(source)
        target = _resample_polygon_boundary(target)

    best = None
    target_radius = math.sqrt(
        float(
            np.mean(
                np.sum(
                    (target - np.mean(target, axis=0)) ** 2,
                    axis=1,
                )
            )
        )
    )
    for reversed_order in (False, True):
        ordered = target[::-1] if reversed_order else target
        for shift in range(len(ordered)):
            candidate = np.roll(ordered, shift, axis=0)
            pose = _similarity_pose(source, candidate)
            target_center, source_center, rotation, scale = pose
            transformed = (
                (source - source_center) @ rotation.T * scale
                + target_center
            )
            error = float(
                np.mean(np.linalg.norm(transformed - candidate, axis=1))
                / max(1e-9, target_radius)
            )
            if best is None or error < best[-1]:
                best = (*pose, error)
    return best


def _boundary_fit_error(source,target):
    """均匀边界到线段的距离；不依赖两个轮廓的顶点数和起点。"""
    samples=_resample_polygon_boundary(source)
    edges=np.roll(target,-1,axis=0)-target
    relative=samples[:,None,:]-target[None,:,:]
    amount=np.clip(np.sum(relative*edges,axis=2)/np.maximum(1e-9,np.sum(edges*edges,axis=1)),0,1)
    distance=np.linalg.norm(relative-amount[:,:,None]*edges,axis=2).min(axis=1)
    return float(distance.mean())


def _rigid_similarity_poses(source, target):
    """保留近等价的顶点对应姿态；只旋转和平移，不改变碎片尺寸。"""
    source = np.asarray(source, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if (
        len(source) < 3 or len(target) < 3
        or not np.all(np.isfinite(source))
        or not np.all(np.isfinite(target))
    ):
        return []
    original_source=source.copy()
    original_target=target.copy()
    if len(source) != len(target):
        source = _resample_polygon_boundary(source)
        target = _resample_polygon_boundary(target)

    source_center = np.mean(source, axis=0)
    target_center = np.mean(target, axis=0)
    centered = source - source_center
    radius = math.sqrt(float(np.mean(np.sum(centered ** 2, axis=1))))
    target_radius = math.sqrt(float(np.mean(np.sum(
        (target - target_center) ** 2, axis=1,
    ))))
    if min(radius, target_radius) < 1e-9:
        return []

    candidates = []
    for ordered in (target, target[::-1]):
        for shift in range(len(ordered)):
            corresponding = np.roll(ordered, shift, axis=0)
            _, _, rotation, _ = _similarity_pose(source, corresponding)
            transformed = centered @ rotation.T + target_center
            error = float(np.mean(np.linalg.norm(
                transformed - corresponding, axis=1,
            )) / max(radius, target_radius))
            candidates.append((target_center, source_center, rotation, 1.0, error))

    best_error = min(pose[-1] for pose in candidates)
    # 容忍轮廓提取噪声，但不把明显不匹配的方向也视为对称方向。
    limit = min(0.12, best_error + 0.035)
    poses = []
    for pose in sorted(candidates, key=lambda item: item[-1]):
        if pose[-1] > limit:
            continue
        if any(np.allclose(pose[2], old[2], atol=1e-7, rtol=0.0) for old in poses):
            continue
        poses.append(pose)
    # 多余的圆角/缺角顶点不能消除近矩形片的半转方向。
    if poses and max(len(original_source),len(original_target))>4:
        source_box=cv2.minAreaRect(original_source.astype(np.float32))
        target_box=cv2.minAreaRect(original_target.astype(np.float32))
        source_area=source_box[1][0]*source_box[1][1]
        target_area=target_box[1][0]*target_box[1][1]
        near_rectangle=(source_area>1 and target_area>1
                        and abs(cv2.contourArea(original_source.astype(np.float32)))/source_area>=.90
                        and abs(cv2.contourArea(original_target.astype(np.float32)))/target_area>=.90)
        if near_rectangle:
            source_middle=np.array(source_box[0],dtype=float)
            target_middle=np.array(target_box[0],dtype=float)
            rotation=-poses[0][2]
            transformed=(original_source-source_middle)@rotation.T+target_middle
            distance=max(_boundary_fit_error(transformed,original_target),
                         _boundary_fit_error(original_target,transformed))
            error=distance/max(radius,target_radius)
            if error<=.06 and not any(np.allclose(rotation,pose[2],atol=1e-7,rtol=0) for pose in poses):
                poses.append((target_middle,source_middle,rotation,1.0,error))
    return poses


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
        source_mask = np.zeros(
            frame_rgb.shape[:2],
            dtype=np.uint8,
        )
        cv2.fillPoly(
            source_mask,
            [np.rint(source).astype(np.int32)],
            255,
        )
        if len(source) == 4 and len(destination) == 4:
            matrix = cv2.getPerspectiveTransform(
                source.astype(np.float32),
                destination.astype(np.float32),
            )
            warped = cv2.warpPerspective(
                frame_rgb,
                matrix,
                (preview.shape[1], preview.shape[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(48, 48, 48),
            )
            warped_mask = cv2.warpPerspective(
                source_mask,
                matrix,
                (preview.shape[1], preview.shape[0]),
                flags=cv2.INTER_NEAREST,
            )
        else:
            target_center, source_center, rotation, scale = (
                _similarity_pose(source, destination)
            )
            matrix = np.zeros((2, 3), dtype=np.float64)
            matrix[:, :2] = rotation * scale
            matrix[:, 2] = target_center - rotation @ source_center * scale
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
        source_mask = np.zeros(frame_rgb.shape[:2], dtype=np.uint8)
        cv2.fillPoly(
            source_mask,
            [np.rint(source).astype(np.int32)],
            255,
        )
        if len(source) == 4 and len(destination) == 4:
            matrix = cv2.getPerspectiveTransform(
                source.astype(np.float32),
                destination.astype(np.float32),
            )
            warped = cv2.warpPerspective(
                frame_rgb,
                matrix,
                (canvas.shape[1], canvas.shape[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=(245, 245, 245),
            )
            warped_mask = cv2.warpPerspective(
                source_mask,
                matrix,
                (canvas.shape[1], canvas.shape[0]),
                flags=cv2.INTER_NEAREST,
            )
        else:
            target_center, source_center, rotation, scale = (
                _similarity_pose(source, destination)
            )
            matrix = np.zeros((2, 3), dtype=np.float64)
            matrix[:, :2] = rotation * scale
            matrix[:, 2] = target_center - rotation @ source_center * scale
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


def _score_rank_index_diagonal_legacy(frame_rgb, pieces, layout):
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
        long_side=480,
        fill_rectangle=True,
    )
    neutral = {
        "score": 0.5,
        "confidence": 0.0,
        "valid": None,
        "locked": False,
        "corners": (0.0, 0.0, 0.0, 0.0),
        "pair": (),
        "component_count": 0,
        "pair_similarity": 0.5,
    }
    if preview is None or min(preview.shape[:2]) <= 64:
        return neutral

    card = preview[24:-24, 24:-24]
    height, width = card.shape[:2]
    if min(height, width) < 52:
        return neutral

    hsv = cv2.cvtColor(card, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(card, cv2.COLOR_RGB2GRAY)
    ink = (
        ((hsv[:, :, 1] > 34) & (hsv[:, :, 2] < 250))
        | (gray < 118)
    ).astype(np.uint8) * 255
    ink[:3, :] = 0
    ink[-3:, :] = 0
    ink[:, :3] = 0
    ink[:, -3:] = 0

    corner_width = max(24, int(width * 0.24))
    corner_height = max(28, int(height * 0.29))
    corner_masks = (
        ink[:corner_height, :corner_width],
        ink[:corner_height, -corner_width:],
        ink[-corner_height:, :corner_width],
        ink[-corner_height:, -corner_width:],
    )

    def corner_presence(mask, corner_id):
        count, _, statistics, centers = cv2.connectedComponentsWithStats(mask, 8)
        minimum_area = max(5, int(mask.size * 0.00045))
        maximum_area = max(minimum_area + 1, int(mask.size * 0.22))
        components = [
            (
                int(statistics[component_id, cv2.CC_STAT_AREA]),
                float(centers[component_id][0]),
                float(centers[component_id][1]),
            )
            for component_id in range(1, count)
            if minimum_area
            <= int(statistics[component_id, cv2.CC_STAT_AREA])
            <= maximum_area
        ]
        ink_ratio = float(np.count_nonzero(mask)) / max(1, mask.size)
        density = min(1.0, ink_ratio / 0.045)
        component_score = min(1.0, len(components) / 2.0)
        target_x = 0.0 if corner_id in (0, 2) else mask.shape[1] - 1.0
        target_y = 0.0 if corner_id in (0, 1) else mask.shape[0] - 1.0
        total_area = sum(item[0] for item in components)
        anchored_area = sum(
            area * math.exp(
                -(
                    ((center_x - target_x) / max(1.0, mask.shape[1] * 0.90)) ** 2
                    + ((center_y - target_y) / max(1.0, mask.shape[0] * 0.90)) ** 2
                ) * 0.7
            )
            for area, center_x, center_y in components
        )
        anchor_score = anchored_area / max(1.0, total_area)
        score = (
            density * 0.30
            + component_score * 0.25
            + anchor_score * 0.45
        )
        return score, len(components), anchor_score

    def opposite_similarity(first, second):
        second = cv2.rotate(second, cv2.ROTATE_180)
        if np.count_nonzero(first) < 4 or np.count_nonzero(second) < 4:
            return 0.0
        # 7x7 的结果正好对应 ±3px 平移，OpenCV 内部完成相关计算。
        padded_second = cv2.copyMakeBorder(
            second,
            3,
            3,
            3,
            3,
            cv2.BORDER_CONSTANT,
            value=0,
        )
        correlation = cv2.matchTemplate(
            padded_second.astype(np.float32),
            first.astype(np.float32),
            cv2.TM_CCORR_NORMED,
        )
        return float(np.max(correlation))

    corner_scores = []
    corner_anchors = []
    component_count = 0
    for corner_id, mask in enumerate(corner_masks):
        score, count, anchor = corner_presence(mask, corner_id)
        corner_scores.append(float(score))
        corner_anchors.append(float(anchor))
        component_count += count

    pair_results = []
    for first_id, second_id in ((0, 3), (1, 2)):
        similarity = opposite_similarity(
            corner_masks[first_id],
            corner_masks[second_id],
        )
        presence = min(
            corner_scores[first_id],
            corner_scores[second_id],
        )
        evidence = min(1.0, presence / 0.58) * min(
            1.0,
            (
                np.count_nonzero(corner_masks[first_id])
                + np.count_nonzero(corner_masks[second_id])
            ) / max(1.0, corner_masks[first_id].size * 0.045),
        ) * min(corner_anchors[first_id], corner_anchors[second_id])
        pair_results.append(
            (similarity, evidence, (first_id, second_id))
        )

    similarity, evidence, pair = max(
        pair_results,
        key=lambda item: item[0] * item[1],
    )
    confidence = float(evidence * min(1.0, similarity / 0.62))
    ordered = sorted(
        range(4),
        key=lambda corner_id: corner_scores[corner_id],
        reverse=True,
    )
    strongest = corner_scores[ordered[0]]
    second = corner_scores[ordered[1]]
    third = corner_scores[ordered[2]]
    component_confidence = (
        max(0.0, min(1.0, (second - 0.55) / 0.25)) * 0.65
        + max(0.0, min(1.0, (second - third) / 0.25)) * 0.35
    )
    dominant_pair = tuple(sorted(ordered[:2]))
    if strongest < 0.58 or second < 0.58:
        component_confidence = 0.0
    valid = None
    score = 0.5
    if confidence >= 0.52:
        valid = similarity >= 0.54
        direction = 1.0 if valid else -1.0
        score = float(
            0.5 + direction * confidence * 0.46
        )
    elif (
        component_confidence >= 0.55
        and dominant_pair not in ((0, 3), (1, 2))
    ):
        # 两组明显角标却落在相邻角，属于强反证；不依赖文字模板。
        confidence = float(component_confidence)
        valid = False
        score = float(0.5 - confidence * 0.46)
        pair = dominant_pair

    return {
        "score": score,
        "confidence": confidence,
        "valid": valid,
        "locked": bool(valid is True and confidence >= 0.80),
        "corners": tuple(corner_scores),
        "corner_anchors": tuple(corner_anchors),
        "pair": pair,
        "component_count": component_count,
        "pair_similarity": similarity,
        "_preview": preview,
    }


def score_rank_index_diagonal(
    frame_rgb,
    pieces,
    layout,
    use_legacy=False,
):
    """只认可外框严格四角的角标；内部数字不作为正证据。"""
    if use_legacy:
        result = _score_rank_index_diagonal_legacy(
            frame_rgb,
            pieces,
            layout,
        )
        result.pop("_preview", None)
        return result

    neutral = {
        "score": 0.5,
        "confidence": 0.0,
        "valid": None,
        "locked": False,
        "corners": (0.0, 0.0, 0.0, 0.0),
        "pair": (),
        "component_count": 0,
        "pair_similarity": 0.5,
        "outer_diagonal_margin": 0.0,
        "outer_diagonal_strength": 0.0,
        "outer_adjacent_strength": 0.0,
        "outer_corner_confidence": 0.0,
    }
    preview = render_layout_preview(
        frame_rgb,
        pieces,
        layout,
        long_side=480,
        fill_rectangle=True,
    )
    if preview is None or min(preview.shape[:2]) <= 64:
        return neutral

    card = preview[24:-24, 24:-24]
    if min(card.shape[:2]) < 52:
        return neutral
    hsv = cv2.cvtColor(card, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(card, cv2.COLOR_RGB2GRAY)
    ink = (
        ((hsv[:, :, 1] > 38) & (hsv[:, :, 2] < 250))
        | (gray < 135)
    ).astype(np.uint8) * 255
    ink[:3, :] = 0
    ink[-3:, :] = 0
    ink[:, :3] = 0
    ink[:, -3:] = 0

    # 把四个角分别旋转到左上角，统一检查靠外框的角标组件。
    canonical_cards = (
        ink,
        cv2.rotate(ink, cv2.ROTATE_90_COUNTERCLOCKWISE),
        cv2.rotate(ink, cv2.ROTATE_90_CLOCKWISE),
        cv2.rotate(ink, cv2.ROTATE_180),
    )
    corner_results = []
    for canonical in canonical_cards:
        height, width = canonical.shape
        patch = canonical[
            :max(20, int(height * 0.28)),
            :max(18, int(width * 0.21)),
        ]
        patch = cv2.resize(
            patch,
            (72, 96),
            interpolation=cv2.INTER_NEAREST,
        )
        count, labels, statistics, centers = (
            cv2.connectedComponentsWithStats(patch, 8)
        )
        filtered = np.zeros_like(patch)
        components = []
        minimum_area = max(4, int(patch.size * 0.0008))
        maximum_area = max(
            minimum_area + 1,
            int(patch.size * 0.15),
        )
        for component_id in range(1, count):
            x, y, component_width, component_height, area = (
                statistics[component_id]
            )
            area = int(area)
            if not minimum_area <= area <= maximum_area:
                continue
            # 中央大花色通常从角区的内侧边界伸入；真正角标应完整落在角区内。
            if (
                x + component_width >= patch.shape[1] - 1
                or y + component_height >= patch.shape[0] - 1
            ):
                continue
            center_x, center_y = centers[component_id]
            anchor = math.exp(
                -(
                    (center_x / patch.shape[1] / 0.62) ** 2
                    + (center_y / patch.shape[0] / 0.72) ** 2
                )
                * 1.2
            )
            if anchor < 0.12:
                continue
            filtered[labels == component_id] = 255
            components.append((area, anchor, x, y))

        component_area = sum(item[0] for item in components)
        if component_area <= 0:
            corner_results.append((0.0, filtered, 0))
            continue
        density = min(
            1.0,
            component_area / max(1.0, patch.size * 0.055),
        )
        component_quality = math.exp(
            -abs(len(components) - 2.5) * 0.32
        )
        anchor_quality = sum(
            area * anchor
            for area, anchor, _, _ in components
        ) / component_area
        minimum_x = min(item[2] for item in components)
        minimum_y = min(item[3] for item in components)
        outer_anchor = min(
            max(
                0.0,
                1.0 - minimum_x / (patch.shape[1] * 0.32),
            ),
            max(
                0.0,
                1.0 - minimum_y / (patch.shape[0] * 0.30),
            ),
        )
        presence = (
            density * 0.40
            + component_quality * 0.25
            + anchor_quality * 0.25
            + outer_anchor * 0.10
        )
        corner_results.append(
            (float(presence), filtered, len(components))
        )

    def pair_similarity(first_id, second_id):
        first = cv2.dilate(
            corner_results[first_id][1],
            np.ones((3, 3), dtype=np.uint8),
        )
        second = cv2.dilate(
            corner_results[second_id][1],
            np.ones((3, 3), dtype=np.uint8),
        )
        first_count = int(np.count_nonzero(first))
        second_count = int(np.count_nonzero(second))
        if min(first_count, second_count) < 4:
            return 0.0
        padded = cv2.copyMakeBorder(
            second,
            5,
            5,
            5,
            5,
            cv2.BORDER_CONSTANT,
            value=0,
        )
        correlation = cv2.matchTemplate(
            padded.astype(np.float32),
            first.astype(np.float32),
            cv2.TM_CCORR_NORMED,
        )
        best = float(np.nanmax(correlation))
        balance = min(first_count, second_count) / max(
            first_count,
            second_count,
        )
        return best * 0.75 + balance * 0.25

    def pair_strength(first_id, second_id):
        similarity = pair_similarity(first_id, second_id)
        presence = min(
            corner_results[first_id][0],
            corner_results[second_id][0],
        )
        return presence * (0.35 + similarity * 0.65), similarity

    diagonal_pairs = ((0, 3), (1, 2))
    adjacent_pairs = ((0, 1), (0, 2), (1, 3), (2, 3))
    diagonal = max(
        (
            (*pair_strength(*pair), pair)
            for pair in diagonal_pairs
        ),
        key=lambda item: item[0],
    )
    adjacent = max(
        (
            (*pair_strength(*pair), pair)
            for pair in adjacent_pairs
        ),
        key=lambda item: item[0],
    )
    margin = float(diagonal[0] - adjacent[0])
    evidence = max(diagonal[0], adjacent[0])
    evidence_confidence = max(
        0.0,
        min(1.0, (evidence - 0.10) / 0.20),
    )
    contrast_confidence = max(
        0.0,
        min(1.0, (abs(margin) - 0.05) / 0.16),
    )
    confidence = float(
        evidence_confidence * contrast_confidence
    )
    if confidence < 0.25:
        return {
            "score": 0.5,
            "confidence": 0.0,
            "valid": None,
            "locked": False,
            "corners": tuple(
                item[0]
                for item in corner_results
            ),
            "pair": diagonal[2] if margin >= 0.0 else adjacent[2],
            "component_count": sum(
                item[2]
                for item in corner_results
            ),
            "pair_similarity": max(diagonal[1], adjacent[1]),
            "outer_diagonal_margin": margin,
            "outer_diagonal_strength": float(diagonal[0]),
            "outer_adjacent_strength": float(adjacent[0]),
            "outer_corner_confidence": confidence,
        }

    valid = margin > 0.0
    score = float(
        0.5 + (1.0 if valid else -1.0) * confidence * 0.46
    )
    selected_pair = diagonal[2] if valid else adjacent[2]
    return {
        "score": score,
        "confidence": confidence,
        "valid": valid,
        "locked": bool(valid and confidence >= 0.72),
        "corners": tuple(
            item[0]
            for item in corner_results
        ),
        "pair": selected_pair,
        "component_count": sum(
            item[2]
            for item in corner_results
        ),
        "pair_similarity": (
            diagonal[1] if valid else adjacent[1]
        ),
        "outer_diagonal_margin": margin,
        "outer_diagonal_strength": float(diagonal[0]),
        "outer_adjacent_strength": float(adjacent[0]),
    }


def _generate_rigid_slot_layouts(pieces, base_layout):
    """每对碎片/槽位只拟合一次，再枚举合法分配和独立姿态。"""
    sources = [np.asarray(piece["points"], dtype=np.float64) for piece in pieces]
    targets = [np.asarray(base_layout[index], dtype=np.float64)
               for index in range(len(pieces))]
    placed = {}
    for source_id, source in enumerate(sources):
        for slot_id, target in enumerate(targets):
            placed[source_id, slot_id] = [
                (source - source_center) @ rotation.T + target_center
                for target_center, source_center, rotation, _, _
                in _rigid_similarity_poses(source, target)
            ]

    layouts = []
    for assignment in itertools.permutations(range(len(pieces))):
        choices = [placed[source_id, slot_id]
                   for slot_id, source_id in enumerate(assignment)]
        if any(not options for options in choices):
            continue
        for polygons in itertools.product(*choices):
            # 保留原顶点顺序，半转/四向的相同轮廓仍有不同纹理对应关系。
            layout = {source_id: polygon.copy()
                      for source_id, polygon in zip(assignment, polygons)}
            layouts.append((layout, assignment))
    return layouts


def generate_shape_swap_layouts(pieces, base_layout):
    """交换刚体外形近似的碎片，并保留每片所有近等价朝向。"""
    return _generate_rigid_slot_layouts(pieces, base_layout)


def generate_all_slot_layouts(pieces, base_layout):
    """枚举全部几何兼容的槽位分配及独立朝向，供低置信度时补搜索。"""
    return _generate_rigid_slot_layouts(pieces, base_layout)


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
    source_masks = []
    for polygon in polygons:
        mask = np.zeros(frame_rgb.shape[:2], dtype=np.uint8)
        cv2.fillPoly(
            mask,
            [np.rint(polygon).astype(np.int32)],
            255,
        )
        source_masks.append(mask)
    best_layout = None
    best_metrics = None
    best_score = -1.0
    best_texture = 0.5
    best_confidence = 0.0
    best_seams = []
    best_at_node = 0
    nodes = 0
    root_node_limit = node_limit
    root_deadline = started + time_limit_s

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
                    polygon_mask=source_masks[first_id],
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
                    polygon_mask=source_masks[second_id],
                )
                strip_cache[second_key] = second_strip
            value = _compare_edge_strips(
                first_strip,
                second_strip,
            )
            texture_cache[key] = value
        return value

    def _every_piece_touches_boundary(placed_polygons):
        """验证每块碎片至少有一条边在拼装矩形外边界上。"""
        if not placed_polygons:
            return False
        all_points = np.vstack(list(placed_polygons.values()))
        x_min, y_min = np.min(all_points, axis=0)
        x_max, y_max = np.max(all_points, axis=0)
        width = x_max - x_min
        height = y_max - y_min
        if width < 1e-6 or height < 1e-6:
            return False
        diagonal = math.hypot(float(width), float(height))
        tolerance = max(2.0, diagonal * 0.012)

        for polygon in placed_polygons.values():
            touches = False
            for edge_id in range(len(polygon)):
                start = polygon[edge_id]
                end = polygon[(edge_id + 1) % len(polygon)]
                length = float(np.linalg.norm(end - start))
                if length < tolerance * 0.5:
                    continue
                on_left = (
                    abs(float(start[0]) - x_min) <= tolerance
                    and abs(float(end[0]) - x_min) <= tolerance
                )
                on_right = (
                    abs(float(start[0]) - x_max) <= tolerance
                    and abs(float(end[0]) - x_max) <= tolerance
                )
                on_top = (
                    abs(float(start[1]) - y_min) <= tolerance
                    and abs(float(end[1]) - y_min) <= tolerance
                )
                on_bottom = (
                    abs(float(start[1]) - y_max) <= tolerance
                    and abs(float(end[1]) - y_max) <= tolerance
                )
                if on_left or on_right or on_top or on_bottom:
                    touches = True
                    break
            if not touches:
                return False
        return True

    def solution_is_strong():
        return (
            best_metrics is not None
            and best_metrics["coverage"] >= 0.97
            and best_metrics["corners"] >= 0.99
            and best_confidence >= 0.55
            and best_score >= 0.90
            and best_texture >= 0.78
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

        if nodes >= root_node_limit:
            return
        if time.perf_counter() >= root_deadline:
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
            # 边界约束：每块碎片至少有一条边在矩形外边界上
            if not _every_piece_touches_boundary(placed):
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
            if nodes >= root_node_limit:
                return
            if time.perf_counter() >= root_deadline:
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
    seed_variants = [
        (seed_id, seed_edge)
        for seed_id in seed_order
        for seed_edge in sorted(
            range(len(polygons[seed_id])),
            key=lambda edge_id: edge_length(
                polygons[seed_id],
                edge_id,
            ),
            reverse=True,
        )
    ]
    for variant_id, (seed_id, seed_edge) in enumerate(seed_variants):
        remaining_variants = len(seed_variants) - variant_id
        remaining_nodes = node_limit - nodes
        remaining_time = started + time_limit_s - time.perf_counter()
        if remaining_nodes <= 0 or remaining_time <= 0.0:
            break
        root_node_limit = nodes + max(
            1800,
            remaining_nodes // remaining_variants,
        )
        root_deadline = time.perf_counter() + max(
            0.10,
            remaining_time / remaining_variants,
        )
        seed = polygons[seed_id]
        vector = seed[(seed_edge + 1) % len(seed)] - seed[seed_edge]
        angle = -math.atan2(float(vector[1]), float(vector[0]))
        cosine = math.cos(angle)
        sine = math.sin(angle)
        rotation = np.asarray(
            [[cosine, -sine], [sine, cosine]],
            dtype=np.float64,
        )
        center = polygon_center(seed)
        oriented_seed = (seed - center) @ rotation.T
        search(
            {seed_id: oriented_seed},
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
