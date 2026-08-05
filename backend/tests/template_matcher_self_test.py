import math

import cv2
import numpy as np

from template_matcher import (
    _best_polygon_rotation,
    align_layout_to_horizontal,
    learn_templates,
    match_templates,
)


def piece(points):
    points = np.asarray(points, dtype=np.float64)
    center = np.mean(points, axis=0)
    return {
        "points": points.tolist(),
        "center": center.tolist(),
        "area": abs(float(cv2.contourArea(points.astype(np.float32)))),
    }


def draw_piece(frame, points, pattern):
    points = np.rint(points).astype(np.int32)
    cv2.fillPoly(frame, [points], (245, 245, 245))
    x, y, width, height = cv2.boundingRect(points)
    if pattern == "vertical":
        cv2.rectangle(
            frame,
            (x + width // 4, y + 4),
            (x + width // 4 + 10, y + height - 5),
            (20, 20, 20),
            -1,
        )
    else:
        cv2.rectangle(
            frame,
            (x + 4, y + height // 3),
            (x + width - 5, y + height // 3 + 10),
            (20, 20, 20),
            -1,
        )


roi = (100, 200, 400, 300)
template_frame = np.full((300, 400, 3), (45, 175, 80), dtype=np.uint8)
template_local = [
    np.asarray([(40, 40), (120, 40), (120, 90), (40, 90)], dtype=np.float64),
    np.asarray([(220, 150), (300, 150), (300, 200), (220, 200)], dtype=np.float64),
]
for polygon, pattern in zip(template_local, ("vertical", "horizontal")):
    draw_piece(template_frame, polygon, pattern)
template_pieces = [
    piece(polygon + np.asarray(roi[:2]))
    for polygon in template_local
]
templates = learn_templates(template_frame, template_pieces, roi)
if len(templates) != 2:
    raise RuntimeError("template learning failed")

detected_frame = np.full((300, 400, 3), (45, 175, 80), dtype=np.uint8)
detected_local = [
    np.asarray([(40, 180), (120, 180), (120, 230), (40, 230)], dtype=np.float64),
    np.asarray([(220, 30), (300, 30), (300, 80), (220, 80)], dtype=np.float64),
]
draw_piece(detected_frame, detected_local[0], "horizontal")
draw_piece(detected_frame, detected_local[1], "vertical")
detected_pieces = [
    piece(polygon + np.asarray(roi[:2]))
    for polygon in detected_local
]
layout, assignments = match_templates(
    detected_frame,
    detected_pieces,
    templates,
    roi,
)
assignment_map = {
    detected_id: template_id
    for detected_id, template_id, _ in assignments
}
if layout is None or assignment_map != {0: 1, 1: 0}:
    raise RuntimeError("texture assignment failed: %s" % assignments)

template_polygon = np.asarray(
    [(150, 250), (260, 250), (240, 320), (170, 300)],
    dtype=np.float64,
)
template_frame = np.full((300, 400, 3), (45, 175, 80), dtype=np.uint8)
draw_piece(template_frame, template_polygon - np.asarray(roi[:2]), "vertical")
single_template = learn_templates(
    template_frame,
    [piece(template_polygon)],
    roi,
)
center = np.mean(template_polygon, axis=0)
angle = math.radians(32.0)
rotation = np.asarray(
    [
        [math.cos(angle), -math.sin(angle)],
        [math.sin(angle), math.cos(angle)],
    ],
    dtype=np.float64,
)
detected_polygon = (
    (template_polygon - center) @ rotation.T
    + np.asarray([360.0, 390.0])
)
detected_frame = np.full((300, 400, 3), (45, 175, 80), dtype=np.uint8)
draw_piece(detected_frame, detected_polygon - np.asarray(roi[:2]), "vertical")
layout, assignments = match_templates(
    detected_frame,
    [piece(detected_polygon)],
    single_template,
    roi,
)
if layout is None:
    raise RuntimeError("rotated template did not match: %s" % assignments)
aligned = np.asarray(layout[0], dtype=np.float64)
error = float(np.mean(np.linalg.norm(aligned - template_polygon, axis=1)))
if error > 0.2:
    raise RuntimeError("rotation direction is wrong: %.3fpx" % error)

if match_templates(
    detected_frame,
    [piece(detected_polygon), piece(detected_polygon)],
    single_template,
    roi,
)[0] is not None:
    raise RuntimeError("piece-count mismatch was accepted")

base_layout = {
    0: np.asarray([(20, 30), (120, 30), (120, 80), (20, 80)], dtype=np.float64),
    1: np.asarray([(120, 30), (220, 30), (220, 80), (120, 80)], dtype=np.float64),
}
base_center = np.asarray([120.0, 55.0])
tilt_angle = math.radians(7.0)
tilt_rotation = np.asarray([
    [math.cos(tilt_angle), -math.sin(tilt_angle)],
    [math.sin(tilt_angle), math.cos(tilt_angle)],
])
tilted_layout = {
    piece_id: (polygon - base_center) @ tilt_rotation.T + base_center
    for piece_id, polygon in base_layout.items()
}
before_distance = np.linalg.norm(
    np.mean(tilted_layout[0], axis=0) - np.mean(tilted_layout[1], axis=0)
)
straight_layout, measured_tilt = align_layout_to_horizontal(tilted_layout)
after_distance = np.linalg.norm(
    np.mean(straight_layout[0], axis=0) - np.mean(straight_layout[1], axis=0)
)
edge = straight_layout[0][1] - straight_layout[0][0]
straight_angle = math.degrees(math.atan2(edge[1], edge[0]))
if abs(straight_angle) > 0.05:
    raise RuntimeError("layout was not straightened: %.3fdeg" % straight_angle)
if abs(before_distance - after_distance) > 1e-6:
    raise RuntimeError("layout alignment changed relative positions")
if abs(measured_tilt - 7.0) > 0.05:
    raise RuntimeError("layout tilt measurement is wrong: %.3fdeg" % measured_tilt)

almost_square = np.asarray(
    [(0.0, 0.0), (100.0, 0.0), (101.0, 99.0), (0.0, 100.0)],
    dtype=np.float64,
)
square_center = np.mean(almost_square, axis=0)
square_angle = math.radians(37.0)
square_rotation = np.asarray([
    [math.cos(square_angle), -math.sin(square_angle)],
    [math.sin(square_angle), math.cos(square_angle)],
])
square_source = (
    (almost_square - square_center) @ square_rotation.T
    + np.asarray([250.0, 180.0])
)
pose_rotation, pose_error = _best_polygon_rotation(
    square_source,
    almost_square,
)
pose_aligned = (
    (square_source - np.mean(square_source, axis=0)) @ pose_rotation.T
    + np.mean(almost_square, axis=0)
)
pose_rms = float(
    np.mean(np.linalg.norm(pose_aligned - almost_square, axis=1))
)
if pose_error > 0.01 or pose_rms > 0.1:
    raise RuntimeError(
        "near-square Procrustes pose is unstable: %.4f %.4f"
        % (pose_error, pose_rms)
    )

print("TEMPLATE_MATCHER_OK assignments=%s rotation_error=%.3fpx "
      "tilt=%.3fdeg pose=%.4fpx" % (
    assignment_map,
    error,
    measured_tilt,
    pose_rms,
))
