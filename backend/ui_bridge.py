# -*- coding: utf-8 -*-

import json
import os
import time

import cv2
import numpy as np


class UiBridge:
    """用 /tmp 内存文件连接视觉后端和 Flutter 界面。"""

    def __init__(self):
        self.control_path = "/tmp/puzzle_ui_control.json"
        self.state_path = "/tmp/puzzle_ui_state.json"
        self.frame_path = "/tmp/puzzle_ui_frame.jpg"
        self.binary_path = "/tmp/puzzle_ui_binary.jpg"
        self.result_path = "/tmp/puzzle_ui_result.jpg"
        self.last_control_revision = -1
        self.last_frame_time = 0.0
        self.last_state_time = 0.0
        self.frame_revision = 0
        self.result_revision = 0
        self.result_available = os.path.exists(self.result_path)
        self.preview_source_x = 0.0
        self.preview_source_y = 0.0
        self.preview_scale = 1.0
        self.preview_offset_x = 0.0
        self.preview_offset_y = 0.0

    @staticmethod
    def _atomic_write(path, data):
        temporary = "%s.%d.tmp" % (path, os.getpid())
        with open(temporary, "wb") as file:
            file.write(data)
            file.flush()
        os.replace(temporary, path)

    @staticmethod
    def _json_default(value):
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            return float(value)
        if isinstance(value, tuple):
            return list(value)
        raise TypeError("unsupported json value %r" % type(value))

    @staticmethod
    def _encode_jpeg(rgb, quality):
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        ok, encoded = cv2.imencode(
            ".jpg",
            bgr,
            [cv2.IMWRITE_JPEG_QUALITY, int(quality)],
        )
        if not ok:
            raise RuntimeError("cannot encode UI jpeg")
        return encoded.tobytes()

    @staticmethod
    def _fit_preview(rgb, width, height):
        source_height, source_width = rgb.shape[:2]
        if source_width < 1 or source_height < 1:
            return np.zeros((height, width, 3), dtype=np.uint8)
        scale = min(
            width / float(source_width),
            height / float(source_height),
        )
        resized_width = max(1, int(round(source_width * scale)))
        resized_height = max(1, int(round(source_height * scale)))
        resized = cv2.resize(
            rgb,
            (resized_width, resized_height),
            interpolation=cv2.INTER_AREA,
        )
        canvas = np.full(
            (height, width, 3),
            24,
            dtype=np.uint8,
        )
        x = (width - resized_width) // 2
        y = (height - resized_height) // 2
        canvas[
            y : y + resized_height,
            x : x + resized_width,
        ] = resized
        return canvas

    def read_control(self):
        try:
            with open(
                self.control_path,
                "r",
                encoding="utf-8",
            ) as file:
                control = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None

        revision = int(control.get("revision", -1))
        if revision == self.last_control_revision:
            return None
        self.last_control_revision = revision
        return control

    def publish_live(self, frame_rgb, mask, roi, force=False):
        now = time.monotonic()
        if not force and now - self.last_frame_time < 0.08:
            return
        self.last_frame_time = now

        roi_x, roi_y, roi_width, roi_height = roi
        margin_x = 24
        margin_y = 12
        x0 = max(0, roi_x - margin_x)
        y0 = max(0, roi_y - margin_y)
        x1 = min(frame_rgb.shape[1], roi_x + roi_width + margin_x)
        y1 = min(frame_rgb.shape[0], roi_y + roi_height + margin_y)
        source_width = max(1, x1 - x0)
        source_height = max(1, y1 - y0)
        self.preview_source_x = float(x0)
        self.preview_source_y = float(y0)
        self.preview_scale = min(
            360.0 / source_width,
            640.0 / source_height,
        )
        resized_width = round(source_width * self.preview_scale)
        resized_height = round(source_height * self.preview_scale)
        self.preview_offset_x = (360.0 - resized_width) * 0.5
        self.preview_offset_y = (640.0 - resized_height) * 0.5
        camera_preview = self._fit_preview(
            frame_rgb[y0:y1, x0:x1],
            360,
            640,
        )
        binary_rgb = cv2.cvtColor(mask, cv2.COLOR_GRAY2RGB)
        binary_preview = self._fit_preview(
            binary_rgb,
            520,
            360,
        )
        self._atomic_write(
            self.frame_path,
            self._encode_jpeg(camera_preview, 78),
        )
        self._atomic_write(
            self.binary_path,
            self._encode_jpeg(binary_preview, 85),
        )
        self.frame_revision += 1

    def preview_to_camera(self, x, y):
        if self.preview_scale <= 0:
            return None
        camera_x = (
            float(x) - self.preview_offset_x
        ) / self.preview_scale + self.preview_source_x
        camera_y = (
            float(y) - self.preview_offset_y
        ) / self.preview_scale + self.preview_source_y
        return camera_x, camera_y

    def publish_result(self, preview_rgb):
        if preview_rgb is None:
            self.clear_result()
            return
        self._atomic_write(
            self.result_path,
            self._encode_jpeg(preview_rgb, 90),
        )
        self.result_revision += 1
        self.result_available = True

    def clear_result(self):
        try:
            os.remove(self.result_path)
        except FileNotFoundError:
            pass
        self.result_revision += 1
        self.result_available = False

    def publish_state(self, state, force=False):
        now = time.monotonic()
        if not force and now - self.last_state_time < 0.08:
            return
        self.last_state_time = now
        payload = dict(state)
        payload["backend_alive"] = True
        payload["updated_at_ms"] = int(time.time() * 1000)
        payload["frame_revision"] = self.frame_revision
        payload["result_revision"] = self.result_revision
        payload["result_available"] = self.result_available
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=self._json_default,
        ).encode("utf-8")
        self._atomic_write(self.state_path, encoded)
