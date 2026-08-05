"""第一问短外边保护的回归测试。"""

import os
import sys


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from layout_constraints import evaluate_layout
from main import solve_piece_set_worker


def main():
    raw_points = [
        [(344, 340), (334, 490), (535, 502)],
        [(300, 393), (182, 447), (160, 540), (181, 545)],
        [(332, 509), (320, 562), (409, 564), (374, 519)],
        [(211, 572), (216, 648), (463, 632), (398, 592)],
    ]
    pieces = [{"points": points} for points in raw_points]
    roi = (160, 340, 375, 310)
    result = solve_piece_set_worker(pieces, roi, True)
    assert result["layout"] is not None, "短外边保护没有给出可执行布局"
    assert result["info"].get("execution_mode") == "RECT_SHORT"
    report = evaluate_layout(result["layout"], edge_tolerance_ratio=0.05)
    assert report["coverage"] >= 0.90
    assert report["overlap"] <= 0.01
    assert report["corners"] >= 0.99
    assert report["internal_match"] >= 0.85
    print("short edge protection self-test passed")


if __name__ == "__main__":
    main()
