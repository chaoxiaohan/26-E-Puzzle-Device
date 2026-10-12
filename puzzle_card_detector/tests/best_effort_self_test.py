import time

from main import layout_has_interior_overlap, solve_piece_set_worker


pieces = [
    {
        "points": [
            (424, 127),
            (455, 224),
            (539, 197),
        ],
    },
    {
        "points": [
            (367, 150),
            (204, 166),
            (236, 240),
            (341, 202),
        ],
    },
    {
        "points": [
            (122, 315),
            (183, 387),
            (332, 319),
            (335, 296),
            (186, 267),
        ],
    },
    {
        "points": [
            (516, 331),
            (472, 277),
            (369, 366),
            (509, 386),
        ],
    },
]

started = time.perf_counter()
result = solve_piece_set_worker(
    pieces,
    (60, 80, 640, 720),
)
elapsed_ms = (time.perf_counter() - started) * 1000.0
if result["layout"] is None:
    raise RuntimeError("best-effort candidate was not returned")
if layout_has_interior_overlap(result["layout"]):
    raise RuntimeError("best-effort candidate contains overlap")
if result["info"]["execution_mode"] != "BEST":
    raise RuntimeError("expected BEST mode: %s" % result["info"])
if elapsed_ms > 6000.0:
    raise RuntimeError("best-effort solve is too slow: %.1fms" % elapsed_ms)

report = result["info"]["constraint_report"]
print(
    "BEST_EFFORT_OK score=%.3f coverage=%.3f internal=%.3f "
    "side=%.3f gap=%.3f nodes=%d time=%.1fms"
    % (
        result["score"],
        report["coverage"],
        report["internal_match"],
        report["boundary_min_coverage"],
        report["boundary_max_gap_ratio"],
        result["nodes"],
        elapsed_ms,
    )
)
