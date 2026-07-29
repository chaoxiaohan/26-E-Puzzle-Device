# -*- coding: utf-8 -*-

import os

import cv2
import numpy as np


class _Runtime:
    def __init__(self):
        self.exit_requested = False
        self.mouse_x = 0
        self.mouse_y = 0
        self.mouse_pressed = False
        self.window_ready = False
        self.frame_count = 0
        self.portrait = os.environ.get(
            "PUZZLE_PORTRAIT",
            "0",
        ) == "1"
        self.rotation = os.environ.get(
            "PUZZLE_ROTATION",
            "CW",
        ).upper()


_runtime = _Runtime()


class _App:
    @staticmethod
    def need_exit():
        maximum = int(os.environ.get("PUZZLE_MAX_FRAMES", "0"))
        return _runtime.exit_requested or (
            maximum > 0 and _runtime.frame_count >= maximum
        )


class _Format:
    FMT_RGB888 = 0


class _Fit:
    FIT_CONTAIN = 0


class _TextSize:
    def __init__(self, width, height):
        self._width = width
        self._height = height

    def width(self):
        return self._width

    def height(self):
        return self._height


class _ImageFrame:
    def __init__(self, rgb):
        self.array = rgb

    def width(self):
        return self.array.shape[1]

    def height(self):
        return self.array.shape[0]

    def draw_line(self, x1, y1, x2, y2, color, thickness=1):
        cv2.line(
            self.array,
            (int(x1), int(y1)),
            (int(x2), int(y2)),
            color,
            int(thickness),
            cv2.LINE_AA,
        )

    def draw_rect(self, x, y, width, height, color, thickness=1):
        cv2.rectangle(
            self.array,
            (int(x), int(y)),
            (int(x + width), int(y + height)),
            color,
            int(thickness),
            cv2.LINE_AA,
        )

    def draw_cross(self, x, y, color, size=5, thickness=1):
        x = int(x)
        y = int(y)
        size = int(size)
        self.draw_line(
            x - size,
            y,
            x + size,
            y,
            color,
            thickness,
        )
        self.draw_line(
            x,
            y - size,
            x,
            y + size,
            color,
            thickness,
        )

    def draw_string(self, x, y, text, color, scale=1):
        font_scale = max(0.4, float(scale) * 0.55)
        cv2.putText(
            self.array,
            str(text),
            (int(x), int(y + 20 * font_scale)),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            color,
            max(1, int(round(float(scale)))),
            cv2.LINE_AA,
        )


class _Image:
    Format = _Format
    Fit = _Fit
    COLOR_BLACK = (0, 0, 0)
    COLOR_WHITE = (255, 255, 255)
    COLOR_RED = (255, 0, 0)
    COLOR_GREEN = (0, 255, 0)
    COLOR_BLUE = (0, 0, 255)
    COLOR_YELLOW = (255, 255, 0)

    @staticmethod
    def image2cv(frame, ensure_bgr=False, copy=False):
        array = frame.array
        if ensure_bgr:
            array = cv2.cvtColor(array, cv2.COLOR_RGB2BGR)
        return array.copy() if copy else array

    @staticmethod
    def string_size(text, scale=1):
        font_scale = max(0.4, float(scale) * 0.55)
        size, baseline = cv2.getTextSize(
            str(text),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            max(1, int(round(float(scale)))),
        )
        return _TextSize(size[0], size[1] + baseline)

    @staticmethod
    def resize_map_pos(
        image_width,
        image_height,
        display_width,
        display_height,
        fit,
        x,
        y,
        width,
        height,
    ):
        scale = min(
            display_width / image_width,
            display_height / image_height,
        )
        offset_x = (display_width - image_width * scale) * 0.5
        offset_y = (display_height - image_height * scale) * 0.5
        return (
            int(round(offset_x + x * scale)),
            int(round(offset_y + y * scale)),
            int(round(width * scale)),
            int(round(height * scale)),
        )


