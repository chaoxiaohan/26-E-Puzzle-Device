import math

import cv2
import numpy as np

from card_face_solver import render_layout_preview, solve_card_face


def transform_points(points, angle, center):
    radians = math.radians(angle)
    cosine = math.cos(radians)
    sine = math.sin(radians)
    rotation = np.array(
        [[cosine, -sine], [sine, cosine]],
        dtype=np.float32,
    )
    local_center = np.mean(points, axis=0)
    return (
        (points - local_center) @ rotation.T
        + np.asarray(center, dtype=np.float32)
    )


def main():
    card = np.full((160, 250, 3), 245, dtype=np.uint8)
    cv2.line(card, (18, 20), (232, 142), (170, 20, 25), 11)
    cv2.line(card, (25, 135), (218, 28), (15, 20, 20), 8)
    cv2.circle(card, (125, 80), 34, (190, 15, 30), 7)
    cv2.putText(
        card,
        "K",
        (94, 105),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.7,
        (10, 10, 10),
        5,
        cv2.LINE_AA,
    )

    source_polygons = [
        np.array([[0, 0], [125, 0], [125, 80], [0, 80]], np.float32),
        np.array([[125, 0], [250, 0], [250, 80], [125, 80]], np.float32),
        np.array([[0, 80], [125, 80], [125, 160], [0, 160]], np.float32),
        np.array([[125, 80], [250, 80], [250, 160], [125, 160]], np.float32),
    ]
    poses = [
        (-17.0, (110, 115)),
        (28.0, (350, 105)),
        (104.0, (115, 330)),
        (-73.0, (350, 325)),
    ]
    frame = np.full((450, 470, 3), 35, dtype=np.uint8)
    pieces = []

    for polygon, pose in zip(source_polygons, poses):
        transformed = transform_points(polygon, pose[0], pose[1])
        source_center = np.mean(polygon, axis=0)
        target_center = np.asarray(pose[1], dtype=np.float32)
        radians = math.radians(pose[0])
        affine = np.array(
            [
                [
                    math.cos(radians),
                    -math.sin(radians),
                    target_center[0]
                    - math.cos(radians) * source_center[0]
                    + math.sin(radians) * source_center[1],
                ],
                [
                    math.sin(radians),
                    math.cos(radians),
                    target_center[1]
                    - math.sin(radians) * source_center[0]
                    - math.cos(radians) * source_center[1],
                ],
            ],
            dtype=np.float32,
        )
        warped = cv2.warpAffine(
            card,
            affine,
            (frame.shape[1], frame.shape[0]),
            flags=cv2.INTER_LINEAR,
        )
        mask = np.zeros(frame.shape[:2], dtype=np.uint8)
        cv2.fillPoly(mask, [np.rint(transformed).astype(np.int32)], 255)
        frame[mask > 0] = warped[mask > 0]
        points = [
            (int(round(point[0])), int(round(point[1])))
            for point in transformed
        ]
        pieces.append(
            {
                "points": points,
                "center": tuple(
                    np.rint(np.mean(transformed, axis=0)).astype(int)
                ),
                "area": abs(cv2.contourArea(transformed)),
                "angle": pose[0],
                "longest_edge": (points[0], points[1]),
                "solidity": 1.0,
            }
        )

    result = solve_card_face(
        frame,
        pieces,
        node_limit=120000,
        time_limit_s=5.0,
    )
    assert result["layout"] is not None, result
    assert result["info"]["overlap"] <= 0.015, result["info"]
    assert result["info"]["coverage"] >= 0.95, result["info"]
    assert result["info"]["texture_score"] >= 0.60, result["info"]
    centers = {
        piece_id: np.mean(polygon, axis=0)
        for piece_id, polygon in result["layout"].items()
    }
    distances = sorted(
        (
            float(np.linalg.norm(centers[first] - centers[second])),
            frozenset((first, second)),
        )
        for first in centers
        for second in centers
        if first < second
    )
    diagonal_pairs = {item[1] for item in distances[-2:]}
    assert diagonal_pairs == {
        frozenset((0, 3)),
        frozenset((1, 2)),
    }, diagonal_pairs
    preview = render_layout_preview(
        frame,
        pieces,
        result["layout"],
    )
    assert preview is not None
    assert max(preview.shape[:2]) == 640, preview.shape
    assert np.count_nonzero(
        np.any(preview != 48, axis=2)
    ) > 1000
    print(
        "CARD_FACE_OK score=%.3f texture=%.3f confidence=%.3f "
        "coverage=%.3f nodes=%d best_at=%d time=%.1fms"
        % (
            result["score"],
            result["info"]["texture_score"],
            result["info"]["texture_confidence"],
            result["info"]["coverage"],
            result["nodes"],
            result["info"]["best_at_node"],
            result["elapsed_ms"],
        )
    )


if __name__ == "__main__":
    main()
