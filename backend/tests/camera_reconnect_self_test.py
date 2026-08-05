# -*- coding: utf-8 -*-

from main import RecoveringCamera


class FakeCamera:
    def __init__(self, frames):
        self.frames = list(frames)
        self.closed = False

    def read(self):
        value = self.frames.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True


attempts = []
first = FakeCamera(["frame-1", RuntimeError("disconnected")])
second = FakeCamera(["frame-2"])
outcomes = [RuntimeError("not found"), first, second]


def open_fake_camera():
    attempts.append(len(attempts))
    value = outcomes.pop(0)
    if isinstance(value, Exception):
        raise value
    return value


camera = RecoveringCamera(open_fake_camera)
assert camera.read(now=0.0) is None
assert camera.online is False
assert camera.read(now=0.5) is None
assert len(attempts) == 1

assert camera.read(now=1.0) == "frame-1"
assert camera.online is True
assert camera.read(now=1.1) is None
assert camera.online is False
assert first.closed is True

assert camera.read(now=1.5) is None
assert camera.read(now=2.1) == "frame-2"
assert camera.online is True
assert len(attempts) == 3

camera.close()
assert second.closed is True

recoveries = []
invalid_first = FakeCamera([None])
invalid_second = FakeCamera([None])
invalid_third = FakeCamera([None])
recovered_camera = FakeCamera(["frame-after-reset"])
invalid_outcomes = [
    invalid_first,
    invalid_second,
    invalid_third,
    recovered_camera,
]


def open_invalid_camera():
    return invalid_outcomes.pop(0)


def recover_usb_camera():
    recoveries.append(True)
    return True


camera = RecoveringCamera(open_invalid_camera, recover_usb_camera)
assert camera.read(now=10.0) is None
assert invalid_first.closed is True
assert camera.read(now=10.8) is None
assert invalid_second.closed is True
assert recoveries == []
assert camera.read(now=11.7) is None
assert invalid_third.closed is True
assert recoveries == [True]
assert camera.read(now=12.5) is None
assert camera.read(now=12.9) == "frame-after-reset"
assert camera.online is True
assert camera.failure_count == 0
print("camera reconnect OK")
