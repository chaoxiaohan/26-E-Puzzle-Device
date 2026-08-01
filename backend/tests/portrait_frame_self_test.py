# -*- coding: utf-8 -*-

import os

import numpy as np

os.environ["PUZZLE_PORTRAIT"] = "1"
os.environ["PUZZLE_ROTATION"] = "CW"

import maix


def main():
    source = np.arange(720 * 1280 * 3, dtype=np.uint8).reshape(
        720,
        1280,
        3,
    )
    rotated = maix._portrait_frame(source)

    assert rotated.shape == (1280, 720, 3)
    assert rotated.size == source.size
    assert np.array_equal(rotated[0, 0], source[719, 0])
    assert np.array_equal(rotated[-1, -1], source[0, 1279])
    assert maix._runtime.portrait
    assert maix._runtime.rotation == "CW"
    print("portrait 1280x720 -> 720x1280 full-frame mapping OK")


if __name__ == "__main__":
    main()
