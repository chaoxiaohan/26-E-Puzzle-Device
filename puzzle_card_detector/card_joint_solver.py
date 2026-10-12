"""保留碎片身份和朝向，用缓存的真实拼缝纹理搜索矩形切法。"""

import itertools
import math
import time

import cv2
import numpy as np

from card_face_solver import _compare_edge_strips, _sample_edge_strip, _texture_summary
from layout_constraints import evaluate_layout
from solver_v2 import normalize_polygon


def relative_texture_matches(texture, pair_cache, best=None):
    """兼顾绝对连续性与双向相对匹配；没有墨迹证据的白边保持中性。"""
    if not texture.get("pair_keys"):
        return texture
    if best is None:
        best = {}
        for pair, (quality, evidence) in pair_cache.items():
            if evidence < 0.05:
                continue
            for key in pair:
                context = key[:-1]
                best[context] = max(best.get(context, 0.05), quality)
    seams = []
    for seam, pair in zip(texture["seams"], texture["pair_keys"]):
        quality, evidence = seam[:2]
        if evidence >= 0.05:
            first = min(1.0, quality / max(0.05, best.get(pair[0][:-1], quality)))
            second = min(1.0, quality / max(0.05, best.get(pair[1][:-1], quality)))
            quality = quality * 0.45 + math.sqrt(first * second) * 0.55
        seams.append((quality, evidence, *seam[2:]))
    score, confidence = _texture_summary(seams)
    return dict(texture, raw_score=texture["score"], score=score,
                confidence=confidence, relative_seams=seams)


def layout_pose_key(layout):
    """只消除整幅拼图的共同旋转和平移，保留每片顶点对应关系。"""
    if not layout:
        return ()
    anchor = np.asarray(layout[min(layout)], dtype=float)
    center = anchor.mean(axis=0)
    vector = anchor[1] - anchor[0]
    angle = -math.atan2(float(vector[1]), float(vector[0]))
    rotation = np.array([[math.cos(angle), -math.sin(angle)],
                         [math.sin(angle), math.cos(angle)]])
    return tuple((int(piece_id), tuple(np.rint(np.round(
        (np.asarray(layout[piece_id]) - center) @ rotation.T * 0.5, 6,
    )).astype(int).ravel())) for piece_id in sorted(layout))


def _rectangle_states(points):
    polygon = normalize_polygon(points)
    center = polygon.mean(axis=0)
    vector = polygon[1] - polygon[0]
    start_angle = math.atan2(float(vector[1]), float(vector[0]))
    states = []
    for turn in range(4):
        angle = turn * math.pi / 2 - start_angle
        rotation = np.array([[math.cos(angle), -math.sin(angle)],
                             [math.sin(angle), math.cos(angle)]])
        target = (polygon - center) @ rotation.T
        target -= target.min(axis=0)
        size = target.max(axis=0)
        midpoints = (target + np.roll(target, -1, axis=0)) * 0.5
        states.append({
            "polygon": target,
            "size": tuple(float(value) for value in size),
            "edges": (int(np.argmin(midpoints[:, 0])),
                      int(np.argmax(midpoints[:, 0])),
                      int(np.argmin(midpoints[:, 1])),
                      int(np.argmax(midpoints[:, 1]))),
            "turn": turn,
        })
    return states


def _partitions(count):
    for cuts in range(1 << (count - 1)):
        groups = [[]]
        for index in range(count):
            groups[-1].append(index)
            if index < count - 1 and cuts & (1 << index):
                groups.append([])
        yield groups


