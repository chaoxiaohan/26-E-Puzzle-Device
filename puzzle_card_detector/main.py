# -*- coding: utf-8 -*-

import concurrent.futures
import copy
import itertools
import json
import math
import multiprocessing
import os
import subprocess
import time

import cv2
import numpy as np
from maix import app, camera, display, image, touchscreen
from hardware_devices import camera_device
from layout_constraints import (
    add_adjacency_gap,
    evaluate_layout,
    repair_layout_for_competition,
)
from cpp_rectangle_solver import solve as solve_rectangle_by_cover_cpp
from card_face_solver import (
    close_card_pattern_layout,
    generate_all_slot_layouts,
    generate_shape_swap_layouts,
    render_layout_preview,
    score_layout_global_pattern,
    score_rank_index_diagonal,
    score_layout_texture,
    solve_card_face,
)
from card_topology_solver import (
    classify_card_pieces,
    generate_rectangle_grid_hypotheses,
)
from card_joint_solver import generate_rectangular_card_candidates, layout_pose_key, relative_texture_matches
from card_graph_solver import generate_card_graph_candidates
from card_structure import score_layout_structure
from card_corner_solver import generate_corner_card_candidates
from card_fan_solver import generate_fan_card_candidates
from card_piece_geometry import refine_card_piece_geometry
from card_strip_solver import generate_strip_card_candidates
from puzzle_solver import normalize_layout, solve_camera_rectangle
from serial_protocol import SerialController
from solver_v2 import solve as solve_edge_layout
from template_matcher import (
    align_layout_to_horizontal,
    learn_templates,
    load_templates,
    match_templates,
    save_templates,
)
from ui_bridge import UiBridge


class RecoveringCamera:
    """相机暂时离线时保留进程，并按间隔自动重新打开。"""

    def __init__(self, factory, recover=None):
        self.factory = factory
        self.recover = recover
        self.device = None
        self.online = False
        self.next_retry_at = 0.0
        self.next_hard_recovery_at = 0.0
        self.failure_count = 0
        self.hard_recovery_count = 0
        self.last_error = ""

    def _close_device(self):
        if self.device is None:
            return
        try:
            close = getattr(self.device, "close", None)
            if close is not None:
                close()
            elif hasattr(self.device, "capture"):
                self.device.capture.release()
        except Exception:
            pass
        self.device = None

    @staticmethod
    def _frame_is_usable(frame):
        if frame is None:
            return False
        width = getattr(frame, "width", None)
        height = getattr(frame, "height", None)
        if not callable(width) or not callable(height):
            return True
        try:
            return int(width()) > 0 and int(height()) > 0
        except Exception:
            return False

    def _record_failure(self, error, now):
        self.last_error = str(error)
        self.online = False
        self.failure_count += 1
        self._close_device()
        self.next_retry_at = now + 0.8
        if (
            self.recover is None
            or self.failure_count < 3
            or now < self.next_hard_recovery_at
        ):
            return
        try:
            recovered = bool(self.recover())
        except Exception as recovery_error:
            self.last_error = "%s; reset: %s" % (
                self.last_error,
                recovery_error,
            )
            recovered = False
        self.next_hard_recovery_at = now + 8.0
        if recovered:
            self.hard_recovery_count += 1
            self.failure_count = 0
            self.next_retry_at = now + 1.2

    def read(self, now=None):
        now = time.monotonic() if now is None else float(now)
        if self.device is None:
            if now < self.next_retry_at:
                return None
            try:
                self.device = self.factory()
            except Exception as error:
                self._record_failure(error, now)
                return None

        try:
            frame = self.device.read()
        except Exception as error:
            self._record_failure(error, now)
            return None

        if not self._frame_is_usable(frame):
            self._record_failure("empty camera frame", now)
            return None

        self.online = True
        self.failure_count = 0
        self.last_error = ""
        return frame

    def close(self):
        self.online = False
        self._close_device()


def reset_usb_video_device(video_device=None):
    """只复位指定 video 节点所属的 USB 设备，不影响 CH340 等其他 USB。"""
    if video_device is None:
        try:
            video_device = camera_device()
        except RuntimeError:
            return False
    device_path = os.path.realpath(
        "/sys/class/video4linux/%s/device"
        % os.path.basename(video_device)
    )
    current = device_path
    authorized = ""
    for _ in range(8):
        candidate = os.path.join(current, "authorized")
        if (
            os.path.isfile(candidate)
            and os.path.isfile(os.path.join(current, "idVendor"))
            and os.path.isfile(os.path.join(current, "idProduct"))
        ):
            authorized = candidate
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    if not authorized or not current.startswith("/sys/devices/"):
        return False

    for value in (b"0\n", b"1\n"):
        result = subprocess.run(
            ["sudo", "-n", "tee", authorized],
            input=value,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=3.0,
            check=False,
        )
        if result.returncode != 0:
            return False
        if value == b"0\n":
            time.sleep(0.45)
    print("CAMERA_USB_RESET %s" % current, flush=True)
    return True


def longest_edge(points):
    """返回多边形最长边及其相对图像水平向右方向的角度。"""
    best_start = points[0]
    best_end = points[1]
    best_length = 0.0

    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = dx * dx + dy * dy
        if length > best_length:
            best_start = start
            best_end = end
            best_length = length

    angle = math.degrees(
        math.atan2(best_end[1] - best_start[1], best_end[0] - best_start[0])
    )
    if angle >= 90:
        angle -= 180
    elif angle < -90:
        angle += 180

    return (best_start, best_end), angle


def intersect_fitted_lines(first, second):
    """计算两条拟合直线的交点，近平行时返回None。"""
    first_point, first_direction = first
    second_point, second_direction = second
    cross = (
        first_direction[0] * second_direction[1]
        - first_direction[1] * second_direction[0]
    )
    if abs(cross) < 1e-5:
        return None
    delta = second_point - first_point
    distance = (
        delta[0] * second_direction[1]
        - delta[1] * second_direction[0]
    ) / cross
    return first_point + first_direction * distance


def refine_polygon_corners(contour, polygon):
    """用原始轮廓逐边拟合直线，再以相邻直线交点精修角点。"""
    contour_points = contour.reshape(-1, 2).astype(np.float32)
    vertices = polygon.reshape(-1, 2).astype(np.float32)
    edge_count = len(vertices)
    if edge_count < 3 or len(contour_points) < edge_count * 6:
        return polygon

    distances = np.empty(
        (len(contour_points), edge_count),
        dtype=np.float32,
    )
    positions = np.empty_like(distances)
    for edge_index, start in enumerate(vertices):
        end = vertices[(edge_index + 1) % edge_count]
        vector = end - start
        length_squared = float(np.dot(vector, vector))
        if length_squared < 1:
            distances[:, edge_index] = float("inf")
            positions[:, edge_index] = 0
            continue
        position = (contour_points - start) @ vector / length_squared
        projection = start + np.clip(position, 0, 1)[:, None] * vector
        positions[:, edge_index] = position
        distances[:, edge_index] = np.linalg.norm(
            contour_points - projection,
            axis=1,
        )
    assigned_edges = np.argmin(distances, axis=1)

    fitted_lines = []
    for edge_index, start in enumerate(vertices):
        end = vertices[(edge_index + 1) % edge_count]
        edge_length = float(np.linalg.norm(end - start))
        edge_positions = positions[:, edge_index]
        edge_distances = distances[:, edge_index]
        middle_points = contour_points[
            (assigned_edges == edge_index)
            & (edge_positions >= 0.06)
            & (edge_positions <= 0.94)
            & (edge_distances <= max(2.5, edge_length * 0.06))
        ]
        if len(middle_points) < 8:
            middle_points = contour_points[
                (assigned_edges == edge_index)
                & (edge_positions >= -0.03)
                & (edge_positions <= 1.03)
                & (edge_distances <= max(4.0, edge_length * 0.10))
            ]
        if len(middle_points) < 6:
            direction = (end - start) / max(edge_length, 1.0)
            fitted_lines.append(((start + end) * 0.5, direction))
            continue

        points = np.asarray(middle_points, dtype=np.float32)
        vx, vy, x, y = cv2.fitLine(
            points,
            cv2.DIST_HUBER,
            0,
            0.01,
            0.01,
        ).reshape(-1)
        direction = np.array([vx, vy], dtype=np.float32)
        direction /= max(float(np.linalg.norm(direction)), 1e-6)
        if float(np.dot(direction, end - start)) < 0:
            direction = -direction
        line_point = np.array([x, y], dtype=np.float32)
        residuals = np.abs(
            (points[:, 0] - line_point[0]) * direction[1]
            - (points[:, 1] - line_point[1]) * direction[0]
        )
        median_residual = float(np.median(residuals))
        inlier_limit = max(1.25, min(3.0, median_residual * 2.5))
        inliers = points[residuals <= inlier_limit]
        if len(inliers) >= 6 and len(inliers) < len(points):
            vx, vy, x, y = cv2.fitLine(
                inliers,
                cv2.DIST_HUBER,
                0,
                0.01,
                0.01,
            ).reshape(-1)
            direction = np.array([vx, vy], dtype=np.float32)
            direction /= max(float(np.linalg.norm(direction)), 1e-6)
            if float(np.dot(direction, end - start)) < 0:
                direction = -direction
            line_point = np.array([x, y], dtype=np.float32)
            residuals = np.abs(
                (inliers[:, 0] - line_point[0]) * direction[1]
                - (inliers[:, 1] - line_point[1]) * direction[0]
            )

        seed_direction = (end - start) / max(edge_length, 1.0)
        direction_agreement = abs(float(np.dot(direction, seed_direction)))
        median_residual = float(np.median(residuals))
        high_residual = float(np.percentile(residuals, 90))
        if (
            direction_agreement < math.cos(math.radians(12.0))
            or median_residual > max(1.8, edge_length * 0.018)
            or high_residual > max(3.0, edge_length * 0.035)
        ):
            direction = (end - start) / max(edge_length, 1.0)
            line_point = (start + end) * 0.5
        fitted_lines.append((line_point, direction))

    refined = []
    for vertex_index, vertex in enumerate(vertices):
        intersection = intersect_fitted_lines(
            fitted_lines[(vertex_index - 1) % edge_count],
            fitted_lines[vertex_index],
        )
        if intersection is None:
            return polygon
        previous_length = float(
            np.linalg.norm(
                vertex - vertices[(vertex_index - 1) % edge_count]
            )
        )
        next_length = float(
            np.linalg.norm(
                vertices[(vertex_index + 1) % edge_count] - vertex
            )
        )
        allowed_shift = max(
            5.0,
            min(18.0, min(previous_length, next_length) * 0.18),
        )
        if float(np.linalg.norm(intersection - vertex)) > allowed_shift:
            return polygon
        refined.append(intersection)

    refined = np.asarray(refined, dtype=np.float32).reshape(-1, 1, 2)
    contour_area = abs(float(cv2.contourArea(contour)))
    refined_area = abs(float(cv2.contourArea(refined)))
    if contour_area < 1:
        return polygon
    if not 0.82 <= refined_area / contour_area <= 1.18:
        return polygon
    return np.rint(refined).astype(np.int32)


def approximate_piece_polygon(contour, polygon_epsilon):
    """在邻近简化尺度中选择稳定的3至5边轮廓。"""
    perimeter = cv2.arcLength(contour, True)
    contour_area = abs(float(cv2.contourArea(contour)))
    if perimeter < 1 or contour_area < 1:
        return None

    candidates = []
    signatures = set()
    for scale in (0.82, 0.92, 1.0, 1.10, 1.22, 1.36, 1.52):
        polygon = cv2.approxPolyDP(
            contour,
            polygon_epsilon * scale * perimeter,
            True,
        )
        if len(polygon) < 3 or len(polygon) > 5:
            continue
        points = polygon.reshape(-1, 2).astype(np.float32)
        signature = tuple(map(tuple, np.rint(points).astype(np.int32)))
        if signature in signatures:
            continue
        signatures.add(signature)

        edge_lengths = np.linalg.norm(
            np.roll(points, -1, axis=0) - points,
            axis=1,
        )
        shortest_ratio = float(np.min(edge_lengths)) / perimeter
        area_ratio = abs(float(cv2.contourArea(polygon))) / contour_area
        area_score = 1.0 - abs(1.0 - area_ratio)
        short_edge_penalty = max(0.0, 0.055 - shortest_ratio) * 1.8
        complexity_penalty = max(0, len(points) - 3) * 0.035
        scale_penalty = abs(scale - 1.0) * 0.002
        score = (
            area_score
            - short_edge_penalty
            - complexity_penalty
            - scale_penalty
        )
        candidates.append((score, scale, polygon))

    if not candidates:
        return None
    finalists = []
    for _, scale, polygon in sorted(
        candidates,
        key=lambda item: item[0],
        reverse=True,
    )[:2]:
        polygon = refine_polygon_corners(contour, polygon)
        points = polygon.reshape(-1, 2).astype(np.float32)
        edge_lengths = np.linalg.norm(
            np.roll(points, -1, axis=0) - points,
            axis=1,
        )
        shortest_ratio = float(np.min(edge_lengths)) / perimeter
        area_ratio = abs(float(cv2.contourArea(polygon))) / contour_area
        score = (
            1.0
            - abs(1.0 - area_ratio)
            - max(0.0, 0.055 - shortest_ratio) * 1.8
            - max(0, len(points) - 3) * 0.020
            - abs(scale - 1.0) * 0.002
        )
        finalists.append((score, polygon))
    return max(finalists, key=lambda item: item[0])[1]


