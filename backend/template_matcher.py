# -*- coding: utf-8 -*-

"""第一问模板匹配：学习拼好的矩形 → 比赛时匹配碎片 → 直接搬运。

学习阶段记录每块碎片在拼好状态下的图像块和位置。
匹配阶段对每块检测到的碎片做旋转校正后与模板比对，
用 Hu 矩做形状初筛、归一化互相关做纹理确认。
"""

import itertools
import json
import math
import os

import cv2
import numpy as np

from solver_v2 import edge_length, normalize_polygon


def _canonical_orientation(polygon):
    """将多边形旋转到规范方向：最长边水平向右。"""
    best = 0
    best_len = 0.0
    for i in range(len(polygon)):
        length = edge_length(polygon, i)
        if length > best_len:
            best_len = length
            best = i
    start = polygon[best]
    end = polygon[(best + 1) % len(polygon)]
    vector = end - start
    angle = math.atan2(vector[1], vector[0])
    return -angle, best_len


def _rotate_image(image, angle_rad, center=None):
    """绕中心旋转图像，返回旋转后的图像和变换矩阵。"""
    h, w = image.shape[:2]
    if center is None:
        center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, math.degrees(angle_rad), 1.0)
    rotated = cv2.warpAffine(
        image, matrix, (w, h),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )
    return rotated, matrix


def align_layout_to_horizontal(layout):
    """把整套模板排布刚性转正，不改变碎片之间的相对位置。"""
    if not layout:
        return layout, 0.0

    polygons = {
        int(piece_id): np.asarray(polygon, dtype=np.float64).copy()
        for piece_id, polygon in layout.items()
    }
    all_points = np.vstack(list(polygons.values())).astype(np.float32)
    if len(all_points) < 3:
        return polygons, 0.0

    box = cv2.boxPoints(cv2.minAreaRect(all_points)).astype(np.float64)
    edge_angles = []
    for index in range(4):
        vector = box[(index + 1) % 4] - box[index]
        angle = math.degrees(math.atan2(vector[1], vector[0]))
        angle = (angle + 90.0) % 180.0 - 90.0
        edge_angles.append(angle)
    tilt = min(edge_angles, key=abs)
    if abs(tilt) < 0.05:
        return polygons, 0.0

    center = np.mean(all_points, axis=0).astype(np.float64)
    angle = math.radians(-tilt)
    rotation = np.array([
        [math.cos(angle), -math.sin(angle)],
        [math.sin(angle), math.cos(angle)],
    ], dtype=np.float64)
    aligned = {
        piece_id: (polygon - center) @ rotation.T + center
        for piece_id, polygon in polygons.items()
    }
    return aligned, float(tilt)


def _extract_piece_patch(frame_rgb, polygon, margin=6):
    """从原图中裁出碎片区域，旋转到最长边水平。"""
    # 外接矩形裁剪
    polygon_i = np.rint(polygon).astype(np.int32)
    x, y, w, h = cv2.boundingRect(polygon_i)
    x = max(0, x - margin)
    y = max(0, y - margin)
    w = min(frame_rgb.shape[1] - x, w + margin * 2)
    h = min(frame_rgb.shape[0] - y, h + margin * 2)
    if w < 5 or h < 5:
        return None, None, None

    patch = frame_rgb[y:y + h, x:x + w].copy()
    # 碎片掩膜（在裁剪区域内的坐标）
    local_polygon = polygon - np.array([x, y], dtype=np.float64)
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillPoly(mask, [np.rint(local_polygon).astype(np.int32)], 255)

    # 旋转到规范方向
    angle, _ = _canonical_orientation(local_polygon)
    patch_rot, matrix = _rotate_image(patch, angle)
    mask_rot = cv2.warpAffine(
        mask, matrix, (w, h),
        flags=cv2.INTER_NEAREST,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0,
    )

    # 裁掉旋转后的黑边
    rows = np.any(mask_rot > 0, axis=1)
    cols = np.any(mask_rot > 0, axis=0)
    if not np.any(rows) or not np.any(cols):
        return None, None, None
    y_min, y_max = np.where(rows)[0][[0, -1]]
    x_min, x_max = np.where(cols)[0][[0, -1]]
    y_max = min(y_max + 2, h - 1)
    x_max = min(x_max + 2, w - 1)
    y_min = max(0, y_min - 2)
    x_min = max(0, x_min - 2)

    return (
        patch_rot[y_min:y_max + 1, x_min:x_max + 1],
        mask_rot[y_min:y_max + 1, x_min:x_max + 1],
        (x, y, angle, local_polygon),
    )


