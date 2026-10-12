"""Synthetic labelled-pose checks; run from the detector directory."""

import math

import cv2
import numpy as np

from card_graph_solver import generate_card_graph_candidates


def _scene(polygons, blank=False, clockwise=False):
    card = np.full((101, 161, 3), 245, dtype=np.uint8)
    if not blank:
        for y, color in ((20, (185, 20, 30)), (45, (25, 25, 25)), (77, (210, 40, 50))):
            cv2.line(card, (0, y), (160, y + 8), color, 13, cv2.LINE_AA)
        cv2.circle(card, (105, 58), 23, (30, 30, 30), 7, cv2.LINE_AA)
    frame = np.full((660, 660, 3), 35, dtype=np.uint8)
    pieces, expected = [], {}
    for index, polygon in enumerate(polygons):
        polygon = np.asarray(polygon, dtype=np.float64)
        if clockwise and index % 2 == 0:
            polygon = polygon[::-1].copy()
        angle = math.radians((17, -61, 128, -149)[index])
        rotation = np.array([[math.cos(angle), -math.sin(angle)],
                             [math.sin(angle), math.cos(angle)]])
        center = np.array(((170, 170), (470, 170), (170, 470), (470, 470))[index])
        shift = center - np.mean(polygon, axis=0) @ rotation.T
        moved = polygon @ rotation.T + shift
        affine = np.column_stack((rotation, shift)).astype(np.float32)
        warped = cv2.warpAffine(card, affine, (660, 660), flags=cv2.INTER_LINEAR)
        mask = np.zeros((660, 660), dtype=np.uint8)
        cv2.fillPoly(mask, [np.rint(moved).astype(np.int32)], 255)
        frame[mask > 0] = warped[mask > 0]
        pieces.append({"points": moved})
        expected[index] = polygon
    return frame, pieces, expected


def _pose_error(layout, expected):
    # Fit a single proper rotation using anchor labels; apply it to every
    # labelled fragment. Coverage alone cannot pass an identity/rotation swap.
    source, target = expected[0], layout[0]
    source_center, target_center = np.mean(source, axis=0), np.mean(target, axis=0)
    first, _, second = np.linalg.svd((source - source_center).T @ (target - target_center))
    rotation = second.T @ first.T
    if np.linalg.det(rotation) < 0:
        second[-1] *= -1
        rotation = second.T @ first.T
    return max(float(np.max(np.linalg.norm(
        (expected[index] - source_center) @ rotation.T + target_center - layout[index], axis=1)))
        for index in expected)


def _assert_rigid(pieces, candidate):
    for index, piece in enumerate(pieces):
        source = np.asarray(piece["points"])
        target = candidate["layout"][index]
        distances = np.linalg.norm(source[:, None] - source[None, :], axis=2)
        target_distances = np.linalg.norm(target[:, None] - target[None, :], axis=2)
        assert np.max(np.abs(distances - target_distances)) < 1e-5
        source_area = cv2.contourArea(source.astype(np.float32), oriented=True)
        target_area = cv2.contourArea(target.astype(np.float32), oriented=True)
        assert source_area * target_area > 0, "reflection or changed vertex correspondence"
    report = candidate["report"]
    assert report["coverage"] >= 0.80 and report["overlap"] <= 0.025
    assert report["outer_piece_ratio"] == 1 and report["aspect"] <= 2.45


def main():
    fixtures = {
        "same-triangles": [
            [(0, 0), (160, 0), (0, 100)],
            [(160, 0), (160, 100), (0, 100)],
        ],
        "same-trapezoids": [
            [(0, 0), (60, 0), (100, 100), (0, 100)],
            [(60, 0), (160, 0), (160, 100), (100, 100)],
        ],
        "three-piece-T": [
            [(0, 0), (80, 0), (80, 100), (0, 100)],
            [(80, 0), (160, 0), (160, 50), (80, 50)],
            [(80, 50), (160, 50), (160, 100), (80, 100)],
        ],
        "four-mixed-pieces": [
            [(0, 0), (80, 0), (80, 100), (0, 100)],
            [(80, 0), (160, 0), (120, 50), (80, 50)],
            [(160, 0), (160, 100), (120, 50)],
            [(80, 50), (120, 50), (160, 100), (80, 100)],
        ],
    }
    for name, polygons in fixtures.items():
        frame, pieces, expected = _scene(polygons, clockwise=True)
        result = generate_card_graph_candidates(frame, pieces, time_limit_s=12.0, candidate_limit=96)
        assert result["candidates"], (name, result)
        for candidate in result["candidates"]:
            _assert_rigid(pieces, candidate)
            assert candidate["source"] == "card-graph-texture"
        correct = [item for item in result["candidates"] if _pose_error(item["layout"], expected) < 0.5]
        assert correct, (name, "expected labelled identities and orientations missing")
        assert max(item["texture"]["confidence"] for item in correct) > 0.05, name
        if name == "three-piece-T":
            assert len(correct[0]["report"]["adjacencies"]) >= 3

    frame, pieces, expected = _scene([
        [(0, 0), (80, 0), (80, 100), (0, 100)],
        [(80, 0), (160, 0), (160, 100), (80, 100)],
    ], blank=True)
    blank = generate_card_graph_candidates(frame, pieces, time_limit_s=8.0, candidate_limit=96)
    assert len(blank["candidates"]) >= 2, "blank texture must retain orientation ambiguity"
    assert any(_pose_error(item["layout"], expected) < 0.5 for item in blank["candidates"])
    assert max(item["texture"]["confidence"] for item in blank["candidates"]) < 0.05
    # A zero budget and truncated beams cannot claim an exhaustive search.
    timed_out = generate_card_graph_candidates(frame, pieces, time_limit_s=0.0)
    assert timed_out["search_complete"] is False and timed_out["candidates"] == []
    malformed = [{"points": [[0, 0], [1, 0], [float("nan"), 1]]}, pieces[1]]
    assert generate_card_graph_candidates(frame, malformed)["search_complete"] is False
    print("card_graph_self_test: OK")


if __name__ == "__main__":
    main()
