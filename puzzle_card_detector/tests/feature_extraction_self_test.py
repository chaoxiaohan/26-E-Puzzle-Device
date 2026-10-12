# -*- coding: utf-8 -*-

import cv2
import numpy as np

from main import (
    approximate_piece_polygon,
    build_stable_piece_set,
    detect_pieces,
    refine_polygon_corners,
)


def test_green_background():
    frame = np.full((300, 420, 3), (28, 155, 48), dtype=np.uint8)
    polygon = np.array(
        [[95, 70], [245, 58], [278, 188], [118, 205]],
        dtype=np.int32,
    )
    cv2.fillPoly(frame, [polygon], (245, 245, 240))
    cv2.line(frame, (155, 65), (145, 201), (8, 8, 8), 18)
    cv2.circle(frame, (215, 125), 24, (205, 20, 35), thickness=-1)

    pieces, info = detect_pieces(
        frame,
        (0, 0, frame.shape[1], frame.shape[0]),
        min_area=1000,
        max_area_ratio=0.45,
        polygon_epsilon=0.022,
        background_mode="GREEN",
    )
    assert info["polarity"] == "GREEN", info
    assert len(pieces) == 1, pieces
    assert len(pieces[0]["points"]) == 4, pieces[0]["points"]


def test_green_background_with_moving_shadow():
    height = 420
    width = 520
    polygons = [
        np.array([[65, 65], [175, 55], [188, 125], [78, 140]]),
        np.array([[300, 55], [405, 75], [390, 150], [285, 135]]),
        np.array([[85, 235], [205, 220], [230, 315], [110, 330]]),
        np.array([[315, 230], [420, 215], [445, 315], [335, 335]]),
    ]
    centers = []
    for shadow_x in (80, 140, 200, 260, 320):
        frame = np.full((height, width, 3), (24, 112, 49), dtype=np.uint8)
        gradient = np.linspace(0.72, 1.18, width, dtype=np.float32)
        frame = np.clip(
            frame.astype(np.float32) * gradient[None, :, None],
            0,
            255,
        ).astype(np.uint8)
        for polygon in polygons:
            cv2.fillPoly(frame, [polygon], (242, 242, 236))
        cv2.circle(frame, (135, 98), 12, (180, 20, 35), thickness=-1)
        cv2.line(frame, (350, 235), (390, 325), (10, 10, 10), 10)

        shadow = np.zeros((height, width), dtype=np.uint8)
        cv2.ellipse(
            shadow,
            (shadow_x, 205),
            (115, 250),
            -12,
            0,
            360,
            255,
            thickness=-1,
        )
        frame[shadow > 0] = np.clip(
            frame[shadow > 0].astype(np.float32) * 0.38,
            0,
            255,
        ).astype(np.uint8)

        pieces, info = detect_pieces(
            frame,
            (0, 0, width, height),
            min_area=1800,
            max_area_ratio=0.20,
            polygon_epsilon=0.018,
            threshold=130,
            polarity_mode="AUTO",
            background_mode="GREEN",
            green_method="largest",
            green_hue_min=55,
            green_hue_max=90,
            green_sat_min=77,
            green_val_min=12,
            green_close_kernel=1,
            green_close_iter=0,
            paper_close_kernel=1,
            paper_close_iter=0,
        )
        assert info["polarity"] == "GREEN", info
        assert len(pieces) == 4, (shadow_x, pieces)
        centers.append(
            np.asarray(
                sorted(piece["center"] for piece in pieces),
                dtype=np.float32,
            )
        )

    center_spread = np.max(np.ptp(np.stack(centers), axis=0))
    assert center_spread <= 2.0, center_spread