def green_background_foreground_mask(roi_rgb):
    """从ROI边缘估计绿色背景，并返回填满内部花纹的碎片掩膜。"""
    hsv = cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2HSV)
    height, width = hsv.shape[:2]
    border_width = max(4, min(height, width) // 45)
    border = np.concatenate(
        [
            hsv[:border_width].reshape(-1, 3),
            hsv[-border_width:].reshape(-1, 3),
            hsv[:, :border_width].reshape(-1, 3),
            hsv[:, -border_width:].reshape(-1, 3),
        ],
        axis=0,
    )
    green_border = border[
        (border[:, 0] >= 25)
        & (border[:, 0] <= 100)
        & (border[:, 1] >= 35)
        & (border[:, 2] >= 12)
    ]
    if len(green_border) < max(40, len(border) // 8):
        return None

    reference_hue = float(np.median(green_border[:, 0]))
    reference_saturation = float(np.median(green_border[:, 1]))
    hue_distance = np.abs(hsv[:, :, 0].astype(np.float32) - reference_hue)
    green = (
        (hue_distance <= 24)
        & (hsv[:, :, 1] >= max(30, reference_saturation * 0.28))
        & (hsv[:, :, 2] >= 8)
    ).astype(np.uint8)
    green = cv2.morphologyEx(
        green,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        iterations=2,
    )

    label_count, labels = cv2.connectedComponents(green, connectivity=8)
    border_labels = np.concatenate(
        [
            labels[:border_width].reshape(-1),
            labels[-border_width:].reshape(-1),
            labels[:, :border_width].reshape(-1),
            labels[:, -border_width:].reshape(-1),
        ]
    )
    counts = np.bincount(border_labels, minlength=label_count)
    connected_labels = np.flatnonzero(counts >= border_width * 2)
    connected_labels = connected_labels[connected_labels != 0]
    if len(connected_labels) == 0:
        return None

    background = np.isin(labels, connected_labels)
    if float(np.mean(background)) < 0.20:
        return None
    foreground = np.where(background, 0, 255).astype(np.uint8)
    # 使用矩形核保留边角，仅闭合细小间隙
    foreground = cv2.morphologyEx(
        foreground,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
        iterations=1,
    )
    contours, _ = cv2.findContours(
        foreground,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    filled = np.zeros_like(foreground)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def green_background_foreground_mask_v2(
    roi_rgb,
    hue_min=30,
    hue_max=95,
    sat_min=20,
    val_min=6,
    green_close_kernel=9,
    green_close_iter=3,
    paper_close_kernel=7,
    paper_close_iter=2,
    exact_thresholds=False,
):
    """使用绿色色度而不是绝对亮度分离深绿色背景。"""
    filtered = cv2.GaussianBlur(roi_rgb, (3, 3), 0)
    hsv = cv2.cvtColor(filtered, cv2.COLOR_RGB2HSV)
    rgb = filtered.astype(np.int32)
    red = rgb[:, :, 0]
    green_channel = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    intensity = red + green_channel + blue + 1
    ratio_green = green_channel * 100 >= intensity * 34
    strong_green = green_channel * 100 >= intensity * 40
    excess_green = (
        (2 * green_channel - red - blue) * 100
        >= intensity * 2
    )

    hue_margin = 0 if exact_thresholds else 10
    lower_hue = max(0, int(hue_min) - hue_margin)
    upper_hue = min(179, int(hue_max) + hue_margin)
    reference_sat_min = (
        max(8, int(sat_min))
        if exact_thresholds
        else max(18, min(60, int(sat_min * 0.45)))
    )
    foreground_sat_min = (
        max(8, int(sat_min))
        if exact_thresholds
        else max(12, min(70, int(sat_min * 0.55)))
    )
    reference_val_min = (
        max(4, int(val_min))
        if exact_thresholds
        else max(4, int(val_min * 0.5))
    )
    hue_valid = (
        (hsv[:, :, 0] >= lower_hue)
        & (hsv[:, :, 0] <= upper_hue)
    )
    reference = (
        hue_valid
        & (hsv[:, :, 1] >= reference_sat_min)
        & (hsv[:, :, 2] >= reference_val_min)
        & ratio_green
        & excess_green
    )
    if np.count_nonzero(reference) < roi_rgb.shape[0] * roi_rgb.shape[1] * 0.02:
        return green_background_foreground_mask(roi_rgb)

    green = (
        hue_valid
        & (hsv[:, :, 2] >= reference_val_min)
        & ratio_green
        & excess_green
        & (
            (
                hsv[:, :, 1] >= foreground_sat_min
            )
            | strong_green
        )
    ).astype(np.uint8) * 255

    green = cv2.medianBlur(green, 3)
    close_size = max(3, int(green_close_kernel))
    if close_size % 2 == 0:
        close_size += 1
    green = cv2.morphologyEx(
        green,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size)),
        iterations=max(1, int(green_close_iter)),
    )

    # 取最大的绿色连通域 = A4纸
    label_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        green, connectivity=8,
    )
    if label_count <= 1:
        return None
    largest_label = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    paper = np.where(labels == largest_label, 255, 0).astype(np.uint8)

    # 填充A4纸内部的空洞
    paper_size = max(3, int(paper_close_kernel))
    if paper_size % 2 == 0:
        paper_size += 1
    paper = cv2.morphologyEx(
        paper,
        cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (paper_size, paper_size)),
        iterations=max(1, int(paper_close_iter)),
    )

    if float(np.mean(paper)) < 0.12:
        return None

    # 非绿色区域 = 碎片前景。
    foreground = np.where(paper > 0, 0, 255).astype(np.uint8)
    foreground = cv2.morphologyEx(
        foreground, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1,
    )
    contours, _ = cv2.findContours(
        foreground, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )
    filled = np.zeros_like(foreground)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def green_background_foreground_mask_auto(
    roi_rgb,
    green_close_kernel=7,
    green_close_iter=2,
    paper_close_kernel=5,
    paper_close_iter=1,
    state=None,
):
    """从当前ROI的主绿色颜色簇自动估计背景范围。"""
    filtered = cv2.GaussianBlur(roi_rgb, (3, 3), 0)
    hsv = cv2.cvtColor(filtered, cv2.COLOR_RGB2HSV)
    rgb = filtered[::3, ::3].astype(np.int32)
    sampled_hsv = hsv[::3, ::3]
    red = rgb[:, :, 0]
    green = rgb[:, :, 1]
    blue = rgb[:, :, 2]
    intensity = red + green + blue + 1
    candidates = (
        (sampled_hsv[:, :, 0] >= 20)
        & (sampled_hsv[:, :, 0] <= 110)
        & (sampled_hsv[:, :, 1] >= 15)
        & (sampled_hsv[:, :, 2] >= 10)
        & (green * 100 >= intensity * 34)
        & ((2 * green - red - blue) * 100 >= intensity * 2)
    )
    candidate_count = int(np.count_nonzero(candidates))
    if candidate_count < max(80, candidates.size // 50):
        return green_background_foreground_mask(roi_rgb), None

    candidate_hue = sampled_hsv[:, :, 0][candidates]
    histogram = np.bincount(candidate_hue, minlength=180).astype(np.float32)
    histogram = np.convolve(
        histogram,
        np.array([1.0, 2.0, 3.0, 2.0, 1.0], dtype=np.float32),
        mode="same",
    )
    hue_center = int(np.argmax(histogram))
    hue_distance = np.abs(candidate_hue.astype(np.int16) - hue_center)
    cluster = hue_distance <= 14
    if int(np.count_nonzero(cluster)) < max(60, candidate_count // 5):
        return green_background_foreground_mask(roi_rgb), None

    cluster_hue = candidate_hue[cluster].astype(np.float32)
    cluster_sat = sampled_hsv[:, :, 1][candidates][cluster].astype(np.float32)
    cluster_val = sampled_hsv[:, :, 2][candidates][cluster].astype(np.float32)
    hue_center = int(round(float(np.median(cluster_hue))))
    hue_spread = float(
        np.percentile(np.abs(cluster_hue - hue_center), 92)
    )
    hue_tolerance = int(np.clip(round(hue_spread + 4.0), 10, 28))
    hue_min = max(0, hue_center - hue_tolerance)
    hue_max = min(179, hue_center + hue_tolerance)
    sat_min = int(np.clip(np.percentile(cluster_sat, 5) * 0.55, 8, 80))
    val_min = int(np.clip(np.percentile(cluster_val, 3) * 0.55, 4, 90))

    current = {
        "hue_min": hue_min,
        "hue_max": hue_max,
        "sat_min": sat_min,
        "val_min": val_min,
    }
    if state is not None:
        if all(key in state for key in current):
            previous_center = (state["hue_min"] + state["hue_max"]) * 0.5
            current_center = (hue_min + hue_max) * 0.5
            if abs(previous_center - current_center) <= 18:
                for key, value in current.items():
                    current[key] = int(round(state[key] * 0.82 + value * 0.18))
        state.update(current)
        hue_min = state["hue_min"]
        hue_max = state["hue_max"]
        sat_min = state["sat_min"]
        val_min = state["val_min"]

    mask = green_background_foreground_mask_v2(
        roi_rgb,
        hue_min=hue_min,
        hue_max=hue_max,
        sat_min=sat_min,
        val_min=val_min,
        green_close_kernel=green_close_kernel,
        green_close_iter=green_close_iter,
        paper_close_kernel=paper_close_kernel,
        paper_close_iter=paper_close_iter,
        exact_thresholds=True,
    )
    return mask, {
        "hue_min": hue_min,
        "hue_max": hue_max,
        "sat_min": sat_min,
        "val_min": val_min,
    }


def split_touching_contour(mask, contour, min_area):
    """用腐蚀后的独立核心把相互接触的碎片重新分开。"""
    component = np.zeros_like(mask)
    cv2.drawContours(
        component,
        [contour],
        -1,
        255,
        thickness=cv2.FILLED,
    )
    core_contours = []
    for iterations in (4, 6, 8, 10):
        cores = cv2.erode(
            component,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
            iterations=iterations,
        )
        found, _ = cv2.findContours(
            cores,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        core_contours = [
            core
            for core in found
            if abs(cv2.contourArea(core))
            >= max(100.0, min_area * 0.20)
        ]
        if 2 <= len(core_contours) <= 4:
            break
    if not 2 <= len(core_contours) <= 4:
        return []

    distances = []
    for core in core_contours:
        core_mask = np.zeros_like(mask)
        cv2.drawContours(
            core_mask,
            [core],
            -1,
            255,
            thickness=cv2.FILLED,
        )
        distances.append(
            cv2.distanceTransform(
                cv2.bitwise_not(core_mask),
                cv2.DIST_L2,
                3,
            )
        )
    owner = np.argmin(np.stack(distances, axis=0), axis=0)

    separated = []
    for core_index in range(len(core_contours)):
        region = np.where(
            (component > 0) & (owner == core_index),
            255,
            0,
        ).astype(np.uint8)
        region_contours, _ = cv2.findContours(
            region,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_NONE,
        )
        if not region_contours:
            return []
        piece_contour = max(region_contours, key=cv2.contourArea)
        if abs(cv2.contourArea(piece_contour)) < min_area:
            return []
        separated.append(piece_contour)
    return separated


def find_candidates(
    mask,
    offset_x,
    offset_y,
    min_area,
    max_area,
    polygon_epsilon,
):
    """从一张二值图中找出可能属于拼图碎片的多边形。"""
    image_height, image_width = mask.shape
    raw_contours, _ = cv2.findContours(
        mask,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_NONE,
    )
    contours = []
    for contour in raw_contours:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(
            contour,
            polygon_epsilon * perimeter,
            True,
        )
        if 3 <= len(polygon) <= 5:
            contours.append(contour)
            continue
        area = abs(cv2.contourArea(contour))
        x, y, width, height = cv2.boundingRect(contour)
        can_split = (
            min_area * 1.6 <= area <= max_area * 2.5
            and x > 2
            and y > 2
            and x + width < image_width - 2
            and y + height < image_height - 2
        )
        split_contours = (
            split_touching_contour(
                mask,
                contour,
                min_area,
            )
            if can_split
            else []
        )
        contours.extend(split_contours or [contour])
    candidates = []

    for contour in contours:
        area = abs(cv2.contourArea(contour))
        if area < min_area or area > max_area:
            continue

        x, y, width, height = cv2.boundingRect(contour)
        if x <= 2 or y <= 2:
            continue
        if x + width >= image_width - 2 or y + height >= image_height - 2:
            continue
        if min(width, height) < 10:
            continue
        if max(width, height) / min(width, height) > 8:
            continue

        perimeter = cv2.arcLength(contour, True)
        if perimeter < 50:
            continue

        polygon = approximate_piece_polygon(contour, polygon_epsilon)
        if polygon is None:
            continue

        polygon_area = abs(cv2.contourArea(polygon))
        if polygon_area < min_area or area / polygon_area < 0.72:
            continue

        hull_area = abs(cv2.contourArea(cv2.convexHull(contour)))
        if hull_area < 1 or area / hull_area < 0.55:
            continue

        moments = cv2.moments(contour)
        if abs(moments["m00"]) < 1:
            continue

        center_x = int(moments["m10"] / moments["m00"]) + offset_x
        center_y = int(moments["m01"] / moments["m00"]) + offset_y
        points = [
            (
                int(point[0][0]) + offset_x,
                int(point[0][1]) + offset_y,
            )
            for point in polygon
        ]
        piece_longest_edge, angle = longest_edge(points)

        candidates.append(
            {
                "points": points,
                "center": (center_x, center_y),
                "area": area,
                "angle": angle,
                "longest_edge": piece_longest_edge,
                "solidity": area / hull_area,
            }
        )

    candidates.sort(key=lambda item: item["area"], reverse=True)
    return candidates


def candidate_set_score(candidates, max_pieces):
    """优先选择包含较大、完整多边形的阈值极性。"""
    selected = candidates[:max_pieces]
    if not selected:
        return 0.0
    return sum(item["area"] * item["solidity"] for item in selected)


def detect_pieces(
    frame_rgb,
    roi,
    min_area=500,
    max_area_ratio=0.35,
    max_pieces=4,
    polygon_epsilon=0.018,
    threshold=None,
    polarity_mode="AUTO",
    background_mode="GREEN",
    green_method="border",
    green_auto=True,
    green_auto_state=None,
    green_hue_min=30,
    green_hue_max=95,
    green_sat_min=20,
    green_val_min=6,
    green_close_kernel=7,
    green_close_iter=2,
    paper_close_kernel=5,
    paper_close_iter=1,
):
    """检测ROI内的拼图碎片。"""
    roi_x, roi_y, roi_width, roi_height = roi
    roi_rgb = frame_rgb[
        roi_y : roi_y + roi_height,
        roi_x : roi_x + roi_width,
    ]
    green_source_rgb = roi_rgb.copy()

    # 光照预处理：Gamma提亮 + CLAHE局部均衡，消除亮暗不均
    hsv = cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2HSV).astype(np.float32)
    v_channel = hsv[:, :, 2] / 255.0
    v_channel = np.power(v_channel, 0.75) * 255.0  # Gamma 提亮暗区
    hsv[:, :, 2] = np.clip(v_channel, 0, 255)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    hsv[:, :, 2] = clahe.apply(hsv[:, :, 2].astype(np.uint8))
    roi_rgb = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2RGB)

    gray = cv2.cvtColor(roi_rgb, cv2.COLOR_RGB2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    if threshold is None:
        threshold_value, bright_mask = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU,
        )
        threshold_mode = "OTSU"
    else:
        threshold_value = min(255, max(0, int(threshold)))
        _, bright_mask = cv2.threshold(
            gray,
            threshold_value,
            255,
            cv2.THRESH_BINARY,
        )
        threshold_mode = "MANUAL"

    dark_mask = cv2.bitwise_not(bright_mask)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    bright_mask = cv2.morphologyEx(
        bright_mask,
        cv2.MORPH_OPEN,
        kernel,
        iterations=1,
    )
    bright_mask = cv2.morphologyEx(
        bright_mask,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2,
    )
    dark_mask = cv2.morphologyEx(
        dark_mask,
        cv2.MORPH_OPEN,
        kernel,
        iterations=1,
    )
    dark_mask = cv2.morphologyEx(
        dark_mask,
        cv2.MORPH_CLOSE,
        kernel,
        iterations=2,
    )

    max_area = roi_width * roi_height * max_area_ratio
    background_mode = background_mode.upper()
    polarity_mode = polarity_mode.upper()
    green_mask = None
    green_auto_values = None
    if background_mode == "GREEN":
        if green_auto:
            green_mask, green_auto_values = (
                green_background_foreground_mask_auto(
                    green_source_rgb,
                    green_close_kernel=green_close_kernel,
                    green_close_iter=green_close_iter,
                    paper_close_kernel=paper_close_kernel,
                    paper_close_iter=paper_close_iter,
                    state=green_auto_state,
                )
            )
        elif green_method == "largest":
            green_mask = green_background_foreground_mask_v2(
                green_source_rgb,
                hue_min=green_hue_min,
                hue_max=green_hue_max,
                sat_min=green_sat_min,
                val_min=green_val_min,
                green_close_kernel=green_close_kernel,
                green_close_iter=green_close_iter,
                paper_close_kernel=paper_close_kernel,
                paper_close_iter=paper_close_iter,
            )
        else:
            green_mask = green_background_foreground_mask(green_source_rgb)
    if green_mask is not None:
        pieces = find_candidates(
            green_mask,
            roi_x,
            roi_y,
            min_area,
            max_area,
            polygon_epsilon,
        )[:max_pieces]
        polarity = "GREEN"
        selected_mask = green_mask
    else:
        bright_candidates = find_candidates(
            bright_mask,
            roi_x,
            roi_y,
            min_area,
            max_area,
            polygon_epsilon,
        )
        dark_candidates = find_candidates(
            dark_mask,
            roi_x,
            roi_y,
            min_area,
            max_area,
            polygon_epsilon,
        )
        if polarity_mode == "LIGHT":
            pieces = bright_candidates[:max_pieces]
            polarity = "LIGHT"
            selected_mask = bright_mask
        elif polarity_mode == "DARK":
            pieces = dark_candidates[:max_pieces]
            polarity = "DARK"
            selected_mask = dark_mask
        elif candidate_set_score(
            bright_candidates,
            max_pieces,
        ) >= candidate_set_score(
            dark_candidates,
            max_pieces,
        ):
            pieces = bright_candidates[:max_pieces]
            polarity = "LIGHT"
            selected_mask = bright_mask
        else:
            pieces = dark_candidates[:max_pieces]
            polarity = "DARK"
            selected_mask = dark_mask

    pieces.sort(key=lambda item: (item["center"][1], item["center"][0]))
    return pieces, {
        "polarity": polarity,
        "polarity_mode": polarity_mode,
        "background_mode": background_mode,
        "green_method": green_method,
        "green_auto": bool(green_auto),
        "green_auto_values": green_auto_values,
        "threshold": int(threshold_value),
        "threshold_mode": threshold_mode,
        "mask": selected_mask,
    }


def polygon_edge_length(polygon, edge_index):
    """计算多边形指定边的长度。"""
    start = polygon[edge_index]
    end = polygon[(edge_index + 1) % len(polygon)]
    return float(np.linalg.norm(end - start))


def normalize_polygon(points):
    """统一多边形顶点方向并把坐标转换为浮点数。"""
    polygon = np.array(points, dtype=np.float32)
    if cv2.contourArea(polygon, oriented=True) < 0:
        polygon = polygon[::-1].copy()
    return polygon


def align_polygon_edge(polygon, edge_index, target_start, target_end):
    """旋转并平移碎片，使指定边与目标边反向贴合。"""
    source_start = polygon[edge_index]
    source_end = polygon[(edge_index + 1) % len(polygon)]
    source_vector = source_end - source_start
    target_vector = target_start - target_end
    source_angle = math.atan2(source_vector[1], source_vector[0])
    target_angle = math.atan2(target_vector[1], target_vector[0])
    angle = target_angle - source_angle

    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotation = np.array(
        [
            [cosine, -sine],
            [sine, cosine],
        ],
        dtype=np.float32,
    )
    source_middle = (source_start + source_end) * 0.5
    target_middle = (target_start + target_end) * 0.5
    return (polygon - source_middle) @ rotation.T + target_middle


def polygon_center(polygon):
    """用顶点平均值计算只用于拼接侧向判断的中心。"""
    return np.mean(polygon, axis=0)


def centers_on_opposite_sides(
    edge_start,
    edge_end,
    first_center,
    second_center,
):
    """公共边两侧必须分别属于两块碎片。"""
    edge = edge_end - edge_start
    first_side = (
        edge[0] * (first_center[1] - edge_start[1])
        - edge[1] * (first_center[0] - edge_start[0])
    )
    second_side = (
        edge[0] * (second_center[1] - edge_start[1])
        - edge[1] * (second_center[0] - edge_start[0])
    )
    return first_side * second_side < 0


def polygons_overlap(first, second):
    """栅格化判断两块碎片是否发生了明显面积重叠。"""
    all_points = np.vstack((first, second))
    minimum = np.floor(np.min(all_points, axis=0)).astype(np.int32) - 3
    maximum = np.ceil(np.max(all_points, axis=0)).astype(np.int32) + 3
    width = int(maximum[0] - minimum[0] + 1)
    height = int(maximum[1] - minimum[1] + 1)
    if width <= 0 or height <= 0:
        return True

    first_mask = np.zeros((height, width), dtype=np.uint8)
    second_mask = np.zeros((height, width), dtype=np.uint8)
    first_points = np.rint(first - minimum).astype(np.int32)
    second_points = np.rint(second - minimum).astype(np.int32)
    cv2.fillPoly(first_mask, [first_points], 255)
    cv2.fillPoly(second_mask, [second_points], 255)

    kernel = np.ones((3, 3), dtype=np.uint8)
    first_mask = cv2.erode(first_mask, kernel, iterations=1)
    second_mask = cv2.erode(second_mask, kernel, iterations=1)
    overlap = cv2.countNonZero(cv2.bitwise_and(first_mask, second_mask))
    smaller_area = min(
        cv2.countNonZero(first_mask),
        cv2.countNonZero(second_mask),
    )
    return overlap > max(12, int(smaller_area * 0.008))


def assembly_quality(layout, length_errors):
    """用真实并集面积、矩形四角和目标比例评价完整拼法。"""
    polygons = list(layout.values())
    all_points = np.vstack(polygons).astype(np.float32)
    rectangle = cv2.minAreaRect(all_points)
    rectangle_width, rectangle_height = rectangle[1]
    if min(rectangle_width, rectangle_height) < 1:
        return -1.0, 0.0, 0.0

    minimum = np.floor(np.min(all_points, axis=0)).astype(np.int32) - 4
    maximum = np.ceil(np.max(all_points, axis=0)).astype(np.int32) + 4
    width = int(maximum[0] - minimum[0] + 1)
    height = int(maximum[1] - minimum[1] + 1)
    union_mask = np.zeros((height, width), dtype=np.uint8)
    summed_piece_area = 0
    for polygon in polygons:
        points = np.rint(polygon - minimum).astype(np.int32)
        piece_mask = np.zeros((height, width), dtype=np.uint8)
        cv2.fillPoly(piece_mask, [points], 255)
        summed_piece_area += cv2.countNonZero(piece_mask)
        cv2.bitwise_or(union_mask, piece_mask, dst=union_mask)

    rectangle_mask = np.zeros((height, width), dtype=np.uint8)
    rectangle_points = np.rint(
        cv2.boxPoints(rectangle) - minimum
    ).astype(np.int32)
    cv2.fillPoly(rectangle_mask, [rectangle_points], 255)
    union_area = cv2.countNonZero(union_mask)
    rectangle_area = cv2.countNonZero(rectangle_mask)
    if rectangle_area < 1:
        return -1.0, 0.0, 0.0

    rectangularity = min(1.0, union_area / rectangle_area)
    overlap_ratio = max(
        0.0,
        (summed_piece_area - union_area) / rectangle_area,
    )

    rectangle_corners = cv2.boxPoints(rectangle)
    corner_tolerance = max(
        5.0,
        math.hypot(rectangle_width, rectangle_height) * 0.035,
    )
    covered_corners = 0
    for corner in rectangle_corners:
        distances = np.linalg.norm(all_points - corner, axis=1)
        if float(np.min(distances)) <= corner_tolerance:
            covered_corners += 1
    corner_score = covered_corners / 4.0

    aspect_ratio = max(rectangle_width, rectangle_height) / min(
        rectangle_width,
        rectangle_height,
    )
    target_ratio = 10.0 / 6.0
    ratio_score = math.exp(
        -abs(math.log(max(0.01, aspect_ratio / target_ratio)))
    )
    mean_length_error = (
        sum(length_errors) / len(length_errors)
        if length_errors
        else 0.0
    )
    score = (
        rectangularity * 0.70
        + corner_score * 0.16
        + ratio_score * 0.14
        - overlap_ratio * 0.35
        - mean_length_error * 0.05
    )
    return score, rectangularity, corner_score


def assembly_score(layout, length_errors):
    """保留单分数接口，便于合成测试和调试。"""
    return assembly_quality(layout, length_errors)[0]


def solve_rectangle(pieces):
    """
    枚举完整公共边和长边分段公共边，返回最佳矩形布局。

    这里只允许旋转和平移碎片，不进行镜像或单块缩放。
    """
    if len(pieces) < 2 or len(pieces) > 4:
        return None, 0.0, 0

    source_polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    best_layout = None
    best_score = -1.0
    best_rectangularity = 0.0
    best_corner_score = 0.0
    total_nodes = 0

    def search(placed, remaining, edge_usage, length_errors):
        nonlocal best_layout
        nonlocal best_score
        nonlocal best_rectangularity
        nonlocal best_corner_score
        nonlocal total_nodes

        if total_nodes >= 12000:
            return
        if (
            best_score >= 0.965
            and best_rectangularity >= 0.94
            and best_corner_score >= 0.99
        ):
            return

        total_nodes += 1
        if not remaining:
            score, rectangularity, corner_score = assembly_quality(
                placed,
                length_errors,
            )
            if score > best_score:
                best_score = score
                best_rectangularity = rectangularity
                best_corner_score = corner_score
                best_layout = {
                    piece_id: polygon.copy()
                    for piece_id, polygon in placed.items()
                }
            return

        branches = []
        generated = set()
        for placed_id, placed_polygon in tuple(placed.items()):
            placed_center = polygon_center(placed_polygon)
            for placed_edge in range(len(placed_polygon)):
                usage = edge_usage.get((placed_id, placed_edge), set())
                if "FULL" in usage or (
                    "START" in usage
                    and "CENTER" in usage
                    and "END" in usage
                ):
                    continue

                target_start = placed_polygon[placed_edge]
                target_end = placed_polygon[
                    (placed_edge + 1) % len(placed_polygon)
                ]
                target_vector = target_end - target_start
                target_length = float(np.linalg.norm(target_vector))
                if target_length < 8:
                    continue
                target_unit = target_vector / target_length

                for new_id in tuple(remaining):
                    source_polygon = source_polygons[new_id]
                    for source_edge in range(len(source_polygon)):
                        source_length = polygon_edge_length(
                            source_polygon,
                            source_edge,
                        )
                        if source_length < 8:
                            continue

                        length_error = abs(
                            source_length - target_length
                        ) / max(source_length, target_length)
                        options = []
                        if not usage and length_error <= 0.16:
                            options.append(
                                (
                                    "FULL",
                                    target_start,
                                    target_end,
                                    length_error,
                                    length_error,
                                )
                            )
                        elif (
                            source_length < target_length * 0.82
                            and source_length > target_length * 0.16
                        ):
                            if "START" not in usage:
                                options.append(
                                    (
                                        "START",
                                        target_start,
                                        target_start
                                        + target_unit * source_length,
                                        0.05,
                                        0.0,
                                    )
                                )
                            if "END" not in usage:
                                options.append(
                                    (
                                        "END",
                                        target_end
                                        - target_unit * source_length,
                                        target_end,
                                        0.05,
                                        0.0,
                                    )
                                )
                            if "CENTER" not in usage:
                                center_offset = (
                                    target_length - source_length
                                ) * 0.5
                                options.append(
                                    (
                                        "CENTER",
                                        target_start
                                        + target_unit * center_offset,
                                        target_start
                                        + target_unit
                                        * (center_offset + source_length),
                                        0.06,
                                        0.0,
                                    )
                                )

                        for (
                            attach_mode,
                            segment_start,
                            segment_end,
                            priority,
                            recorded_error,
                        ) in options:
                            transformed = align_polygon_edge(
                                source_polygon,
                                source_edge,
                                segment_start,
                                segment_end,
                            )
                            transformed_center = polygon_center(transformed)
                            if not centers_on_opposite_sides(
                                segment_start,
                                segment_end,
                                placed_center,
                                transformed_center,
                            ):
                                continue

                            if any(
                                polygons_overlap(transformed, polygon)
                                for polygon in placed.values()
                            ):
                                continue

                            first_edge = transformed[1] - transformed[0]
                            pose_angle = math.degrees(
                                math.atan2(first_edge[1], first_edge[0])
                            )
                            pose_key = (
                                new_id,
                                int(round(transformed_center[0] / 3)),
                                int(round(transformed_center[1] / 3)),
                                int(round(pose_angle / 3)),
                            )
                            if pose_key in generated:
                                continue
                            generated.add(pose_key)
                            branches.append(
                                (
                                    priority,
                                    placed_id,
                                    placed_edge,
                                    new_id,
                                    source_edge,
                                    attach_mode,
                                    transformed,
                                    recorded_error,
                                )
                            )

        branches.sort(key=lambda item: item[0])
        for (
            _,
            placed_id,
            placed_edge,
            new_id,
            source_edge,
            attach_mode,
            transformed,
            recorded_error,
        ) in branches:
            next_placed = dict(placed)
            next_placed[new_id] = transformed
            next_remaining = set(remaining)
            next_remaining.remove(new_id)
            next_usage = {
                key: set(value)
                for key, value in edge_usage.items()
            }
            next_usage.setdefault(
                (placed_id, placed_edge),
                set(),
            ).add(attach_mode)
            next_usage[(new_id, source_edge)] = {"FULL"}
            search(
                next_placed,
                next_remaining,
                next_usage,
                length_errors + [recorded_error],
            )
            if (
                best_score >= 0.965
                and best_rectangularity >= 0.94
                and best_corner_score >= 0.99
            ):
                return

    seed_order = sorted(
        range(len(source_polygons)),
        key=lambda piece_id: (
            0 if len(source_polygons[piece_id]) == 3 else 1,
            -max(
                polygon_edge_length(
                    source_polygons[piece_id],
                    edge_index,
                )
                for edge_index in range(len(source_polygons[piece_id]))
            ),
        ),
    )
    for seed_id in seed_order:
        search(
            {seed_id: source_polygons[seed_id].copy()},
            set(range(len(source_polygons))) - {seed_id},
            {},
            [],
        )
        if (
            best_score >= 0.965
            and best_rectangularity >= 0.94
            and best_corner_score >= 0.99
        ):
            break

    if (
        best_layout is None
        or best_rectangularity < 0.90
        or best_corner_score < 0.75
        or best_score < 0.86
    ):
        return None, 0.0, total_nodes
    return best_layout, best_score, total_nodes


def polygon_mask_bits(polygon, width, height):
    """把候选碎片转换成整数位图，便于快速计算覆盖和重叠。"""
    mask = np.zeros((height, width), dtype=np.uint8)
    cv2.fillPoly(
        mask,
        [np.rint(polygon).astype(np.int32)],
        1,
    )
    core_mask = cv2.erode(
        mask,
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    )
    packed = np.packbits(mask.reshape(-1))
    packed_core = np.packbits(core_mask.reshape(-1))
    return (
        int.from_bytes(packed.tobytes(), "little"),
        int.from_bytes(packed_core.tobytes(), "little"),
        int(np.sum(mask)),
    )


def count_mask_bits(value):
    """统计整数位图中的有效像素。"""
    return value.bit_count()


def polygons_have_interior_overlap(first, second):
    all_points = np.vstack((first, second))
    minimum = np.floor(np.min(all_points, axis=0)) - 2.0
    maximum = np.ceil(np.max(all_points, axis=0)) + 2.0
    width = int((maximum[0] - minimum[0]) * 4.0) + 1
    height = int((maximum[1] - minimum[1]) * 4.0) + 1
    if width <= 0 or height <= 0:
        return True

    first_mask = np.zeros((height, width), dtype=np.uint8)
    second_mask = np.zeros((height, width), dtype=np.uint8)
    first_points = np.rint(
        (first - minimum) * 4.0
    ).astype(np.int32)
    second_points = np.rint(
        (second - minimum) * 4.0
    ).astype(np.int32)
    cv2.fillPoly(first_mask, [first_points], 1)
    cv2.fillPoly(second_mask, [second_points], 1)

    kernel = np.ones((3, 3), dtype=np.uint8)
    first_core = cv2.erode(
        first_mask,
        kernel,
        iterations=1,
    )
    second_core = cv2.erode(
        second_mask,
        kernel,
        iterations=1,
    )
    return (
        cv2.countNonZero(
            cv2.bitwise_and(first_core, second_mask)
        )
        > 0
        or cv2.countNonZero(
            cv2.bitwise_and(first_mask, second_core)
        )
        > 0
    )


def layout_has_interior_overlap(layout):
    polygons = [
        layout[piece_id]
        for piece_id in sorted(layout)
    ]
    for first_id in range(len(polygons)):
        for second_id in range(first_id + 1, len(polygons)):
            if polygons_have_interior_overlap(
                polygons[first_id],
                polygons[second_id],
            ):
                return True
    return False


def layout_can_be_separated(layout):
    piece_ids = sorted(layout)
    polygons = [
        layout[piece_id]
        for piece_id in piece_ids
    ]
    all_points = np.vstack(polygons)
    target_center = (
        np.min(all_points, axis=0)
        + np.max(all_points, axis=0)
    ) * 0.5
    centers = [
        np.mean(polygon, axis=0)
        for polygon in polygons
    ]

    moved = {
        piece_id: (
            polygon
            + (center - target_center) * 0.6
        )
        for piece_id, polygon, center in zip(
            piece_ids,
            polygons,
            centers,
        )
    }
    return not layout_has_interior_overlap(moved)


def rectangle_result_is_valid(result):
    return (
        result[0] is not None
        and result[2] >= 0.94
        and result[3] <= 0.06
        and layout_can_be_separated(result[0])
    )


def generate_boundary_candidates(
    polygon,
    width,
    height,
    position_step=4,
):
    """
    枚举碎片外边落在目标矩形四条边上的所有候选姿态。

    题目保证每块碎片至少有一条边属于矩形外边，因此不需要在整张
    矩形内部做二维平移搜索，只沿四条边搜索即可。
    """
    candidates = []
    generated = set()
    inside_tolerance = 2.5

    for edge_index in range(len(polygon)):
        edge_length = polygon_edge_length(polygon, edge_index)
        if edge_length < 8:
            continue

        for side in range(4):
            side_length = width if side < 2 else height
            if edge_length > side_length + inside_tolerance:
                continue

            maximum_position = max(0.0, side_length - edge_length)
            positions = list(
                np.arange(
                    0.0,
                    maximum_position + 0.1,
                    position_step,
                )
            )
            positions.extend((0.0, maximum_position))

            for position in positions:
                if side == 0:
                    first = np.array([position, 0.0], dtype=np.float32)
                    second = np.array(
                        [position + edge_length, 0.0],
                        dtype=np.float32,
                    )
                elif side == 1:
                    first = np.array(
                        [position, height - 1.0],
                        dtype=np.float32,
                    )
                    second = np.array(
                        [position + edge_length, height - 1.0],
                        dtype=np.float32,
                    )
                elif side == 2:
                    first = np.array([0.0, position], dtype=np.float32)
                    second = np.array(
                        [0.0, position + edge_length],
                        dtype=np.float32,
                    )
                else:
                    first = np.array(
                        [width - 1.0, position],
                        dtype=np.float32,
                    )
                    second = np.array(
                        [width - 1.0, position + edge_length],
                        dtype=np.float32,
                    )

                for target_start, target_end in (
                    (first, second),
                    (second, first),
                ):
                    transformed = align_polygon_edge(
                        polygon,
                        edge_index,
                        target_start,
                        target_end,
                    )
                    minimum = np.min(transformed, axis=0)
                    maximum = np.max(transformed, axis=0)
                    if (
                        minimum[0] < -inside_tolerance
                        or minimum[1] < -inside_tolerance
                        or maximum[0] > width - 1 + inside_tolerance
                        or maximum[1] > height - 1 + inside_tolerance
                    ):
                        continue

                    transformed[:, 0] = np.clip(
                        transformed[:, 0],
                        0,
                        width - 1,
                    )
                    transformed[:, 1] = np.clip(
                        transformed[:, 1],
                        0,
                        height - 1,
                    )
                    center = polygon_center(transformed)
                    pose_key = (
                        int(round(center[0] / 2)),
                        int(round(center[1] / 2)),
                        edge_index,
                        side,
                    )
                    if pose_key in generated:
                        continue
                    generated.add(pose_key)

                    (
                        mask_bits,
                        core_mask_bits,
                        area,
                    ) = polygon_mask_bits(
                        transformed,
                        width,
                        height,
                    )
                    candidates.append(
                        {
                            "mask": mask_bits,
                            "core_mask": core_mask_bits,
                            "area": area,
                            "polygon": transformed.copy(),
                            "corners": sum(
                                1 << corner_id
                                for corner_id, corner in enumerate(
                                    (
                                        (0.0, 0.0),
                                        (width - 1.0, 0.0),
                                        (
                                            width - 1.0,
                                            height - 1.0,
                                        ),
                                        (0.0, height - 1.0),
                                    )
                                )
                                if float(
                                    np.min(
                                        np.linalg.norm(
                                            transformed
                                            - np.asarray(corner),
                                            axis=1,
                                        )
                                    )
                                )
                                <= 3.5
                            ),
                        }
                    )
    return candidates


def search_rectangle_ratio(
    polygons,
    target_ratio,
    beam_width,
    position_step=4,
    max_piece_overlap_ratio=0.30,
):
    """在一个给定的矩形长宽比下搜索拼片位置。"""
    width = int(round(math.sqrt(6000.0 * target_ratio)))
    height = int(round(6000.0 / width))
    candidate_sets = [
        generate_boundary_candidates(
            polygon,
            width,
            height,
            position_step,
        )
        for polygon in polygons
    ]
    if any(not candidates for candidates in candidate_sets):
        return (
            None,
            0.0,
            0.0,
            0.0,
            sum(len(item) for item in candidate_sets),
            width,
            height,
        )

    piece_order = sorted(
        range(len(polygons)),
        key=lambda piece_id: len(candidate_sets[piece_id]),
    )
    rectangle_area = width * height
    states = [
        {
            "union": 0,
            "core_union": 0,
            "covered": 0,
            "overlap": 0,
            "corners": 0,
            "proximity": 0.0,
            "layout": {},
        }
    ]
    evaluated = 0

    for piece_id in piece_order:
        next_states = []
        for state in states:
            for candidate in candidate_sets[piece_id]:
                evaluated += 1
                boundary_overlap = count_mask_bits(
                    state["union"] & candidate["mask"]
                )
                candidate_core_overlap = count_mask_bits(
                    state["union"] & candidate["core_mask"]
                )
                placed_core_overlap = count_mask_bits(
                    state["core_union"] & candidate["mask"]
                )
                interior_overlap = max(
                    candidate_core_overlap,
                    placed_core_overlap,
                )
                if interior_overlap > max(
                    6,
                    int(
                        candidate["area"]
                        * max_piece_overlap_ratio
                    ),
                ):
                    continue

                layout = dict(state["layout"])
                layout[piece_id] = candidate["polygon"]
                proximity = state["proximity"]
                for old_polygon in state["layout"].values():
                    distance = float(
                        np.min(
                            np.linalg.norm(
                                candidate["polygon"][:, None, :]
                                - old_polygon[None, :, :],
                                axis=2,
                            )
                        )
                    )
                    proximity += max(
                        0.0,
                        24.0 - distance,
                    ) ** 2
                next_states.append(
                    {
                        "union": state["union"] | candidate["mask"],
                        "core_union": (
                            state["core_union"]
                            | candidate["core_mask"]
                        ),
                        "covered": (
                            state["covered"]
                            + candidate["area"]
                            - boundary_overlap
                        ),
                        "overlap": (
                            state["overlap"]
                            + interior_overlap
                        ),
                        "corners": (
                            state["corners"]
                            | candidate["corners"]
                        ),
                        "proximity": proximity,
                        "layout": layout,
                    }
                )

        if not next_states:
            return None, 0.0, 0.0, 0.0, evaluated, width, height

        next_states.sort(
            key=lambda state: (
                state["covered"]
                - state["overlap"] * 12
                + state["corners"].bit_count()
                * rectangle_area
                * 0.18
                + state["proximity"] * 2.5
            ),
            reverse=True,
        )
        states = next_states[:beam_width]

    ranked_states = sorted(
        states,
        key=lambda state: (
            state["covered"]
            - state["overlap"] * 12
            + state["corners"].bit_count()
            * rectangle_area
            * 0.18
            + state["proximity"] * 2.5
        ),
        reverse=True,
    )
    best_state = None
    for state in ranked_states:
        if (
            state["corners"] == 15
            and not layout_has_interior_overlap(state["layout"])
        ):
            best_state = state
            break
    if best_state is None:
        return None, 0.0, 0.0, 0.0, evaluated, width, height
    coverage = best_state["covered"] / rectangle_area
    overlap_ratio = best_state["overlap"] / rectangle_area
    score = coverage - overlap_ratio * 2.0
    return (
        best_state["layout"],
        score,
        coverage,
        overlap_ratio,
        evaluated,
        width,
        height,
    )


def solve_rectangle_by_cover(
    pieces,
    max_piece_overlap_ratio=0.012,
    target_fill_ratio=0.80,
    position_step=4,
):
    """
    自动搜索允许范围内的目标矩形比例，再用位图束搜索拼接。

    返回的solve_info用于把求解坐标恢复为相机像素坐标。
    """
    if not 2 <= len(pieces) <= 4:
        return None, 0.0, 0, None

    polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    total_piece_area = sum(
        abs(cv2.contourArea(polygon))
        for polygon in polygons
    )
    if total_piece_area < 100:
        return None, 0.0, 0, None

    solve_scale = math.sqrt(
        6000.0 * target_fill_ratio / total_piece_area
    )
    polygons = [
        polygon * solve_scale
        for polygon in polygons
    ]

    ratios = [
        10.0 / 6.0,
        1.45,
        1.50,
        1.40,
        1.60,
        1.80,
        2.00,
        1.20,
        2.20,
        1.00,
        2.40,
    ]
    total_evaluated = 0
    best_ratio = ratios[0]
    best_result = None
    refined_ratios = set()

    for index, ratio in enumerate(ratios):
        beam_width = 16
        if index == 0:
            beam_width = 240
        elif index <= 3:
            beam_width = 120
        else:
            beam_width = 40
        result = search_rectangle_ratio(
            polygons,
            ratio,
            beam_width,
            position_step=position_step,
            max_piece_overlap_ratio=max_piece_overlap_ratio,
        )
        total_evaluated += result[4]
        if (
            result[0] is not None
            and (
                best_result is None
                or result[1] > best_result[1]
            )
        ):
            best_result = result
            best_ratio = ratio

        if rectangle_result_is_valid(result):
            return (
                result[0],
                result[1],
                total_evaluated,
                {
                    "ratio": ratio,
                    "solve_scale": solve_scale,
                    "width": result[5],
                    "height": result[6],
                    "coverage": result[2],
                    "overlap": result[3],
                    "forced": False,
                    "boundary_safe": True,
                },
            )
        if (
            index >= 2
            and best_result is not None
            and best_result[1] >= 0.72
            and best_ratio not in refined_ratios
        ):
            refined_result = search_rectangle_ratio(
                polygons,
                best_ratio,
                240,
                position_step=position_step,
                max_piece_overlap_ratio=max_piece_overlap_ratio,
            )
            refined_ratios.add(best_ratio)
            total_evaluated += refined_result[4]
            if refined_result[1] > best_result[1]:
                best_result = refined_result
            if rectangle_result_is_valid(refined_result):
                return (
                    refined_result[0],
                    refined_result[1],
                    total_evaluated,
                    {
                        "ratio": best_ratio,
                        "solve_scale": solve_scale,
                        "width": refined_result[5],
                        "height": refined_result[6],
                        "coverage": refined_result[2],
                        "overlap": refined_result[3],
                        "forced": False,
                        "boundary_safe": True,
                    },
                )

    if (
        best_result is not None
        and best_ratio not in refined_ratios
    ):
        refined_result = search_rectangle_ratio(
            polygons,
            best_ratio,
            240,
            position_step=position_step,
            max_piece_overlap_ratio=max_piece_overlap_ratio,
        )
        total_evaluated += refined_result[4]
        if refined_result[1] > best_result[1]:
            best_result = refined_result
        if rectangle_result_is_valid(refined_result):
            return (
                refined_result[0],
                refined_result[1],
                total_evaluated,
                {
                    "ratio": best_ratio,
                    "solve_scale": solve_scale,
                    "width": refined_result[5],
                    "height": refined_result[6],
                    "coverage": refined_result[2],
                    "overlap": refined_result[3],
                    "forced": False,
                    "boundary_safe": True,
                },
            )

    if best_result is None or best_result[0] is None:
        return None, 0.0, total_evaluated, None
    return (
        best_result[0],
        best_result[1],
        total_evaluated,
        {
            "ratio": best_ratio,
            "solve_scale": solve_scale,
            "width": best_result[5],
            "height": best_result[6],
            "coverage": best_result[2],
            "overlap": best_result[3],
            "forced": True,
            "boundary_safe": True,
        },
    )


def fit_layout_to_box(layout, target_box):
    """把求出的整体拼图旋转、缩放到屏幕下半区显示。"""
    ordered_ids = sorted(layout)
    polygons = [layout[piece_id] for piece_id in ordered_ids]
    all_points = np.vstack(polygons).astype(np.float32)
    rectangle = cv2.minAreaRect(all_points)
    rectangle_points = cv2.boxPoints(rectangle)

    longest_vector = rectangle_points[1] - rectangle_points[0]
    for index in range(1, 4):
        vector = rectangle_points[(index + 1) % 4] - rectangle_points[index]
        if np.dot(vector, vector) > np.dot(longest_vector, longest_vector):
            longest_vector = vector

    angle = -math.atan2(longest_vector[1], longest_vector[0])
    cosine = math.cos(angle)
    sine = math.sin(angle)
    rotation = np.array(
        [
            [cosine, -sine],
            [sine, cosine],
        ],
        dtype=np.float32,
    )
    center = np.mean(all_points, axis=0)
    rotated = [
        (polygon - center) @ rotation.T
        for polygon in polygons
    ]
    rotated_all = np.vstack(rotated)
    minimum = np.min(rotated_all, axis=0)
    maximum = np.max(rotated_all, axis=0)
    size = maximum - minimum

    if size[1] > size[0]:
        quarter_turn = np.array(
            [
                [0.0, -1.0],
                [1.0, 0.0],
            ],
            dtype=np.float32,
        )
        rotated = [polygon @ quarter_turn.T for polygon in rotated]
        rotated_all = np.vstack(rotated)
        minimum = np.min(rotated_all, axis=0)
        maximum = np.max(rotated_all, axis=0)
        size = maximum - minimum

    target_x, target_y, target_width, target_height = target_box
    scale = min(
        target_width / max(1.0, size[0]),
        target_height / max(1.0, size[1]),
    )
    target_center = np.array(
        [
            target_x + target_width * 0.5,
            target_y + target_height * 0.5,
        ],
        dtype=np.float32,
    )
    source_center = (minimum + maximum) * 0.5

    fitted = []
    for piece_id, polygon in zip(ordered_ids, rotated):
        points = np.rint(
            (polygon - source_center) * scale + target_center
        ).astype(np.int32)
        fitted.append(
            {
                "piece_id": piece_id,
                "points": [
                    (int(point[0]), int(point[1]))
                    for point in points
                ],
            }
        )
    return fitted


def point_segment_distance(point, start, end):
    vector = end - start
    length_squared = float(np.dot(vector, vector))
    if length_squared < 1e-6:
        return float(np.linalg.norm(point - start))
    amount = float(
        np.dot(point - start, vector) / length_squared
    )
    amount = min(1.0, max(0.0, amount))
    nearest = start + vector * amount
    return float(np.linalg.norm(point - nearest))


def polygon_distance(first, second):
    if polygons_have_interior_overlap(first, second):
        return -1.0

    best = float("inf")
    for point in first:
        for edge_id, start in enumerate(second):
            end = second[(edge_id + 1) % len(second)]
            best = min(
                best,
                point_segment_distance(point, start, end),
            )
    for point in second:
        for edge_id, start in enumerate(first):
            end = first[(edge_id + 1) % len(first)]
            best = min(
                best,
                point_segment_distance(point, start, end),
            )
    return best


def spread_layout_with_gap(polygons, target_center, gap_pixels):
    centers = [
        np.mean(polygon, axis=0)
        for polygon in polygons
    ]
    def move_and_measure(factor):
        moved = [
            polygon + (center - target_center) * factor
            for polygon, center in zip(polygons, centers)
        ]
        distances = []
        for first_id in range(len(moved)):
            for second_id in range(first_id + 1, len(moved)):
                distance = polygon_distance(
                    moved[first_id],
                    moved[second_id],
                )
                if distance < 0:
                    return moved, distance
                distances.append(distance)
        return moved, (
            min(distances)
            if distances
            else gap_pixels
        )

    best_layout, best_distance = move_and_measure(0.0)
    if best_distance >= gap_pixels:
        return best_layout

    low = 0.0
    high = 0.02
    while high <= 2.0:
        moved, distance = move_and_measure(high)
        if distance > best_distance:
            best_layout = moved
            best_distance = distance
        if distance >= gap_pixels:
            for _ in range(18):
                middle = (low + high) * 0.5
                candidate, candidate_distance = move_and_measure(middle)
                if candidate_distance >= gap_pixels:
                    high = middle
                    best_layout = candidate
                else:
                    low = middle
            return best_layout
        low = high
        high *= 2.0

    return best_layout


def place_layout_on_paper(
    layout,
    solve_info,
    roi,
    assembly_gap_pixels=36,
):
    """把目标矩形放到A4纸下半区，并保持设定的均匀接缝。"""
    roi_x, roi_y, roi_width, roi_height = roi
    scale = 1.0 / solve_info["solve_scale"]
    execution_layout = {
        int(piece_id): np.asarray(
            polygon,
            dtype=np.float64,
        ).copy()
        for piece_id, polygon in layout.items()
    }
    previous_translations = (
        solve_info.get("repair", {})
        .get("gap", {})
        .get("translations", {})
    )
    for piece_id, translation in previous_translations.items():
        piece_id = int(piece_id)
        if piece_id in execution_layout:
            execution_layout[piece_id] -= np.asarray(
                translation,
                dtype=np.float64,
            )

    execution_layout, gap_info = add_adjacency_gap(
        execution_layout,
        float(assembly_gap_pixels) * solve_info["solve_scale"],
        edge_tolerance_ratio=0.08,
        align_vertices=False,
    )
    solve_info["execution_gap"] = gap_info

    scaled_layout = {
        piece_id: polygon * scale
        for piece_id, polygon in execution_layout.items()
    }
    piece_ids = sorted(scaled_layout)
    scaled_polygons = [scaled_layout[piece_id] for piece_id in piece_ids]
    layout_center = np.mean(np.vstack(scaled_polygons), axis=0)
    spread_polygons = spread_layout_with_gap(
        scaled_polygons,
        layout_center,
        float(assembly_gap_pixels),
    )
    scaled_layout = {
        piece_id: polygon
        for piece_id, polygon in zip(piece_ids, spread_polygons)
    }
    clearances = [
        polygon_distance(
            scaled_layout[piece_ids[first]],
            scaled_layout[piece_ids[second]],
        )
        for first in range(len(piece_ids))
        for second in range(first + 1, len(piece_ids))
    ]
    gap_info["clearance_applied"] = bool(clearances)
    gap_info["minimum_clearance"] = (
        float(min(clearances)) if clearances else 0.0
    )
    gap_info["maximum_clearance"] = (
        float(max(clearances)) if clearances else 0.0
    )
    all_points = np.vstack(list(scaled_layout.values()))
    minimum = np.min(all_points, axis=0)
    maximum = np.max(all_points, axis=0)
    target_width, target_height = maximum - minimum
    target_left = (
        roi_x
        + (roi_width - target_width) * 0.5
        - minimum[0]
    )
    lower_top = roi_y + roi_height * 0.5
    target_top = lower_top + (
        roi_height * 0.5 - target_height
    ) * 0.5 - minimum[1]
    placed_polygons = []
    for piece_id in piece_ids:
        points = scaled_layout[piece_id] + np.array(
            [target_left, target_top],
            dtype=np.float32,
        )
        placed_polygons.append(points)

    fitted = []
    for piece_id, points in zip(piece_ids, placed_polygons):
        fitted.append(
            {
                "piece_id": piece_id,
                "points": [
                    (float(point[0]), float(point[1]))
                    for point in points
                ],
            }
        )
    return fitted


def short_edge_rectangle_is_usable(report):
    """第一问短外边补偿后的近似矩形验收。"""
    return (
        report["coverage"] >= 0.90
        and report["overlap"] <= 0.01
        and report["corners"] >= 0.99
        and report["outer_piece_ratio"] >= 0.75
        and report["internal_match"] >= 0.85
        and report["boundary_min_coverage"] >= 0.78
        and report["boundary_max_gap_ratio"] <= 0.22
        and report["boundary_angle_error"] <= 5.0
    )


def prepare_layout_for_execution(layout, solve_info, roi):
    """把识别误差形成的轻微重叠修正掉，并在相邻边之间保留约1mm缝隙。"""
    strict_report = evaluate_layout(layout)
    gap_pixels = max(1.0, roi[3] / 297.0) * solve_info[
        "solve_scale"
    ]
    if solve_info.get("boundary_safe", False):
        frame_report = evaluate_layout(
            layout,
            edge_tolerance_ratio=0.035,
        )
        frame_invalid = (
            frame_report["corners"] < 0.99
            or frame_report["outer_piece_ratio"] < 0.999
            or frame_report["coverage"] < 0.82
            or frame_report["internal_match"] < 0.42
            or frame_report["boundary_min_coverage"] < 0.88
            or frame_report["boundary_max_gap_ratio"] > 0.12
            or frame_report["boundary_angle_error"] > 7.0
            or layout_has_interior_overlap(layout)
        )
        short_edge_rect = (
            solve_info.get("short_edge_protection", False)
            and short_edge_rectangle_is_usable(frame_report)
        )
        if frame_invalid and not short_edge_rect:
            return None, {
                "valid": False,
                "stage": "rectangle-frame",
                "reasons": ["straight-four-side-frame"],
            }
        prepared = frame_report["normalized_layout"]
        mode = "RECT_SHORT" if short_edge_rect else "RECT"
        repair_info = {
            "valid": True,
            "stage": (
                "short-edge-rectangle"
                if short_edge_rect
                else "rectangle-frame"
            ),
            "reasons": [],
            "maximum_move": 0.0,
            "gap": {
                "applied": False,
                "reason": "preserve-four-corners",
            },
        }
    elif strict_report["valid"] and not solve_info.get(
        "forced",
        False,
    ):
        prepared = strict_report["normalized_layout"]
        mode = "EXACT"
        repair_info = {
            "valid": True,
            "stage": "strict",
            "reasons": [],
            "maximum_move": 0.0,
            "gap": {
                "applied": False,
                "reason": "preserve-four-corners",
            },
        }
    else:
        prepared, repair_info = repair_layout_for_competition(
            layout,
            gap_pixels=gap_pixels,
            force=solve_info.get("forced", False),
        )
        mode = (
            "ASSUME"
            if solve_info.get("forced", False)
            else "EXEC"
        )

    if prepared is None or layout_has_interior_overlap(prepared):
        return None, repair_info

    final_report = evaluate_layout(
        prepared,
        edge_tolerance_ratio=0.05,
    )
    final_invalid = (
        final_report["corners"] < 0.99
        or final_report["outer_piece_ratio"] < 0.999
        or final_report["coverage"] < 0.82
        or final_report["internal_match"] < 0.42
        or final_report["boundary_min_coverage"] < 0.88
        or final_report["boundary_max_gap_ratio"] > 0.12
        or final_report["boundary_angle_error"] > 7.0
        or layout_has_interior_overlap(prepared)
    )
    final_short_edge_rect = (
        solve_info.get("short_edge_protection", False)
        and short_edge_rectangle_is_usable(final_report)
    )
    if final_invalid and not final_short_edge_rect:
        return None, {
            "valid": False,
            "stage": "final-rectangle",
            "reasons": ["straight-four-side-frame"],
        }
    solve_info["width"] = final_report["width"]
    solve_info["height"] = final_report["height"]
    solve_info["ratio"] = (
        final_report["width"]
        / max(1.0, final_report["height"])
    )
    solve_info["execution_mode"] = mode
    solve_info["constraint_report"] = {
        "coverage": final_report["coverage"],
        "overlap": final_report["overlap"],
        "outer_piece_ratio": final_report["outer_piece_ratio"],
        "internal_match": final_report["internal_match"],
        "boundary_min_coverage": final_report[
            "boundary_min_coverage"
        ],
        "boundary_max_gap_ratio": final_report[
            "boundary_max_gap_ratio"
        ],
        "boundary_angle_error": final_report[
            "boundary_angle_error"
        ],
    }
    solve_info["repair"] = repair_info
    return prepared, repair_info


def prepare_best_effort_layout(layout, solve_info, roi):
    """比赛保底：严格矩形无解时，保留无重叠且几何评分最高的候选。"""
    report = evaluate_layout(
        layout,
        edge_tolerance_ratio=0.035,
    )
    prepared = report["normalized_layout"]
    repair_info = {
        "valid": True,
        "forced": True,
        "stage": "best-effort",
        "reasons": report["competition_reasons"],
        "maximum_move": 0.0,
        "gap": {
            "applied": False,
            "reason": "preserve-best-candidate",
        },
    }
    if layout_has_interior_overlap(prepared):
        prepared, repair_info = repair_layout_for_competition(
            prepared,
            gap_pixels=max(1.0, roi[3] / 297.0) * solve_info[
                "solve_scale"
            ],
            force=True,
        )
    if prepared is None or layout_has_interior_overlap(prepared):
        return None, {
            "valid": False,
            "stage": "best-effort",
            "reasons": ["overlap"],
        }

    report = evaluate_layout(
        prepared,
        edge_tolerance_ratio=0.05,
    )
    solve_info["width"] = report["width"]
    solve_info["height"] = report["height"]
    solve_info["ratio"] = report["width"] / max(1.0, report["height"])
    solve_info["method"] = "cpp-best-effort"
    solve_info["execution_mode"] = "BEST"
    solve_info["forced"] = True
    solve_info["constraint_report"] = {
        "coverage": report["coverage"],
        "overlap": report["overlap"],
        "outer_piece_ratio": report["outer_piece_ratio"],
        "internal_match": report["internal_match"],
        "boundary_min_coverage": report["boundary_min_coverage"],
        "boundary_max_gap_ratio": report["boundary_max_gap_ratio"],
        "boundary_angle_error": report["boundary_angle_error"],
    }
    solve_info["repair"] = repair_info
    return prepared, repair_info


def best_effort_layout_score(layout):
    report = evaluate_layout(
        layout,
        edge_tolerance_ratio=0.035,
    )
    angle_score = max(
        0.0,
        1.0 - report["boundary_angle_error"] / 15.0,
    )
    score = (
        report["coverage"] * 0.32
        + report["internal_match"] * 0.28
        + report["boundary_min_coverage"] * 0.22
        + (1.0 - report["boundary_max_gap_ratio"]) * 0.10
        + angle_score * 0.05
        + report["corners"] * 0.03
        - report["overlap"] * 8.0
    )
    return score, report


def build_last_resort_layout(pieces, roi):
    """所有搜索器都无候选时，紧凑排列碎片并保证仍可输出无重叠方案。"""
    polygons = [
        normalize_polygon(piece["points"])
        for piece in pieces
    ]
    total_area = sum(
        abs(cv2.contourArea(polygon))
        for polygon in polygons
    )
    if not 2 <= len(polygons) <= 4 or total_area < 100.0:
        return None, 0.0, None

    solve_scale = math.sqrt(4320.0 / total_area)
    polygons = [
        polygon * solve_scale
        for polygon in polygons
    ]
    columns = len(polygons) if len(polygons) == 2 else 2
    rows = (len(polygons) + columns - 1) // columns
    sizes = []
    local_polygons = []
    for polygon in polygons:
        minimum = np.min(polygon, axis=0)
        local = polygon - minimum
        local_polygons.append(local)
        sizes.append(np.max(local, axis=0))

    column_widths = [
        max(
            (
                sizes[index][0]
                for index in range(column, len(sizes), columns)
            ),
            default=0.0,
        )
        for column in range(columns)
    ]
    row_heights = [
        max(
            (
                sizes[index][1]
                for index in range(
                    row * columns,
                    min((row + 1) * columns, len(sizes)),
                )
            ),
            default=0.0,
        )
        for row in range(rows)
    ]
    gap = 2.0
    x_offsets = [
        sum(column_widths[:column]) + column * gap
        for column in range(columns)
    ]
    y_offsets = [
        sum(row_heights[:row]) + row * gap
        for row in range(rows)
    ]
    layout = {}
    for piece_id, (polygon, size) in enumerate(
        zip(local_polygons, sizes)
    ):
        row = piece_id // columns
        column = piece_id % columns
        offset = np.array(
            [
                x_offsets[column]
                + (column_widths[column] - size[0]) * 0.5,
                y_offsets[row]
                + (row_heights[row] - size[1]) * 0.5,
            ],
            dtype=np.float32,
        )
        layout[piece_id] = polygon + offset

    info = {
        "solve_scale": solve_scale,
        "method": "last-resort-grid",
        "forced": True,
        "boundary_safe": False,
    }
    prepared, repair_info = prepare_best_effort_layout(
        layout,
        info,
        roi,
    )
    if prepared is None:
        return None, 0.0, None
    # 补充 place_layout_on_paper 需要的宽高字段
    all_points = np.vstack(list(prepared.values()))
    x_min, y_min = np.min(all_points, axis=0)
    x_max, y_max = np.max(all_points, axis=0)
    info["width"] = float(x_max - x_min)
    info["height"] = float(y_max - y_min)
    info["ratio"] = info["width"] / max(1.0, info["height"])
    score, _ = best_effort_layout_score(prepared)
    info["method"] = "last-resort-grid"
    info["repair"] = repair_info
    return prepared, score, info


def build_motion_plan(pieces, fitted_layout):
    """
    计算每块拼片的吸取点、放置点和图像坐标系旋转角。

    目标轮廓由当前轮廓刚体变换得到，顶点顺序保持一致，因此不会产生
    仅依靠最长边判断时常见的180度方向歧义。
    """
    targets = {
        item["piece_id"]: np.array(
            item["points"],
            dtype=np.float32,
        )
        for item in fitted_layout
    }
    plan = []

    for piece_id, piece in enumerate(pieces):
        source = np.array(
            piece["points"],
            dtype=np.float32,
        )
        target = targets[piece_id]

        best_start = 0
        best_end = 1
        best_length = 0.0
        for start in range(len(source)):
            for end in range(start + 1, len(source)):
                vector = source[end] - source[start]
                length = float(np.dot(vector, vector))
                if length > best_length:
                    best_start = start
                    best_end = end
                    best_length = length

        source_vector = (
            source[best_end] - source[best_start]
        )
        target_vector = (
            target[best_end] - target[best_start]
        )
        rotation = math.degrees(
            math.atan2(
                target_vector[1],
                target_vector[0],
            )
            - math.atan2(
                source_vector[1],
                source_vector[0],
            )
        )
        while rotation > 180:
            rotation -= 360
        while rotation <= -180:
            rotation += 360

        radians = math.radians(rotation)
        rotation_matrix = np.array(
            [
                [math.cos(radians), -math.sin(radians)],
                [math.sin(radians), math.cos(radians)],
            ],
            dtype=np.float32,
        )
        translation = (
            target[best_start]
            - rotation_matrix @ source[best_start]
        )
        pick = np.array(
            piece["center"],
            dtype=np.float32,
        )
        place = rotation_matrix @ pick + translation
        plan.append(
            {
                "piece_id": piece_id,
                "pick": (
                    float(pick[0]),
                    float(pick[1]),
                ),
                "place": (
                    float(place[0]),
                    float(place[1]),
                ),
                "rotation": rotation,
            }
        )
    return plan


def print_motion_plan(plan):
    """打印视觉坐标搬运指令，便于后续发送给机械臂控制器。"""
    for move in plan:
        print(
            "MOVE P%d PICK=(%.1f,%.1f) PLACE=(%.1f,%.1f) ROT_IMG=%+.1f"
            % (
                move["piece_id"] + 1,
                move["pick"][0],
                move["pick"][1],
                move["place"][0],
                move["place"][1],
                move["rotation"],
            ),
            flush=True,
        )


def draw_solved_rectangle(
    img,
    fitted_layout,
    target_box,
    score,
    motion_plan,
):
    """在A4纸下半区画出拼接后的矩形及内部接缝。"""
    target_x, target_y, _, _ = target_box
    colors = (
        image.COLOR_GREEN,
        image.COLOR_RED,
        image.COLOR_YELLOW,
        image.COLOR_BLUE,
    )
    rotations = {
        move["piece_id"]: move["rotation"]
        for move in motion_plan
    }
    for item in fitted_layout:
        points = item["points"]
        color = colors[item["piece_id"] % len(colors)]
        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            img.draw_line(
                int(round(start[0])),
                int(round(start[1])),
                int(round(end[0])),
                int(round(end[1])),
                color,
                4,
            )
        center_x = int(
            round(
                sum(point[0] for point in points)
                / len(points)
            )
        )
        center_y = int(
            round(
                sum(point[1] for point in points)
                / len(points)
            )
        )
        img.draw_string(
            center_x - 20,
            center_y - 18,
            "S%d R%+.0f"
            % (
                item["piece_id"] + 1,
                rotations.get(item["piece_id"], 0.0),
            ),
            color,
            scale=1,
        )

    img.draw_string(
        target_x,
        target_y - 36,
        "SOLVED %.3f" % score,
        image.COLOR_WHITE,
        scale=2,
    )


def draw_roi(img, roi):
    """在屏幕上画出当前参与识别的区域。"""
    x, y, width, height = roi
    right = x + width - 1
    bottom = y + height - 1
    img.draw_line(x, y, right, y, image.COLOR_YELLOW, 1)
    img.draw_line(right, y, right, bottom, image.COLOR_YELLOW, 1)
    img.draw_line(right, bottom, x, bottom, image.COLOR_YELLOW, 1)
    img.draw_line(x, bottom, x, y, image.COLOR_YELLOW, 1)


def draw_piece(img, piece, piece_id):
    """画出一块碎片的轮廓、中心、最长边和简洁编号。"""
    points = piece["points"]

    # 先画深色底线，再画绿色轮廓。亮、暗碎片都能看清，而且每条边都会被描出。
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        img.draw_line(
            start[0],
            start[1],
            end[0],
            end[1],
            image.COLOR_BLACK,
            6,
        )

    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        img.draw_line(
            start[0],
            start[1],
            end[0],
            end[1],
            image.COLOR_GREEN,
            3,
        )

    edge_start, edge_end = piece["longest_edge"]
    img.draw_line(
        edge_start[0],
        edge_start[1],
        edge_end[0],
        edge_end[1],
        image.COLOR_YELLOW,
        3,
    )

    center_x, center_y = piece["center"]
    img.draw_cross(
        center_x,
        center_y,
        image.COLOR_RED,
        size=6,
        thickness=2,
    )
    label = "P%d" % piece_id
    img.draw_string(
        max(0, center_x - 24),
        max(0, center_y - 44),
        label,
        image.COLOR_GREEN,
        scale=2,
    )


def print_detection(pieces, threshold_info):
    """把结果打印到串口终端，之后可直接扩展为机械控制数据。"""
    print(
        "pieces=%d polarity=%s mode=%s threshold=%d"
        % (
            len(pieces),
            threshold_info["polarity"],
            threshold_info["threshold_mode"],
            threshold_info["threshold"],
        ),
        flush=True,
    )
    for index, piece in enumerate(pieces, 1):
        print(
            "  P%d center=(%d,%d) vertices=%d area=%d angle=%.1f"
            % (
                index,
                piece["center"][0],
                piece["center"][1],
                len(piece["points"]),
                int(piece["area"]),
                piece["angle"],
            ),
            flush=True,
        )


def touch_in_box(
    touch_status,
    box,
    image_width,
    image_height,
    display_width,
    display_height,
):
    """把图像上的按钮位置映射到实际屏幕触摸坐标。"""
    if not touch_status[2]:
        return False

    mapped = image.resize_map_pos(
        image_width,
        image_height,
        display_width,
        display_height,
        image.Fit.FIT_CONTAIN,
        box[0],
        box[1],
        box[2],
        box[3],
    )
    return (
        mapped[0] <= touch_status[0] < mapped[0] + mapped[2]
        and mapped[1] <= touch_status[1] < mapped[1] + mapped[3]
    )


def get_button_boxes(image_width, image_height):
    """返回右侧调参按钮在摄像头图像中的位置。"""
    if image_height > image_width:
        return {
            # 主界面按钮（不变）
            "solve": [20, 760, 210, 70],
            "card_solve": [255, 760, 210, 70],
            "tune": [490, 760, 210, 70],
            "capture": [20, 840, 680, 70],
            # 绿色分割参数（新增）
            "green_method": [20, 665, 680, 40],
            "green_sat_down": [490, 712, 50, 38],
            "green_sat_up": [545, 712, 50, 38],
            "green_close_k_down": [490, 756, 50, 38],
            "green_close_k_up": [545, 756, 50, 38],
            "green_close_i_down": [490, 800, 50, 38],
            "green_close_i_up": [545, 800, 50, 38],
            "paper_close_k_down": [490, 844, 50, 38],
            "paper_close_k_up": [545, 844, 50, 38],
            "paper_close_i_down": [490, 888, 50, 38],
            "paper_close_i_up": [545, 888, 50, 38],
            # 原有调参按钮（下移）
            "threshold_down": [20, 940, 220, 44],
            "threshold_up": [245, 940, 220, 44],
            "auto_threshold": [20, 990, 330, 44],
            "polarity": [355, 990, 345, 44],
            "area_down": [20, 1040, 330, 44],
            "area_up": [355, 1040, 345, 44],
            "close": [20, 1140, 680, 55],
        }

    panel_x = image_width - 350
    return {
        # 主界面按钮（不变）
        "solve": [panel_x + 10, 10, 100, 70],
        "card_solve": [panel_x + 120, 10, 100, 70],
        "tune": [panel_x + 230, 10, 100, 70],
        "capture": [panel_x + 10, 90, 320, 70],
        # 绿色分割参数（新增）
        "green_method": [panel_x + 10, 15, 320, 34],
        "green_sat_down": [panel_x + 180, 56, 48, 34],
        "green_sat_up": [panel_x + 233, 56, 48, 34],
        "green_close_k_down": [panel_x + 180, 96, 48, 34],
        "green_close_k_up": [panel_x + 233, 96, 48, 34],
        "green_close_i_down": [panel_x + 180, 136, 48, 34],
        "green_close_i_up": [panel_x + 233, 136, 48, 34],
        "paper_close_k_down": [panel_x + 180, 176, 48, 34],
        "paper_close_k_up": [panel_x + 233, 176, 48, 34],
        "paper_close_i_down": [panel_x + 180, 216, 48, 34],
        "paper_close_i_up": [panel_x + 233, 216, 48, 34],
        # 原有调参按钮（下移）
        "threshold_down": [panel_x + 10, 265, 125, 40],
        "threshold_up": [panel_x + 140, 265, 125, 40],
        "auto_threshold": [panel_x + 10, 310, 320, 40],
        "polarity": [panel_x + 10, 355, 320, 40],
        "area_down": [panel_x + 10, 400, 155, 40],
        "area_up": [panel_x + 175, 400, 155, 40],
        "close": [panel_x + 10, 490, 320, 50],
    }


def draw_button(img, box, text, active=False):
    """绘制适合高分辨率画面缩放显示的触摸按钮。"""
    color = image.COLOR_GREEN if active else image.COLOR_WHITE
    img.draw_rect(
        box[0],
        box[1],
        box[2],
        box[3],
        image.COLOR_BLACK,
        -1,
    )
    img.draw_rect(
        box[0],
        box[1],
        box[2],
        box[3],
        color,
        3,
    )

    text_size = image.string_size(text, scale=2)
    text_width = (
        text_size.width()
        if hasattr(text_size, "width")
        else text_size[0]
    )
    text_height = (
        text_size.height()
        if hasattr(text_size, "height")
        else text_size[1]
    )
    img.draw_string(
        box[0] + (box[2] - text_width) // 2,
        box[1] + (box[3] - text_height) // 2,
        text,
        color,
        scale=2,
    )


def draw_controls(
    img,
    boxes,
    auto_threshold,
    threshold_value,
    polarity_mode,
    min_piece_area,
    green_method="largest",
    green_sat_min=20,
    green_close_kernel=7,
    green_close_iter=2,
    paper_close_kernel=5,
    paper_close_iter=1,
):
    """显示阈值、极性和最小面积的触摸调参面板。"""
    if img.height() > img.width():
        # 竖屏：面板从 y=650 开始，覆盖下半区
        img.draw_rect(
            0,
            650,
            img.width(),
            img.height() - 650,
            image.COLOR_BLACK,
            -1,
        )
        img.draw_string(20, 655, "TUNE PARAMS", image.COLOR_WHITE, scale=2)
        label_x = 20
        btn_w = 50
        btn_h = 38
    else:
        panel_x = boxes["green_method"][0] - 10
        # 横屏：面板填满右侧整列
        img.draw_rect(
            panel_x,
            0,
            img.width() - panel_x,
            640,
            image.COLOR_BLACK,
            -1,
        )
        img.draw_string(
            panel_x + 10, 5, "TUNE PARAMS", image.COLOR_WHITE, scale=2,
        )
        label_x = panel_x + 10
        btn_w = 48
        btn_h = 34

    # ---- 绿色背景分割参数 ----
    draw_button(
        img, boxes["green_method"],
        "METHOD %s" % green_method.upper(),
        active=(green_method == "largest"),
    )

    def _param_row(label, value, down_key, up_key):
        y = boxes[down_key][1]
        img.draw_string(label_x, y + 8, "%s %d" % (label, value),
                        image.COLOR_WHITE, scale=2)
        draw_button(img, boxes[down_key], "-")
        draw_button(img, boxes[up_key], "+")

    _param_row("G-SAT", green_sat_min, "green_sat_down", "green_sat_up")
    _param_row("CLS-K", green_close_kernel, "green_close_k_down", "green_close_k_up")
    _param_row("CLS-I", green_close_iter, "green_close_i_down", "green_close_i_up")
    _param_row("PAP-K", paper_close_kernel, "paper_close_k_down", "paper_close_k_up")
    _param_row("PAP-I", paper_close_iter, "paper_close_i_down", "paper_close_i_up")

    # ---- 二值化参数 ----
    draw_button(img, boxes["threshold_down"], "TH -5")
    draw_button(img, boxes["threshold_up"], "TH +5")
    draw_button(
        img, boxes["auto_threshold"],
        "TH AUTO" if auto_threshold else "TH %d" % threshold_value,
        active=auto_threshold,
    )
    draw_button(
        img, boxes["polarity"],
        "POL %s" % polarity_mode,
        active=polarity_mode != "AUTO",
    )
    draw_button(img, boxes["area_down"], "AREA -")
    draw_button(img, boxes["area_up"], "AREA +")
    img.draw_string(
        boxes["area_down"][0],
        boxes["area_down"][1] + boxes["area_down"][3] + 12,
        "MIN AREA %d" % min_piece_area,
        image.COLOR_WHITE,
        scale=2,
    )
    draw_button(img, boxes["close"], "BACK")


def show_binary_preview(frame_rgb, mask, roi):
    """调参页面中把当前参与识别的二值图直接显示出来。"""
    roi_x, roi_y, roi_width, roi_height = roi
    frame_rgb[:, :, :] = 0
    preview = frame_rgb[
        roi_y : roi_y + roi_height,
        roi_x : roi_x + roi_width,
    ]
    preview[:, :, 0] = mask
    preview[:, :, 1] = mask
    preview[:, :, 2] = mask


def show_card_assembly_preview(preview_rgb):
    """在独立窗口中显示带有原始牌面纹理的拼接结果。"""
    if preview_rgb is None:
        return

    height, width = preview_rgb.shape[:2]
    scale = min(1.0, 640.0 / width, 560.0 / height)
    cv2.namedWindow(
        "Card Pattern Check - Gap Closed",
        cv2.WINDOW_NORMAL,
    )
    cv2.resizeWindow(
        "Card Pattern Check - Gap Closed",
        max(320, int(width * scale)),
        max(240, int(height * scale)),
    )
    cv2.moveWindow(
        "Card Pattern Check - Gap Closed",
        760,
        80,
    )
    cv2.imshow(
        "Card Pattern Check - Gap Closed",
        cv2.cvtColor(
            preview_rgb,
            cv2.COLOR_RGB2BGR,
        ),
    )


def save_capture(
    frame_rgb,
    mask,
    pieces,
    threshold_info,
    roi,
    settings,
):
    capture_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
    os.makedirs(capture_dir, exist_ok=True)
    timestamp = "%s_%03d" % (
        time.strftime("%Y%m%d_%H%M%S"),
        int(time.time() * 1000) % 1000,
    )
    prefix = os.path.join(capture_dir, timestamp)
    roi_x, roi_y, roi_width, roi_height = roi
    raw_bgr = cv2.cvtColor(
        frame_rgb,
        cv2.COLOR_RGB2BGR,
    )
    roi_bgr = raw_bgr[
        roi_y : roi_y + roi_height,
        roi_x : roi_x + roi_width,
    ]
    if not cv2.imwrite(prefix + "_raw.png", raw_bgr):
        raise RuntimeError("cannot save raw capture")
    if not cv2.imwrite(prefix + "_roi.png", roi_bgr):
        raise RuntimeError("cannot save ROI capture")
    if not cv2.imwrite(prefix + "_binary.png", mask):
        raise RuntimeError("cannot save binary capture")

    metadata = {
        "timestamp": timestamp,
        "raw_file": timestamp + "_raw.png",
        "roi_file": timestamp + "_roi.png",
        "binary_file": timestamp + "_binary.png",
        "image_size": [
            int(frame_rgb.shape[1]),
            int(frame_rgb.shape[0]),
        ],
        "roi": [
            int(roi_x),
            int(roi_y),
            int(roi_width),
            int(roi_height),
        ],
        "threshold": int(threshold_info["threshold"]),
        "threshold_mode": threshold_info["threshold_mode"],
        "polarity": threshold_info["polarity"],
        "settings": settings,
        "pieces": [
            {
                "index": index,
                "points": [
                    [int(point[0]), int(point[1])]
                    for point in piece["points"]
                ],
                "center": [
                    int(piece["center"][0]),
                    int(piece["center"][1]),
                ],
                "area": float(piece["area"]),
                "solidity": float(piece["solidity"]),
                "angle": float(piece["angle"]),
            }
            for index, piece in enumerate(pieces, 1)
        ],
    }
    with open(prefix + ".json", "w", encoding="utf-8") as file:
        json.dump(
            metadata,
            file,
            ensure_ascii=False,
            indent=2,
        )
    print(
        "CAPTURE_SAVED %s pieces=%d"
        % (timestamp, len(pieces)),
        flush=True,
    )
    return timestamp


def align_polygon_points(reference, points):
    reference = np.asarray(reference, dtype=np.float64)
    points = np.asarray(points, dtype=np.float64)
    best = points
    best_error = float("inf")
    for candidate in (points, points[::-1]):
        for offset in range(len(candidate)):
            aligned = np.roll(candidate, offset, axis=0)
            error = float(
                np.mean((aligned - reference) ** 2)
            )
            if error < best_error:
                best = aligned
                best_error = error
    return best


def build_stable_piece_set(recent_piece_sets):
    """从最近的连续画面中生成一组中值轮廓。"""
    if not recent_piece_sets:
        return None

    latest = recent_piece_sets[-1][2]
    if not 2 <= len(latest) <= 4:
        return None
    recent_candidates = [
        item[2]
        for item in recent_piece_sets[-8:]
        if len(item[2]) == len(latest)
    ]
    if not recent_candidates:
        return None
    signatures = [
        tuple(sorted(len(piece["points"]) for piece in candidate))
        for candidate in recent_candidates
    ]
    reference_signature = max(
        set(signatures),
        key=signatures.count,
    )
    reference = next(
        candidate
        for candidate in reversed(recent_candidates)
        if tuple(sorted(len(piece["points"]) for piece in candidate))
        == reference_signature
    )
    if not 2 <= len(reference) <= 4:
        return None

    aligned_sets = []
    for _, _, candidate in reversed(recent_piece_sets[-8:]):
        if len(candidate) != len(reference):
            continue
        best_order = None
        best_error = float("inf")
        for order in itertools.permutations(range(len(candidate))):
            distances = []
            valid = True
            for piece_id, candidate_id in enumerate(order):
                if len(candidate[candidate_id]["points"]) != len(
                    reference[piece_id]["points"]
                ):
                    valid = False
                    break
                first = np.asarray(
                    reference[piece_id]["center"],
                    dtype=np.float64,
                )
                second = np.asarray(
                    candidate[candidate_id]["center"],
                    dtype=np.float64,
                )
                distances.append(
                    float(np.linalg.norm(first - second))
                )
            if not valid or max(distances, default=99.0) > 12.0:
                continue
            error = sum(distance * distance for distance in distances)
            if error < best_error:
                best_error = error
                best_order = order
        if best_order is not None:
            aligned_sets.append(
                [candidate[index] for index in best_order]
            )
        if len(aligned_sets) >= 5:
            break

    if len(aligned_sets) < 3:
        return None

    stable_pieces = []
    for piece_id, reference_piece in enumerate(reference):
        reference_points = np.asarray(
            reference_piece["points"],
            dtype=np.float64,
        )
        point_samples = []
        area_samples = []
        solidity_samples = []
        for pieces in aligned_sets:
            piece = pieces[piece_id]
            point_samples.append(
                align_polygon_points(
                    reference_points,
                    piece["points"],
                )
            )
            area_samples.append(float(piece["area"]))
            solidity_samples.append(float(piece["solidity"]))

        points_array = np.asarray(point_samples)
        median_points = np.median(points_array, axis=0)
        sample_errors = np.sqrt(
            np.mean((points_array - median_points) ** 2, axis=(1, 2))
        )
        error_median = float(np.median(sample_errors))
        error_mad = float(np.median(np.abs(sample_errors - error_median)))
        error_limit = max(3.5, error_median + max(1.5, error_mad * 3.0))
        inliers = sample_errors <= error_limit
        if int(np.count_nonzero(inliers)) >= 3:
            points_array = points_array[inliers]
            area_samples = np.asarray(area_samples, dtype=np.float64)[inliers]
            solidity_samples = np.asarray(
                solidity_samples,
                dtype=np.float64,
            )[inliers]
            median_points = np.median(points_array, axis=0)
            sample_errors = sample_errors[inliers]
        point_spread = float(np.percentile(sample_errors, 90))
        median_area = float(np.median(area_samples))
        area_spread = float(
            np.percentile(area_samples, 90)
            - np.percentile(area_samples, 10)
        ) / max(1.0, median_area)
        if point_spread > 5.0 or area_spread > 0.14:
            return None

        points = [
            (int(round(point[0])), int(round(point[1])))
            for point in median_points
        ]
        contour = np.asarray(points, dtype=np.float32)
        moments = cv2.moments(contour)
        if abs(moments["m00"]) < 1:
            return None
        center = (
            int(round(moments["m10"] / moments["m00"])),
            int(round(moments["m01"] / moments["m00"])),
        )
        piece_longest_edge, angle = longest_edge(points)
        stable_pieces.append(
            {
                "points": points,
                "center": center,
                "area": median_area,
                "angle": angle,
                "longest_edge": piece_longest_edge,
                "solidity": float(
                    np.median(solidity_samples)
                ),
            }
        )
    return stable_pieces


def build_best_effort_piece_set(recent_piece_sets):
    """稳定窗口超时时，选择轮廓质量最高且结构最常见的一帧。"""
    candidates = [
        item
        for item in recent_piece_sets[-16:]
        if 2 <= len(item[2]) <= 4
    ]
    if not candidates:
        return None
    piece_counts = [len(item[2]) for item in candidates]
    expected_count = max(set(piece_counts), key=piece_counts.count)
    candidates = [
        item for item in candidates if len(item[2]) == expected_count
    ]
    signatures = [
        tuple(sorted(len(piece["points"]) for piece in item[2]))
        for item in candidates
    ]
    expected_signature = max(set(signatures), key=signatures.count)
    preferred = [
        item
        for item, signature in zip(candidates, signatures)
        if signature == expected_signature
    ]
    return max(preferred or candidates, key=lambda item: item[1])[2]


def solve_piece_set_worker(
    pieces,
    roi,
    short_edge_protection=False,
):
    """在独立进程中求解，避免搜索期间停止读取摄像头。"""
    cv2.setNumThreads(1)
    started = time.monotonic()
    solved_layout = None
    solved_score = 0.0
    solver_nodes = 0
    solve_info = None

    print(
        "SOLVE_STABLE %s"
        % [piece["points"] for piece in pieces],
        flush=True,
    )
    best_cpp_result = None
    best_effort_result = None
    search_settings = (
        (0.96, 4),
        (0.88, 4),
        (0.80, 3),
        (0.72, 2),
    )

    for fill_ratio, position_step in search_settings:
        (
            candidate_layout,
            candidate_score,
            candidate_nodes,
            candidate_info,
        ) = solve_rectangle_by_cover_cpp(
            pieces,
            fill_ratio=fill_ratio,
            position_step=position_step,
            short_edge_protection=short_edge_protection,
        )
        solver_nodes += candidate_nodes
        solved_score = max(solved_score, candidate_score)
        if candidate_layout is None:
            continue
        candidate_info = dict(candidate_info)
        candidate_info["short_edge_protection"] = bool(
            short_edge_protection
        )
        fallback_score, fallback_report = best_effort_layout_score(
            candidate_layout
        )
        if (
            not layout_has_interior_overlap(candidate_layout)
            and (
                best_effort_result is None
                or fallback_score > best_effort_result[0]
            )
        ):
            fallback_info = dict(candidate_info)
            fallback_info["best_effort_score"] = fallback_score
            fallback_info["best_effort_report"] = {
                "coverage": fallback_report["coverage"],
                "internal_match": fallback_report["internal_match"],
                "boundary_min_coverage": fallback_report[
                    "boundary_min_coverage"
                ],
                "boundary_max_gap_ratio": fallback_report[
                    "boundary_max_gap_ratio"
                ],
                "boundary_angle_error": fallback_report[
                    "boundary_angle_error"
                ],
            }
            best_effort_result = (
                fallback_score,
                candidate_score,
                candidate_layout,
                fallback_info,
            )
        candidate_layout, repair_info = (
            prepare_layout_for_execution(
                candidate_layout,
                candidate_info,
                roi,
            )
        )
        if candidate_layout is not None:
            if (
                best_cpp_result is None
                or candidate_score > best_cpp_result[0]
            ):
                best_cpp_result = (
                    candidate_score,
                    candidate_layout,
                    candidate_info,
                )
            break

        if best_effort_result is not None:
            fallback_report = best_effort_result[3][
                "best_effort_report"
            ]
            if (
                best_effort_result[0] >= 0.78
                and fallback_report["coverage"] >= 0.86
                and fallback_report["internal_match"] >= 0.55
                and fallback_report["boundary_min_coverage"] >= 0.78
                and fallback_report["boundary_max_gap_ratio"] <= 0.22
            ):
                break

    if best_cpp_result is not None:
        solved_score, solved_layout, solve_info = best_cpp_result
    elif best_effort_result is not None:
        (
            fallback_score,
            candidate_score,
            candidate_layout,
            candidate_info,
        ) = best_effort_result
        candidate_layout, repair_info = prepare_best_effort_layout(
            candidate_layout,
            candidate_info,
            roi,
        )
        if candidate_layout is not None:
            solved_score = fallback_score
            solved_layout = candidate_layout
            solve_info = candidate_info

    if solved_layout is None and 2 <= len(pieces) <= 4:
        (
            candidate_layout,
            candidate_score,
            candidate_nodes,
            candidate_info,
        ) = solve_rectangle_by_cover(pieces)
        solver_nodes += candidate_nodes
        solved_score = max(solved_score, candidate_score)
        if candidate_layout is None:
            (
                candidate_layout,
                candidate_score,
                candidate_nodes,
                candidate_info,
            ) = solve_rectangle_by_cover(
                pieces,
                position_step=3,
            )
            solver_nodes += candidate_nodes
            solved_score = max(
                solved_score,
                candidate_score,
            )
        if candidate_layout is None:
            (
                candidate_layout,
                candidate_score,
                candidate_nodes,
                candidate_info,
            ) = solve_rectangle_by_cover(
                pieces,
                target_fill_ratio=0.72,
                position_step=4,
            )
            solver_nodes += candidate_nodes
            solved_score = max(
                solved_score,
                candidate_score,
            )
        if candidate_layout is not None:
            candidate_info = dict(candidate_info)
            candidate_info["method"] = "legacy-cover"
            measured_layout = candidate_layout
            candidate_layout, repair_info = (
                prepare_layout_for_execution(
                    candidate_layout,
                    candidate_info,
                    roi,
                )
            )
            if candidate_layout is None:
                print(
                    "SOLVE_REJECT legacy %s" % repair_info,
                    flush=True,
                )
                candidate_info["forced"] = True
                candidate_layout, repair_info = (
                    prepare_layout_for_execution(
                        measured_layout,
                        candidate_info,
                        roi,
                    )
                )
            if candidate_layout is not None:
                solved_layout = candidate_layout
                solved_score = candidate_score
                solve_info = candidate_info

    if solved_layout is None:
        (
            candidate_layout,
            candidate_score,
            candidate_nodes,
            candidate_info,
        ) = solve_camera_rectangle(
            pieces,
            roi,
            time_limit_s=2.2,
            allow_relaxed=False,
        )
        solver_nodes += candidate_nodes
        solved_score = max(solved_score, candidate_score)
        if candidate_layout is not None:
            candidate_info = dict(candidate_info)
            measured_layout = candidate_layout
            candidate_layout, repair_info = (
                prepare_layout_for_execution(
                    candidate_layout,
                    candidate_info,
                    roi,
                )
            )
            if candidate_layout is None:
                candidate_info["forced"] = True
                candidate_layout, repair_info = (
                    prepare_layout_for_execution(
                        measured_layout,
                        candidate_info,
                        roi,
                    )
                )
        if candidate_layout is not None:
            solved_layout = candidate_layout
            solved_score = candidate_score
            solve_info = candidate_info

    if solved_layout is None:
        (
            candidate_layout,
            candidate_score,
            candidate_nodes,
            candidate_metrics,
        ) = solve_edge_layout(
            pieces,
            time_limit_s=2.2,
            return_best=True,
        )
        solver_nodes += candidate_nodes
        solved_score = max(solved_score, candidate_score)
        if candidate_layout is not None:
            candidate_layout = normalize_layout(
                candidate_layout
            )
            candidate_info = {
                "solve_scale": 1.0,
                "width": candidate_metrics["width"],
                "height": candidate_metrics["height"],
                "ratio": (
                    candidate_metrics["width"]
                    / max(1.0, candidate_metrics["height"])
                ),
                "coverage": candidate_metrics["coverage"],
                "overlap": candidate_metrics["overlap"],
                "method": "edge-assumed",
                "forced": True,
            }
            candidate_layout, repair_info = (
                prepare_layout_for_execution(
                    candidate_layout,
                    candidate_info,
                    roi,
                )
            )
        if candidate_layout is not None:
            solved_layout = candidate_layout
            solved_score = candidate_score
            solve_info = candidate_info

    if solved_layout is None:
        (
            candidate_layout,
            candidate_score,
            candidate_info,
        ) = build_last_resort_layout(pieces, roi)
        if candidate_layout is not None:
            solved_layout = candidate_layout
            solved_score = candidate_score
            solve_info = candidate_info

    return {
        "layout": solved_layout,
        "score": solved_score,
        "nodes": solver_nodes,
        "info": solve_info,
        "pieces": pieces,
        "elapsed_ms": (
            time.monotonic() - started
        ) * 1000.0,
    }


def refine_card_layout_geometry(layout, time_limit_s=0.8):
    """保持候选拓扑不变，联合移动碎片组并闭合矩形与内部拼接边。"""
    refined = {
        piece_id: np.asarray(
            polygon,
            dtype=np.float64,
        ).copy()
        for piece_id, polygon in layout.items()
    }
    piece_ids = sorted(refined)
    if len(piece_ids) < 2:
        return refined, evaluate_layout(
            refined,
            edge_tolerance_ratio=0.07,
        )

    original = {
        piece_id: polygon.copy()
        for piece_id, polygon in refined.items()
    }
    original_centers = {
        piece_id: np.mean(polygon, axis=0)
        for piece_id, polygon in original.items()
    }
    all_points = np.vstack(list(original.values()))
    diagonal = float(np.linalg.norm(
        np.max(all_points, axis=0) - np.min(all_points, axis=0)
    ))
    maximum_translation = max(12.0, diagonal * 0.32)
    maximum_rotation = 12.0

    edge_indices = {}
    for piece_id, polygon in original.items():
        lengths = [
            np.linalg.norm(
                polygon[(index + 1) % len(polygon)] - polygon[index]
            )
            for index in range(len(polygon))
        ]
        edge_indices[piece_id] = int(np.argmax(lengths))

    def topology_preserved(candidate):
        centers = {
            piece_id: np.mean(polygon, axis=0)
            for piece_id, polygon in candidate.items()
        }
        for piece_id in piece_ids:
            if (
                np.linalg.norm(
                    centers[piece_id] - original_centers[piece_id]
                )
                > maximum_translation
            ):
                return False
            index = edge_indices[piece_id]
            source_edge = (
                original[piece_id][(index + 1) % len(original[piece_id])]
                - original[piece_id][index]
            )
            target_edge = (
                candidate[piece_id][
                    (index + 1) % len(candidate[piece_id])
                ]
                - candidate[piece_id][index]
            )
            angle = math.degrees(math.atan2(
                source_edge[0] * target_edge[1]
                - source_edge[1] * target_edge[0],
                np.dot(source_edge, target_edge),
            ))
            if abs(angle) > maximum_rotation:
                return False
        for first_index, first_id in enumerate(piece_ids):
            for second_id in piece_ids[first_index + 1:]:
                before = (
                    original_centers[second_id]
                    - original_centers[first_id]
                )
                after = centers[second_id] - centers[first_id]
                if np.dot(before, after) <= 0.0:
                    return False
        return True

    def quality(candidate):
        report = evaluate_layout(
            candidate,
            edge_tolerance_ratio=0.07,
        )
        angle_quality = max(
            0.0,
            1.0 - report["boundary_angle_error"] / 10.0,
        )
        score = (
            report["coverage"] * 0.38
            + report["internal_match"] * 0.34
            + report["corners"] * 0.08
            + report["outer_piece_ratio"] * 0.07
            + report["boundary_min_coverage"] * 0.06
            + (1.0 - report["boundary_max_gap_ratio"]) * 0.04
            + angle_quality * 0.03
            - report["overlap"] * 10.0
        )
        return score, report

    def move_group(candidate, group, dx, dy, angle=0.0):
        moved = {
            piece_id: polygon.copy()
            for piece_id, polygon in candidate.items()
        }
        group_points = np.vstack([
            moved[piece_id]
            for piece_id in group
        ])
        center = np.mean(group_points, axis=0)
        radians = math.radians(angle)
        rotation = np.array(
            [
                [math.cos(radians), -math.sin(radians)],
                [math.sin(radians), math.cos(radians)],
            ],
            dtype=np.float64,
        )
        translation = np.array([dx, dy], dtype=np.float64)
        for piece_id in group:
            moved[piece_id] = (
                (moved[piece_id] - center) @ rotation.T
                + center
                + translation
            )
        return moved

    movable_ids = piece_ids[1:]
    groups = [
        tuple(
            piece_id
            for index, piece_id in enumerate(movable_ids)
            if mask & (1 << index)
        )
        for mask in range(1, 1 << len(movable_ids))
    ]

    best_score, best_report = quality(refined)
    deadline = time.monotonic() + time_limit_s

    # 先按“哪两条边应当相接”生成整组平移建议。这里不改变排列和旋转，
    # 只把相似、平行的候选内边中点吸附到一起，解决单块移动的局部最优。
    for _ in range(3):
        proposals = []
        for first_index, first_id in enumerate(piece_ids):
            first_polygon = refined[first_id]
            for second_id in piece_ids[first_index + 1:]:
                second_polygon = refined[second_id]
                for first_edge_id in range(len(first_polygon)):
                    first_start = first_polygon[first_edge_id]
                    first_end = first_polygon[
                        (first_edge_id + 1) % len(first_polygon)
                    ]
                    first_vector = first_end - first_start
                    first_length = float(np.linalg.norm(first_vector))
                    for second_edge_id in range(len(second_polygon)):
                        second_start = second_polygon[second_edge_id]
                        second_end = second_polygon[
                            (second_edge_id + 1) % len(second_polygon)
                        ]
                        second_vector = second_end - second_start
                        second_length = float(np.linalg.norm(second_vector))
                        length_ratio = min(first_length, second_length) / max(
                            1e-9,
                            max(first_length, second_length),
                        )
                        parallel = abs(float(np.dot(
                            first_vector,
                            second_vector,
                        ))) / max(1e-9, first_length * second_length)
                        if length_ratio < 0.72 or parallel < 0.975:
                            continue
                        first_midpoint = (first_start + first_end) * 0.5
                        second_midpoint = (second_start + second_end) * 0.5
                        delta = first_midpoint - second_midpoint
                        distance = float(np.linalg.norm(delta))
                        if distance < 1.0 or distance > diagonal * 0.28:
                            continue
                        priority = (
                            length_ratio * 0.65
                            + parallel * 0.35
                            - distance / max(1.0, diagonal) * 0.30
                        )
                        for group in groups:
                            first_moves = first_id in group
                            second_moves = second_id in group
                            if first_moves == second_moves:
                                continue
                            movement = -delta if first_moves else delta
                            proposals.append((
                                priority,
                                group,
                                float(movement[0]),
                                float(movement[1]),
                            ))
        improved = False
        for _, group, dx, dy in sorted(
            proposals,
            key=lambda item: item[0],
            reverse=True,
        )[:36]:
            if time.monotonic() >= deadline:
                return refined, best_report
            candidate = move_group(refined, group, dx, dy)
            if not topology_preserved(candidate):
                continue
            score, report = quality(candidate)
            if score > best_score + 1e-5:
                refined = candidate
                best_score = score
                best_report = report
                improved = True
                break
        if not improved:
            break

    for move, angle in (
        (max(6.0, diagonal * 0.075), 4.0),
        (max(3.0, diagonal * 0.035), 2.0),
        (max(1.5, diagonal * 0.016), 1.0),
        (0.75, 0.45),
        (0.35, 0.20),
    ):
        improved = True
        rounds = 0
        while improved and rounds < 5:
            improved = False
            rounds += 1
            for group in groups:
                for dx, dy in (
                    (move, 0.0),
                    (-move, 0.0),
                    (0.0, move),
                    (0.0, -move),
                ):
                    if time.monotonic() >= deadline:
                        return refined, best_report
                    candidate = move_group(refined, group, dx, dy)
                    if not topology_preserved(candidate):
                        continue
                    score, report = quality(candidate)
                    if score > best_score + 1e-5:
                        refined = candidate
                        best_score = score
                        best_report = report
                        improved = True
            for piece_id in piece_ids:
                for rotation in (angle, -angle):
                    if time.monotonic() >= deadline:
                        return refined, best_report
                    candidate = move_group(
                        refined,
                        (piece_id,),
                        0.0,
                        0.0,
                        rotation,
                    )
                    if not topology_preserved(candidate):
                        continue
                    score, report = quality(candidate)
                    if score > best_score + 1e-5:
                        refined = candidate
                        best_score = score
                        best_report = report
                        improved = True
    return refined, best_report


def card_layout_signature(layout):
    """保留有序顶点对应关系，不能合并同形碎片的独立旋转。"""
    return tuple((int(piece_id), tuple(np.rint(
        np.asarray(layout[piece_id], dtype=float) * 0.5,
    ).astype(int).ravel())) for piece_id in sorted(layout))


def card_structure_enabled(frame_rgb, roi):
    x, y, width, height = roi
    region = frame_rgb[y:y + height, x:x + width]
    if not region.size:
        return False
    scale = min(1.0, 240.0 / max(region.shape[:2]))
    if scale < 1.0:
        region = cv2.resize(region, None, fx=scale, fy=scale)
    hsv = cv2.cvtColor(region, cv2.COLOR_RGB2HSV)
    green = ((hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 100)
             & (hsv[:, :, 1] >= 35) & (hsv[:, :, 2] >= 30))
    return float(np.mean(green)) >= 0.20


def evaluate_card_candidate(
    frame_rgb,
    pieces,
    layout,
    base_info,
    roi,
    texture_cache,
    source,
    assignment,
    allow_refine=True,
):
    """统一修复和评分不同来源的扑克牌候选。"""
    if layout is None or base_info is None:
        return None

    solve_info = dict(base_info)
    solve_info["boundary_safe"] = False
    solve_info["method"] = source
    prepared, _ = prepare_layout_for_execution(
        layout,
        solve_info,
        roi,
    )
    if prepared is None:
        prepared, _ = prepare_best_effort_layout(
            layout,
            solve_info,
            roi,
        )
        if prepared is None:
            return None
        solve_info["method"] = source + "-best-effort"
        solve_info["execution_mode"] = "BEST"

    def geometry_quality(info):
        report = info["constraint_report"]
        angle_quality = max(
            0.0,
            1.0 - report["boundary_angle_error"] / 10.0,
        )
        return (
            report["coverage"] * 0.46
            + report["internal_match"] * 0.38
            + report["boundary_min_coverage"] * 0.08
            + (1.0 - report["boundary_max_gap_ratio"]) * 0.04
            + angle_quality * 0.04
        )

    initial_geometry = geometry_quality(solve_info)
    if allow_refine:
        identity_assignment = tuple(range(len(pieces)))
        refinement_time = (
            0.8
            if tuple(assignment) == identity_assignment
            else 0.08
        )
        refined_layout, refined_report = refine_card_layout_geometry(
            layout,
            time_limit_s=refinement_time,
        )
        refined_info = dict(base_info)
        refined_info["boundary_safe"] = False
        refined_info["method"] = source
        refined_prepared, _ = prepare_layout_for_execution(
            refined_layout,
            refined_info,
            roi,
        )
        if refined_prepared is None:
            refined_prepared, _ = prepare_best_effort_layout(
                refined_layout,
                refined_info,
                roi,
            )
            if refined_prepared is not None:
                refined_info["method"] = source + "-best-effort"
                refined_info["execution_mode"] = "BEST"
        if refined_prepared is not None:
            refined_geometry = geometry_quality(refined_info)
            if refined_geometry > initial_geometry + 1e-4:
                prepared = refined_prepared
                solve_info = refined_info
                solve_info["topology_refined"] = True
                solve_info["refined_raw_report"] = {
                    "coverage": refined_report["coverage"],
                    "overlap": refined_report["overlap"],
                    "internal_match": refined_report["internal_match"],
                }

    pattern_layout = close_card_pattern_layout(prepared, solve_info)
    pattern_report = evaluate_layout(
        pattern_layout,
        edge_tolerance_ratio=0.07,
    )
    # 允许轮廓栅格化造成的极小误差，实际内部重叠仍然硬拒绝。
    if pattern_report.get("overlap", 1.0) > 0.008:
        return None

    texture = score_layout_texture(
        frame_rgb,
        pieces,
        pattern_layout,
        cache=texture_cache,
    )
    if "face_source" not in texture_cache:
        scale = min(1.0, 640.0 / max(frame_rgb.shape[:2]))
        reduced = cv2.resize(frame_rgb, None, fx=scale, fy=scale) if scale < 1.0 else frame_rgb
        reduced_pieces = [dict(piece, points=np.asarray(piece["points"]) * scale) for piece in pieces]
        texture_cache["face_source"] = (reduced, reduced_pieces, scale)
    reduced, reduced_pieces, scale = texture_cache["face_source"]
    reduced_layout = {piece_id: polygon * scale for piece_id, polygon in pattern_layout.items()}
    if texture_cache.get("card_structure_enabled", False):
        structure = score_layout_structure(frame_rgb, pieces, pattern_layout, texture_cache)
        global_pattern = {"score": structure.get("body", 0.5),
                          "confidence": structure.get("body_confidence", 0.0)}
        rank_index = {"score": 0.5 + (structure.get("index", 0.5) - 0.5)
                      * structure.get("index_confidence", 0.0),
                      "confidence": structure.get("index_confidence", 0.0),
                      "valid": structure.get("index", 0.5) >= 0.60,
                      "locked": False, "pair": None}
    else:
        structure = {"score": 0.5, "confidence": 0.0, "valid": False}
        global_pattern = score_layout_global_pattern(reduced, reduced_pieces, reduced_layout)
        rank_index = score_rank_index_diagonal(reduced, reduced_pieces, reduced_layout)
    report = {
        "coverage": pattern_report["coverage"],
        "overlap": pattern_report["overlap"],
        "corners": pattern_report["corners"],
        "outer_piece_ratio": pattern_report["outer_piece_ratio"],
        "internal_match": pattern_report["internal_match"],
        "perimeter_error": pattern_report["perimeter_error"],
        "boundary_min_coverage": pattern_report[
            "boundary_min_coverage"
        ],
        "boundary_max_gap_ratio": pattern_report[
            "boundary_max_gap_ratio"
        ],
        "boundary_angle_error": pattern_report[
            "boundary_angle_error"
        ],
    }
    solve_info["constraint_report"] = report
    effective_texture = 0.5 + (
        texture["score"] - 0.5
    ) * texture["confidence"]
    effective_global = 0.5 + (
        global_pattern["score"] - 0.5
    ) * global_pattern["confidence"]
    effective_index = rank_index["score"]
    angle_quality = max(
        0.0,
        1.0 - report["boundary_angle_error"] / 10.0,
    )
    boundary_quality = (
        report["corners"] * 0.35
        + report["outer_piece_ratio"] * 0.25
        + report["boundary_min_coverage"] * 0.25
        + angle_quality * 0.15
    )
    p = get_card_scoring_params()
    base_rank = (
        effective_texture * p["card_weight_texture"]
        + report["coverage"] * p["card_weight_coverage"]
        + report["internal_match"] * p["card_weight_internal_match"]
        + boundary_quality * p["card_weight_boundary"]
        + effective_global * p["card_weight_global"]
        + effective_index * p["card_weight_index"]
    )

    if (
        report["coverage"] >= 0.90
        and report["internal_match"] >= 0.70
        and report["corners"] >= 0.99
        and report["outer_piece_ratio"] >= 0.999
        and report["boundary_min_coverage"] >= 0.90
        and report["boundary_angle_error"] <= 5.5
    ):
        geometry_tier = 3
    elif (
        report["coverage"] >= 0.82
        and report["internal_match"] >= 0.52
        and report["corners"] >= 0.75
        and report["outer_piece_ratio"] >= 0.999
        and report["boundary_angle_error"] <= 7.0
    ):
        geometry_tier = 2
    elif (
        report["coverage"] >= 0.70
        and report["internal_match"] >= 0.20
        and report["outer_piece_ratio"] >= 0.75
    ):
        geometry_tier = 1
    else:
        geometry_tier = 0

    solve_info["texture_score"] = texture["score"]
    solve_info["texture_confidence"] = texture["confidence"]
    solve_info["global_pattern_score"] = global_pattern["score"]
    solve_info["global_pattern_confidence"] = global_pattern[
        "confidence"
    ]
    solve_info["corner_diagonal_score"] = global_pattern.get(
        "diagonal",
        0.5,
    )
    solve_info["rank_index_score"] = rank_index["score"]
    solve_info["rank_index_confidence"] = rank_index["confidence"]
    solve_info["rank_index_valid"] = rank_index["valid"]
    solve_info["rank_index_locked"] = rank_index.get("locked", False)
    solve_info["rank_index_pair"] = rank_index["pair"]
    solve_info["card_structure"] = structure
    solve_info["card_structure_score"] = structure["score"]
    solve_info["card_structure_confidence"] = structure["confidence"]
    solve_info["card_assignment"] = tuple(assignment)
    solve_info["geometry_tier"] = geometry_tier
    solve_info["card_candidate_source"] = source
    return {
        "base_rank": float(base_rank),
        "layout": prepared,
        "pattern_layout": pattern_layout,
        "raw_texture": texture,
        "info": solve_info,
    }


def card_candidate_primary_score(candidate):
    """对已经通过安全检查的候选，用花纹为主进行统一排名。"""
    info = candidate["info"]
    report = info.get("constraint_report", {})
    if info.get("card_joint_search", False):
        texture = info.get("texture_score", 0.5)
        pattern = 0.5 + (info.get("global_pattern_score", 0.5) - 0.5) * info.get("global_pattern_confidence", 0.0)
        index = info.get("rank_index_score", 0.5)
        p = get_card_scoring_params()
        angle = max(0.0, 1.0 - report.get("boundary_angle_error", 10.0) / 10.0)
        boundary = (report.get("corners", 0.0) * 0.35 + report.get("outer_piece_ratio", 0.0) * 0.25
                    + report.get("boundary_min_coverage", 0.0) * 0.25 + angle * 0.15)
        rank = float(texture * p["card_weight_texture"] + report.get("coverage", 0.0) * p["card_weight_coverage"]
                     + report.get("internal_match", 0.0) * p["card_weight_internal_match"]
                     + boundary * p["card_weight_boundary"] + pattern * p["card_weight_global"] + index * p["card_weight_index"])
        if info.get("card_structure_confidence", 0.0) >= 0.25:
            rank = rank * 0.45 + info["card_structure_score"] * 0.55
        return rank
    p = get_card_scoring_params()
    texture_score = info.get("texture_score", 0.5)
    texture_confidence = info.get("texture_confidence", 0.0)
    effective_texture = (
        0.5
        + (texture_score - 0.5) * texture_confidence
    )
    global_score = info.get("global_pattern_score", 0.5)
    global_confidence = info.get("global_pattern_confidence", 0.0)
    effective_global = (
        0.5
        + (global_score - 0.5) * global_confidence
    )
    index_score = info.get("rank_index_score", 0.5)
    index_confidence = info.get("rank_index_confidence", 0.0)
    effective_index = (
        0.5
        + (index_score - 0.5) * index_confidence
    )
    angle_quality = max(
        0.0,
        1.0
        - report.get("boundary_angle_error", 10.0) / 10.0,
    )
    boundary_quality = (
        report.get("corners", 0.0) * 0.35
        + report.get("outer_piece_ratio", 0.0) * 0.25
        + report.get("boundary_min_coverage", 0.0) * 0.25
        + angle_quality * 0.15
    )
    score = (
        effective_texture * p["card_weight_texture"]
        + report.get("coverage", 0.0) * p["card_weight_coverage"]
        + report.get("internal_match", 0.0) * p["card_weight_internal_match"]
        + boundary_quality * p["card_weight_boundary"]
        + effective_global * p["card_weight_global"]
        + effective_index * p["card_weight_index"]
    )
    geometry_tier = int(info.get("geometry_tier", 0))
    if geometry_tier == 1:
        score -= p["card_tier1_penalty"]
    elif geometry_tier <= 0:
        score -= p["card_tier0_penalty"]
    return float(score)


def select_card_candidate(candidates):
    """先比较不同刚体牌面；角标只作软证据，不锁死候选。"""
    if not candidates:
        return None
    structured=any(item['info'].get('card_structure_mode',False) for item in candidates)
    safe = list(candidates) if structured else [item for item in candidates if item["info"].get("geometry_tier", 0) >= 2]
    preview_only = not safe
    if not safe:
        safe = list(candidates)
    unique = {}
    for candidate in safe:
        candidate["primary_score"] = card_candidate_primary_score(candidate)
        key = layout_pose_key(candidate["pattern_layout"])
        previous = unique.get(key)
        if previous is None or candidate["primary_score"] > previous["primary_score"]:
            unique[key] = candidate
    ordered = sorted(unique.values(), key=lambda item: item["primary_score"], reverse=True)
    selected = ordered[0]
    info = selected["info"]
    if structured:
        preview_only=info.get('geometry_tier',0)<2
    margin = selected["primary_score"] - ordered[1]["primary_score"] if len(ordered) > 1 else 0.0
    texture = info.get("texture_score", 0.5)
    confidence = info.get("texture_confidence", 0.0)
    report = info.get("constraint_report", {})
    unique_geometry = (len(ordered) == 1 and info.get("card_search_complete", False)
                       and info.get("card_candidate_pool_complete", False)
                       and info.get("card_generated_candidate_count") == 1)
    effective_texture = lambda item: item["info"].get("texture_score", 0.5)
    competitors = [effective_texture(item) for item in ordered[1:]]
    excluded_bound = info.get("card_excluded_texture_bound")
    if excluded_bound is not None:
        competitors.append(float(excluded_bound))
    texture_margin = effective_texture(selected) - max(competitors) if competitors else 0.0
    verified = bool(not preview_only and confidence >= 0.30 and texture >= 0.62
                    and report.get("coverage", 0.0) >= 0.84
                    and report.get("internal_match", 0.0) >= 0.55
                    and report.get("outer_piece_ratio", 0.0) >= 0.999
                    and ((margin >= 0.025 and texture_margin >= 0.025) or unique_geometry))
    if structured:
        structure=info.get('card_structure',{})
        printed=structure.get('ink_fraction',0.0)>=.008 and structure.get('confidence',0.0)>=.30
        bad_outer=structure.get('outer_confidence',0.0)>=.60 and structure.get('outer',.5)<.50
        bad_index=structure.get('index_confidence',0.0)>=.60 and structure.get('index',.5)<.40
        bad_cut=structure.get('cut_integrity_confidence',0.0)>=.65 and structure.get('cut_integrity',.5)<.35
        strong=(structure.get('confidence',0.0)>=.65 and structure.get('outer',0.0)>=.65
                and structure.get('index_confidence',0.0)>=.65 and structure.get('index',0.0)>=.70
                and structure.get('body_confidence',0.0)>=.45 and structure.get('body',0.0)>=.70)
        geometry_ok=(not preview_only and report.get('coverage',0)>=.88 and report.get('overlap',1)<=.008
                     and report.get('internal_match',0)>=.55 and report.get('outer_piece_ratio',0)>=.999)
        verified=bool(printed and not bad_outer and not bad_index and not bad_cut
                      and (verified or (geometry_ok and strong and margin>=.025)))
        info['card_structure_reasons']=[reason for failed,reason in ((not printed,'insufficient-print'),
                                      (bad_outer,'outer-print-cut'),(bad_index,'misplaced-indices'),
                                      (bad_cut,'unmatched-print-cut')) if failed]
    info["selection_score"] = float(selected["primary_score"])
    info["selection_margin"] = float(margin)
    info["texture_selection_margin"] = float(texture_margin)
    info["selection_candidate_count"] = len(ordered)
    info["card_execution_ready"] = verified
    info["card_status"] = ("VERIFIED" if verified else "GEOMETRY_ONLY" if preview_only
                           else "WEAK_TEXTURE" if structured and not printed
                           else "WEAK_TEXTURE" if confidence < 0.30 else "AMBIGUOUS")
    selected["score"] = float(selected["primary_score"])
    return selected


def card_topology_primary_score(candidate):
    """全矩形扑克牌候选的专用排序，不让弱角标锁死正确拓扑。"""
    info = candidate["info"]
    report = info.get("constraint_report", {})
    texture = 0.5 + (
        info.get("texture_score", 0.5) - 0.5
    ) * info.get("texture_confidence", 0.0)
    global_pattern = 0.5 + (
        info.get("global_pattern_score", 0.5) - 0.5
    ) * info.get("global_pattern_confidence", 0.0)
    index = 0.5
    if info.get("rank_index_confidence", 0.0) >= 0.72:
        index = 0.5 + (
            info.get("rank_index_score", 0.5) - 0.5
        ) * info.get("rank_index_confidence", 0.0)
    geometry = (
        report.get("coverage", 0.0) * 0.40
        + report.get("internal_match", 0.0) * 0.35
        + report.get("corners", 0.0) * 0.15
        + report.get("outer_piece_ratio", 0.0) * 0.10
    )
    return float(
        texture * 0.62
        + global_pattern * 0.18
        + index * 0.08
        + geometry * 0.12
    )


def select_card_topology_candidate(candidates):
    """矩形碎片拓扑候选：所有合法布局按跨缝证据直接比较。"""
    if not candidates:
        return None
    for candidate in candidates:
        candidate["primary_score"] = card_topology_primary_score(
            candidate
        )
    ordered = sorted(
        candidates,
        key=lambda item: item["primary_score"],
        reverse=True,
    )
    selected = ordered[0]
    selection_margin = (
        selected["primary_score"] - ordered[1]["primary_score"]
        if len(ordered) > 1
        else 1.0
    )
    selected["score"] = float(selected["primary_score"])
    selected["info"]["selection_score"] = float(
        selected["primary_score"]
    )
    selected["info"]["selection_margin"] = float(selection_margin)
    selected["info"]["selection_candidate_count"] = len(ordered)
    selected["info"]["selection_method"] = "card-topology"
    return selected


def build_card_candidate_pool(
    frame_rgb,
    pieces,
    candidates,
    selected,
    score_function=card_candidate_primary_score,
    limit=8,
    preview_long_side=640,
):
    """生成供界面检查的扑克牌候选，不重新运行求解。"""
    if selected is None:
        return []
    for candidate in candidates:
        candidate["primary_score"] = score_function(candidate)
    ordered = [selected]
    ordered.extend(
        candidate
        for candidate in sorted(
            candidates,
            key=lambda item: item["primary_score"],
            reverse=True,
        )
        if candidate is not selected
    )
    pool = []
    for rank, candidate in enumerate(ordered[:limit], start=1):
        info = candidate["info"]
        pool.append(
            {
                "rank": rank,
                "score": float(candidate["primary_score"]),
                "selected": candidate is selected,
                "source": info.get("card_candidate_source", ""),
                "geometry_tier": int(info.get("geometry_tier", 0)),
                "assignment": list(info.get("card_assignment", ())),
                "score_items": build_ui_score_items(info),
                "preview_rgb": render_layout_preview(
                    frame_rgb,
                    pieces,
                    candidate["pattern_layout"],
                    long_side=preview_long_side,
                    fill_rectangle=True,
                ),
            }
        )
    return pool


def card_candidates_are_confident(candidates):
    """与最终执行共用牌面准入，不用相同 assignment 冒充稳定朝向。"""
    selected = select_card_candidate(candidates)
    return selected is not None and card_execution_ready(selected["info"])


def card_execution_ready(solve_info):
    return bool(solve_info and solve_info.get("card_status") == "VERIFIED"
                and solve_info.get("card_execution_ready", False))


def solve_card_piece_set_worker(frame_rgb, pieces, roi):
    """形状约束合法摆放，纹理同时决定块的身份、朝向和邻接。"""
    global _card_scoring_params
    _card_scoring_params = get_default_card_scoring_params()
    _card_scoring_params.update(load_card_scoring_settings())
    cv2.setNumThreads(1)
    started = time.monotonic()
    empty = {"layout": None, "score": 0.0, "nodes": 0, "info": None,
             "pieces": pieces, "mode": "CARD", "elapsed_ms": 0.0}
    if not 2 <= len(pieces) <= 4:
        return empty
    for piece in pieces:
        polygon = np.asarray(piece["points"], dtype=float)
        if (polygon.ndim != 2 or polygon.shape[1] != 2 or not 3 <= len(polygon) <= 32
                or not np.isfinite(polygon).all()):
            return empty
        if (abs(cv2.contourArea(polygon.astype(np.float32))) < 1.0
                or np.min(np.linalg.norm(np.roll(polygon, -1, axis=0) - polygon, axis=1)) < 1e-6):
            return empty
    cache = {"card_structure_enabled": card_structure_enabled(frame_rgb, roi)}
    geometry_refinement={"changed":0}
    if cache["card_structure_enabled"]:
        pieces,geometry_refinement=refine_card_piece_geometry(frame_rgb,pieces,roi)
        empty["pieces"]=pieces
    classification = classify_card_pieces(pieces)
    generated = generate_corner_card_candidates(frame_rgb, pieces, candidate_limit=24, cache=cache) if cache["card_structure_enabled"] else {"candidates": []}
    if cache["card_structure_enabled"] and max((item.get('structure',{}).get('score',.5) for item in generated['candidates']),default=0)<.65:
        previous=generated
        fan=generate_fan_card_candidates(frame_rgb,pieces,candidate_limit=24,cache=cache)
        strip=generate_strip_card_candidates(frame_rgb,pieces,candidate_limit=24,cache=cache)
        combined=previous['candidates']+fan['candidates']+strip['candidates']
        if combined:
            generated=dict(previous,candidates=combined,nodes=previous.get('nodes',0)+fan['nodes']+strip['nodes'],
                           search_complete=previous.get('search_complete',True) and fan['search_complete'] and strip['search_complete'],
                           candidate_pool_complete=False)
    if generated["candidates"]:
        pass
    elif classification["kind"] == "all-rectangles":
        generated = generate_rectangular_card_candidates(frame_rgb, pieces, candidate_limit=12, cache=cache)
        if not generated["candidates"]:
            generated = generate_card_graph_candidates(frame_rgb, pieces, time_limit_s=4.0, candidate_limit=12, cache=cache)
    else:
        generated = generate_card_graph_candidates(frame_rgb, pieces, time_limit_s=4.0, candidate_limit=12, cache=cache)
    nodes = generated["nodes"]
    search_complete = generated["search_complete"]
    layouts = generated["candidates"]
    geometry_seed = None
    candidates = []
    seen = set()

    def add_candidates(items):
        for item in items:
            layout = item["layout"]
            key = layout_pose_key(layout)
            if key in seen:
                continue
            seen.add(key)
            report = item.get("report") or evaluate_layout(layout, edge_tolerance_ratio=0.065)
            if report["overlap"] > 0.008 or report["coverage"] < 0.80:
                continue
            base_info = {"ratio": report["width"] / max(1.0, report["height"]),
                         "solve_scale": 1.0, "width": report["width"], "height": report["height"],
                         "coverage": report["coverage"], "overlap": report["overlap"],
                         "forced": False, "method": item["source"], "card_mode": True,
                         "card_joint_search": True, "card_search_complete": search_complete,
                         "card_candidate_pool_complete": generated.get("candidate_pool_complete", search_complete),
                         "card_generated_candidate_count": len(layouts),
                         "card_excluded_texture_bound": generated.get("excluded_texture_bound"),
                         "card_search_nodes": nodes,
                         "card_structure_mode": cache["card_structure_enabled"],
                         "card_piece_geometry_refinement": geometry_refinement}
            candidate = evaluate_card_candidate(
                frame_rgb, pieces, layout, base_info, roi, cache, item["source"],
                item.get("assignment", tuple(range(len(pieces)))), allow_refine=False)
            if candidate is not None:
                candidates.append(candidate)

    add_candidates(layouts)
    # 修复并评分后仍无可用牌面时才搜几何种子，避免正常矩形牌重复搜索。
    weak_print = bool(cache['card_structure_enabled'] and candidates
                      and max(item['info']['card_structure'].get('ink_fraction',0) for item in candidates)>=.008
                      and (max(item['info']['card_structure_score'] for item in candidates)<.70
                           or all(item['info']['card_structure'].get('index_confidence',0)>=.60
                                  and item['info']['card_structure'].get('index',.5)<.40 for item in candidates)))
    if not candidates or weak_print:
        base, _, tested, base_info = solve_rectangle_by_cover_cpp(pieces, fill_ratio=0.88, position_step=3)
        nodes += tested
        search_complete = False
        if base is not None:
            solve_scale = float(base_info["solve_scale"])
            base = {piece_id: polygon / solve_scale for piece_id, polygon in base.items()}
            base_info = dict(base_info, solve_scale=1.0,
                             width=base_info["width"] / solve_scale,
                             height=base_info["height"] / solve_scale)
            geometry_seed = (base, base_info)
            alternatives = []
            for layout, assignment in generate_all_slot_layouts(pieces, base):
                texture = score_layout_texture(frame_rgb, pieces, layout, cache=cache)
                alternatives.append({"layout": layout, "texture": texture,
                                     "source": "card-joint-cpp", "assignment": assignment})
            for alternative in alternatives:
                alternative["texture"] = relative_texture_matches(alternative["texture"], cache.get("pairs", {}))
                if cache["card_structure_enabled"]:
                    alternative["structure"] = score_layout_structure(frame_rgb, pieces, alternative["layout"], cache)
            alternatives.sort(key=lambda item: item["texture"]["score"] * 0.45
                              + item.get("structure", {}).get("score", 0.5) * 0.55
                              if cache["card_structure_enabled"] else item["texture"]["score"], reverse=True)
            generated["candidate_pool_complete"] = False
            generated["excluded_texture_bound"] = alternatives[12]["texture"]["score"] if len(alternatives) > 12 else None
            layouts = layouts + alternatives[:12]
            add_candidates(alternatives[:12])
    pairs = dict(cache.get("joint_pairs", {}))
    pairs.update(cache.get("card_graph", {}).get("texture", {}).get("pairs", {}))
    pairs.update(cache.get("pairs", {}))
    for candidate in candidates:
        relative = relative_texture_matches(candidate["raw_texture"], pairs)
        candidate["info"].update(texture_score=relative["score"], texture_confidence=relative["confidence"],
                                  raw_texture_score=candidate["raw_texture"]["score"],
                                  card_search_complete=search_complete, card_search_nodes=nodes,
                                  card_generated_candidate_count=len(layouts),
                                  card_candidate_pool_complete=generated.get("candidate_pool_complete", search_complete),
                                  card_excluded_texture_bound=generated.get("excluded_texture_bound"))
    best = select_card_candidate(candidates)
    print("CARD_JOINT kind=%s nodes=%d candidates=%d complete=%s status=%s margin=%.4f" % (
        classification["kind"], nodes, len(candidates), search_complete,
        best["info"]["card_status"] if best else "NO_RECTANGLE",
        best["info"]["selection_margin"] if best else 0.0), flush=True)
    if best is None:
        # 几何兜底仍可预览，但不会冒充花纹正确或驱动比赛自动执行。
        empty["elapsed_ms"] = (time.monotonic() - started) * 1000.0
        empty["nodes"] = nodes
        if geometry_seed is not None:
            base, info = geometry_seed
            info.update(method="card-geometry-only", card_mode=True,
                        card_status="GEOMETRY_ONLY", card_execution_ready=False, boundary_safe=False)
            prepared, _ = prepare_best_effort_layout(base, info, roi)
            if prepared is not None:
                empty.update(layout=prepared, info=info,
                             preview_rgb=render_layout_preview(frame_rgb, pieces, base, fill_rectangle=True))
        return empty
    return {"layout": best["layout"], "score": best["score"], "nodes": nodes,
            "info": best["info"], "pieces": pieces, "mode": "CARD",
            "preview_rgb": render_layout_preview(frame_rgb, pieces, best["pattern_layout"], fill_rectangle=True),
            "candidate_pool": build_card_candidate_pool(frame_rgb, pieces, candidates, best,
                                                       limit=12, preview_long_side=240),
            "elapsed_ms": (time.monotonic() - started) * 1000.0}


VISION_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "vision_settings.json",
)


