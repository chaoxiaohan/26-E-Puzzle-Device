import json
import os
import sys

import cv2
import numpy as np

from main import solve_card_piece_set_worker


def main():
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: python3 tests/export_card_candidate_pool.py "
            "capture.json output.png"
        )
    metadata_path, output_path = map(os.path.abspath, sys.argv[1:])
    with open(metadata_path, "r", encoding="utf-8") as file:
        metadata = json.load(file)
    frame_bgr = cv2.imread(
        os.path.join(
            os.path.dirname(metadata_path),
            metadata["raw_file"],
        )
    )
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    pieces = []
    for item in metadata["pieces"]:
        points = [tuple(point) for point in item["points"]]
        pieces.append(
            {
                "points": points,
                "center": tuple(item["center"]),
                "area": float(item["area"]),
                "angle": float(item["angle"]),
                "longest_edge": (points[0], points[1]),
                "solidity": float(item["solidity"]),
            }
        )
    result = solve_card_piece_set_worker(
        frame_rgb,
        pieces,
        tuple(metadata["roi"]),
    )
    pool = result.get("candidate_pool", [])
    if not pool:
        raise RuntimeError("candidate pool is empty")

    columns = 4
    cell_width = 300
    cell_height = 230
    rows = (len(pool) + columns - 1) // columns
    sheet = np.full(
        (rows * cell_height, columns * cell_width, 3),
        245,
        dtype=np.uint8,
    )
    for index, candidate in enumerate(pool):
        row, column = divmod(index, columns)
        preview = cv2.cvtColor(
            candidate["preview_rgb"],
            cv2.COLOR_RGB2BGR,
        )
        scale = min(270 / preview.shape[1], 170 / preview.shape[0])
        resized = cv2.resize(
            preview,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
        x = column * cell_width + 15
        y = row * cell_height + 38
        sheet[y:y + resized.shape[0], x:x + resized.shape[1]] = resized
        color = (220, 80, 20) if candidate["selected"] else (30, 30, 30)
        cv2.putText(
            sheet,
            "#%d %.1f%% %s T%d"
            % (
                candidate["rank"],
                candidate["score"] * 100.0,
                candidate["source"],
                candidate["geometry_tier"],
            ),
            (x, row * cell_height + 27),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            color,
            1,
            cv2.LINE_AA,
        )
    cv2.imwrite(output_path, sheet)
    with open(output_path + ".json", "w", encoding="utf-8") as file:
        json.dump(
            [
                {
                    key: value
                    for key, value in candidate.items()
                    if key != "preview_rgb"
                }
                for candidate in pool
            ],
            file,
            ensure_ascii=False,
            indent=2,
        )
    print("CARD_POOL_EXPORTED count=%d output=%s" % (len(pool), output_path))


if __name__ == "__main__":
    main()
