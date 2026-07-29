import ctypes
import os

import numpy as np


_library = None


def load_library():
    global _library
    if _library is not None:
        return _library
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "librectangle_solver.so",
    )
    if not os.path.exists(path):
        return None
    library = ctypes.CDLL(path)
    library.solve_rectangle_cpp.argtypes = [
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_int),
        ctypes.c_int,
        ctypes.c_double,
        ctypes.c_int,
        ctypes.POINTER(ctypes.c_double),
        ctypes.POINTER(ctypes.c_double),
    ]
    library.solve_rectangle_cpp.restype = ctypes.c_int
    _library = library
    return library


def solve(pieces, fill_ratio=0.80, position_step=4):
    library = load_library()
    if library is None or not 2 <= len(pieces) <= 4:
        return None, 0.0, 0, None

    counts = np.asarray(
        [len(piece["points"]) for piece in pieces],
        dtype=np.int32,
    )
    if np.any(counts < 3) or np.any(counts > 5):
        return None, 0.0, 0, None
    points = np.asarray(
        [
            coordinate
            for piece in pieces
            for point in piece["points"]
            for coordinate in point
        ],
        dtype=np.float64,
    )
    output = np.zeros_like(points)
    info = np.zeros(8, dtype=np.float64)
    status = library.solve_rectangle_cpp(
        points.ctypes.data_as(
            ctypes.POINTER(ctypes.c_double)
        ),
        counts.ctypes.data_as(
            ctypes.POINTER(ctypes.c_int)
        ),
        len(pieces),
        float(fill_ratio),
        int(position_step),
        output.ctypes.data_as(
            ctypes.POINTER(ctypes.c_double)
        ),
        info.ctypes.data_as(
            ctypes.POINTER(ctypes.c_double)
        ),
    )
    if status != 1:
        return None, 0.0, int(info[7]), None

    layout = {}
    point_offset = 0
    for piece_id, count in enumerate(counts):
        next_offset = point_offset + int(count) * 2
        layout[piece_id] = output[
            point_offset:next_offset
        ].reshape(-1, 2)
        point_offset = next_offset
    return (
        layout,
        float(info[0]),
        int(info[7]),
        {
            "ratio": float(info[5]),
            "solve_scale": float(info[6]),
            "width": float(max(info[3], info[4])),
            "height": float(min(info[3], info[4])),
            "coverage": float(info[1]),
            "overlap": float(info[2]),
            "forced": False,
            "boundary_safe": True,
            "method": "cpp-boundary",
        },
    )
