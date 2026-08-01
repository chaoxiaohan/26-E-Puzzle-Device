# -*- coding: utf-8 -*-

import time

from main import (
    competition_candidate_confidence,
    competition_candidate_safe,
    competition_result_ready,
    competition_timeout_reached,
    create_solver_executor,
    stop_solver_executor,
)


def main():
    display = [
        {
            "piece_id": 1,
            "points": [(0, 0), (40, 0), (40, 50), (0, 50)],
        },
        {
            "piece_id": 2,
            "points": [(42, 0), (82, 0), (82, 50), (42, 50)],
        },
    ]
    motion_plan = [
        {"piece_id": 1},
        {"piece_id": 2},
    ]
    solve_info = {
        "forced": False,
        "method": "cpp-cover",
        "constraint_report": {
            "coverage": 0.94,
            "overlap": 0.0,
            "outer_piece_ratio": 1.0,
            "internal_match": 0.83,
            "boundary_min_coverage": 0.95,
            "boundary_max_gap_ratio": 0.03,
            "boundary_angle_error": 1.2,
        },
    }

    assert competition_result_ready(display, motion_plan, solve_info, 2)
    assert competition_candidate_safe(display, motion_plan, 2)
    assert competition_result_ready(
        display,
        motion_plan,
        dict(solve_info, forced=True),
        2,
    )
    assert competition_result_ready(
        display,
        motion_plan,
        None,
        2,
    )

    overlap_display = [
        display[0],
        {
            "piece_id": 2,
            "points": [(35, 0), (75, 0), (75, 50), (35, 50)],
        },
    ]
    assert not competition_candidate_safe(
        overlap_display,
        motion_plan,
        2,
    )
    assert not competition_candidate_safe(
        display,
        [{"piece_id": 1}, {"piece_id": 3}],
        2,
    )
    assert not competition_result_ready(
        overlap_display,
        motion_plan,
        solve_info,
        2,
    )
    assert competition_result_ready(
        display,
        motion_plan,
        {"method": "template-match", "forced": False},
        2,
    )
    assert not competition_timeout_reached(
        "NORMAL",
        100.0,
        {"confidence": 0.8},
        now=179.99,
    )
    assert competition_timeout_reached(
        "NORMAL",
        100.0,
        {"confidence": 0.8},
        now=180.0,
    )
    assert competition_timeout_reached(
        "CARD",
        100.0,
        {"confidence": 0.8},
        now=181.0,
    )
    assert not competition_timeout_reached(
        "FIRST",
        100.0,
        {"confidence": 0.8},
        now=200.0,
    )
    assert not competition_timeout_reached(
        "CARD",
        100.0,
        None,
        now=200.0,
    )
    assert competition_candidate_confidence(
        {"selection_score": 0.82},
        0.61,
    ) == 0.82
    assert competition_candidate_confidence({}, 0.61) == 0.61

    executor = create_solver_executor()
    future = executor.submit(time.sleep, 5)
    time.sleep(0.2)
    executor = stop_solver_executor(executor, future)
    assert executor.submit(pow, 2, 5).result(timeout=3) == 32
    executor.shutdown(wait=False, cancel_futures=True)

    print("competition mode validation and cancellation OK")


if __name__ == "__main__":
    main()
