"""检查同形块的真实身份和朝向，不能只用矩形覆盖度通过测试。"""

import time

import numpy as np

from card_joint_solver import generate_rectangular_card_candidates, layout_pose_key
from tests.card_graph_self_test import _scene, _pose_error, _assert_rigid


def run():
    fixtures = {
        "quarters": [
            [(0, 0), (80, 0), (80, 50), (0, 50)],
            [(80, 0), (160, 0), (160, 50), (80, 50)],
            [(0, 50), (80, 50), (80, 100), (0, 100)],
            [(80, 50), (160, 50), (160, 100), (80, 100)],
        ],
        "strips": [
            [(x, 0), (x + 40, 0), (x + 40, 100), (x, 100)]
            for x in (0, 40, 80, 120)
        ],
        "unequal-strips": [
            [(left, 0), (right, 0), (right, 100), (left, 100)]
            for left, right in ((0, 30), (30, 65), (65, 105), (105, 160))
        ],
        "T": [
            [(0, 0), (80, 0), (80, 100), (0, 100)],
            [(80, 0), (160, 0), (160, 50), (80, 50)],
            [(80, 50), (160, 50), (160, 100), (80, 100)],
        ],
    }
    for name, polygons in fixtures.items():
        frame, pieces, expected = _scene(polygons, clockwise=True)
        started = time.monotonic()
        result = generate_rectangular_card_candidates(frame, pieces)
        assert result["candidates"], name
        for candidate in result["candidates"]:
            _assert_rigid(pieces, candidate)
        errors = [_pose_error(item["layout"], expected) for item in result["candidates"]]
        correct_rank = next((rank for rank, error in enumerate(errors) if error < 0.5), None)
        assert correct_rank is not None and correct_rank < 4, (name, correct_rank, errors[:4])
        keys = [layout_pose_key(item["layout"]) for item in result["candidates"]]
        assert len(keys) == len(set(keys)), "global duplicates consumed the candidate pool"
        assert result["search_complete"]
        print(name, "rank", correct_rank, "nodes", result["nodes"],
              "pairs", result["edge_pairs"], "seconds", round(time.monotonic() - started, 3))

    frame, pieces, expected = _scene(fixtures["quarters"], blank=True)
    blank = generate_rectangular_card_candidates(frame, pieces)
    assert len(blank["candidates"]) > 1
    assert max(item["texture"]["confidence"] for item in blank["candidates"]) < 0.05
    first = np.array(fixtures["quarters"][0], dtype=float)
    assert layout_pose_key({0: first, 1: first + (80, 0)}) != layout_pose_key(
        {0: first, 1: 2 * (first.mean(axis=0) + (80, 0)) - (first + (80, 0))})
    print("CARD_JOINT_OK")


if __name__ == "__main__":
    run()
