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
        self.candidate_prefix = "/tmp/puzzle_ui_candidate_"
        self.last_control_revision = self._read_control_revision(
            self.control_path
        )
        self.last_frame_time = 0.0
        self.last_state_time = 0.0
        self.frame_revision = 0
        self.result_revision = 0
        self.result_available = os.path.exists(self.result_path)
        self.candidate_revision = 0
        self.candidate_count = 0
        self.preview_source_x = 0.0
        self.preview_source_y = 0.0
        self.preview_scale = 1.0
        self.preview_offset_x = 0.0
        self.preview_offset_y = 0.0

    @staticmethod
    def _read_control_revision(path):
        try:
            with open(path, "r", encoding="utf-8") as file:
                return int(json.load(file).get("revision", -1))
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return -1

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
        source_height, source_width = frame_rgb.shape[:2]
        self.preview_source_x = 0.0
        self.preview_source_y = 0.0
        self.preview_scale = min(
            360.0 / source_width,
            640.0 / source_height,
        )
        resized_width = round(source_width * self.preview_scale)
        resized_height = round(source_height * self.preview_scale)
        self.preview_offset_x = (360.0 - resized_width) * 0.5
        self.preview_offset_y = (640.0 - resized_height) * 0.5
        preview_source = frame_rgb.copy()
        cv2.rectangle(
            preview_source,
            (roi_x, roi_y),
            (roi_x + roi_width - 1, roi_y + roi_height - 1),
            (255, 220, 0),
            3,
            cv2.LINE_AA,
        )
        camera_preview = self._fit_preview(
            preview_source,
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

    def publish_candidates(self, previews):
        count = min(8, len(previews))
        for index, preview in enumerate(previews[:count]):
            self._atomic_write(
                "%s%d.jpg" % (self.candidate_prefix, index),
                self._encode_jpeg(preview, 86),
            )
        for index in range(count, 8):
            try:
                os.remove("%s%d.jpg" % (self.candidate_prefix, index))
            except FileNotFoundError:
                pass
        self.candidate_count = count
        self.candidate_revision += 1

    def clear_candidates(self):
        for index in range(8):
            try:
                os.remove("%s%d.jpg" % (self.candidate_prefix, index))
            except FileNotFoundError:
                pass
        self.candidate_count = 0
        self.candidate_revision += 1

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
        payload["candidate_revision"] = self.candidate_revision
        payload["candidate_count"] = self.candidate_count
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=self._json_default,
        ).encode("utf-8")
        self._atomic_write(self.state_path, encoded)
