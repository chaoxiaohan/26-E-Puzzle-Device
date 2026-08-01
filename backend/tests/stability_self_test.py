from copy import deepcopy

from main import build_best_effort_piece_set, build_stable_piece_set


base = [
    {
        "points": [(100, 100), (180, 100), (180, 160), (100, 160)],
        "center": (140, 130),
        "area": 4800.0,
        "angle": 0.0,
        "longest_edge": 80.0,
        "solidity": 0.98,
    },
    {
        "points": [(240, 110), (320, 110), (320, 170), (240, 170)],
        "center": (280, 140),
        "area": 4800.0,
        "angle": 0.0,
        "longest_edge": 80.0,
        "solidity": 0.98,
    },
]

recent = []
for frame_id, shift in enumerate((0, 1, -1, 1, 0, -1)):
    pieces = deepcopy(base)
    for piece in pieces:
        piece["points"] = [
            (x + shift, y - shift) for x, y in piece["points"]
        ]
        piece["center"] = (
            piece["center"][0] + shift,
            piece["center"][1] - shift,
        )
        piece["area"] += shift * 18.0
    if frame_id == 2:
        x, y = pieces[0]["points"][0]
        pieces[0]["points"][0] = (x + 9, y - 7)
    recent.append((frame_id * 0.03, 9000.0 + frame_id, pieces))

stable = build_stable_piece_set(recent)
if stable is None or len(stable) != 2:
    raise RuntimeError("robust median rejected a recoverable contour jitter")

fallback = build_best_effort_piece_set(recent[-2:])
if fallback is None or len(fallback) != 2:
    raise RuntimeError("best-effort stability fallback returned no pieces")

print("STABILITY_OK pieces=%d" % len(stable))
