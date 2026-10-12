import glob
import os


def camera_device(sysfs_dir="/sys/class/video4linux", device_dir="/dev"):
    """Select a USB capture node, skipping Rockchip codecs and UVC metadata."""
    configured = os.environ.get("PUZZLE_CAMERA", "auto").strip()
    if configured and configured != "auto":
        return configured

    devices = glob.glob(os.path.join(sysfs_dir, "video*"))
    devices.sort(key=lambda path: int(os.path.basename(path)[5:]))
    for path in devices:
        driver = os.path.realpath(os.path.join(path, "device", "driver"))
        if os.path.basename(driver) != "uvcvideo":
            continue
        try:
            with open(os.path.join(path, "index")) as file:
                if int(file.read()) != 0:
                    continue
        except (OSError, ValueError):
            continue
        device = os.path.join(device_dir, os.path.basename(path))
        if os.path.exists(device):
            return device
    raise RuntimeError("USB camera not connected; waiting for a UVC capture device")
