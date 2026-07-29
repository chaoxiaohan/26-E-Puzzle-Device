import time

try:
    from .solver_boundary import solve as solve_by_boundary
    from .solver_v2 import solve as solve_by_edges
except ImportError:
    from solver_boundary import solve as solve_by_boundary
    from solver_v2 import solve as solve_by_edges


def is_strict_rectangle(metrics, dimension_range=None):
    if dimension_range is None:
        dimension_range = (89.0, 121.0, 49.0, 91.0)
    if dimension_range == "auto":
        dimension_ok = bool(
            metrics
            and 0.98
            <= metrics["width"] / max(1.0, metrics["height"])
            <= 2.45
        )
    else:
        long_min, long_max, short_min, short_max = dimension_range
        dimension_ok = bool(
            metrics
            and long_min <= metrics["width"] <= long_max
            and short_min <= metrics["height"] <= short_max
        )
    return bool(
        metrics
        and metrics["coverage"] >= 0.985
        and metrics["overlap"] <= 0.006
        and metrics["corners"] >= 0.99
        and dimension_ok
    )


def solve(
    pieces,
    time_limit_s=3.0,
    dimension_range=None,
    allow_relaxed=False,
):
    started = time.perf_counter()
    first_time = (
        max(0.3, time_limit_s * 0.85)
        if allow_relaxed
        else min(1.2, max(0.3, time_limit_s * 0.45))
    )
    edge_result = solve_by_edges(
        pieces,
        time_limit_s=first_time,
        return_best=allow_relaxed,
    )
    if is_strict_rectangle(
        edge_result[3],
        dimension_range,
    ):
        return (*edge_result, "edge")

    remaining = time_limit_s - (time.perf_counter() - started)
    if remaining <= 0.1:
        return (*edge_result, "edge")

    boundary_result = solve_by_boundary(
        pieces,
        time_limit_s=remaining,
        dimension_range=dimension_range,
    )
    if is_strict_rectangle(
        boundary_result[3],
        dimension_range,
    ):
        return (*boundary_result, "boundary")

    edge_metrics = edge_result[3]
    boundary_metrics = boundary_result[3]
    if boundary_metrics and (
        not edge_metrics
        or boundary_metrics["score"] > edge_metrics["score"]
    ):
        return (*boundary_result, "boundary")
    return (*edge_result, "edge")