def _hu_distance(first, second):
    """两个多边形之间的 Hu 矩距离（越小越相似）。"""
    m1 = cv2.HuMoments(
        cv2.moments(first.astype(np.float32))
    ).flatten()
    m2 = cv2.HuMoments(
        cv2.moments(second.astype(np.float32))
    ).flatten()
    # Hu 矩用对数压缩后比较
    m1_log = np.sign(m1) * np.log1p(np.abs(m1))
    m2_log = np.sign(m2) * np.log1p(np.abs(m2))
    return float(np.sum(np.abs(m1_log - m2_log)))


def _normalized_correlation(patch1, mask1, patch2, mask2):
    """两张碎片图像块之间的归一化互相关分数（越高越相似）。"""
    if patch1 is None or patch2 is None:
        return 0.0
    # 统一缩放到相同高度
    target_h = 64
    scale1 = target_h / max(1, patch1.shape[0])
    scale2 = target_h / max(1, patch2.shape[0])
    p1 = cv2.resize(patch1, None, fx=scale1, fy=scale1,
                    interpolation=cv2.INTER_AREA)
    p2 = cv2.resize(patch2, None, fx=scale2, fy=scale2,
                    interpolation=cv2.INTER_AREA)
    # 统一宽度（取较大者）
    max_w = max(p1.shape[1], p2.shape[1])
    canvas1 = np.zeros((target_h, max_w, 3), dtype=np.uint8)
    canvas2 = np.zeros((target_h, max_w, 3), dtype=np.uint8)
    canvas1[:, :p1.shape[1]] = p1
    canvas2[:, :p2.shape[1]] = p2
    # 转灰度做 NCC
    gray1 = cv2.cvtColor(canvas1, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gray2 = cv2.cvtColor(canvas2, cv2.COLOR_RGB2GRAY).astype(np.float32)
    # 归一化互相关
    m1 = gray1 - np.mean(gray1)
    m2 = gray2 - np.mean(gray2)
    ncc = np.sum(m1 * m2) / max(
        1e-9, np.sqrt(np.sum(m1 * m1) * np.sum(m2 * m2))
    )
    return float(max(0.0, ncc))


def _rotation_invariant_correlation(patch1, mask1, patch2, mask2):
    """枚举四个直角方向，避免近似等长边使规范方向跳变。"""
    if patch1 is None or patch2 is None:
        return 0.0
    return max(
        _normalized_correlation(
            np.rot90(patch1, turns).copy(),
            np.rot90(mask1, turns).copy(),
            patch2,
            mask2,
        )
        for turns in range(4)
    )


def _resample_polygon(polygon, sample_count=40):
    """沿闭合轮廓等距采样，消除起始顶点和伪角点数量的影响。"""
    polygon = np.asarray(polygon, dtype=np.float64)
    following = np.roll(polygon, -1, axis=0)
    lengths = np.linalg.norm(following - polygon, axis=1)
    perimeter = float(np.sum(lengths))
    if len(polygon) < 3 or perimeter < 1e-6:
        return None

    distances = np.linspace(
        0.0,
        perimeter,
        sample_count,
        endpoint=False,
    )
    cumulative = np.concatenate(([0.0], np.cumsum(lengths)))
    sampled = []
    edge_id = 0
    for distance in distances:
        while (
            edge_id + 1 < len(cumulative) - 1
            and distance >= cumulative[edge_id + 1]
        ):
            edge_id += 1
        amount = (
            distance - cumulative[edge_id]
        ) / max(1e-9, lengths[edge_id])
        sampled.append(
            polygon[edge_id]
            + (following[edge_id] - polygon[edge_id]) * amount
        )
    return np.asarray(sampled, dtype=np.float64)


def _best_polygon_rotation(source, target):
    """循环枚举轮廓对应关系，返回 source 到 target 的最佳刚体旋转。"""
    source_samples = _resample_polygon(source)
    target_samples = _resample_polygon(target)
    if source_samples is None or target_samples is None:
        return np.eye(2, dtype=np.float64), 1.0

    source_centered = source_samples - np.mean(source_samples, axis=0)
    target_centered = target_samples - np.mean(target_samples, axis=0)
    source_energy = float(np.sum(source_centered * source_centered))
    target_radius = math.sqrt(
        float(np.mean(np.sum(target_centered * target_centered, axis=1)))
    )
    best_rotation = np.eye(2, dtype=np.float64)
    best_error = float("inf")

    for reversed_order in (False, True):
        ordered = target_centered[::-1] if reversed_order else target_centered
        for shift in range(len(ordered)):
            candidate = np.roll(ordered, shift, axis=0)
            covariance = source_centered.T @ candidate
            first, singular_values, second = np.linalg.svd(covariance)
            rotation = second.T @ first.T
            if np.linalg.det(rotation) < 0.0:
                second[-1, :] *= -1.0
                rotation = second.T @ first.T
            scale = float(np.sum(singular_values) / max(1e-9, source_energy))
            aligned = source_centered @ rotation.T * scale
            error = float(
                np.mean(np.linalg.norm(aligned - candidate, axis=1))
                / max(1e-9, target_radius)
            )
            if error < best_error:
                best_error = error
                best_rotation = rotation

    return best_rotation, best_error


def learn_templates(frame_rgb, pieces, roi):
    """从拼好的矩形中学习每块碎片的模板。

    Args:
        frame_rgb: ROI 区域 RGB 图像
        pieces: detect_pieces 返回的碎片列表
        roi: (roi_x, roi_y, roi_width, roi_height)

    Returns:
        templates: 列表，每项包含 image_patch, mask, polygon, center, area
        写入 templates.json 持久化
    """
    templates = []
    for piece in pieces:
        polygon = np.asarray(piece["points"], dtype=np.float64)
        # 转为ROI局部坐标
        local_polygon = polygon - np.array([roi[0], roi[1]], dtype=np.float64)
        patch, mask, meta = _extract_piece_patch(frame_rgb, local_polygon)
        if patch is None:
            continue
        templates.append({
            "patch": patch,
            "mask": mask,
            "polygon": piece["points"],       # 相机全帧坐标
            "center": piece["center"],         # 相机全帧坐标
            "area": piece["area"],
        })
    return templates


def match_templates(frame_rgb, pieces, templates, roi):
    """将检测到的碎片与模板匹配，返回每块碎片应放置的位置。

    Args:
        frame_rgb: ROI 区域 RGB 图像
        pieces: 当前检测到的碎片列表
        templates: 学习阶段保存的模板列表
        roi: 当前ROI在完整相机画面中的位置

    Returns:
        layout: {piece_idx: polygon} 的排布，或 None
        assignments: [(detected_idx, template_idx, score)]
    """
    if (
        not templates
        or not pieces
        or len(pieces) != len(templates)
    ):
        return None, []

    roi_origin = np.asarray(roi[:2], dtype=np.float64)

    # 为每个检测碎片提取特征
    detected_features = []
    for piece in pieces:
        polygon = np.asarray(piece["points"], dtype=np.float64)
        local_polygon = polygon - roi_origin
        patch, mask, _ = _extract_piece_patch(frame_rgb, local_polygon)
        detected_features.append({
            "polygon": polygon,
            "patch": patch,
            "mask": mask,
            "center": piece["center"],
            "area": piece["area"],
        })

    # 碎片不超过4块，直接穷举一一分配最多只有24种。
    n_det = len(detected_features)
    n_tpl = len(templates)
    scores = np.zeros((n_det, n_tpl), dtype=np.float64)
    rotations = [[None for _ in range(n_tpl)] for _ in range(n_det)]

    for i, det in enumerate(detected_features):
        for j, tpl in enumerate(templates):
            # Hu 矩形状相似度
            det_poly = np.asarray(pieces[i]["points"], dtype=np.float64)
            tpl_poly = np.asarray(tpl["polygon"], dtype=np.float64)
            hu_dist = _hu_distance(det_poly, tpl_poly)
            shape_score = math.exp(-hu_dist * 3.0)

            rotation, pose_error = _best_polygon_rotation(
                det_poly,
                tpl_poly,
            )
            rotations[i][j] = rotation
            pose_score = math.exp(-pose_error * 8.0)

            # 面积比惩罚
            area_ratio = min(det["area"], tpl["area"]) / max(
                1.0, max(det["area"], tpl["area"])
            )
            area_score = 1.0 / (1.0 + abs(1.0 - area_ratio) * 4.0)

            # 纹理相关度
            texture_score = _rotation_invariant_correlation(
                det["patch"], det["mask"],
                tpl["patch"], tpl["mask"],
            )

            # 第一问是白色纸面，形状与顶点对应关系优先，纹理只作辅助。
            scores[i, j] = (
                shape_score * 0.30
                + pose_score * 0.40
                + area_score * 0.20
                + texture_score * 0.10
            )

    best_order = None
    best_score = -1.0
    for order in itertools.permutations(range(n_tpl)):
        total = sum(
            scores[index, order[index]]
            for index in range(n_det)
        )
        if total > best_score:
            best_score = total
            best_order = order
    assignments = [
        (
            index,
            best_order[index],
            float(scores[index, best_order[index]]),
        )
        for index in range(n_det)
    ]
    if min(score for _, _, score in assignments) < 0.25:
        return None, assignments

    # 生成排布：每块检测碎片放到对应模板的位置
    layout = {}
    for det_idx, tpl_idx, _ in assignments:
        tpl = templates[tpl_idx]
        det_polygon = np.asarray(pieces[det_idx]["points"], dtype=np.float64)
        tpl_polygon = np.asarray(tpl["polygon"], dtype=np.float64)

        # 计算刚体变换：检测碎片 → 模板位置
        det_center = np.mean(det_polygon, axis=0)
        tpl_center = np.mean(tpl_polygon, axis=0)

        rot_matrix = rotations[det_idx][tpl_idx]

        # 碎片变换到模板位置
        transformed = (det_polygon - det_center) @ rot_matrix.T + tpl_center
        layout[det_idx] = transformed

    return layout, assignments


TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "templates.json",
)


