# -*- coding: utf-8 -*-
"""扑克牌专用的几何拓扑候选生成器。

它不替换普通拼图的 C++ 求解器。这里的任务只是在扑克牌模式下保留
“谁和谁相邻、哪条边相接”的不同拓扑，供后续牌面花纹评分选择。
"""

import itertools
import math
import time

import cv2
import numpy as np

from layout_constraints import evaluate_layout
from solver_v2 import (
    align_edge_segment,
    edge_length,
    interval_is_free,
    interval_positions,
    normalize_polygon,
    opposite_sides,
    polygon_center,
    polygons_overlap,
    residual_partition_error,
)


def _rotate_polygon(polygon, angle):
    center = np.mean(polygon, axis=0)
    radians = math.radians(angle)
    rotation = np.array(
        [
            [math.cos(radians), -math.sin(radians)],
            [math.sin(radians), math.cos(radians)],
        ],
        dtype=np.float64,
    )
    return (polygon - center) @ rotation.T + center


def _rectangle_profile(points):
    polygon = normalize_polygon(points)
    area = abs(float(cv2.contourArea(polygon.astype(np.float32))))
    rectangle = cv2.minAreaRect(polygon.astype(np.float32))
    width, height = rectangle[1]
    fill = area / max(1.0, float(width * height))
    score = fill
    if len(polygon) != 4 or min(width, height) < 4.0:
        return {
            "score": 0.0,
            "rectangular": False,
            "polygon": polygon,
        }

    vectors = [
        polygon[(index + 1) % 4] - polygon[index]
        for index in range(4)
    ]
    lengths = [float(np.linalg.norm(vector)) for vector in vectors]
    if min(lengths) < 4.0:
        return {
            "score": 0.0,
            "rectangular": False,
            "polygon": polygon,
        }

    right_angles = []
    for index in range(4):
        first = vectors[index - 1] / lengths[index - 1]
        second = vectors[index] / lengths[index]
        right_angles.append(1.0 - abs(float(np.dot(first, second))))
    parallel = []
    for first_id, second_id in ((0, 2), (1, 3)):
        first = vectors[first_id] / lengths[first_id]
        second = vectors[second_id] / lengths[second_id]
        parallel.append(abs(float(np.dot(first, second))))
    opposite_size = min(
        lengths[0], lengths[2]
    ) / max(lengths[0], lengths[2])
    opposite_size += min(
        lengths[1], lengths[3]
    ) / max(lengths[1], lengths[3])
    opposite_size *= 0.5
    score = (
        fill * 0.35
        + float(np.mean(right_angles)) * 0.30
        + float(np.mean(parallel)) * 0.20
        + opposite_size * 0.15
    )
    return {
        "score": float(score),
        "rectangular": bool(score >= 0.80),
        "polygon": polygon,
    }


def classify_card_pieces(pieces):
    """返回矩形可信度；灰区碎片会同时进入两类候选路径。"""
    profiles = [
        _rectangle_profile(piece["points"])
        for piece in pieces
    ]
    strong = [
        index
        for index, profile in enumerate(profiles)
        if profile["score"] >= 0.80
    ]
    uncertain = [
        index
        for index, profile in enumerate(profiles)
        if 0.65 <= profile["score"] < 0.80
    ]
    if len(strong) == len(pieces):
        kind = "all-rectangles"
    elif strong:
        kind = "mixed"
    else:
        kind = "irregular"
    return {
        "kind": kind,
        "profiles": profiles,
        "strong_rectangles": tuple(strong),
        "uncertain_rectangles": tuple(uncertain),
    }


def _layout_key(layout, topology, orientation=()):
    centers = []
    for piece_id in sorted(layout):
        center = np.mean(layout[piece_id], axis=0)
        centers.append((
            piece_id,
            int(round(center[0] * 0.15)),
            int(round(center[1] * 0.15)),
        ))
    return tuple(topology), tuple(centers), tuple(orientation)


def _topology_info(layout, topology, source, orientation=()):
    report = evaluate_layout(layout, edge_tolerance_ratio=0.065)
    geometry = (
        report.get("coverage", 0.0) * 0.50
        + report.get("internal_match", 0.0) * 0.28
        + report.get("corners", 0.0) * 0.12
        + report.get("outer_piece_ratio", 0.0) * 0.10
        - report.get("overlap", 1.0) * 4.0
    )
    return {
        "layout": layout,
        "topology": tuple(topology),
        "source": source,
        "orientation": tuple(orientation),
        "geometry_score": float(geometry),
        "report": report,
        "signature": _layout_key(layout, topology, orientation),
    }


