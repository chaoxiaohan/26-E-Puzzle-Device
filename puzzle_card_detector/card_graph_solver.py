"""Bounded, texture-ranked edge graph search for two to four card pieces."""

import math
import time

import cv2
import numpy as np

from card_face_solver import score_layout_texture
from card_joint_solver import relative_texture_matches
from layout_constraints import evaluate_layout
from solver_v2 import (
    align_edge_segment, edge_length, interval_is_free, interval_positions,
    normalize_polygon, opposite_sides, polygon_center, polygons_overlap,
    residual_partition_error,
)


def _layout_key(layout):
    # The labelled first edge fixes a global rigid pose. Keep every other
    # piece's labelled vertices: symmetric shapes can have different textures.
    anchor = layout[min(layout)]
    vector = anchor[1] - anchor[0]
    angle = -math.atan2(vector[1], vector[0])
    rotation = np.array([[math.cos(angle), -math.sin(angle)],
                         [math.sin(angle), math.cos(angle)]])
    return tuple((piece_id, tuple(np.rint(np.round(
        ((polygon - anchor[0]) @ rotation.T) * 4.0, 6,
    )).astype(np.int64).ravel())) for piece_id, polygon in sorted(layout.items()))


def _occupied_intervals(layout, piece_id, edge_id):
    polygon = layout[piece_id]
    start = polygon[edge_id]
    vector = polygon[(edge_id + 1) % len(polygon)] - start
    length = float(np.linalg.norm(vector))
    unit = vector / length
    normal = np.array([-unit[1], unit[0]])
    intervals = []
    for other_id, other in layout.items():
        if other_id == piece_id:
            continue
        for index, other_start in enumerate(other):
            other_end = other[(index + 1) % len(other)]
            other_vector = other_end - other_start
            other_length = float(np.linalg.norm(other_vector))
            if other_length < 1e-6 or np.dot(unit, other_vector / other_length) > -0.999:
                continue
            if max(abs(np.dot(other_start - start, normal)),
                   abs(np.dot(other_end - start, normal))) > 0.5:
                continue
            projected = sorted((float(np.dot(other_start - start, unit)),
                                float(np.dot(other_end - start, unit))))
            low, high = max(0.0, projected[0]), min(length, projected[1])
            if high > low:
                intervals.append((low, high))
    return intervals


def _overlap(first, second):
    # Exact and allocation-free for the usual convex card fragments.
    if cv2.isContourConvex(first.astype(np.float32)) and cv2.isContourConvex(second.astype(np.float32)):
        area, _ = cv2.intersectConvexConvex(first.astype(np.float32), second.astype(np.float32))
        smaller = min(abs(cv2.contourArea(first.astype(np.float32))),
                      abs(cv2.contourArea(second.astype(np.float32))))
        return area > max(0.5, smaller * 0.008)
    points = np.vstack((first, second))
    origin = np.min(points, axis=0)
    scale = min(1.0, 220.0 / max(1.0, float(np.ptp(points, axis=0).max())))
    return polygons_overlap((first - origin) * scale, (second - origin) * scale, 0.008)