def load_vision_settings():
    """从磁盘加载视觉参数，加载失败时返回空字典。"""
    try:
        with open(VISION_SETTINGS_PATH, "r", encoding="utf-8") as file:
            return json.load(file)
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
    ):
        return {}


def save_vision_settings(settings):
    """将视觉参数写入磁盘，原子写入避免损坏。"""
    temporary = VISION_SETTINGS_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)
    os.replace(temporary, VISION_SETTINGS_PATH)


CARD_SCORING_SETTINGS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "card_scoring_settings.json",
)


def load_card_scoring_settings():
    """从磁盘加载扑克牌计算参数，加载失败时返回空字典。"""
    try:
        with open(CARD_SCORING_SETTINGS_PATH, "r", encoding="utf-8") as file:
            settings = json.load(file)
            # 旧权重属于先几何后评分的算法，磁盘保留原值，新搜索使用新默认值。
            return settings if isinstance(settings, dict) and settings.get("card_scoring_version") == 2 else {}
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
    ):
        return {}


def save_card_scoring_settings(settings):
    """将扑克牌计算参数写入磁盘，原子写入避免损坏。"""
    temporary = CARD_SCORING_SETTINGS_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(settings, file, ensure_ascii=False, indent=2)
    os.replace(temporary, CARD_SCORING_SETTINGS_PATH)


