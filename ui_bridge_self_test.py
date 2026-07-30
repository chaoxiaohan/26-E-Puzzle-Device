# -*- coding: utf-8 -*-

import json
import os
import tempfile

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

print("ui bridge revision OK")