def _generic_edge_candidates(pieces, deadline):
    """对异形和混合碎片按真实边接触关系递归装配。"""
    polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    piece_count = len(polygons)
    reference_lengths = [
        edge_length(polygon, edge_id)
        for polygon in polygons
        for edge_id in range(len(polygon))
    ]
    results = []
    node_limit = 14000
    node_count = 0

    def has_overlap(layout, candidate):
        return any(
            polygons_overlap(candidate, existing, tolerance_ratio=0.004)
            for existing in layout.values()
        )

    def visit(layout, remaining, usage, topology):
        nonlocal node_count
        if node_count >= node_limit or time.monotonic() >= deadline:
            return
        node_count += 1
        if not remaining:
            item = _topology_info(layout, topology, "card-topology-edge")
            report = item["report"]
            if (
                report.get("overlap", 1.0) <= 0.01
                and report.get("coverage", 0.0) >= 0.72
                and report.get("corners", 0.0) >= 0.50
                and report.get("outer_piece_ratio", 0.0) >= 0.75
            ):
                results.append(item)
            return

        for source_id in tuple(remaining):
            source = polygons[source_id]
            for target_id, target in tuple(layout.items()):
                target_center = polygon_center(target)
                for target_edge in range(len(target)):
                    target_length = edge_length(target, target_edge)
                    target_start = target[target_edge]
                    target_end = target[
                        (target_edge + 1) % len(target)
                    ]
                    target_unit = (target_end - target_start) / max(
                        1e-9,
                        target_length,
                    )
                    target_intervals = usage.get(
                        (target_id, target_edge),
                        [],
                    )
                    for source_edge in range(len(source)):
                        source_length = edge_length(source, source_edge)
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
                            relative_error > 0.16
                            and partition_error > 0.14
                        ):
                            continue
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
                                placed = align_edge_segment(
                                    source,
                                    source_edge,
                                    source_offset,
                                    shared,
                                    segment_start,
                                    segment_end,
                                )
                                if placed is None or has_overlap(
                                    layout,
                                    placed,
                                ):
                                    continue
                                if not opposite_sides(
                                    segment_start,
                                    segment_end,
                                    target_center,
                                    polygon_center(placed),
                                ):
                                    continue
                                next_layout = dict(layout)
                                next_layout[source_id] = placed
                                next_usage = {
                                    key: list(value)
                                    for key, value in usage.items()
                                }
                                next_usage.setdefault(
                                    (target_id, target_edge),
                                    [],
                                ).append((
                                    target_offset,
                                    target_offset + shared,
                                ))
                                next_topology = list(topology)
                                next_topology.append((
                                    target_id,
                                    target_edge,
                                    source_id,
                                    source_edge,
                                    int(round(target_offset)),
                                    int(round(source_offset)),
                                ))
                                visit(
                                    next_layout,
                                    tuple(
                                        item
                                        for item in remaining
                                        if item != source_id
                                    ),
                                    next_usage,
                                    next_topology,
                                )

    for root_id, polygon in enumerate(polygons):
        visit(
            {root_id: polygon.copy()},
            tuple(
                piece_id
                for piece_id in range(piece_count)
                if piece_id != root_id
            ),
            {},
            (),
        )
    return results, node_count


def _rectangle_variants(polygon):
    """将同一矩形的 0/90/180/270 度姿态保留为不同顶点对应。"""
    polygon = normalize_polygon(polygon)
    side_lengths = [
        edge_length(polygon, index)
        for index in range(4)
    ]
    width = (side_lengths[0] + side_lengths[2]) * 0.5
    height = (side_lengths[1] + side_lengths[3]) * 0.5
    base = np.array(
        [[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]],
        dtype=np.float64,
    )
    variants = []
    for quarter_turn in range(4):
        transformed = _rotate_polygon(
            base,
            quarter_turn * 90.0,
        )
        transformed -= np.min(transformed, axis=0)
        size = np.max(transformed, axis=0)
        variants.append({
            "polygon": transformed,
            "width": float(size[0]),
            "height": float(size[1]),
            "rotation": quarter_turn,
        })
    return variants


def _row_compositions(count):
    for mask in range(1 << max(0, count - 1)):
        rows = [[]]
        for index in range(count):
            rows[-1].append(index)
            if index < count - 1 and mask & (1 << index):
                rows.append([])
        yield rows


def _build_row_layout(selected, rows):
    row_heights = []
    row_widths = []
    for row in rows:
        heights = [selected[index]["height"] for index in row]
        height = float(np.mean(heights))
        if max(heights) - min(heights) > max(3.0, height * 0.12):
            return None
        row_heights.append(height)
        row_widths.append(sum(selected[index]["width"] for index in row))
    target_width = float(np.mean(row_widths))
    if max(row_widths) - min(row_widths) > max(4.0, target_width * 0.12):
        return None

    layout = {}
    y = 0.0
    for row, height, row_width in zip(rows, row_heights, row_widths):
        x = 0.0
        width_scale = target_width / max(1e-9, row_width)
        for index in row:
            variant = selected[index]
            width = variant["width"] * width_scale
            polygon = np.array(
                [
                    [x, y],
                    [x + width, y],
                    [x + width, y + height],
                    [x, y + height],
                ],
                dtype=np.float64,
            )
            layout[variant["piece_id"]] = polygon
            x += width
        y += height
    return layout