def _place_groups(selected, groups, axis):
    along, across = axis, 1 - axis
    spans = [sum(selected[index]["size"][along] for index in group)
             for group in groups]
    if max(spans) - min(spans) > max(3.0, sum(spans) / len(spans) * 0.06):
        return None
    placed = []
    offset = 0.0
    for group in groups:
        sizes = [selected[index]["size"][across] for index in group]
        height = sum(sizes) / len(sizes)
        if max(sizes) - min(sizes) > max(2.5, height * 0.06):
            return None
        position = 0.0
        for index in group:
            item = dict(selected[index])
            translation = np.zeros(2)
            translation[along], translation[across] = position, offset
            item["target"] = item["polygon"] + translation
            item["minimum"] = translation
            item["maximum"] = translation + np.asarray(item["size"])
            placed.append(item)
            position += item["size"][along]
        offset += height
    total = np.max([item["maximum"] for item in placed], axis=0)
    if min(total) < 4.0 or max(total) / min(total) > 2.45:
        return None
    return placed


class _SeamCache:
    def __init__(self, frame_rgb, pieces, cache):
        self.frame = frame_rgb
        self.polygons = [normalize_polygon(piece["points"]) for piece in pieces]
        self.strips = cache.setdefault("joint_strips", {})
        self.pairs = cache.setdefault("joint_pairs", {})
        self.masks = []
        for polygon in self.polygons:
            mask = np.zeros(frame_rgb.shape[:2], dtype=np.uint8)
            cv2.fillPoly(mask, [np.rint(polygon).astype(np.int32)], 255)
            mask = cv2.erode(mask, np.ones((3, 3), dtype=np.uint8))
            self.masks.append(mask)

    def strip(self, key, offset, length):
        if key not in self.strips:
            piece_id, edge_id, _, _, reverse = key
            self.strips[key] = _sample_edge_strip(
                self.frame, self.polygons[piece_id], edge_id, offset, length,
                reverse=reverse, polygon_mask=self.masks[piece_id],
            )
        return self.strips[key]

    def compare(self, first, second, first_edge, second_edge, low, high, axis):
        length = high - low
        offsets = []
        for item, edge in ((first, first_edge), (second, second_edge)):
            polygon = item["target"]
            start = polygon[edge]
            vector = polygon[(edge + 1) % 4] - start
            unit = vector / max(1e-9, np.linalg.norm(vector))
            edge_start = low if unit[axis] > 0 else high
            offsets.append(max(0.0, float((edge_start - start[axis]) / unit[axis])))
        length /= max(0.9, min(abs((item["target"][(edge + 1) % 4] - item["target"][edge])[axis])
                              / np.linalg.norm(item["target"][(edge + 1) % 4] - item["target"][edge])
                              for item, edge in ((first, first_edge), (second, second_edge))))
        keys = [
            (item["piece_id"], edge, round(offset * 2), round(length * 2), reverse)
            for item, edge, offset, reverse in (
                (first, first_edge, offsets[0], False),
                (second, second_edge, offsets[1], True),
            )
        ]
        pair = tuple(keys)
        if pair not in self.pairs:
            self.pairs[pair] = _compare_edge_strips(
                self.strip(keys[0], offsets[0], length),
                self.strip(keys[1], offsets[1], length),
            )
        return (*self.pairs[pair], pair)

    def score(self, placed):
        seams = []
        pair_keys = []
        for index, first in enumerate(placed):
            for second in placed[index + 1:]:
                for axis in (0, 1):
                    normal = 1 - axis
                    low = max(first["minimum"][axis], second["minimum"][axis])
                    high = min(first["maximum"][axis], second["maximum"][axis])
                    if high - low < 4.0:
                        continue
                    if abs(first["maximum"][normal] - second["minimum"][normal]) <= 2.5:
                        a, b = first, second
                    elif abs(second["maximum"][normal] - first["minimum"][normal]) <= 2.5:
                        a, b = second, first
                    else:
                        continue
                    edge_a = a["edges"][1 if normal == 0 else 3]
                    edge_b = b["edges"][0 if normal == 0 else 2]
                    quality, evidence, pair = self.compare(a, b, edge_a, edge_b, low, high, axis)
                    pair_keys.append(pair)
                    seams.append((quality, evidence, a["piece_id"], b["piece_id"], high - low))
        score, confidence = _texture_summary(seams)
        return {"score": score, "confidence": confidence,
                "seam_count": len(seams), "seams": seams, "pair_keys": pair_keys}


