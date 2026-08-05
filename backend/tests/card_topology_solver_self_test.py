# -*- coding: utf-8 -*-

import math
import os
import sys

import numpy as np


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from card_topology_solver import classify_card_pieces, generate_card_topology_candidates


def rotated_rectangle(width, height, angle, offset):
    polygon = np.array(
        [[0.0, 0.0], [width, 0.0], [width, height], [0.0, height]],
        dtype=np.float64,
    )
    center = np.mean(polygon, axis=0)
    radians = math.radians(angle)
    rotation = np.array(
        [
            [math.cos(radians), -math.sin(radians)],
            [math.sin(radians), math.cos(radians)],
        ],
        dtype=np.float64,
    )
    return (polygon - center) @ rotation.T + center + offset


def perspective_like_rectangle(width, height, offset):
    return np.array(
        [
            [0.0, 0.0],
            [width * 0.82, height * 0.04],
            [width, height],
            [width * 0.05, height * 0.96],
        ],
        dtype=np.float64,
    ) + np.asarray(offset, dtype=np.float64)


def main():
    pieces = [
        {"points": rotated_rectangle(100, 80, 14, (300, 200))},
        {"points": rotated_rectangle(100, 80, -37, (500, 300))},
        {"points": rotated_rectangle(100, 80, 66, (200, 500))},
        {"points": rotated_rectangle(100, 80, 128, (700, 450))},
    ]
    classified = classify_card_pieces(pieces)
    assert classified["kind"] == "all-rectangles"

    result = generate_card_topology_candidates(pieces, time_limit_s=1.6)
    assert result["candidates"], "矩形分割没有生成候选"
    assert any(
        len(candidate["topology"][1]) == 2
        and all(len(row) == 2 for row in candidate["topology"][1])
        for candidate in result["candidates"]
    ), "候选池缺少 2x2 矩形分割"

    distorted = [
        {"points": perspective_like_rectangle(132, 68, (200, 150))},
        {"points": perspective_like_rectangle(107, 70, (450, 180))},
        {"points": perspective_like_rectangle(150, 71, (260, 450))},
        {"points": perspective_like_rectangle(102, 70, (560, 460))},
    ]
    distorted_result = generate_card_topology_candidates(
        distorted,
        time_limit_s=1.6,
    )
    assert distorted_result["candidates"], "梯形检测矩形没有生成候选"
    assert all(
        max(candidate["report"]["width"], candidate["report"]["height"])
        / min(candidate["report"]["width"], candidate["report"]["height"])
        <= 2.0
        for candidate in distorted_result["candidates"]
    ), "候选池保留了不可能的条带布局"
    assert any(
        candidate["report"]["competition_valid"]
        for candidate in distorted_result["candidates"]
    ), "梯形检测矩形没有形成严格矩形网格"

    mixed = pieces[:3] + [{
        "points": [(30, 40), (140, 45), (80, 180)],
    }]
    assert classify_card_pieces(mixed)["kind"] == "mixed"
    print("card topology solver self-test passed")


if __name__ == "__main__":
    main()