def test_line_refinement():
    mask = np.zeros((260, 360), dtype=np.uint8)
    expected = np.array(
        [[70, 55], [270, 72], [250, 205], [55, 185]],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [expected], 255)
    cv2.rectangle(mask, (155, 57), (164, 63), 0, thickness=-1)
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    contour = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(contour, True)
    initial = cv2.approxPolyDP(contour, 0.022 * perimeter, True)
    refined = refine_polygon_corners(contour, initial)

    assert len(refined) == 4, refined
    for index, start in enumerate(refined.reshape(-1, 2)):
        end = refined.reshape(-1, 2)[(index + 1) % 4]
        assert np.linalg.norm(end - start) > 100

    shifted = expected + np.array(
        [[5, -4], [-4, 5], [5, 4], [-5, -4]],
        dtype=np.int32,
    )
    shifted = shifted.reshape(-1, 1, 2)
    corrected = refine_polygon_corners(contour, shifted).reshape(-1, 2)
    initial_error = float(
        np.mean(np.linalg.norm(shifted.reshape(-1, 2) - expected, axis=1))
    )
    corrected_error = float(
        np.mean(np.linalg.norm(corrected - expected, axis=1))
    )
    assert corrected_error < initial_error * 0.45, (
        initial_error,
        corrected_error,
        corrected,
    )


def test_adaptive_polygon_approximation():
    mask = np.zeros((280, 380), dtype=np.uint8)
    expected = np.array(
        [[55, 65], [315, 78], [290, 220], [70, 205]],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [expected], 255)
    for x in range(90, 290, 24):
        cv2.circle(mask, (x, 70 + (x - 55) * 13 // 260), 3, 0, -1)
    contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    contour = max(contours, key=cv2.contourArea)
    polygon = approximate_piece_polygon(contour, 0.012)
    assert polygon is not None
    assert len(polygon) == 4, polygon
    area_ratio = abs(cv2.contourArea(polygon)) / abs(cv2.contourArea(contour))
    assert area_ratio >= 0.94, area_ratio

    pentagon_mask = np.zeros((280, 380), dtype=np.uint8)
    pentagon = np.array(
        [[45, 105], [175, 40], [325, 100], [285, 225], [75, 220]],
        dtype=np.int32,
    )
    cv2.fillPoly(pentagon_mask, [pentagon], 255)
    contours, _ = cv2.findContours(
        pentagon_mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    contour = max(contours, key=cv2.contourArea)
    polygon = approximate_piece_polygon(contour, 0.015)
    assert polygon is not None
    assert len(polygon) == 5, polygon


def test_temporal_corner_stability():
    first = np.array([[40, 40], [140, 42], [138, 115], [42, 112]])
    second = np.array([[210, 55], [310, 58], [305, 132], [208, 128]])

    def piece(points):
        points = np.asarray(points, dtype=np.int32)
        center = tuple(np.rint(np.mean(points, axis=0)).astype(int))
        return {
            "points": [tuple(point) for point in points],
            "center": center,
            "area": abs(float(cv2.contourArea(points))),
            "angle": 0.0,
            "longest_edge": (tuple(points[0]), tuple(points[1])),
            "solidity": 1.0,
        }

    recent = []
    for index, shift in enumerate((-1, 1, 0, 1, -1)):
        pieces = [
            piece(first + (shift, 0)),
            piece(second + (0, -shift)),
        ]
        recent.append((float(index), 1.0, pieces))
    outlier = np.vstack([first, [[88, 37]]])
    recent.append((6.0, 1.0, [piece(outlier), piece(second)]))

    stable = build_stable_piece_set(recent)
    assert stable is not None
    assert [len(item["points"]) for item in stable] == [4, 4], stable
    assert np.max(np.abs(np.asarray(stable[0]["points"]) - first)) <= 1


def test_touching_piece_separation():
    frame = np.zeros((280, 420, 3), dtype=np.uint8)
    first = np.array(
        [[65, 65], [205, 70], [190, 155], [75, 170]],
        dtype=np.int32,
    )
    second = np.array(
        [[205, 70], [340, 92], [325, 205], [225, 190]],
        dtype=np.int32,
    )
    cv2.fillPoly(frame, [first, second], (245, 245, 245))

    pieces, _ = detect_pieces(
        frame,
        (0, 0, frame.shape[1], frame.shape[0]),
        min_area=1000,
        max_area_ratio=0.40,
        polygon_epsilon=0.022,
        threshold=100,
        polarity_mode="LIGHT",
        background_mode="BLACK",
    )
    assert len(pieces) == 2, pieces


if __name__ == "__main__":
    test_green_background()
    test_green_background_with_moving_shadow()
    test_line_refinement()
    test_adaptive_polygon_approximation()
    test_temporal_corner_stability()
    test_touching_piece_separation()
    print("feature extraction OK")