def generate_rectangular_card_candidates(frame_rgb, pieces, candidate_limit=64, cache=None):
    """枚举行、列、条带及T连接，评分在截断之前完成，不依赖几何种子。"""
    started = time.monotonic()
    if not 2 <= len(pieces) <= 4 or any(len(piece["points"]) != 4 for piece in pieces):
        return {"candidates": [], "nodes": 0, "search_complete": True}
    cache = {} if cache is None else cache
    scorer = _SeamCache(frame_rgb, pieces, cache)
    variants = [_rectangle_states(piece["points"]) for piece in pieces]
    state_groups = []
    for piece_id, states in enumerate(variants):
        grouped = {}
        for state in states[:1] if piece_id == 0 else states:
            key = tuple(round(value, 5) for value in state["size"])
            grouped.setdefault(key, []).append(state)
        state_groups.append(list(grouped.values()))
    partitions = list(_partitions(len(pieces)))
    unique = {}
    nodes = 0
    for order in itertools.permutations(range(len(pieces))):
        # 锚块方向固定，只删除整牌共同旋转；每个其他块仍独立四向。
        for geometry in itertools.product(*(state_groups[piece_id] for piece_id in order)):
            selected = [dict(states[0], piece_id=piece_id)
                        for piece_id, states in zip(order, geometry)]
            for axis in (0, 1):
                for groups in partitions:
                    placed = _place_groups(selected, groups, axis)
                    if placed is None:
                        continue
                    positions = {item["piece_id"]: item["minimum"] for item in placed}
                    for states in itertools.product(*geometry):
                        origin = positions[0]
                        key = tuple((piece_id, state["turn"],
                                     round(round(float(positions[piece_id][0] - origin[0]) * 0.5, 6)),
                                     round(round(float(positions[piece_id][1] - origin[1]) * 0.5, 6)))
                                    for piece_id, state in sorted(zip(order, states)))
                        if key in unique:
                            continue
                        oriented = []
                        layout = {}
                        for piece_id, state in zip(order, states):
                            position = positions[piece_id]
                            item = dict(state, piece_id=piece_id, minimum=position,
                                        maximum=position + np.asarray(state["size"]),
                                        target=state["polygon"] + position)
                            oriented.append(item)
                            target = item["target"]
                            source = np.asarray(pieces[piece_id]["points"], dtype=float)
                            layout[piece_id] = (target[::-1].copy() if cv2.contourArea(
                                source.astype(np.float32), oriented=True) < 0 else target)
                        nodes += 1
                        texture = scorer.score(oriented)
                        unique[key] = {"layout": layout, "texture": texture,
                                       "source": "card-joint-rectangle", "assignment": order}
    for candidate in unique.values():
        candidate["texture"] = relative_texture_matches(candidate["texture"], scorer.pairs)
    ordered = sorted(unique.values(), key=lambda item: item["texture"]["score"], reverse=True)
    kept = []
    last_rank = -1
    for last_rank, candidate in enumerate(ordered):
        report = evaluate_layout(candidate["layout"], edge_tolerance_ratio=0.065)
        if (report["overlap"] > 0.008 or report["coverage"] < 0.82
                or report["outer_piece_ratio"] < 0.999 or report["corners"] < 0.75):
            continue
        candidate["report"] = report
        kept.append(candidate)
        if len(kept) >= candidate_limit:
            break
    return {"candidates": kept, "nodes": nodes, "search_complete": True,
            "candidate_pool_complete": len(kept) < candidate_limit,
            "excluded_texture_bound": (ordered[last_rank + 1]["texture"]["score"]
                                       if last_rank + 1 < len(ordered) else None),
            "elapsed_ms": (time.monotonic() - started) * 1000,
            "edge_pairs": len(scorer.pairs)}
