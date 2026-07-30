# -*- coding: utf-8 -*-

import json
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
        self.sequence = 0
        self.task_id = 0
        self.last_reply = ""
        self.last_error = ""
        self.event_revision = 0
        self.last_payload = b""
        self.current_x = 0
        self.current_y = 0
        self.current_z = 0
        self.current_rotation = 0
        self.position_valid = False
        self.visual_a = None
        self.visual_b = None
        self.platform_a = None
        self.platform_b = None
        self.calibration_valid = False
        self.scale_x = 0.0
        self.scale_y = 0.0
        self._lock = threading.RLock()
        self._load_settings()

    def _set_status(self, reply, error=""):
        self.last_reply = reply
        self.last_error = error
        self.event_revision += 1

    @property
    def connected(self):
        return self.device is not None and self.device.is_open

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
        self.visual_a = settings.get("visual_a")
        self.visual_b = settings.get("visual_b")
        self.platform_a = settings.get("platform_a")
        self.platform_b = settings.get("platform_b")
        self._calculate_calibration(save=False)

    def _save_settings(self):
        settings = {
            "port": self.port,
            "baud": self.baud,
            "pick_z": self.pick_z,
            "place_z": self.place_z,
            "visual_a": self.visual_a,
            "visual_b": self.visual_b,
            "platform_a": self.platform_a,
            "platform_b": self.platform_b,
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
        if reconnect and self.connected:
            self.disconnect()
        self._save_settings()

    def connect(self):
        with self._lock:
            if self.connected:
                return True
            try:
                self.device = serial.Serial(
                    self.port,
                    self.baud,
                    timeout=0.035,
                    write_timeout=0.1,
                )
                self.device.reset_input_buffer()
                self._set_status("串口已连接")
                print(
                    "SERIAL_CONNECTED %s %d"
                    % (self.port, self.baud),
                    flush=True,
                )
                return True
            except (OSError, serial.SerialException) as error:
                self.device = None
                self._set_status("串口连接失败", str(error))
                print(
                    "SERIAL_CONNECT_ERROR %s" % error,
                    flush=True,
                )
                return False

    def disconnect(self):
        with self._lock:
            if self.device is not None:
                try:
                    self.device.close()
                except (OSError, serial.SerialException):
                    pass
            self.device = None
            self._set_status("串口已断开")
            print("SERIAL_DISCONNECTED", flush=True)

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
            return command, flags, sequence, payload
        return None

    def send(self, command, payload=b"", flags=0x20):
        with self._lock:
            if not self.connected and not self.connect():
                return False
            sequence = self._next_sequence()
            frame = build_frame(command, flags, sequence, payload)
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
                except (OSError, serial.SerialException) as error:
                    self._set_status("串口通信失败", str(error))
                    self.device = None
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
        point = [float(x), float(y)]
        if name == "a":
            self.visual_a = point
        else:
            self.visual_b = point
        self.calibration_valid = False
        self._save_settings()
        self._set_status("已记录视觉点%s" % name.upper())

    def record_platform_point(self, name):
        if not self.query_position():
            return False
        point = [self.current_x, self.current_y]
        if name == "a":
            self.platform_a = point
        else:
            self.platform_b = point
        self.calibration_valid = False
        self._save_settings()
        self._set_status("已记录平台点%s" % name.upper())
        return True

    def _calculate_calibration(self, save=True):
        self.calibration_valid = False
        if not all(
            (
                self.visual_a,
                self.visual_b,
                self.platform_a,
                self.platform_b,
            )
        ):
            return False
        visual_dx = float(self.visual_b[0]) - float(self.visual_a[0])
        visual_dy = float(self.visual_b[1]) - float(self.visual_a[1])
        if abs(visual_dx) < 5.0 or abs(visual_dy) < 5.0:
            return False
        self.scale_x = (
            float(self.platform_b[0]) - float(self.platform_a[0])
        ) / visual_dx
        self.scale_y = (
            float(self.platform_b[1]) - float(self.platform_a[1])
        ) / visual_dy
        self.calibration_valid = (
            abs(self.scale_x) > 1e-9
            and abs(self.scale_y) > 1e-9
        )
        if save:
            self._save_settings()
        return self.calibration_valid

    def calculate_calibration(self):
        if self._calculate_calibration():
            self._set_status("两点坐标系标定完成")
            return True
        self._set_status(
            "标定点不完整或距离过近",
            "invalid calibration points",
        )
        return False

    def vision_to_platform(self, x, y):
        if not self.calibration_valid:
            raise RuntimeError("platform calibration required")
        return (
            float(self.platform_a[0])
            + (float(x) - float(self.visual_a[0])) * self.scale_x,
            float(self.platform_a[1])
            + (float(y) - float(self.visual_a[1])) * self.scale_y,
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
            if self.scale_x * self.scale_y < 0:
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
        return {
            "serial_connected": self.connected,
            "serial_port": self.port,
            "serial_baud": self.baud,
            "serial_pick_z": self.pick_z,
            "serial_place_z": self.place_z,
            "serial_last_reply": self.last_reply,
            "serial_error": self.last_error,
            "serial_event_revision": self.event_revision,
            "platform_x": self.current_x,
            "platform_y": self.current_y,
            "platform_z": self.current_z,
            "platform_rotation": self.current_rotation,
            "platform_position_valid": self.position_valid,
            "calibration_visual_a": self.visual_a,
            "calibration_visual_b": self.visual_b,
            "calibration_platform_a": self.platform_a,
            "calibration_platform_b": self.platform_b,
            "calibration_valid": self.calibration_valid,
            "calibration_scale_x": self.scale_x,
            "calibration_scale_y": self.scale_y,
        }