class _CameraDevice:
    def __init__(
        self,
        width,
        height,
        image_format,
        fps=30,
        buff_num=3,
    ):
        device = os.environ.get("PUZZLE_CAMERA", "/dev/video0")
        self.capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
        self.capture.set(
            cv2.CAP_PROP_FOURCC,
            cv2.VideoWriter_fourcc(*"MJPG"),
        )
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, int(width))
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, int(height))
        self.capture.set(cv2.CAP_PROP_FPS, int(fps))
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, int(buff_num))

        if not self.capture.isOpened():
            raise RuntimeError("cannot open camera %s" % device)

        actual_width = int(
            self.capture.get(cv2.CAP_PROP_FRAME_WIDTH)
        )
        actual_height = int(
            self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
        )
        actual_fps = self.capture.get(cv2.CAP_PROP_FPS)
        print(
            "camera=%s mode=%dx%d %.1ffps"
            % (
                device,
                actual_width,
                actual_height,
                actual_fps,
            ),
            flush=True,
        )

    def read(self):
        ok, bgr = self.capture.read()
        if not ok:
            raise RuntimeError("camera frame read failed")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if _runtime.portrait:
            crop_x = int(
                os.environ.get(
                    "PUZZLE_PORTRAIT_CROP_X",
                    "280",
                )
            )
            crop_x = max(
                0,
                min(crop_x, rgb.shape[1] - 720),
            )
            canvas = np.zeros(
                (1280, 720, 3),
                dtype=np.uint8,
            )
            canvas[:720, :, :] = rgb[
                :720,
                crop_x : crop_x + 720,
            ]
            rgb = canvas
        return _ImageFrame(rgb)

    def __del__(self):
        if hasattr(self, "capture"):
            self.capture.release()


class _Camera:
    Camera = _CameraDevice


def _mouse_callback(event, x, y, flags, parameter):
    _runtime.mouse_x = int(x)
    _runtime.mouse_y = int(y)
    if event == cv2.EVENT_LBUTTONDOWN:
        _runtime.mouse_pressed = True
    elif event == cv2.EVENT_LBUTTONUP:
        _runtime.mouse_pressed = False


class _DisplayDevice:
    def __init__(self):
        if _runtime.portrait:
            self._width = 720
            self._height = 1280
            window_width = 720
            window_height = 1280
        else:
            self._width = 1280
            self._height = 720
            window_width = 1280
            window_height = 720
        window_width = int(
            os.environ.get(
                "PUZZLE_DISPLAY_WIDTH",
                str(window_width),
            )
        )
        window_height = int(
            os.environ.get(
                "PUZZLE_DISPLAY_HEIGHT",
                str(window_height),
            )
        )
        self.headless = os.environ.get(
            "PUZZLE_HEADLESS",
            "0",
        ) == "1"
        self.window_name = "Puzzle Detector"

        if not self.headless:
            cv2.namedWindow(
                self.window_name,
                cv2.WINDOW_NORMAL,
            )
            cv2.resizeWindow(
                self.window_name,
                window_width,
                window_height,
            )
            cv2.setMouseCallback(
                self.window_name,
                _mouse_callback,
            )
            _runtime.window_ready = True

    def width(self):
        return self._width

    def height(self):
        return self._height

    def show(self, frame):
        _runtime.frame_count += 1
        if self.headless:
            return

        bgr = cv2.cvtColor(
            frame.array,
            cv2.COLOR_RGB2BGR,
        )
        cv2.imshow(self.window_name, bgr)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q"), ord("Q")):
            _runtime.exit_requested = True
            cv2.destroyAllWindows()


class _Display:
    Display = _DisplayDevice


class _TouchScreen:
    @staticmethod
    def read():
        return (
            _runtime.mouse_x,
            _runtime.mouse_y,
            _runtime.mouse_pressed,
        )


class _Touchscreen:
    TouchScreen = _TouchScreen


app = _App()
camera = _Camera()
display = _Display()
image = _Image()
touchscreen = _Touchscreen()
