# -*- coding: utf-8 -*-

import cv2
import numpy as np

from main import detect_pieces, refine_polygon_corners


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


if __name__ == "__main__":
    test_green_background()
    test_line_refinement()
    print("feature extraction OK")