def generate_card_graph_candidates(frame_rgb, pieces, time_limit_s=3.5,
                                   candidate_limit=48, cache=None):
    started = time.perf_counter()
    deadline = started + max(0.0, float(time_limit_s))
    nodes = 0
    complete = True
    candidates = []
    excluded_texture_bound = None

    def result():
        return {"candidates": candidates, "nodes": nodes,
                "search_complete": complete,
                "excluded_texture_bound": excluded_texture_bound,
                "elapsed_ms": (time.perf_counter() - started) * 1000.0}

    if not 2 <= len(pieces) <= 4 or candidate_limit <= 0:
        return result()
    polygons, reversed_order = [], []
    for piece in pieces:
        polygon = np.asarray(piece["points"], dtype=np.float64)
        if (polygon.ndim != 2 or polygon.shape[1] != 2 or not 3 <= len(polygon) <= 32
                or not np.isfinite(polygon).all()):
            complete = False
            return result()
        lengths = np.linalg.norm(np.roll(polygon, -1, axis=0) - polygon, axis=1)
        if (lengths.min() < 1e-4 or np.ptp(polygon, axis=0).max() > 2048
                or abs(cv2.contourArea(polygon.astype(np.float32))) < 1.0):
            complete = False
            return result()
        reversed_order.append(cv2.contourArea(polygon.astype(np.float32), oriented=True) < 0)
        polygons.append(normalize_polygon(polygon))

    normalized_pieces = [dict(piece, points=polygon)
                         for piece, polygon in zip(pieces, polygons)]
    # Keep source ordering consistent with the scorer, including CW inputs.
    if cache is None:
        cache = {}
    signature = (id(frame_rgb), frame_rgb.shape,
                 tuple(tuple(polygon.ravel()) for polygon in polygons))
    graph_cache = cache.setdefault("card_graph", {})
    if graph_cache.get("signature") != signature:
        graph_cache.clear()
        graph_cache["signature"] = signature
    texture_cache = graph_cache.setdefault("texture", {})
    scores = graph_cache.setdefault("scores", {})
    geometry = graph_cache.setdefault("geometry", {})
    lengths = [[edge_length(polygon, index) for index in range(len(polygon))]
               for polygon in polygons]
    references = [length for piece_lengths in lengths for length in piece_lengths]
    total_area = sum(abs(cv2.contourArea(polygon.astype(np.float32))) for polygon in polygons)
    beam_width = max(96, int(candidate_limit) * 4)
    node_limit = 16000
    anchor = polygons[0] - polygons[0][0]
    beam = [{0: anchor}]
    accepted = set()

    def stopped():
        return nodes >= node_limit or time.perf_counter() >= deadline

    def phase_stopped():
        return stopped() or nodes >= phase_node_limit or time.perf_counter() >= phase_deadline

    def texture_for(layout, key):
        if key not in scores:
            scores[key] = score_layout_texture(frame_rgb, normalized_pieces, layout, texture_cache)
        return scores[key]

    for depth in range(1, len(polygons)):
        # Reserve time for complete leaves even when an earlier beam is large.
        phase_deadline = started + max(0.0, float(time_limit_s)) * depth / (len(polygons) - 1)
        phase_node_limit = node_limit * depth / (len(polygons) - 1)
        branches = {}
        examined = set()
        for placed in beam:
            if phase_stopped():
                complete = False
                break
            remaining = [index for index in range(len(polygons)) if index not in placed]
            for target_id, target in placed.items():
                for target_edge in range(len(target)):
                    target_length = lengths[target_id][target_edge]
                    start = target[target_edge]
                    unit = (target[(target_edge + 1) % len(target)] - start) / target_length
                    occupied = _occupied_intervals(placed, target_id, target_edge)
                    for source_id in remaining:
                        for source_edge, source_length in enumerate(lengths[source_id]):
                            if phase_stopped():
                                complete = False
                                break
                            shared = min(target_length, source_length)
                            if shared < max(2.0, max(target_length, source_length) * 0.12):
                                continue
                            partition = residual_partition_error(target_length, source_length, references)
                            # Residual lengths guide ordering, never exclude T joints.
                            offsets = interval_positions(target_length, shared, occupied, references)
                            source_offsets = interval_positions(source_length, shared, [], references)
                            for target_offset in offsets:
                                if not interval_is_free(occupied, target_offset, target_offset + shared, 0.5):
                                    continue
                                for source_offset in source_offsets:
                                    if phase_stopped():
                                        complete = False
                                        break
                                    nodes += 1
                                    transformed = align_edge_segment(
                                        polygons[source_id], source_edge, source_offset, shared,
                                        start + unit * target_offset, start + unit * (target_offset + shared))
                                    if transformed is None or not opposite_sides(
                                            start, start + unit * target_length,
                                            polygon_center(target), polygon_center(transformed)):
                                        continue
                                    layout = dict(placed)
                                    layout[source_id] = transformed
                                    key = _layout_key(layout)
                                    if key in examined or key in accepted:
                                        continue
                                    examined.add(key)
                                    if key not in geometry:
                                        rectangle = cv2.minAreaRect(np.vstack(list(layout.values())).astype(np.float32))
                                        width, height = rectangle[1]
                                        rectangle_area = float(width * height)
                                        geometry[key] = (rectangle_area > total_area / 0.78
                                                         or any(_overlap(transformed, other) for other in placed.values()))
                                    if geometry[key]:
                                        continue
                                    if phase_stopped():
                                        complete = False
                                        break
                                    texture = texture_for(layout, key)
                                    if depth == len(polygons) - 1:
                                        original_order = {index: (polygon[::-1].copy() if reversed_order[index]
                                                                   else polygon.copy())
                                                          for index, polygon in layout.items()}
                                        report = evaluate_layout(original_order)
                                        if (report.get("coverage", 0.0) < 0.80
                                                or report.get("overlap", 1.0) > 0.025
                                                or report.get("outer_piece_ratio", 0.0) < 0.999
                                                or report.get("components", 0) != 1
                                                or report.get("aspect", 99.0) > 2.45):
                                            continue
                                        accepted.add(key)
                                        candidates.append({"layout": original_order, "source": "card-graph-texture",
                                                           "texture": texture, "report": report})
                                    else:
                                        placed_area = sum(abs(cv2.contourArea(polygon.astype(np.float32)))
                                                          for polygon in layout.values())
                                        rectangle = cv2.minAreaRect(np.vstack(list(layout.values())).astype(np.float32))
                                        compactness = placed_area / max(1.0, rectangle[1][0] * rectangle[1][1])
                                        rank = texture["score"] + 0.035 * compactness - 0.002 * partition
                                        branches[key] = (rank, layout)
        if depth < len(polygons) - 1:
            ordered = sorted(branches.values(), key=lambda item: item[0], reverse=True)
            if len(ordered) > beam_width:
                complete = False
            beam = [item[1] for item in ordered[:beam_width]]
            if not beam or stopped():
                break
    for candidate in candidates:
        candidate["texture"] = relative_texture_matches(candidate["texture"], texture_cache.get("pairs", {}))
    candidates.sort(key=lambda item: (item["texture"]["score"], item["report"]["score"]), reverse=True)
    if len(candidates) > candidate_limit:
        excluded_texture_bound = candidates[int(candidate_limit)]["texture"]["score"]
        candidates = candidates[:int(candidate_limit)]
        complete = False
    return result()
