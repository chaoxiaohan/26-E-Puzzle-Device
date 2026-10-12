"""C++ 缩放坐标进入 CARD 时必须恢复像素单位，不能缩小真实碎片。"""

from unittest.mock import patch

import numpy as np

import main as backend
from card_face_solver import close_card_pattern_layout
from tests.card_graph_self_test import _scene, _pose_error


def main():
    polygons = [
        [(0, 0), (80, 0), (80, 50), (0, 50)],
        [(80, 0), (160, 0), (160, 50), (80, 50)],
        [(0, 50), (80, 50), (80, 100), (0, 100)],
        [(80, 50), (160, 50), (160, 100), (80, 100)],
    ]
    frame, pieces, expected = _scene(polygons, clockwise=True)
    seed = {piece_id: polygon * 0.5 for piece_id, polygon in expected.items()}
    info = {"solve_scale": 0.5, "width": 80.0, "height": 50.0, "ratio": 1.6,
            "coverage": 1.0, "overlap": 0.0, "method": "cpp-boundary"}
    empty_search = {"candidates": [], "nodes": 0, "search_complete": False}
    with patch.object(backend, 'classify_card_pieces', return_value={"kind": "irregular"}), \
         patch.object(backend, 'generate_card_graph_candidates', return_value=empty_search), \
         patch.object(backend, 'solve_rectangle_by_cover_cpp', return_value=(seed, 1.0, 20, info)) as cpp:
        result = backend.solve_card_piece_set_worker(frame, pieces, (0, 0, 660, 660))
    assert cpp.call_count == 1
    assert result["layout"] is not None and result["candidate_pool"]
    assert result["info"]["solve_scale"] == 1.0
    pattern = close_card_pattern_layout(result["layout"], result["info"])
    assert _pose_error(pattern, expected) < 0.5
    for piece_id, target in pattern.items():
        source = np.asarray(pieces[piece_id]["points"])
        before = np.linalg.norm(source[:, None] - source[None, :], axis=2)
        after = np.linalg.norm(target[:, None] - target[None, :], axis=2)
        assert np.max(np.abs(before - after)) < 1e-5
    print("CARD_CPP_SEED_OK")


if __name__ == '__main__':
    main()