def get_default_card_scoring_params():
    """返回所有扑克牌计算参数的默认值。"""
    return {
        "card_scoring_version": 2,
        "card_weight_texture": 0.78,
        "card_weight_coverage": 0.055,
        "card_weight_internal_match": 0.045,
        "card_weight_boundary": 0.0,
        "card_weight_global": 0.08,
        "card_weight_index": 0.04,
        "card_tier1_penalty": 0.12,
        "card_tier0_penalty": 0.25,
        "card_locked_filter_enabled": False,
    }


_card_scoring_params = None


def get_card_scoring_params():
    """获取当前的扑克牌计算参数（若未初始化则返回默认值）。"""
    global _card_scoring_params
    if _card_scoring_params is None:
        _card_scoring_params = get_default_card_scoring_params()
    return _card_scoring_params


def clamp_roi(roi, frame_width, frame_height):
    minimum_size = 80
    x = max(0, min(int(roi[0]), frame_width - minimum_size))
    y = max(0, min(int(roi[1]), frame_height - minimum_size))
    width = max(
        minimum_size,
        min(int(roi[2]), frame_width - x),
    )
    height = max(
        minimum_size,
        min(int(roi[3]), frame_height - y),
    )
    return x, y, width, height


def load_roi(path, default_roi, frame_width, frame_height):
    try:
        with open(path, "r", encoding="utf-8") as file:
            data = json.load(file)
        roi = (
            data["x"],
            data["y"],
            data["width"],
            data["height"],
        )
    except (
        FileNotFoundError,
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        OSError,
    ):
        roi = default_roi
    return clamp_roi(roi, frame_width, frame_height)


