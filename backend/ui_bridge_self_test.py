# -*- coding: utf-8 -*-

import json
import os
import tempfile

import cv2
import numpy as np

from ui_bridge import UiBridge


def write_control(path, revision, action):
    temporary = "%s.tmp" % path
    with open(temporary, "w", encoding="utf-8") as control_file:
        json.dump(
            {
                "revision": revision,
                "action": action,
            },
            control_file,
        )
    os.replace(temporary, path)


with tempfile.TemporaryDirectory() as directory:
    bridge = UiBridge()
    bridge.control_path = os.path.join(directory, "control.json")

    write_control(bridge.control_path, 9000000000, "capture")
    assert bridge.read_control()["action"] == "capture"

    write_control(bridge.control_path, 100, "solve")
    assert bridge.read_control()["action"] == "solve"
    assert bridge.read_control() is None

    bridge.frame_path = os.path.join(directory, "frame.jpg")
    bridge.binary_path = os.path.join(directory, "binary.jpg")
    frame = np.zeros((1280, 720, 3), dtype=np.uint8)
    mask = np.zeros((700, 520), dtype=np.uint8)
    bridge.publish_live(
        frame,
        mask,
        (100, 10, 520, 700),
        force=True,
    )
    preview = cv2.imread(bridge.frame_path)
    assert preview.shape[:2] == (640, 360)
    assert bridge.preview_to_camera(0, 0) == (0.0, 0.0)
    assert bridge.preview_to_camera(360, 640) == (720.0, 1280.0)

print("ui bridge revision and full-frame preview OK")