def _rectangle_partition_candidates(pieces, deadline):
    """枚举不大于四块的矩形行列分割，并保留牌面朝向差异。"""
    variants = [
        _rectangle_variants(normalize_polygon(piece["points"]))
        for piece in pieces
    ]
    results = []
    piece_count = len(pieces)
    for permutation in itertools.permutations(range(piece_count)):
        if time.monotonic() >= deadline:
            break
        # 固定碎片 0 的全局朝向，避免整副牌同时旋转造成四倍重复。
        orientation_options = [
            range(4) if piece_id != 0 else (0,)
            for piece_id in permutation
        ]
        for rotations in itertools.product(*orientation_options):
            if time.monotonic() >= deadline:
                break
            selected = []
            for piece_id, rotation in zip(permutation, rotations):
                item = dict(variants[piece_id][rotation])
                item["piece_id"] = piece_id
                selected.append(item)
            for rows in _row_compositions(piece_count):
                layout = _build_row_layout(selected, rows)
                if layout is None:
                    continue
                topology = (
                    "rect-grid",
                    tuple(tuple(permutation[index] for index in row) for row in rows),
                )
                item = _topology_info(
                    layout,
                    topology,
                    "card-topology-rect",
                    rotations,
                )
                report = item["report"]
                long_short_ratio = max(
                    report.get("width", 0.0),
                    report.get("height", 0.0),
                ) / max(
                    1e-9,
                    min(
                        report.get("width", 0.0),
                        report.get("height", 0.0),
                    ),
                )
                if (
                    report.get("overlap", 1.0) <= 0.01
                    and report.get("coverage", 0.0) >= 0.90
                    and report.get("corners", 0.0) >= 0.99
                    and report.get("outer_piece_ratio", 0.0) >= 0.999
                    and long_short_ratio <= 2.0
                ):
                    results.append(item)
    return results


def generate_rectangle_grid_hypotheses(pieces):
    """快速枚举四块近矩形的完整 2x2 拓扑，不在生成阶段做昂贵评分。"""
    if len(pieces) != 4 or any(
        len(normalize_polygon(piece["points"])) != 4
        for piece in pieces
    ):
        return []
    variants = [
        _rectangle_variants(normalize_polygon(piece["points"]))
        for piece in pieces
    ]
    results = []
    for permutation in itertools.permutations(range(4)):
        orientation_options = [
            (0,) if piece_id == 0 else range(4)
            for piece_id in permutation
        ]
        for rotations in itertools.product(*orientation_options):
            selected = []
            for piece_id, rotation in zip(permutation, rotations):
                item = dict(variants[piece_id][rotation])
                item["piece_id"] = piece_id
                selected.append(item)
            layout = _build_row_layout(selected, ((0, 1), (2, 3)))
            if layout is None:
                continue
            topology = (
                "rect-grid-fast",
                ((permutation[0], permutation[1]),
                 (permutation[2], permutation[3])),
            )
            results.append({
                "layout": layout,
                "topology": topology,
                "source": "card-topology-grid",
                "orientation": tuple(rotations),
                "signature": _layout_key(layout, topology, rotations),
            })
    return results


def generate_card_topology_candidates(pieces, time_limit_s=1.6):
    """生成拓扑多样的候选；只服务于扑克牌模式。"""
    if not 2 <= len(pieces) <= 4:
        return {
            "classification": {"kind": "invalid"},
            "candidates": [],
            "nodes": 0,
        }
    started = time.monotonic()
    deadline = started + max(0.1, float(time_limit_s))
    classification = classify_card_pieces(pieces)
    if classification["kind"] == "all-rectangles":
        candidates = _rectangle_partition_candidates(pieces, deadline)
        nodes = 0
    else:
        candidates, nodes = _generic_edge_candidates(pieces, deadline)
        if (
            classification["uncertain_rectangles"]
            and all(len(piece["points"]) == 4 for piece in pieces)
        ):
            candidates.extend(
                _rectangle_partition_candidates(pieces, deadline)
            )

    unique = {}
    for candidate in candidates:
        key = candidate["signature"]
        previous = unique.get(key)
        if (
            previous is None
            or candidate["geometry_score"] > previous["geometry_score"]
        ):
            unique[key] = candidate
    ordered = sorted(
        unique.values(),
        key=lambda item: item["geometry_score"],
        reverse=True,
    )
    # 轮流从不同拓扑取候选，不能让同一矩形排列的方向组合占满池子。
    groups = {}
    for candidate in ordered:
        groups.setdefault(repr(candidate["topology"]), []).append(
            candidate
        )
    group_list = sorted(
        groups.values(),
        key=lambda group: group[0]["geometry_score"],
        reverse=True,
    )
    kept = []
    for orientation_rank in range(4):
        for group in group_list:
            if orientation_rank >= len(group):
                continue
            kept.append(group[orientation_rank])
            if len(kept) >= 72:
                break
        if len(kept) >= 72:
            break
    return {
        "classification": classification,
        "candidates": kept,
        "nodes": nodes,
        "elapsed_ms": (time.monotonic() - started) * 1000.0,
    }