def save_roi(path, roi):
    temporary = "%s.%d.tmp" % (path, os.getpid())
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(
            {
                "x": roi[0],
                "y": roi[1],
                "width": roi[2],
                "height": roi[3],
            },
            file,
            ensure_ascii=False,
            indent=2,
        )
    os.replace(temporary, path)


def get_solution_box(roi):
    """返回ROI下半区的装配目标矩形区域。

    A4纸上半区为碎片初始位置，下半区为拼装目标区域。
    """
    x, y, width, height = roi
    return (
        x + 40,
        y + height // 2 + 65,
        max(80, width - 80),
        max(80, height // 2 - 105),
    )


def get_assembly_zone(roi):
    """返回下半区装配区域的边界 (x, y, w, h) 和分割线y坐标。"""
    x, y, width, height = roi
    split_y = y + height // 2
    return {
        "split_y": int(split_y),
        "x": int(x + 40),
        "y": int(split_y + 65),
        "width": int(max(80, width - 80)),
        "height": int(max(80, height // 2 - 105)),
    }


def build_ui_score_items(solve_info):
    """将当前求解的评分项转换为前端可直接展示的数值。"""
    if not solve_info:
        return []

    report = solve_info.get("constraint_report", {})
    items = []

    def add(label, value, weight=None):
        if value is None:
            return
        item = {
            "label": label,
            "value": round(float(value), 4),
        }
        if weight is not None:
            item["weight"] = round(float(weight), 4)
            item["contribution"] = round(
                float(value) * float(weight),
                4,
            )
        items.append(item)

    if "card_status" in solve_info:
        status = solve_info["card_status"]
        label = {"VERIFIED": "牌面已验证", "WEAK_TEXTURE": "花纹证据不足",
                 "GEOMETRY_ONLY": "仅几何可行"}.get(status, "牌面存在歧义")
        add(label, 1.0 if status == "VERIFIED" else 0.0)
    if "texture_score" in solve_info:
        texture_score = solve_info.get("texture_score", 0.5)
        texture_confidence = solve_info.get("texture_confidence", 0.0)
        effective_texture = 0.5 + (
            texture_score - 0.5
        ) * texture_confidence
        angle_quality = max(
            0.0,
            1.0 - report.get("boundary_angle_error", 10.0) / 10.0,
        )
        boundary_quality = (
            report.get("corners", 0.0) * 0.35
            + report.get("outer_piece_ratio", 0.0) * 0.25
            + report.get("boundary_min_coverage", 0.0) * 0.25
            + angle_quality * 0.15
        )
        global_confidence = solve_info.get(
            "global_pattern_confidence",
            0.0,
        )
        effective_global = 0.5 + (
            solve_info.get("global_pattern_score", 0.5) - 0.5
        ) * global_confidence
        index_confidence = solve_info.get(
            "rank_index_confidence",
            0.0,
        )
        effective_index = 0.5 + (
            solve_info.get("rank_index_score", 0.5) - 0.5
        ) * index_confidence
        if solve_info.get("card_joint_search", False):
            effective_texture = texture_score
            effective_index = solve_info.get("rank_index_score", 0.5)
            p = get_card_scoring_params()
            scale = 0.45 if solve_info.get("card_structure_confidence", 0.0) >= 0.25 else 1.0
            add("相对拼缝匹配", effective_texture, p["card_weight_texture"] * scale)
            add("原始拼缝分", solve_info.get("raw_texture_score"))
            add("矩形覆盖度", report.get("coverage", 0.0), p["card_weight_coverage"] * scale)
            add("内部边匹配", report.get("internal_match", 0.0), p["card_weight_internal_match"] * scale)
            add("外框质量", boundary_quality, p["card_weight_boundary"] * scale)
            add("全局牌面", effective_global, p["card_weight_global"] * scale)
            add("对角角标", effective_index, p["card_weight_index"] * scale)
            if scale < 1.0:
                structure = solve_info["card_structure"]
                add("牌面结构", structure["score"], 0.55)
                add("切开花色留在内部", structure.get("outer"))
                add("角标位置与朝向", structure.get("index"))
                add("牌面图案完整度", structure.get("body"))
                add("切口图案跨片接合", structure.get("cut_integrity"))
                if structure.get('letter_index_confidence',0)>.0:
                    add("两端完整字形串", structure.get("letter_index"))
            add("不同牌面分差", solve_info.get("selection_margin"))
        else:
            p = get_card_scoring_params()
            add("跨缝连续", effective_texture, p["card_weight_texture"])
            add("矩形覆盖度", report.get("coverage", 0.0), p["card_weight_coverage"])
            add("内部边匹配", report.get("internal_match", 0.0), p["card_weight_internal_match"])
            add("外框质量", boundary_quality, p["card_weight_boundary"])
            add("全局牌面", effective_global, p["card_weight_global"])
            add("对角角标", effective_index, p["card_weight_index"])
        add("纹理证据", texture_confidence)
        add("角标证据", solve_info.get("rank_index_confidence", 0.0))
        add("最终候选", solve_info.get("selection_score"))
        return items

    add("矩形覆盖度", report.get("coverage"))
    add("内部边匹配", report.get("internal_match"))
    add("四角直角", report.get("corners"))
    add("外边界完整", report.get("boundary_min_coverage"))
    add("外框碎片占比", report.get("outer_piece_ratio"))
    return items


def create_solver_executor():
    """创建单进程求解器，避免求解占满相机主循环。"""
    return concurrent.futures.ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    )


def stop_solver_executor(executor, future):
    """立即停止当前求解进程，并返回一个可继续使用的新执行器。"""
    if future is not None:
        future.cancel()
    processes = list(getattr(executor, "_processes", {}).values())
    try:
        executor.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        executor.shutdown(wait=False)
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=0.2)
    return create_solver_executor()


def competition_candidate_safe(
    solved_display,
    motion_plan,
    expected_piece_count,
):
    """判断候选是否具备强制执行所需的完整性与无重叠条件。"""
    if not 2 <= int(expected_piece_count) <= 4:
        return False
    if (
        not solved_display
        or not motion_plan
        or len(solved_display) != expected_piece_count
        or len(motion_plan) != expected_piece_count
    ):
        return False

    piece_ids = [int(item["piece_id"]) for item in solved_display]
    motion_piece_ids = [int(item["piece_id"]) for item in motion_plan]
    if (
        len(set(piece_ids)) != expected_piece_count
        or len(set(motion_piece_ids)) != expected_piece_count
        or set(piece_ids) != set(motion_piece_ids)
    ):
        return False
    display_layout = {
        int(item["piece_id"]): np.asarray(
            item["points"],
            dtype=np.float32,
        )
        for item in solved_display
    }
    if layout_has_interior_overlap(display_layout):
        return False
    return True


def competition_candidate_confidence(solve_info, solved_score):
    """优先使用候选综合选择分，缺失时退回求解器分数。"""
    value = (
        solve_info.get("selection_score")
        if solve_info is not None
        else None
    )
    try:
        confidence = float(solved_score if value is None else value)
    except (TypeError, ValueError):
        confidence = float(solved_score)
    return confidence if math.isfinite(confidence) else 0.0


def competition_result_ready(
    solved_display,
    motion_plan,
    solve_info,
    expected_piece_count,
    mode=None,
):
    """普通拼图保留原行为；扑克牌必须有明确的牌面准入结果。"""
    if not competition_candidate_safe(
        solved_display,
        motion_plan,
        expected_piece_count,
    ):
        return False
    is_card = str(mode).upper() == "CARD" or bool(solve_info and (
        solve_info.get("card_mode") or "texture_score" in solve_info
        or str(solve_info.get("method", "")).startswith("card-")))
    if is_card:
        return card_execution_ready(solve_info)
    return True


def competition_timeout_reached(
    mode,
    started_at,
    best_candidate,
    now=None,
):
    """普通拼图和扑克牌累计运行80秒后启用最佳安全候选。"""
    now = time.monotonic() if now is None else float(now)
    return (
        str(mode).upper() in ("NORMAL", "CARD")
        and float(started_at) > 0
        and now - float(started_at) >= 80.0
        and best_candidate is not None
    )


def competition_retry_limit_reached(
    retry_count,
    best_candidate,
    retry_limit=10,
):
    """达到重试上限时，只允许恢复已保存的最高置信度可执行候选。"""
    return (
        int(retry_count) >= int(retry_limit)
        and best_candidate is not None
    )


def main():
    global _card_scoring_params
    cv2.setLogLevel(2)
    portrait_mode = os.environ.get("PUZZLE_PORTRAIT", "0") == "1"
    capture_width = 1280
    capture_height = 720
    camera_width = 720 if portrait_mode else capture_width
    camera_height = 1280 if portrait_mode else capture_height
    portrait_rotation = os.environ.get(
        "PUZZLE_ROTATION",
        "CW",
    ).upper()

    default_roi = (
        (10, 100, 700, 900)
        if portrait_mode
        else (380, 10, 520, 700)
    )
    roi_settings_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "roi_settings.json",
    )
    roi_x, roi_y, roi_width, roi_height = load_roi(
        roi_settings_path,
        default_roi,
        camera_width,
        camera_height,
    )
    if portrait_mode and (
        roi_x,
        roi_y,
        roi_width,
        roi_height,
    ) in (
        (100, 10, 520, 700),
        (10, 380, 700, 520),
    ):
        roi_x, roi_y, roi_width, roi_height = default_roi
        save_roi(roi_settings_path, default_roi)

    min_piece_area = 1500
    max_piece_area_ratio = 0.35
    max_piece_count = 4
    polygon_epsilon = 0.015

    def create_camera():
        return camera.Camera(
            capture_width,
            capture_height,
            image.Format.FMT_RGB888,
            fps=30,
            buff_num=3,
        )

    cam = RecoveringCamera(
        create_camera,
        reset_usb_video_device,
    )
    disp = display.Display()
    touch = touchscreen.TouchScreen()

    fps = 0.0
    fps_frames = 0
    fps_start = time.monotonic()
    last_print_time = 0.0
    touch_was_pressed = False
    current_threshold = 128
    saved = load_vision_settings()
    background_mode = str(
        saved.get("background_mode", "GREEN")
    ).upper()
    green_method = str(
        saved.get("green_method", "largest")
    ).lower()
    green_auto = bool(saved.get("green_auto", True))
    auto_threshold = bool(saved.get("auto_threshold", True))
    manual_threshold = min(255, max(0, int(saved.get("manual_threshold", 128))))
    polarity_mode = str(saved.get("polarity_mode", "AUTO")).upper()
    green_hue_min = min(255, max(0, int(saved.get("green_hue_min", 30))))
    green_hue_max = min(255, max(0, int(saved.get("green_hue_max", 95))))
    green_sat_min = min(255, max(0, int(saved.get("green_sat_min", 20))))
    green_val_min = min(255, max(0, int(saved.get("green_val_min", 6))))
    green_close_kernel = min(21, max(1, int(saved.get("green_close_kernel", 7))))
    green_close_iter = min(5, max(0, int(saved.get("green_close_iter", 2))))
    paper_close_kernel = min(15, max(1, int(saved.get("paper_close_kernel", 5))))
    paper_close_iter = min(5, max(0, int(saved.get("paper_close_iter", 1))))
    min_piece_area = min(
        50000, max(100, int(saved.get("min_piece_area", 1500)))
    )
    assembly_gap_pixels = min(
        80,
        max(0, int(saved.get("assembly_gap_pixels", 36))),
    )
    tuning_open = False
    solve_requested = False
    card_requested = False
    solved_display = None
    solved_mode = ""
    solved_score = 0.0
    solved_ratio = 0.0
    solve_info = None
    solve_pieces = []
    current_result_preview = None
    motion_plan = []
    candidate_pool_items = []
    saved_card = load_card_scoring_settings()
    _card_scoring_params = get_default_card_scoring_params()
    _card_scoring_params.update(saved_card)
    solver_message = ""
    solver_nodes = 0
    solver_ms = 0.0
    recent_piece_sets = []
    green_auto_state = {}
    solver_executor = create_solver_executor()
    solver_future = None
    solve_started_at = 0.0
    pending_solve_until = 0.0
    pending_solve_mode = ""
    active_solver_mode = ""
    pending_card_frame = None
    pending_card_pieces = None
    active_solve_frame = None
    last_capture_name = ""
    last_capture_time = 0.0
    ui_bridge = UiBridge()
    ui_bridge.clear_result()
    ui_bridge.clear_candidates()
    serial_controller = SerialController()
    learned_templates = load_templates()
    ui_mode = "CARD"
    competition_mode = bool(saved.get("competition_mode", False))
    competition_active = False
    competition_retry_count = 0
    competition_retry_at = 0.0
    competition_started_at = 0.0
    competition_best_candidate = None
    competition_forced_best = False
    camera_was_online = False
    offline_preview_published = False
    reported_camera_error = ""
    button_boxes = get_button_boxes(
        camera_width,
        camera_height,
    )
    solution_box = get_solution_box(
        (roi_x, roi_y, roi_width, roi_height)
    )
    print("Puzzle detector started", flush=True)

    while not app.need_exit():
        solve_requested = False
        card_requested = False
        capture_requested = False
        control = ui_bridge.read_control()
        if control is not None:
            if any(
                key in control
                for key in (
                    "background_mode",
                    "green_auto",
                    "roi_x",
                    "roi_y",
                    "roi_width",
                    "roi_height",
                )
            ):
                green_auto_state.clear()
            requested_mode = str(
                control.get("mode", ui_mode)
            ).upper()
            if requested_mode in ("FIRST", "NORMAL", "CARD"):
                if requested_mode != ui_mode:
                    ui_mode = requested_mode
                    solved_display = None
                    solved_mode = ""
                    motion_plan = []
                    ui_bridge.clear_result()
                    candidate_pool_items = []
                    ui_bridge.clear_candidates()
            if any(
                key in control
                for key in (
                    "background_mode",
                    "green_auto",
                    "green_hue_min",
                    "green_hue_max",
                    "green_sat_min",
                    "green_val_min",
                    "roi_x",
                    "roi_y",
                    "roi_width",
                    "roi_height",
                )
            ):
                candidate_pool_items = []
                ui_bridge.clear_candidates()
            if "auto_threshold" in control:
                auto_threshold = bool(control["auto_threshold"])
            if "manual_threshold" in control:
                manual_threshold = min(
                    255,
                    max(0, int(control["manual_threshold"])),
                )
            if "polarity_mode" in control:
                requested_polarity = str(
                    control["polarity_mode"]
                ).upper()
                if requested_polarity in ("AUTO", "LIGHT", "DARK"):
                    polarity_mode = requested_polarity
            if "background_mode" in control:
                requested_background = str(
                    control["background_mode"]
                ).upper()
                if requested_background in ("BLACK", "GREEN"):
                    background_mode = requested_background
            if "green_method" in control:
                requested_method = str(
                    control["green_method"]
                ).lower()
                if requested_method in ("border", "largest"):
                    green_method = requested_method
            if "green_auto" in control:
                green_auto = bool(control["green_auto"])
            if "green_hue_min" in control:
                green_hue_min = min(255, max(0, int(control["green_hue_min"])))
            if "green_hue_max" in control:
                green_hue_max = min(255, max(0, int(control["green_hue_max"])))
            if "green_sat_min" in control:
                green_sat_min = min(255, max(0, int(control["green_sat_min"])))
            if "green_val_min" in control:
                green_val_min = min(255, max(0, int(control["green_val_min"])))
            if "green_close_kernel" in control:
                green_close_kernel = min(21, max(1, int(control["green_close_kernel"])))
            if "green_close_iter" in control:
                green_close_iter = min(5, max(0, int(control["green_close_iter"])))
            if "paper_close_kernel" in control:
                paper_close_kernel = min(15, max(1, int(control["paper_close_kernel"])))
            if "paper_close_iter" in control:
                paper_close_iter = min(5, max(0, int(control["paper_close_iter"])))
            if "min_piece_area" in control:
                min_piece_area = min(
                    50000,
                    max(100, int(control["min_piece_area"])),
                )
            if "assembly_gap_pixels" in control:
                assembly_gap_pixels = min(
                    80,
                    max(0, int(control["assembly_gap_pixels"])),
                )
            if "competition_mode" in control:
                competition_mode = bool(control["competition_mode"])
                if not competition_mode:
                    competition_active = False
                    competition_retry_at = 0.0
                    competition_started_at = 0.0
                    competition_best_candidate = None
                    competition_forced_best = False
            if any(
                key in control
                for key in (
                    "roi_x",
                    "roi_y",
                    "roi_width",
                    "roi_height",
                )
            ):
                new_roi = clamp_roi(
                    (
                        control.get("roi_x", roi_x),
                        control.get("roi_y", roi_y),
                        control.get("roi_width", roi_width),
                        control.get("roi_height", roi_height),
                    ),
                    camera_width,
                    camera_height,
                )
                if new_roi != (
                    roi_x,
                    roi_y,
                    roi_width,
                    roi_height,
                ):
                    roi_x, roi_y, roi_width, roi_height = new_roi
                    solution_box = get_solution_box(new_roi)
                    save_roi(roi_settings_path, new_roi)
                    recent_piece_sets = []
                    solved_display = None
                    solved_mode = ""
                    motion_plan = []
                    ui_bridge.clear_result()
            serial_controller.configure(
                port=control.get("serial_port"),
                baud=control.get("serial_baud"),
                pick_z=control.get("serial_pick_z"),
                place_z=control.get("serial_place_z"),
            )
            action = str(control.get("action", "")).lower()
            if action == "solve":
                if ui_mode == "CARD":
                    card_requested = True
                else:
                    solve_requested = True
            elif action == "competition_start":
                competition_active = competition_mode
                competition_retry_count = 0
                competition_retry_at = 0.0
                competition_started_at = time.monotonic()
                competition_best_candidate = None
                competition_forced_best = False
                if competition_active:
                    if ui_mode == "CARD":
                        card_requested = True
                    else:
                        solve_requested = True
            elif action == "stop_solve":
                competition_active = False
                competition_retry_at = 0.0
                competition_started_at = 0.0
                competition_best_candidate = None
                competition_forced_best = False
                pending_solve_until = 0.0
                pending_solve_mode = ""
                pending_card_frame = None
                pending_card_pieces = None
                if solver_future is not None:
                    solver_executor = stop_solver_executor(
                        solver_executor,
                        solver_future,
                    )
                    solver_future = None
                active_solver_mode = ""
                active_solve_frame = None
                solver_message = "STOPPED"
            elif action == "capture":
                capture_requested = True
            elif action == "shutdown":
                print("Shutdown requested by frontend", flush=True)
                break
            elif action == "serial_connect":
                serial_controller.connect()
            elif action == "serial_disconnect":
                serial_controller.disconnect()
            elif action in (
                "arm_move_absolute",
                "arm_move_relative",
            ):
                serial_controller.move(
                    control.get("arm_x", 0),
                    control.get("arm_y", 0),
                    control.get("arm_z", 0),
                    control.get("arm_rotation_cdeg", 0),
                    relative=action == "arm_move_relative",
                )
            elif action == "arm_home":
                serial_controller.home()
            elif action == "arm_send_plan":
                if (solved_mode != "CARD" and ui_mode != "CARD") or card_execution_ready(solve_info):
                    serial_controller.send_motion_plan(motion_plan)
                else:
                    solver_message = "CARD AMBIGUOUS"
            elif action == "platform_query_position":
                serial_controller.query_position()
            elif action in (
                "calibration_visual_a",
                "calibration_visual_b",
                "calibration_visual_c",
                "calibration_visual_d",
                "calibration_visual_e",
                "calibration_visual_f",
            ):
                point = ui_bridge.preview_to_camera(
                    control.get("calibration_preview_x", 0),
                    control.get("calibration_preview_y", 0),
                )
                if point is not None:
                    serial_controller.record_visual_point(
                        action[-1],
                        point[0],
                        point[1],
                    )
            elif action in (
                "calibration_platform_a",
                "calibration_platform_b",
                "calibration_platform_c",
                "calibration_platform_d",
                "calibration_platform_e",
                "calibration_platform_f",
            ):
                serial_controller.record_platform_point(action[-1])
            elif action == "calibration_compute":
                serial_controller.calculate_calibration()
            elif action == "learn_template":
                if 2 <= len(pieces) <= 4:
                    roi_rgb = frame_rgb[
                        roi_y:roi_y + roi_height,
                        roi_x:roi_x + roi_width,
                    ]
                    learned = learn_templates(
                        roi_rgb, pieces,
                        (roi_x, roi_y, roi_width, roi_height),
                    )
                    if learned:
                        save_templates(learned)
                        learned_templates = learned
                        solver_message = "LEARN OK"
                    else:
                        solver_message = "LEARN FAIL"
                else:
                    solver_message = "LEARN NEED 2-4"

            # 参数变更后立即持久化
            save_vision_settings({
                "background_mode": background_mode,
                "green_method": green_method,
                "green_auto": bool(green_auto),
                "auto_threshold": bool(auto_threshold),
                "manual_threshold": int(manual_threshold),
                "polarity_mode": polarity_mode,
                "green_hue_min": int(green_hue_min),
                "green_hue_max": int(green_hue_max),
                "green_sat_min": int(green_sat_min),
                "green_val_min": int(green_val_min),
                "green_close_kernel": int(green_close_kernel),
                "green_close_iter": int(green_close_iter),
                "paper_close_kernel": int(paper_close_kernel),
                "paper_close_iter": int(paper_close_iter),
                "min_piece_area": int(min_piece_area),
                "assembly_gap_pixels": int(assembly_gap_pixels),
                "competition_mode": bool(competition_mode),
            })
            # 扑克牌计算参数持久化
            _card_param_keys = {
                "card_weight_texture",
                "card_weight_coverage",
                "card_weight_internal_match",
                "card_weight_boundary",
                "card_weight_global",
                "card_weight_index",
                "card_tier1_penalty",
                "card_tier0_penalty",
                "card_locked_filter_enabled",
            }
            if any(key in control for key in _card_param_keys):
                params_changed = False
                for key in _card_param_keys:
                    if key in control:
                        val = control[key]
                        if key == "card_locked_filter_enabled":
                            val = bool(val)
                        else:
                            val = float(val)
                        if _card_scoring_params.get(key) != val:
                            _card_scoring_params[key] = val
                            params_changed = True
                if params_changed:
                    save_card_scoring_settings(_card_scoring_params)
                    candidate_pool_items = []
                    ui_bridge.clear_candidates()
            # 强制下一帧 publish_state 不节流，避免 Web UI 在两个文件之间
            # 读到旧状态导致滑块回弹。
            ui_bridge.last_state_time = 0.0

        serial_controller.service()
        img = cam.read()
        if img is None:
            if cam.last_error and cam.last_error != reported_camera_error:
                print(
                    "CAMERA_OFFLINE %s" % cam.last_error,
                    flush=True,
                )
                reported_camera_error = cam.last_error
            if camera_was_online:
                print("CAMERA_DISCONNECTED", flush=True)
            camera_was_online = False
            recent_piece_sets = []
            green_auto_state.clear()
            pending_solve_until = 0.0
            pending_solve_mode = ""
            pending_card_frame = None
            pending_card_pieces = None
            solver_message = "CAMERA OFFLINE"
            if competition_active and solver_future is None:
                competition_retry_at = time.monotonic() + 0.5

            if not offline_preview_published:
                offline_frame = np.zeros(
                    (camera_height, camera_width, 3),
                    dtype=np.uint8,
                )
                cv2.putText(
                    offline_frame,
                    "CAMERA OFFLINE - RETRYING",
                    (35, min(camera_height - 30, 180)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (255, 255, 255),
                    2,
                    cv2.LINE_AA,
                )
                ui_bridge.publish_live(
                    offline_frame,
                    np.zeros(
                        (roi_height, roi_width),
                        dtype=np.uint8,
                    ),
                    (roi_x, roi_y, roi_width, roi_height),
                    force=True,
                )
                offline_preview_published = True

            ui_bridge.publish_state(
                {
                    "mode": ui_mode.lower(),
                    "camera_ok": False,
                    "fps": 0.0,
                    "piece_count": 0,
                    "auto_threshold": bool(auto_threshold),
                    "manual_threshold": int(manual_threshold),
                    "current_threshold": int(current_threshold),
                    "polarity_mode": polarity_mode,
                    "background_mode": background_mode,
                    "green_method": green_method,
                    "green_auto": bool(green_auto),
                    "green_detected_hue_min": 0,
                    "green_detected_hue_max": 0,
                    "green_detected_sat_min": 0,
                    "green_detected_val_min": 0,
                    "green_hue_min": int(green_hue_min),
                    "green_hue_max": int(green_hue_max),
                    "green_sat_min": int(green_sat_min),
                    "green_val_min": int(green_val_min),
                    "green_close_kernel": int(green_close_kernel),
                    "green_close_iter": int(green_close_iter),
                    "paper_close_kernel": int(paper_close_kernel),
                    "paper_close_iter": int(paper_close_iter),
                    "detected_polarity": "",
                    "min_piece_area": int(min_piece_area),
                    "assembly_gap_pixels": int(assembly_gap_pixels),
                    "camera_width": int(camera_width),
                    "camera_height": int(camera_height),
                    "roi_x": int(roi_x),
                    "roi_y": int(roi_y),
                    "roi_width": int(roi_width),
                    "roi_height": int(roi_height),
                    "assembly_split_y": int(roi_y + roi_height // 2),
                    "solving": bool(solver_future is not None),
                    "solver_message": solver_message,
                    "score": round(float(solved_score), 4),
                    "ratio": round(float(solved_ratio), 4),
                    "solver_ms": round(float(solver_ms), 1),
                    "solver_nodes": int(solver_nodes),
                    "solved_mode": solved_mode.lower(),
                    "last_capture_name": last_capture_name,
                    "score_items": build_ui_score_items(solve_info),
                    "motion_plan": motion_plan,
                    "motion_plan_count": len(motion_plan),
                    "solved_display": solved_display or [],
                    "candidate_items": candidate_pool_items,
                    "card_solver_revision": "structure-portfolio-20261013",
                    "card_scoring": get_card_scoring_params(),
                    "competition_mode": bool(competition_mode),
                    "competition_active": bool(competition_active),
                    "competition_retry_count": int(
                        competition_retry_count
                    ),
                    **serial_controller.state(),
                }
            )
            time.sleep(0.08)
            continue

        if not camera_was_online:
            print("CAMERA_ONLINE", flush=True)
            fps = 0.0
            fps_frames = 0
            fps_start = time.monotonic()
            if solver_message == "CAMERA OFFLINE":
                solver_message = ""
        camera_was_online = True
        offline_preview_published = False
        reported_camera_error = ""
        frame_rgb = image.image2cv(
            img,
            ensure_bgr=False,
            copy=False,
        )
        frame_height, frame_width = frame_rgb.shape[:2]
        if (
            frame_width != camera_width
            or frame_height != camera_height
        ):
            camera_width = frame_width
            camera_height = frame_height
            roi_x, roi_y, roi_width, roi_height = clamp_roi(
                (roi_x, roi_y, roi_width, roi_height),
                camera_width,
                camera_height,
            )
            solution_box = get_solution_box(
                (roi_x, roi_y, roi_width, roi_height)
            )
            button_boxes = get_button_boxes(
                camera_width,
                camera_height,
            )
        if os.path.exists("/tmp/puzzle_capture_once"):
            os.remove("/tmp/puzzle_capture_once")
            cv2.imwrite(
                "/tmp/puzzle_frame.png",
                cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR),
            )

        touch_status = touch.read()
        touch_clicked = touch_status[2] and not touch_was_pressed
        if touch_clicked:
            touch_args = (
                camera_width,
                camera_height,
                disp.width(),
                disp.height(),
            )
            if not tuning_open:
                if touch_in_box(
                    touch_status,
                    button_boxes["solve"],
                    *touch_args,
                ):
                    solve_requested = True
                elif touch_in_box(
                    touch_status,
                    button_boxes["card_solve"],
                    *touch_args,
                ):
                    card_requested = True
                elif touch_in_box(
                    touch_status,
                    button_boxes["tune"],
                    *touch_args,
                ):
                    tuning_open = True
                elif touch_in_box(
                    touch_status,
                    button_boxes["capture"],
                    *touch_args,
                ):
                    capture_requested = True
            elif touch_in_box(
                touch_status,
                button_boxes["close"],
                *touch_args,
            ):
                tuning_open = False
            elif touch_in_box(
                touch_status,
                button_boxes["threshold_down"],
                *touch_args,
            ):
                if auto_threshold:
                    manual_threshold = current_threshold
                manual_threshold = max(0, manual_threshold - 5)
                auto_threshold = False
            elif touch_in_box(
                touch_status,
                button_boxes["threshold_up"],
                *touch_args,
            ):
                if auto_threshold:
                    manual_threshold = current_threshold
                manual_threshold = min(255, manual_threshold + 5)
                auto_threshold = False
            elif touch_in_box(
                touch_status,
                button_boxes["auto_threshold"],
                *touch_args,
            ):
                auto_threshold = True
            elif touch_in_box(
                touch_status,
                button_boxes["polarity"],
                *touch_args,
            ):
                if polarity_mode == "AUTO":
                    polarity_mode = "LIGHT"
                elif polarity_mode == "LIGHT":
                    polarity_mode = "DARK"
                else:
                    polarity_mode = "AUTO"
            elif touch_in_box(
                touch_status,
                button_boxes["area_down"],
                *touch_args,
            ):
                min_piece_area = max(100, min_piece_area - 250)
            elif touch_in_box(
                touch_status,
                button_boxes["area_up"],
                *touch_args,
            ):
                min_piece_area = min(50000, min_piece_area + 250)
            elif touch_in_box(
                touch_status,
                button_boxes["green_method"],
                *touch_args,
            ):
                green_method = "border" if green_method == "largest" else "largest"
            elif touch_in_box(
                touch_status,
                button_boxes["green_sat_down"],
                *touch_args,
            ):
                green_sat_min = max(0, green_sat_min - 5)
            elif touch_in_box(
                touch_status,
                button_boxes["green_sat_up"],
                *touch_args,
            ):
                green_sat_min = min(255, green_sat_min + 5)
            elif touch_in_box(
                touch_status,
                button_boxes["green_close_k_down"],
                *touch_args,
            ):
                green_close_kernel = max(3, green_close_kernel - 2)
            elif touch_in_box(
                touch_status,
                button_boxes["green_close_k_up"],
                *touch_args,
            ):
                green_close_kernel = min(21, green_close_kernel + 2)
            elif touch_in_box(
                touch_status,
                button_boxes["green_close_i_down"],
                *touch_args,
            ):
                green_close_iter = max(1, green_close_iter - 1)
            elif touch_in_box(
                touch_status,
                button_boxes["green_close_i_up"],
                *touch_args,
            ):
                green_close_iter = min(5, green_close_iter + 1)
            elif touch_in_box(
                touch_status,
                button_boxes["paper_close_k_down"],
                *touch_args,
            ):
                paper_close_kernel = max(3, paper_close_kernel - 2)
            elif touch_in_box(
                touch_status,
                button_boxes["paper_close_k_up"],
                *touch_args,
            ):
                paper_close_kernel = min(15, paper_close_kernel + 2)
            elif touch_in_box(
                touch_status,
                button_boxes["paper_close_i_down"],
                *touch_args,
            ):
                paper_close_iter = max(1, paper_close_iter - 1)
            elif touch_in_box(
                touch_status,
                button_boxes["paper_close_i_up"],
                *touch_args,
            ):
                paper_close_iter = min(5, paper_close_iter + 1)
        touch_was_pressed = touch_status[2]
        if os.path.exists("/tmp/puzzle_solve_once"):
            os.remove("/tmp/puzzle_solve_once")
            solve_requested = True
        if os.path.exists("/tmp/puzzle_card_solve_once"):
            os.remove("/tmp/puzzle_card_solve_once")
            card_requested = True
        if os.path.exists("/tmp/puzzle_dataset_capture_once"):
            os.remove("/tmp/puzzle_dataset_capture_once")
            capture_requested = True

        pieces, threshold_info = detect_pieces(
            frame_rgb,
            (roi_x, roi_y, roi_width, roi_height),
            min_area=min_piece_area,
            max_area_ratio=max_piece_area_ratio,
            max_pieces=max_piece_count,
            polygon_epsilon=polygon_epsilon,
            threshold=None if auto_threshold else manual_threshold,
            polarity_mode=polarity_mode,
            background_mode=background_mode,
            green_method=green_method,
            green_auto=green_auto,
            green_auto_state=green_auto_state,
            green_hue_min=green_hue_min,
            green_hue_max=green_hue_max,
            green_sat_min=green_sat_min,
            green_val_min=green_val_min,
            green_close_kernel=green_close_kernel,
            green_close_iter=green_close_iter,
            paper_close_kernel=paper_close_kernel,
            paper_close_iter=paper_close_iter,
        )
        current_threshold = threshold_info["threshold"]
        if capture_requested:
            last_capture_name = save_capture(
                frame_rgb,
                threshold_info["mask"],
                pieces,
                threshold_info,
                (roi_x, roi_y, roi_width, roi_height),
                {
                    "auto_threshold": bool(auto_threshold),
                    "manual_threshold": int(manual_threshold),
                    "polarity_mode": polarity_mode,
                    "background_mode": background_mode,
                    "green_method": green_method,
                    "green_auto": bool(green_auto),
                    "min_piece_area": int(min_piece_area),
                    "max_piece_area_ratio": float(
                        max_piece_area_ratio
                    ),
                    "polygon_epsilon": float(polygon_epsilon),
                    "portrait_rotation": portrait_rotation,
                },
            )
            last_capture_time = time.monotonic()
        frame_time = time.monotonic()
        recent_piece_sets = [
            item
            for item in recent_piece_sets
            if frame_time - item[0] <= 0.8
        ]
        if 2 <= len(pieces) <= 4:
            recent_piece_sets.append(
                (
                    frame_time,
                    sum(
                        piece["area"] * piece["solidity"]
                        for piece in pieces
                    ),
                    pieces,
                )
            )

        if (
            competition_active
            and competition_retry_at > 0
            and time.monotonic() >= competition_retry_at
            and solver_future is None
            and pending_solve_until <= 0
            and not competition_result_ready(
                solved_display,
                motion_plan,
                solve_info,
                len(solve_pieces),
            )
        ):
            competition_retry_at = 0.0
            if ui_mode == "CARD":
                card_requested = True
            else:
                solve_requested = True

        if solve_requested:
            if solver_future is not None:
                solver_message = "SOLVING"
            else:
                solved_display = None
                solved_mode = ""
                solve_info = None
                solve_pieces = []
                current_result_preview = None
                motion_plan = []
                candidate_pool_items = []
                pending_solve_until = time.monotonic() + 2.0
                pending_solve_mode = (
                    "FIRST"
                    if ui_mode == "FIRST"
                    else "NORMAL"
                )
                pending_card_frame = None
                pending_card_pieces = None
                solver_message = "HOLD STILL"
                solver_ms = 0.0
                ui_bridge.clear_result()
                ui_bridge.clear_candidates()

        if card_requested:
            if solver_future is not None:
                solver_message = "CARD BUSY"
            elif 2 <= len(pieces) <= 4:
                solved_display = None
                solved_mode = ""
                solve_info = None
                solve_pieces = []
                current_result_preview = None
                motion_plan = []
                candidate_pool_items = []
                pending_solve_until = time.monotonic() + 2.0
                pending_solve_mode = "CARD"
                pending_card_frame = None
                pending_card_pieces = None
                solver_message = "CARD HOLD"
                solver_ms = 0.0
                ui_bridge.clear_result()
                ui_bridge.clear_candidates()
            else:
                solver_message = "CARD NEED 2-4"

        if (
            pending_solve_until > 0
            and solver_future is None
        ):
            stable_pieces = build_stable_piece_set(
                recent_piece_sets
            )
            stability_fallback = False
            if (
                stable_pieces is None
                and time.monotonic() >= pending_solve_until
            ):
                stable_pieces = build_best_effort_piece_set(
                    recent_piece_sets
                )
                stability_fallback = stable_pieces is not None
            card_ready = (
                pending_solve_mode == "CARD"
                and stable_pieces is not None
            )
            if stable_pieces is not None and (
                pending_solve_mode in ("FIRST", "NORMAL")
                or card_ready
            ):
                pending_solve_until = 0.0
                solved_display = None
                solved_mode = ""
                motion_plan = []
                solved_score = 0.0
                solved_ratio = 0.0
                solver_nodes = 0
                solver_message = (
                    "SOLVING BEST"
                    if stability_fallback
                    else "SOLVING"
                )
                solve_started_at = time.monotonic()
                active_solver_mode = pending_solve_mode
                active_solve_frame = (
                    frame_rgb.copy()
                )
                solve_roi = (
                    roi_x,
                    roi_y,
                    roi_width,
                    roi_height,
                )
                if active_solver_mode == "CARD":
                    solver_message = (
                        "CARD SOLVING BEST"
                        if stability_fallback
                        else "CARD SOLVING"
                    )
                    solver_future = solver_executor.submit(
                        solve_card_piece_set_worker,
                        active_solve_frame,
                        stable_pieces,
                        solve_roi,
                    )
                elif (
                    active_solver_mode == "FIRST"
                    and learned_templates
                ):
                    # 第一问模板匹配：直接在主线做，速度快
                    solver_message = "TEMPLATE MATCH"
                    roi_rgb = active_solve_frame[
                        roi_y:roi_y + roi_height,
                        roi_x:roi_x + roi_width,
                    ]
                    matched, assignments = match_templates(
                        roi_rgb,
                        stable_pieces,
                        learned_templates,
                        solve_roi,
                    )
                    if matched is not None:
                        solved_layout, template_tilt = (
                            align_layout_to_horizontal(matched)
                        )
                        template_points = np.vstack(
                            list(solved_layout.values())
                        )
                        template_width = float(
                            np.max(template_points[:, 0])
                            - np.min(template_points[:, 0])
                        )
                        template_height = float(
                            np.max(template_points[:, 1])
                            - np.min(template_points[:, 1])
                        )
                        solved_score = 1.0
                        solved_mode = "FIRST"
                        solved_ratio = 1.0
                        solver_nodes = len(assignments)
                        solver_ms = 0.0
                        solve_info = {
                            "solve_scale": 1.0,
                            "width": template_width,
                            "height": template_height,
                            "ratio": template_width / max(
                                1.0,
                                template_height,
                            ),
                            "coverage": 1.0,
                            "overlap": 0.0,
                            "method": "template-match",
                            "execution_mode": "RECT",
                            "forced": False,
                            "template_tilt": template_tilt,
                        }
                        solve_pieces = list(stable_pieces)
                        # 直接处理结果
                        is_fallback = False
                        result_mode = "FIRST"
                        current_result_preview = render_layout_preview(
                            active_solve_frame, solve_pieces,
                            solved_layout, fill_rectangle=True,
                        )
                        # 模板已经记录了第一问的准确目标位置，不能再调用
                        # 普通拼图的50像素外移，否则会破坏学习好的布局。
                        solved_display = [
                            {
                                "piece_id": int(piece_id),
                                "points": [
                                    (float(point[0]), float(point[1]))
                                    for point in polygon
                                ],
                            }
                            for piece_id, polygon in sorted(
                                solved_layout.items()
                            )
                        ]
                        safe_layout = {
                            item["piece_id"]: np.array(
                                item["points"], dtype=np.float32)
                            for item in solved_display
                        }
                        if not layout_has_interior_overlap(safe_layout):
                            motion_plan = build_motion_plan(
                                solve_pieces,
                                solved_display,
                            )
                            ui_bridge.publish_result(current_result_preview)
                            solver_message = "TEMPLATE OK"
                        else:
                            solver_message = "TEMPLATE TOUCH"
                            solved_display = None
                            motion_plan = []
                            solver_future = solver_executor.submit(
                                solve_piece_set_worker,
                                stable_pieces,
                                solve_roi,
                            )
                    else:
                        solver_message = "TEMPLATE FAIL"
                        # 降级到普通求解
                        solver_future = solver_executor.submit(
                            solve_piece_set_worker,
                            stable_pieces,
                            solve_roi,
                        )
                else:
                    solver_future = solver_executor.submit(
                        solve_piece_set_worker,
                        stable_pieces,
                        solve_roi,
                        active_solver_mode == "NORMAL",
                    )
                pending_solve_mode = ""
                pending_card_frame = None
                pending_card_pieces = None
            elif time.monotonic() >= pending_solve_until:
                pending_solve_until = 0.0
                solver_message = (
                    "CARD NO STABLE"
                    if pending_solve_mode == "CARD"
                    else "NO STABLE"
                )
                pending_solve_mode = ""
                pending_card_frame = None
                pending_card_pieces = None

        force_best_by_time = (
            competition_active
            and competition_timeout_reached(
                ui_mode,
                competition_started_at,
                competition_best_candidate,
            )
        )
        force_best_by_retry = (
            competition_active
            and competition_retry_limit_reached(
                competition_retry_count,
                competition_best_candidate,
                10,
            )
        )
        force_best_due = force_best_by_time or force_best_by_retry
        if force_best_due:
            if (
                solver_future is not None
                and not solver_future.done()
            ):
                solver_executor = stop_solver_executor(
                    solver_executor,
                    solver_future,
                )
                solver_future = None
                active_solver_mode = ""
                active_solve_frame = None
            if solver_future is None:
                pending_solve_until = 0.0
                pending_solve_mode = ""
                pending_card_frame = None
                pending_card_pieces = None

        if solver_future is not None and not solver_future.done():
            solver_ms = (
                time.monotonic() - solve_started_at
            ) * 1000.0

        if solver_future is not None and solver_future.done():
            result_mode = active_solver_mode
            try:
                result = solver_future.result()
            except Exception as error:
                print(
                    "SOLVE_ERROR %r" % error,
                    flush=True,
                )
                result = None
            solver_future = None
            active_solver_mode = ""

            if result is None:
                solved_display = None
                solved_mode = ""
                solved_ratio = 0.0
                motion_plan = []
                candidate_pool_items = []
                ui_bridge.clear_result()
                ui_bridge.clear_candidates()
                solver_message = (
                    "CARD ERROR"
                    if result_mode == "CARD"
                    else "SOLVE ERROR"
                )
                # 尝试用当前碎片直接做降级搬运
                if result_mode != "CARD" and 2 <= len(pieces) <= 4:
                    fallback_layout, _, fallback_info = (
                        build_last_resort_layout(
                            pieces,
                            (roi_x, roi_y, roi_width, roi_height),
                        )
                    )
                    if fallback_layout is not None:
                        solve_pieces = pieces
                        solve_info = fallback_info
                        solved_display = place_layout_on_paper(
                            fallback_layout, fallback_info,
                            (roi_x, roi_y, roi_width, roi_height),
                            assembly_gap_pixels,
                        )
                        safe_layout = {
                            item["piece_id"]: np.array(
                                item["points"], dtype=np.float32)
                            for item in solved_display
                        }
                        if not layout_has_interior_overlap(safe_layout):
                            solved_mode = result_mode
                            solved_ratio = fallback_info["ratio"]
                            motion_plan = build_motion_plan(
                                solve_pieces, solved_display)
                            solver_message = "FALLBACK"
            else:
                result_mode = result.get("mode", result_mode)
                candidate_pool_items = []
                candidate_previews = []
                if result_mode == "CARD":
                    for item in result.get("candidate_pool", []):
                        metadata = dict(item)
                        preview = metadata.pop("preview_rgb", None)
                        if preview is None:
                            continue
                        candidate_pool_items.append(metadata)
                        candidate_previews.append(preview)
                if candidate_previews:
                    ui_bridge.publish_candidates(candidate_previews)
                else:
                    ui_bridge.clear_candidates()
                solved_layout = result["layout"]
                solved_score = result["score"]
                solver_nodes = result["nodes"]
                solver_ms = result["elapsed_ms"]
                solve_info = result["info"]
                solve_pieces = result["pieces"]
                is_fallback = False
                if solved_layout is None and result_mode != "CARD":
                    # 求解器失败时自动降级：用紧凑排列至少完成搬运
                    solved_layout, solved_score, fallback_info = (
                        build_last_resort_layout(
                            solve_pieces,
                            (roi_x, roi_y, roi_width, roi_height),
                        )
                    )
                    if solved_layout is not None:
                        solve_info = fallback_info
                        solver_message = "FALLBACK"
                        is_fallback = True
                if solved_layout is None:
                    solved_display = None
                    solved_mode = ""
                    solved_ratio = 0.0
                    motion_plan = []
                    ui_bridge.clear_result()
                    if not is_fallback:
                        solver_message = (
                            "CARD NO RECT"
                            if result_mode == "CARD"
                            else "NO RECT"
                        )
                else:
                    current_result_preview = (
                        None if is_fallback
                        else result.get("preview_rgb")
                    )
                    if (
                        current_result_preview is None
                        and active_solve_frame is not None
                    ):
                        current_result_preview = render_layout_preview(
                            active_solve_frame,
                            solve_pieces,
                            solved_layout,
                            fill_rectangle=True,
                        )
                    solved_display = place_layout_on_paper(
                        solved_layout,
                        solve_info,
                        (
                            roi_x,
                            roi_y,
                            roi_width,
                            roi_height,
                        ),
                        assembly_gap_pixels,
                    )
                    solved_ratio = solve_info["ratio"]
                    safe_layout = {
                        item["piece_id"]: np.array(
                            item["points"],
                            dtype=np.float32,
                        )
                        for item in solved_display
                    }
                    if layout_has_interior_overlap(safe_layout):
                        # 尝试用更大间隙推开重叠碎片，而非直接拒绝
                        gap_pixels = (
                            max(2.5, roi_height / 297.0 * 2.5)
                            * solve_info.get("solve_scale", 1.0)
                        )
                        separated, _ = add_adjacency_gap(
                            solved_layout, gap_pixels,
                            edge_tolerance_ratio=0.04,
                        )
                        overlap_fixed = False
                        if separated is not None:
                            solved_display = place_layout_on_paper(
                                separated, solve_info,
                                (roi_x, roi_y, roi_width, roi_height),
                                assembly_gap_pixels,
                            )
                            safe_layout = {
                                item["piece_id"]: np.array(
                                    item["points"], dtype=np.float32,
                                )
                                for item in solved_display
                            }
                            if not layout_has_interior_overlap(safe_layout):
                                solver_message = "SOLVE GAP2"
                                overlap_fixed = True
                        if not overlap_fixed:
                            # 仍有轻微接触，标记后仍继续执行
                            solver_message = "SOLVE TOUCH"
                    if solved_layout is not None:
                        solved_mode = result_mode
                        ui_bridge.publish_result(current_result_preview)
                        if (
                            result_mode == "CARD"
                            and os.environ.get(
                                "PUZZLE_HEADLESS",
                                "0",
                            )
                            != "1"
                        ):
                            show_card_assembly_preview(
                                result.get("preview_rgb")
                            )
                        motion_plan = build_motion_plan(
                            solve_pieces,
                            solved_display,
                        )
                        if is_fallback:
                            solver_message = "FALLBACK"
                        elif result_mode == "CARD":
                            status = solve_info.get("card_status", "GEOMETRY_ONLY")
                            solver_message = {
                                "VERIFIED": "CARD VERIFIED",
                                "GEOMETRY_ONLY": "CARD GEOMETRY ONLY",
                                "WEAK_TEXTURE": "CARD WEAK TEXTURE",
                            }.get(status, "CARD AMBIGUOUS")
                        elif solve_info.get("execution_mode") == "RECT":
                            solver_message = "SOLVE RECT"
                        elif (
                            solve_info.get("execution_mode")
                            == "RECT_SHORT"
                        ):
                            solver_message = "SOLVE SHORT"
                        elif solve_info.get("execution_mode") == "BEST":
                            solver_message = "SOLVE BEST"
                        elif solve_info.get("execution_mode") == "ASSUME":
                            solver_message = "SOLVE BEST G1.0"
                        elif solve_info["method"] == "legacy-cover":
                            solver_message = "SOLVE COVER G1.0"
                        else:
                            solver_message = "SOLVE HYB G1.0"
                        print_motion_plan(motion_plan)
                print(
                    "%s score=%.3f ratio=%.3f tested=%d "
                    "time=%.1fms method=%s"
                    % (
                        solver_message,
                        solved_score,
                        solved_ratio,
                        solver_nodes,
                        solver_ms,
                        (
                            solve_info["method"]
                            if solve_info is not None
                            else "-"
                        ),
                    ),
                    flush=True,
                )
            active_solve_frame = None

        if (
            competition_active
            and ui_mode in ("NORMAL", "CARD")
            and solve_info is not None
            and ((ui_mode != "CARD" and solved_mode != "CARD") or card_execution_ready(solve_info))
            and competition_candidate_safe(
                solved_display,
                motion_plan,
                len(solve_pieces),
            )
        ):
            candidate_score = competition_candidate_confidence(
                solve_info,
                solved_score,
            )
            if (
                competition_best_candidate is None
                or candidate_score
                > competition_best_candidate["confidence"]
            ):
                competition_best_candidate = {
                    "confidence": candidate_score,
                    "score": float(solved_score),
                    "ratio": float(solved_ratio),
                    "mode": solved_mode,
                    "solved_display": copy.deepcopy(solved_display),
                    "motion_plan": copy.deepcopy(motion_plan),
                    "solve_info": copy.deepcopy(solve_info),
                    "solve_pieces": copy.deepcopy(solve_pieces),
                    "preview": (
                        current_result_preview.copy()
                        if current_result_preview is not None
                        else None
                    ),
                }
                print(
                    "AUTO_BEST confidence=%.3f retry=%d"
                    % (candidate_score, competition_retry_count),
                    flush=True,
                )

        force_best_by_time = (
            competition_active
            and competition_timeout_reached(
                ui_mode,
                competition_started_at,
                competition_best_candidate,
            )
        )
        force_best_by_retry = (
            competition_active
            and competition_retry_limit_reached(
                competition_retry_count,
                competition_best_candidate,
                10,
            )
        )
        force_best_due = force_best_by_time or force_best_by_retry
        if force_best_due and not competition_forced_best:
            solved_display = copy.deepcopy(
                competition_best_candidate["solved_display"]
            )
            motion_plan = copy.deepcopy(
                competition_best_candidate["motion_plan"]
            )
            solve_info = copy.deepcopy(
                competition_best_candidate["solve_info"]
            )
            solve_pieces = copy.deepcopy(
                competition_best_candidate["solve_pieces"]
            )
            solved_score = competition_best_candidate["score"]
            solved_ratio = competition_best_candidate["ratio"]
            solved_mode = competition_best_candidate["mode"]
            current_result_preview = competition_best_candidate["preview"]
            if current_result_preview is not None:
                ui_bridge.publish_result(current_result_preview)
            competition_forced_best = True
            solver_message = (
                "AUTO BEST 10X"
                if force_best_by_retry
                else "AUTO BEST 80S"
            )
            print(
                "AUTO_FORCE_BEST confidence=%.3f retry=%d elapsed=%.1fs"
                % (
                    competition_best_candidate["confidence"],
                    competition_retry_count,
                    time.monotonic() - competition_started_at,
                ),
                flush=True,
            )

        if (
            competition_active
            and solver_future is None
            and pending_solve_until <= 0
        ):
            ready_to_execute = competition_result_ready(
                solved_display,
                motion_plan,
                solve_info,
                len(solve_pieces) if solve_pieces else 0,
                mode=ui_mode,
            ) or (competition_forced_best and ui_mode != "CARD" and solved_mode != "CARD")
            if ready_to_execute:
                if time.monotonic() >= competition_retry_at:
                    if serial_controller.send_motion_plan(motion_plan):
                        competition_active = False
                        competition_retry_at = 0.0
                        solver_message = (
                            "AUTO BEST EXECUTING"
                            if competition_forced_best
                            else "AUTO EXECUTING"
                        )
                    else:
                        competition_retry_at = time.monotonic() + 1.0
                        solver_message = "AUTO SEND WAIT"
            elif competition_retry_at <= 0:
                if competition_retry_count < 10:
                    competition_retry_count += 1
                    competition_retry_at = time.monotonic() + 0.35
                    solver_message = (
                        "AUTO RETRY %d/10" % competition_retry_count
                    )
                else:
                    competition_active = False
                    competition_retry_at = 0.0
                    solver_message = "AUTO STOP NO CANDIDATE"

        if tuning_open:
            show_binary_preview(
                frame_rgb,
                threshold_info["mask"],
                (roi_x, roi_y, roi_width, roi_height),
            )

        draw_roi(
            img,
            (roi_x, roi_y, roi_width, roi_height),
        )
        display_pieces = build_stable_piece_set(recent_piece_sets)
        if display_pieces is None:
            display_pieces = pieces
        for index, piece in enumerate(display_pieces, 1):
            draw_piece(img, piece, index)
        ui_bridge.publish_live(
            frame_rgb,
            threshold_info["mask"],
            (roi_x, roi_y, roi_width, roi_height),
        )

        if not tuning_open and solved_display is not None:
            draw_solved_rectangle(
                img,
                solved_display,
                solution_box,
                solved_score,
                motion_plan,
            )

        img.draw_string(
            4,
            4,
            "PIECES %d  %s  T%d"
            % (
                len(pieces),
                threshold_info["polarity"],
                threshold_info["threshold"],
            ),
            image.COLOR_WHITE,
            scale=2,
        )
        if not tuning_open and solver_message:
            img.draw_string(
                4,
                42,
                "%s %.3f R%.2f %.0fms"
                % (
                    solver_message,
                    solved_score,
                    solved_ratio,
                    solver_ms,
                ),
                image.COLOR_GREEN
                if (
                    solver_message.startswith("SOLVE")
                    or solver_message == "CARD RECT"
                )
                else image.COLOR_YELLOW,
                scale=2,
            )
        if tuning_open:
            draw_controls(
                img,
                button_boxes,
                auto_threshold,
                manual_threshold,
                polarity_mode,
                min_piece_area,
                green_method=green_method,
                green_sat_min=green_sat_min,
                green_close_kernel=green_close_kernel,
                green_close_iter=green_close_iter,
                paper_close_kernel=paper_close_kernel,
                paper_close_iter=paper_close_iter,
            )
        else:
            draw_button(
                img,
                button_boxes["solve"],
                "SOLVE",
                active=(
                    solved_display is not None
                    and solved_mode != "CARD"
                ),
            )
            draw_button(
                img,
                button_boxes["card_solve"],
                "CARD",
                active=(
                    solved_display is not None
                    and solved_mode == "CARD"
                ),
            )
            draw_button(
                img,
                button_boxes["tune"],
                "TUNE",
            )
            draw_button(
                img,
                button_boxes["capture"],
                "CAPTURE",
            )
            if (
                last_capture_name
                and time.monotonic() - last_capture_time < 2.5
            ):
                img.draw_string(
                    20,
                    920 if img.height() > img.width() else 175,
                    "SAVED %s" % last_capture_name[-10:],
                    image.COLOR_GREEN,
                    scale=2,
                )

        now = time.monotonic()
        fps_frames += 1
        elapsed = now - fps_start
        if elapsed >= 1:
            fps = fps_frames / elapsed
            fps_frames = 0
            fps_start = now
        ui_bridge.publish_state(
            {
                "mode": ui_mode.lower(),
                "camera_ok": True,
                "fps": round(float(fps), 1),
                "piece_count": len(pieces),
                "auto_threshold": bool(auto_threshold),
                "manual_threshold": int(manual_threshold),
                "current_threshold": int(current_threshold),
                "polarity_mode": polarity_mode,
                "background_mode": background_mode,
                "green_method": green_method,
                "green_auto": bool(green_auto),
                "green_detected_hue_min": int(
                    (threshold_info.get("green_auto_values") or {}).get(
                        "hue_min", 0
                    )
                ),
                "green_detected_hue_max": int(
                    (threshold_info.get("green_auto_values") or {}).get(
                        "hue_max", 0
                    )
                ),
                "green_detected_sat_min": int(
                    (threshold_info.get("green_auto_values") or {}).get(
                        "sat_min", 0
                    )
                ),
                "green_detected_val_min": int(
                    (threshold_info.get("green_auto_values") or {}).get(
                        "val_min", 0
                    )
                ),
                "green_hue_min": int(green_hue_min),
                "green_hue_max": int(green_hue_max),
                "green_sat_min": int(green_sat_min),
                "green_val_min": int(green_val_min),
                "green_close_kernel": int(green_close_kernel),
                "green_close_iter": int(green_close_iter),
                "paper_close_kernel": int(paper_close_kernel),
                "paper_close_iter": int(paper_close_iter),
                "detected_polarity": threshold_info["polarity"],
                "min_piece_area": int(min_piece_area),
                "assembly_gap_pixels": int(assembly_gap_pixels),
                "camera_width": int(camera_width),
                "camera_height": int(camera_height),
                "roi_x": int(roi_x),
                "roi_y": int(roi_y),
                "roi_width": int(roi_width),
                "roi_height": int(roi_height),
                "assembly_split_y": int(roi_y + roi_height // 2),
                "solving": bool(
                    solver_future is not None
                    or pending_solve_until > 0
                ),
                "solver_message": solver_message,
                "score": round(float(solved_score), 4),
                "ratio": round(float(solved_ratio), 4),
                "solver_ms": round(float(solver_ms), 1),
                "solver_nodes": int(solver_nodes),
                "solved_mode": solved_mode.lower(),
                "last_capture_name": last_capture_name,
                "score_items": build_ui_score_items(solve_info),
                "motion_plan": motion_plan,
                "motion_plan_count": len(motion_plan),
                "solved_display": solved_display or [],
                "candidate_items": candidate_pool_items,
                "card_solver_revision": "structure-portfolio-20261013",
                "card_scoring": get_card_scoring_params(),
                "competition_mode": bool(competition_mode),
                "competition_active": bool(competition_active),
                "competition_retry_count": int(competition_retry_count),
                **serial_controller.state(),
            }
        )
        img.draw_string(
            4,
            camera_height - 38,
            "FPS %.1f" % fps,
            image.COLOR_WHITE,
            scale=2,
        )

        if now - last_print_time >= 1:
            print_detection(pieces, threshold_info)
            last_print_time = now

        disp.show(img)

    cam.close()
    serial_controller.disconnect()
    try:
        solver_executor.shutdown(wait=False, cancel_futures=True)
    except TypeError:
        solver_executor.shutdown(wait=False)


if __name__ == "__main__":
    main()
