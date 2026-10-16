import os
import pathlib
import tempfile

from hardware_devices import camera_device


with tempfile.TemporaryDirectory() as directory:
    root = pathlib.Path(directory)
    sysfs = root / "sys"
    devices = root / "dev"
    sysfs.mkdir()
    devices.mkdir()
    os.environ.pop("PUZZLE_CAMERA", None)

    def add_video(name, driver, index):
        node = sysfs / name
        (node / "device").mkdir(parents=True)
        (node / "device" / "driver").symlink_to(root / driver)
        (node / "index").write_text(str(index))
        (devices / name).touch()

    add_video("video0", "rkisp", 0)
    add_video("video1", "rkvdec", 0)
    add_video("video2", "bcm2835-isp", 0)
    add_video("video3", "rp1-cfe", 0)
    add_video("video4", "pispbe", 0)
    try:
        camera_device(str(sysfs), str(devices))
        raise AssertionError("SoC ISP/codec/CSI nodes must not be selected as USB cameras")
    except RuntimeError:
        pass

    add_video("video11", "uvcvideo", 1)
    add_video("video10", "uvcvideo", 0)
    assert camera_device(str(sysfs), str(devices)) == str(devices / "video10")
    (devices / "video10").unlink()
    try:
        camera_device(str(sysfs), str(devices))
        raise AssertionError("Disconnected nodes and metadata must be skipped")
    except RuntimeError:
        pass
    add_video("video12", "uvcvideo", 0)
    assert camera_device(str(sysfs), str(devices)) == str(devices / "video12")
    os.environ["PUZZLE_CAMERA"] = "/dev/v4l/by-id/custom-camera"
    assert camera_device(str(sysfs), str(devices)) == "/dev/v4l/by-id/custom-camera"
    os.environ.pop("PUZZLE_CAMERA")

print("USB camera selection and reconnect OK")
