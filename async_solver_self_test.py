import concurrent.futures
import multiprocessing
import time

from main import build_stable_piece_set, solve_piece_set_worker


def make_piece(points):
    center = (
        int(round(sum(point[0] for point in points) / len(points))),
        int(round(sum(point[1] for point in points) / len(points))),
    )
    width = max(point[0] for point in points) - min(
        point[0] for point in points
    )
    height = max(point[1] for point in points) - min(
        point[1] for point in points
    )
    return {
        "points": points,
        "center": center,
        "area": float(width * height),
        "angle": 0.0,
        "longest_edge": (points[0], points[1]),
        "solidity": 1.0,
    }


def main():
    pieces = [
        make_piece([(0, 0), (120, 0), (120, 144), (0, 144)]),
        make_piece(
            [(120, 0), (240, 0), (240, 144), (120, 144)]
        ),
    ]
    entries = []
    now = time.monotonic()
    for frame_id in range(6):
        jitter = -1 if frame_id % 3 == 0 else frame_id % 2
        frame_pieces = []
        for piece in pieces:
            points = [
                (point[0] + jitter, point[1] - jitter)
                for point in piece["points"]
            ]
            frame_pieces.append(make_piece(points))
        entries.append((now + frame_id * 0.02, 1.0, frame_pieces))

    stable = build_stable_piece_set(entries)
    if stable is None:
        raise RuntimeError("stable median rejected")

    with concurrent.futures.ProcessPoolExecutor(
        max_workers=1,
        mp_context=multiprocessing.get_context("spawn"),
    ) as executor:
        result = executor.submit(
            solve_piece_set_worker,
            stable,
            (100, 10, 520, 700),
        ).result(timeout=15)
    if result["layout"] is None:
        raise RuntimeError("worker did not solve rectangle")
    print(
        "ASYNC_OK pieces=%d nodes=%d time=%.1fms"
        % (
            len(stable),
            result["nodes"],
            result["elapsed_ms"],
        )
    )


if __name__ == "__main__":
    main()