def save_templates(templates, path=None):
    """将模板序列化保存为 JSON。图像块用 base64 编码。"""
    import base64
    path = path or TEMPLATE_PATH
    data = []
    for tpl in templates:
        # 编码图像块
        _, patch_bytes = cv2.imencode(".png", cv2.cvtColor(tpl["patch"], cv2.COLOR_RGB2BGR))
        _, mask_bytes = cv2.imencode(".png", tpl["mask"])
        data.append({
            "patch_b64": base64.b64encode(patch_bytes).decode("ascii"),
            "mask_b64": base64.b64encode(mask_bytes).decode("ascii"),
            "polygon": tpl["polygon"],
            "center": tpl["center"],
            "area": tpl["area"],
        })
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_templates(path=None):
    """从 JSON 文件加载模板。"""
    import base64
    path = path or TEMPLATE_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    templates = []
    for item in data:
        patch_bytes = base64.b64decode(item["patch_b64"])
        mask_bytes = base64.b64decode(item["mask_b64"])
        patch = cv2.cvtColor(
            cv2.imdecode(np.frombuffer(patch_bytes, np.uint8), cv2.IMREAD_COLOR),
            cv2.COLOR_BGR2RGB,
        )
        mask = cv2.imdecode(np.frombuffer(mask_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        templates.append({
            "patch": patch,
            "mask": mask,
            "polygon": item["polygon"],
            "center": item["center"],
            "area": item["area"],
        })
    return templates
