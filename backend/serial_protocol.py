# -*- coding: utf-8 -*-

import glob
import json
import math
import os
import struct
import threading
import time

import serial


def crc16_ccitt(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def build_frame(command, flags, sequence, payload=b""):
    body = bytes(
        (
            command & 0xFF,
            flags & 0xFF,
            sequence & 0xFF,
            len(payload) & 0xFF,
        )
    ) + payload
    return b"\xAA\x55" + body + struct.pack(
        "<H",
        crc16_ccitt(body),
    )


class SerialController:
    """实现拼图平台的简化串口协议。"""

    def __init__(self, settings_path=None):
        self.settings_path = settings_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "serial_settings.json",
        )
        self.port = "/dev/ttyUSB0"
        self.baud = 115200
        self.pick_z = 0
        self.place_z = 0
        self.device = None
        self.active_port = ""
        self.connection_requested = False
        self.next_reconnect_at = 0.0
        self.last_health_check = 0.0
        self.sequence = 0
        self.task_id = 0
        self.last_reply = ""
        self.last_error = ""
        self.event_revision = 0
        self.last_payload = b""
        self._raw_log = []  # [(timestamp, direction, hex_string), ...]
        self.current_x = 0
        self.current_y = 0
        self.current_z = 0
        self.current_rotation = 0
        self.position_valid = False
        self.visual_a = None
        self.visual_b = None
        self.visual_c = None
        self.visual_d = None
        self.visual_e = None
        self.visual_f = None
        self.platform_a = None
        self.platform_b = None
        self.platform_c = None
        self.platform_d = None
        self.platform_e = None
        self.platform_f = None
        self.calibration_valid = False
        self.affine = None
        self.affine_determinant = 0.0
        self.scale_x = 0.0
        self.scale_y = 0.0
        self.calibration_rms_error = 0.0
        self.calibration_max_error = 0.0
        self._lock = threading.RLock()
        self._load_settings()

    def _set_status(self, reply, error=""):
        if reply == self.last_reply and error == self.last_error:
            return
        self.last_reply = reply
        self.last_error = error
        self.event_revision += 1

    @property
    def connected(self):
        return (
            self.device is not None
            and self.device.is_open
            and bool(self.active_port)
            and os.path.exists(self.active_port)
        )

    def _candidate_ports(self):
        ports = []

        def add(path):
            if path and os.path.exists(path) and path not in ports:
                ports.append(path)

        add(self.port)
        add("/dev/puzzle-arm")
        for pattern in (
            "/dev/serial/by-id/*",
            "/dev/ttyUSB*",
            "/dev/ttyACM*",
        ):
            for path in sorted(glob.glob(pattern)):
                add(path)
        return ports

    def _close_device(self):
        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                pass
        self.device = None
        self.active_port = ""
        self.last_health_check = 0.0

    def _load_settings(self):
        try:
            with open(
                self.settings_path,
                "r",
                encoding="utf-8",
            ) as file:
                settings = json.load(file)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        self.port = str(settings.get("port", self.port))
        self.baud = int(settings.get("baud", self.baud))
        self.pick_z = int(settings.get("pick_z", self.pick_z))
        self.place_z = int(settings.get("place_z", self.place_z))
        self.connection_requested = bool(
            settings.get("auto_connect", False)
        )
        self.visual_a = settings.get("visual_a")
        self.visual_b = settings.get("visual_b")
        self.visual_c = settings.get("visual_c")
        self.visual_d = settings.get("visual_d")
        self.visual_e = settings.get("visual_e")
        self.visual_f = settings.get("visual_f")
        self.platform_a = settings.get("platform_a")
        self.platform_b = settings.get("platform_b")
        self.platform_c = settings.get("platform_c")
        self.platform_d = settings.get("platform_d")
        self.platform_e = settings.get("platform_e")
        self.platform_f = settings.get("platform_f")
        self._calculate_calibration(save=False)

    def _save_settings(self):
        settings = {
            "port": self.port,
            "baud": self.baud,
            "pick_z": self.pick_z,
            "place_z": self.place_z,
            "auto_connect": self.connection_requested,
            "visual_a": self.visual_a,
            "visual_b": self.visual_b,
            "visual_c": self.visual_c,
            "visual_d": self.visual_d,
            "visual_e": self.visual_e,
            "visual_f": self.visual_f,
            "platform_a": self.platform_a,
            "platform_b": self.platform_b,
            "platform_c": self.platform_c,
            "platform_d": self.platform_d,
            "platform_e": self.platform_e,
            "platform_f": self.platform_f,
        }
        temporary = "%s.%d.tmp" % (
            self.settings_path,
            os.getpid(),
        )
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump(
                settings,
                file,
                ensure_ascii=False,
                indent=2,
            )
        os.replace(temporary, self.settings_path)

    def configure(
        self,
        port=None,
        baud=None,
        pick_z=None,
        place_z=None,
    ):
        reconnect = False
        if port is not None:
            new_port = str(port).strip()
            if new_port and new_port != self.port:
                self.port = new_port
                reconnect = True
        if baud is not None:
            new_baud = max(1200, min(2000000, int(baud)))
            if new_baud != self.baud:
                self.baud = new_baud
                reconnect = True
        if pick_z is not None:
            self.pick_z = int(pick_z)
        if place_z is not None:
            self.place_z = int(place_z)
        if reconnect and self.device is not None:
            self._close_device()
            self.next_reconnect_at = 0.0
        self._save_settings()

    def _connect_locked(self):
        if self.connected:
            return True
        self._close_device()
        ports = self._candidate_ports()
        if not ports:
            self.next_reconnect_at = time.monotonic() + 1.0
            self._set_status(
                "等待USB串口重新上线",
                "未找到可用USB串口",
            )
            return False

        errors = []
        for port in ports:
            try:
                self.device = serial.Serial(
                    port,
                    self.baud,
                    timeout=0.035,
                    write_timeout=0.1,
                )
                self.device.reset_input_buffer()
                self.active_port = port
                self.next_reconnect_at = 0.0
                self.last_health_check = time.monotonic()
                self._set_status("串口已连接")
                print(
                    "SERIAL_CONNECTED %s %d"
                    % (port, self.baud),
                    flush=True,
                )
                return True
            except Exception as error:
                errors.append("%s: %s" % (port, error))
                self._close_device()

        message = "; ".join(errors)
        self.next_reconnect_at = time.monotonic() + 1.0
        self._set_status("串口连接失败，等待重试", message)
        print("SERIAL_CONNECT_ERROR %s" % message, flush=True)
        return False

    def connect(self):
        with self._lock:
            self.connection_requested = True
            self._save_settings()
            return self._connect_locked()

    def disconnect(self):
        with self._lock:
            self.connection_requested = False
            self.next_reconnect_at = 0.0
            self._close_device()
            self._save_settings()
            self._set_status("串口已断开")
            print("SERIAL_DISCONNECTED", flush=True)

    def service(self, now=None):
        with self._lock:
            now = time.monotonic() if now is None else float(now)
            if (
                self.device is not None
                and self.device.is_open
                and now - self.last_health_check >= 0.5
            ):
                self.last_health_check = now
                try:
                    self.device.in_waiting
                except Exception as error:
                    self._communication_failed(error)
            if self.device is not None and not self.connected:
                self._close_device()
                if self.connection_requested:
                    self._set_status(
                        "USB串口已掉线，等待自动重连",
                        "设备节点已消失",
                    )
            if (
                not self.connection_requested
                or self.connected
                or now < self.next_reconnect_at
            ):
                return self.connected
            return self._connect_locked()

    def _communication_failed(self, error):
        self._close_device()
        self.next_reconnect_at = time.monotonic() + 0.3
        self._set_status(
            "USB串口通信中断，正在自动重连",
            str(error),
        )
        print("SERIAL_IO_ERROR %s" % error, flush=True)

    def _next_sequence(self):
        sequence = self.sequence
        self.sequence = (self.sequence + 1) & 0xFF
        return sequence

    def _read_exact(self, size, deadline):
        data = bytearray()
        while len(data) < size and time.monotonic() < deadline:
            chunk = self.device.read(size - len(data))
            if chunk:
                data.extend(chunk)
        return bytes(data)

    def _read_response(self, deadline):
        matched = 0
        while time.monotonic() < deadline:
            byte = self.device.read(1)
            if not byte:
                continue
            if matched == 0:
                matched = 1 if byte == b"\xAA" else 0
                continue
            if byte != b"\x55":
                matched = 1 if byte == b"\xAA" else 0
                continue
            header = self._read_exact(4, deadline)
            if len(header) != 4:
                return None
            command, flags, sequence, length = header
            tail = self._read_exact(length + 2, deadline)
            if len(tail) != length + 2:
                return None
            payload = tail[:length]
            received_crc = struct.unpack("<H", tail[length:])[0]
            if crc16_ccitt(header + payload) != received_crc:
                matched = 0
                continue
            full_frame = b"\xAA\x55" + header + payload + tail[length:]
            self._log_raw("RX", full_frame)
            return command, flags, sequence, payload
        return None

    def _log_raw(self, direction, frame_bytes):
        hex_str = " ".join("%02X" % b for b in frame_bytes)
        entry = (time.monotonic(), direction, hex_str)
        self._raw_log.append(entry)
        if len(self._raw_log) > 60:
            self._raw_log = self._raw_log[-40:]

    def send(self, command, payload=b"", flags=0x20):
        with self._lock:
            if not self.connected and not self.connect():
                return False
            sequence = self._next_sequence()
            frame = build_frame(command, flags, sequence, payload)
            self._log_raw("TX", frame)
            self.last_payload = b""
            for attempt in range(3):
                try:
                    if attempt:
                        frame = build_frame(
                            command,
                            flags | 0x10,
                            sequence,
                            payload,
                        )
                    self.device.reset_input_buffer()
                    self.device.write(frame)
                    self.device.flush()
                    response = self._read_response(
                        time.monotonic() + 0.12
                    )
                except Exception as error:
                    self._communication_failed(error)
                    return False
                if response is None:
                    continue
                reply_command, _, reply_sequence, reply_payload = response
                acknowledged_sequence = (
                    reply_payload[0]
                    if reply_payload
                    else reply_sequence
                )
                if acknowledged_sequence != sequence:
                    continue
                if reply_command == 0x80:
                    self.last_payload = (
                        reply_payload[1:]
                        if reply_payload
                        and reply_payload[0] == sequence
                        else reply_payload
                    )
                    self._set_status("发送成功")
                    return True
                if reply_command != 0x81:
                    continue
            self._set_status("发送失败", "ACK timeout")
            print(
                "SERIAL_RETRY_FAILED cmd=%02X seq=%d"
                % (command, sequence),
                flush=True,
            )
            return False

    @staticmethod
    def _coordinate(value):
        return max(-2147483648, min(2147483647, int(round(value))))

    @staticmethod
    def _rotation(value):
        return max(-18000, min(18000, int(round(value))))

    def move(self, x, y, z, rotation, relative=False):
        payload = struct.pack(
            "<Biiih",
            2 if relative else 1,
            self._coordinate(x),
            self._coordinate(y),
            self._coordinate(z),
            self._rotation(rotation),
        )
        return self.send(
            0x20,
            payload,
            0x21 if relative else 0x20,
        )

    def home(self):
        return self.send(
            0x20,
            struct.pack("<Biiih", 3, 0, 0, 0, 0),
        )

    def query_position(self):
        payload = struct.pack("<Biiih", 4, 0, 0, 0, 0)
        if not self.send(0x20, payload):
            return False
        if len(self.last_payload) < 14:
            self.position_valid = False
            self._set_status(
                "读取位置失败",
                "position payload too short",
            )
            return False
        (
            self.current_x,
            self.current_y,
            self.current_z,
            self.current_rotation,
        ) = struct.unpack("<iiih", self.last_payload[:14])
        self.position_valid = True
        self._set_status("当前位置已更新")
        return True

    def record_visual_point(self, name, x, y):
        if name not in "abcdef":
            return False
        point = [float(x), float(y)]
        setattr(self, "visual_" + name, point)
        self.calibration_valid = False
        self._save_settings()
        self._set_status("已记录视觉点%s" % name.upper())
        return True

    def record_platform_point(self, name):
        if name not in "abcdef":
            return False
        if not self.query_position():
            return False
        point = [self.current_x, self.current_y]
        setattr(self, "platform_" + name, point)
        self.calibration_valid = False
        self._save_settings()
        self._set_status("已记录平台点%s" % name.upper())
        return True

    @staticmethod
    def _point_cloud_quality(points):
        mean_x = sum(float(point[0]) for point in points) / len(points)
        mean_y = sum(float(point[1]) for point in points) / len(points)
        xx = sum((float(point[0]) - mean_x) ** 2 for point in points)
        yy = sum((float(point[1]) - mean_y) ** 2 for point in points)
        xy = sum(
            (float(point[0]) - mean_x) * (float(point[1]) - mean_y)
            for point in points
        )
        longest_variance = max(xx, yy)
        if longest_variance < 1e-9:
            return 0.0
        return max(0.0, (xx * yy - xy * xy) / (longest_variance ** 2))

    @staticmethod
    def _solve_3x3(matrix, values):
        rows = [
            [float(value) for value in matrix[row]]
            + [float(values[row])]
            for row in range(3)
        ]
        for column in range(3):
            pivot = max(
                range(column, 3),
                key=lambda row: abs(rows[row][column]),
            )
            if abs(rows[pivot][column]) < 1e-9:
                return None
            rows[column], rows[pivot] = rows[pivot], rows[column]
            divisor = rows[column][column]
            rows[column] = [value / divisor for value in rows[column]]
            for row in range(3):
                if row == column:
                    continue
                factor = rows[row][column]
                rows[row] = [
                    rows[row][index] - factor * rows[column][index]
                    for index in range(4)
                ]
        return [rows[row][3] for row in range(3)]

    def _calculate_calibration(self, save=True):
        self.calibration_valid = False
        self.affine = None
        self.affine_determinant = 0.0
        self.calibration_rms_error = 0.0
        self.calibration_max_error = 0.0
        visual_points = [
            getattr(self, "visual_" + name)
            for name in "abcdef"
        ]
        platform_points = [
            getattr(self, "platform_" + name)
            for name in "abcdef"
        ]
        if not all(visual_points + platform_points):
            return False
        if (
            self._point_cloud_quality(visual_points) < 0.01
            or self._point_cloud_quality(platform_points) < 0.01
        ):
            return False
        visual_matrix = [
            [float(point[0]), float(point[1]), 1.0]
            for point in visual_points
        ]
        platform_x = [float(point[0]) for point in platform_points]
        platform_y = [float(point[1]) for point in platform_points]
        normal_matrix = [
            [
                sum(row[column] * row[other] for row in visual_matrix)
                for other in range(3)
            ]
            for column in range(3)
        ]
        normal_x = [
            sum(
                visual_matrix[row][column] * platform_x[row]
                for row in range(6)
            )
            for column in range(3)
        ]
        normal_y = [
            sum(
                visual_matrix[row][column] * platform_y[row]
                for row in range(6)
            )
            for column in range(3)
        ]
        affine_x = self._solve_3x3(normal_matrix, normal_x)
        affine_y = self._solve_3x3(normal_matrix, normal_y)
        if affine_x is None or affine_y is None:
            return False
        self.affine = [affine_x, affine_y]
        self.affine_determinant = (
            affine_x[0] * affine_y[1]
            - affine_x[1] * affine_y[0]
        )
        self.scale_x = math.hypot(affine_x[0], affine_y[0])
        self.scale_y = math.hypot(affine_x[1], affine_y[1])
        self.calibration_valid = (
            abs(self.affine_determinant) > 1e-9
            and abs(self.scale_x) > 1e-9
            and abs(self.scale_y) > 1e-9
        )
        errors = []
        for visual, platform in zip(visual_points, platform_points):
            predicted_x = (
                affine_x[0] * float(visual[0])
                + affine_x[1] * float(visual[1])
                + affine_x[2]
            )
            predicted_y = (
                affine_y[0] * float(visual[0])
                + affine_y[1] * float(visual[1])
                + affine_y[2]
            )
            errors.append(
                math.hypot(
                    predicted_x - float(platform[0]),
                    predicted_y - float(platform[1]),
                )
            )
        self.calibration_rms_error = math.sqrt(
            sum(error * error for error in errors) / len(errors)
        )
        self.calibration_max_error = max(errors)
        if save:
            self._save_settings()
        return self.calibration_valid

    def calculate_calibration(self):
        if self._calculate_calibration():
            self._set_status(
                "六点仿射标定完成，均方根误差 %.1f"
                % self.calibration_rms_error
            )
            return True
        self._set_status(
            "标定失败：请记录六个分散的对应点",
            "six well-spread point pairs required",
        )
        return False

    def vision_to_platform(self, x, y):
        if not self.calibration_valid or self.affine is None:
            raise RuntimeError("platform calibration required")
        return (
            self.affine[0][0] * float(x)
            + self.affine[0][1] * float(y)
            + self.affine[0][2],
            self.affine[1][0] * float(x)
            + self.affine[1][1] * float(y)
            + self.affine[1][2],
        )

    def send_motion_plan(self, motion_plan):
        if not motion_plan:
            self._set_status(
                "没有可发送的拼图动作",
                "empty motion plan",
            )
            return False
        if len(motion_plan) > 255:
            self._set_status("动作数量过多", "too many actions")
            return False
        if not self.calibration_valid:
            self._set_status(
                "请先完成平台坐标标定",
                "platform calibration required",
            )
            return False

        self.task_id = (self.task_id + 1) & 0xFF
        count = len(motion_plan)
        for index, move in enumerate(motion_plan):
            pick = move["pick"]
            place = move["place"]
            pick_x, pick_y = self.vision_to_platform(
                pick[0],
                pick[1],
            )
            place_x, place_y = self.vision_to_platform(
                place[0],
                place[1],
            )
            rotation = float(move["rotation"])
            if self.affine_determinant < 0:
                rotation = -rotation
            payload = struct.pack(
                "<BBBBiiiiiih",
                self.task_id,
                index,
                count,
                int(move.get("piece_id", index)) & 0xFF,
                self._coordinate(pick_x),
                self._coordinate(pick_y),
                self._coordinate(self.pick_z),
                self._coordinate(place_x),
                self._coordinate(place_y),
                self._coordinate(self.place_z),
                self._rotation(rotation * 100.0),
            )
            if not self.send(0x10, payload, 0x21):
                self._set_status(
                    "动作%d发送失败" % (index + 1),
                    self.last_error,
                )
                return False
        if not self.send(
            0x11,
            struct.pack("<B", self.task_id),
        ):
            self._set_status("执行命令发送失败", self.last_error)
            return False
        self._set_status("已发送%d个动作并开始执行" % count)
        return True

    def state(self):
        # 只返回最近30条日志，减少JSON体积
        recent_log = self._raw_log[-30:] if self._raw_log else []
        return {
            "serial_connected": self.connected,
            "serial_port": self.port,
            "serial_active_port": self.active_port,
            "serial_reconnecting": (
                self.connection_requested and not self.connected
            ),
            "serial_device_present": bool(self._candidate_ports()),
            "serial_baud": self.baud,
            "serial_pick_z": self.pick_z,
            "serial_place_z": self.place_z,
            "serial_last_reply": self.last_reply,
            "serial_error": self.last_error,
            "serial_raw_log": [
                {"t": round(t, 3), "d": d, "hex": h}
                for t, d, h in recent_log
            ],
            "serial_event_revision": self.event_revision,
            "platform_x": self.current_x,
            "platform_y": self.current_y,
            "platform_z": self.current_z,
            "platform_rotation": self.current_rotation,
            "platform_position_valid": self.position_valid,
            "calibration_visual_a": self.visual_a,
            "calibration_visual_b": self.visual_b,
            "calibration_visual_c": self.visual_c,
            "calibration_visual_d": self.visual_d,
            "calibration_visual_e": self.visual_e,
            "calibration_visual_f": self.visual_f,
            "calibration_platform_a": self.platform_a,
            "calibration_platform_b": self.platform_b,
            "calibration_platform_c": self.platform_c,
            "calibration_platform_d": self.platform_d,
            "calibration_platform_e": self.platform_e,
            "calibration_platform_f": self.platform_f,
            "calibration_valid": self.calibration_valid,
            "calibration_scale_x": self.scale_x,
            "calibration_scale_y": self.scale_y,
            "calibration_affine": self.affine,
            "calibration_affine_determinant": self.affine_determinant,
            "calibration_rms_error": self.calibration_rms_error,
            "calibration_max_error": self.calibration_max_error,
        }
