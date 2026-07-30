# -*- coding: utf-8 -*-

import os
import pty
import struct
import threading

from serial_protocol import SerialController
from serial_protocol import build_frame
from serial_protocol import crc16_ccitt


def read_exact(device, size):
    data = bytearray()
    while len(data) < size:
        data.extend(os.read(device, size - len(data)))
    return bytes(data)


def fake_arm(device, received):
    while len(received) < 4:
        if read_exact(device, 2) != b"\xAA\x55":
            continue
        header = read_exact(device, 4)
        command, flags, sequence, length = header
        tail = read_exact(device, length + 2)
        payload = tail[:length]
        assert crc16_ccitt(header + payload) == struct.unpack(
            "<H",
            tail[length:],
        )[0]
        received.append((command, flags, sequence, payload))
        os.write(
            device,
            build_frame(
                0x80,
                0,
                sequence,
                bytes((sequence,)),
            ),
        )


def main():
    master, slave = pty.openpty()
    port = os.ttyname(slave)
    received = []
    worker = threading.Thread(
        target=fake_arm,
        args=(master, received),
        daemon=True,
    )
    worker.start()

    controller = SerialController("/tmp/puzzle_serial_test.json")
    controller.configure(
        port=port,
        baud=115200,
        pick_z=120,
        place_z=80,
    )
    assert controller.move(10, -20, 30, 4500, relative=True)
    plan = [
        {
            "piece_id": 0,
            "pick": (100.0, 200.0),
            "place": (300.0, 400.0),
            "rotation": -45.25,
        },
        {
            "piece_id": 1,
            "pick": (110.0, 210.0),
            "place": (310.0, 410.0),
            "rotation": 90.0,
        },
    ]
    assert controller.send_motion_plan(plan)
    worker.join(timeout=1.0)
    assert [item[0] for item in received] == [
        0x20,
        0x10,
        0x10,
        0x11,
    ]
    first_action = struct.unpack("<BBBBiiiiiih", received[1][3])
    assert first_action[6] == 120
    assert first_action[9] == 80
    assert first_action[10] == -4525
    controller.disconnect()
    try:
        os.remove("/tmp/puzzle_serial_test.json")
    except FileNotFoundError:
        pass
    print("SERIAL_PROTOCOL_OK frames=4")


if __name__ == "__main__":
    main()
