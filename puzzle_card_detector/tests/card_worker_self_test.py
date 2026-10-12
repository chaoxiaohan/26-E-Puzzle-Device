"""完整CARD流程的有标签合成回归：不把矩形成立等同于牌面正确。"""

from card_face_solver import close_card_pattern_layout
from main import card_execution_ready, solve_card_piece_set_worker
from tests.card_graph_self_test import _scene, _pose_error


def main():
    fixtures = {
        "four-equal-rectangles": [
            [(0, 0), (80, 0), (80, 50), (0, 50)],
            [(80, 0), (160, 0), (160, 50), (80, 50)],
            [(0, 50), (80, 50), (80, 100), (0, 100)],
            [(80, 50), (160, 50), (160, 100), (80, 100)],
        ],
        "equal-strips": [
            [(x, 0), (x + 40, 0), (x + 40, 100), (x, 100)] for x in (0, 40, 80, 120)
        ],
        "same-triangles": [
            [(0, 0), (160, 0), (0, 100)],
            [(160, 0), (160, 100), (0, 100)],
        ],
        "same-trapezoids": [
            [(0, 0), (60, 0), (100, 100), (0, 100)],
            [(60, 0), (160, 0), (160, 100), (100, 100)],
        ],
    }
    verified = 0
    for name, polygons in fixtures.items():
        frame, pieces, expected = _scene(polygons, clockwise=True)
        result = solve_card_piece_set_worker(frame, pieces, (0, 0, 660, 660))
        assert result["layout"] is not None and result["preview_rgb"] is not None, name
        assert result["candidate_pool"], name
        pattern = close_card_pattern_layout(result["layout"], result["info"])
        error = _pose_error(pattern, expected)
        if card_execution_ready(result["info"]):
            assert error < 0.5, (name, "verified a wrong printed arrangement", error)
            verified += 1
        if name in ("four-equal-rectangles", "equal-strips", "same-triangles"):
            assert card_execution_ready(result["info"]), (name, result["info"]["card_status"])
        print("CARD_WORKER_CASE", name, result["info"]["card_status"],
              "pose_error", round(error, 3), "seconds", round(result["elapsed_ms"] / 1000, 3))
    assert verified >= 3, "informative repeated-shape cases were rejected"

    frame, pieces, _ = _scene(fixtures["four-equal-rectangles"], blank=True)
    result = solve_card_piece_set_worker(frame, pieces, (0, 0, 660, 660))
    assert not card_execution_ready(result["info"])
    assert result["info"]["card_status"] in ("WEAK_TEXTURE", "AMBIGUOUS")
    assert len(result["candidate_pool"]) > 1
    print("CARD_WORKER_OK")


if __name__ == "__main__":
    main()
