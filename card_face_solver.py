# -*- coding: utf-8 -*-

import math
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
