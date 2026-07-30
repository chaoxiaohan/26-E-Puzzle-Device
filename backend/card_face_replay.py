import json
import itertools
import os
import sys

import cv2
import numpy as np

from card_face_solver import (
    generate_shape_swap_layouts,
    score_layout_global_pattern,
    score_layout_texture,
    solve_card_face,
)


def save_layout_preview(
    frame_bgr,
    pieces,
    layout,
    output_path,
):
    all_points = np.vstack(list(layout.values()))
    minimum = np.min(all_points, axis=0)
    maximum = np.max(all_points, axis=0)
    scale = 5.0
    size = np.ceil((maximum - minimum) * scale + 24).astype(int)
    preview = np.full(
        (size[1], size[0], 3),
        70,
        dtype=np.uint8,
    )
    for piece_id, target in layout.items():
        source = np.asarray(
            pieces[piece_id]["points"],
            dtype=np.float32,
        )
        destination = (
            (np.asarray(target, dtype=np.float32) - minimum) * scale
            + 12.0
        )
        transform, _ = cv2.estimateAffinePartial2D(
            source,
            destination,
            method=cv2.LMEDS,
        )
        if transform is None:
            continue
        source_mask = np.zeros(frame_bgr.shape[:2], dtype=np.uint8)
        cv2.fillPoly(
            source_mask,
            [np.rint(source).astype(np.int32)],
            255,
        )
        warped = cv2.warpAffine(
            frame_bgr,
            transform,
            (preview.shape[1], preview.shape[0]),
            flags=cv2.INTER_LINEAR,
        )
        warped_mask = cv2.warpAffine(
            source_mask,
            transform,
            (preview.shape[1], preview.shape[0]),
            flags=cv2.INTER_NEAREST,
        )
        preview[warped_mask > 0] = warped[warped_mask > 0]
    cv2.imwrite(output_path, preview)


def main():
    paths = [
        argument
        for argument in sys.argv[1:]
        if not argument.startswith("--")
    ]
    if len(paths) != 1:
        raise SystemExit("usage: python3 card_face_replay.py capture.json")

    metadata_path = os.path.abspath(paths[0])
    with open(metadata_path, "r", encoding="utf-8") as file:
        metadata = json.load(file)
    capture_dir = os.path.dirname(metadata_path)
    frame_bgr = cv2.imread(
        os.path.join(capture_dir, metadata["raw_file"])
    )
    if frame_bgr is None:
        raise RuntimeError("cannot read capture image")
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    pieces = []
    for item in metadata["pieces"]:
        points = [
            tuple(point)
            for point in item["points"]
        ]
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

    if "--worker" in sys.argv:
        from main import solve_card_piece_set_worker

        result = solve_card_piece_set_worker(
            frame_rgb,
            pieces,
            tuple(metadata["roi"]),
        )
        if result["layout"] is None:
            raise RuntimeError("card worker returned no layout")
        if result.get("preview_rgb") is None:
            raise RuntimeError("card worker returned no preview")
        output_path = (
            os.path.splitext(metadata_path)[0]
            + "_worker.png"
        )
        cv2.imwrite(
            output_path,
            cv2.cvtColor(result["preview_rgb"], cv2.COLOR_RGB2BGR),
        )
        print(
            "CARD_WORKER_OK score=%.3f mode=%s method=%s "
            "nodes=%d time=%.1fms output=%s"
            % (
                result["score"],
                result["info"]["execution_mode"],
                result["info"]["method"],
                result["nodes"],
                result["elapsed_ms"],
                output_path,
            )
        )
        return

    if "--swaps" in sys.argv:
        from cpp_rectangle_solver import solve as solve_cpp
        from main import prepare_layout_for_execution

        base_layout, _, _, base_info = solve_cpp(
            pieces,
            fill_ratio=0.92,
            position_step=3,
        )
        if base_layout is None:
            raise RuntimeError("no base layout")
        results = []
        for layout, assignment in generate_shape_swap_layouts(
            pieces,
            base_layout,
        ):
            raw_texture = score_layout_texture(
                frame_rgb,
                pieces,
                layout,
            )
            raw_global = score_layout_global_pattern(
                frame_rgb,
                pieces,
                layout,
            )
            print(
                "SWAP RAW",
                assignment,
                "texture=%.6f" % raw_texture["score"],
                "global=%.6f" % raw_global["score"],
                "global_conf=%.6f" % raw_global["confidence"],
                "details=%s" % (raw_global["corner_details"],),
            )
            info = dict(base_info)
            info["boundary_safe"] = False
            prepared, repair = prepare_layout_for_execution(
                layout,
                info,
                tuple(metadata["roi"]),
            )
            if prepared is None:
                info["forced"] = True
                prepared, forced_repair = prepare_layout_for_execution(
                    layout,
                    info,
                    tuple(metadata["roi"]),
                )
                if prepared is None:
                    print(
                        "SWAP REJECT",
                        assignment,
                        repair,
                        forced_repair,
                    )
                    continue
            texture = score_layout_texture(
                frame_rgb,
                pieces,
                prepared,
            )
            global_pattern = score_layout_global_pattern(
                frame_rgb,
                pieces,
                prepared,
            )
            report = info["constraint_report"]
            rank = (
                report["coverage"] * 0.38
                + report["internal_match"] * 0.17
                + texture["score"] * 0.20
                + global_pattern["score"] * 0.35
            )
            results.append(
                (
                    rank,
                    assignment,
                    prepared,
                    info,
                    texture,
                    global_pattern,
                )
            )
        results.sort(key=lambda item: item[0], reverse=True)
        for result_id, result in enumerate(results):
            (
                rank,
                assignment,
                prepared,
                info,
                texture,
                global_pattern,
            ) = result
            print(
                "SWAP",
                result_id,
                assignment,
                "rank=%.3f" % rank,
                "coverage=%.3f"
                % info["constraint_report"]["coverage"],
                "internal=%.3f"
                % info["constraint_report"]["internal_match"],
                "texture=%.3f" % texture["score"],
                "global=%.3f" % global_pattern["score"],
                "confidence=%.3f" % texture["confidence"],
                "seams=%d" % texture["seam_count"],
            )
            output_path = (
                os.path.splitext(metadata_path)[0]
                + "_swap_%02d.png" % result_id
            )
            save_layout_preview(
                frame_bgr,
                pieces,
                prepared,
                output_path,
            )
        return
    if "--permutations" in sys.argv:
        from cpp_rectangle_solver import solve as solve_cpp
        from main import prepare_layout_for_execution

        results = []
        for candidate_id, order in enumerate(
            itertools.permutations(range(len(pieces)))
        ):
            permuted = [pieces[piece_id] for piece_id in order]
            layout, score, nodes, info = solve_cpp(
                permuted,
                fill_ratio=0.92,
                position_step=3,
            )
            if layout is None:
                continue
            original_layout = {
                order[local_id]: polygon
                for local_id, polygon in layout.items()
            }
            info = dict(info)
            prepared, _ = prepare_layout_for_execution(
                original_layout,
                info,
                tuple(metadata["roi"]),
            )
            if prepared is None:
                continue
            texture = score_layout_texture(
                frame_rgb,
                pieces,
                prepared,
            )
            rank = (
                info["coverage"] * 0.55
                + info["internal_quality"] * 0.20
                + info["boundary_quality"] * 0.10
                + texture["score"] * 0.35
            )
            results.append(
                (
                    rank,
                    candidate_id,
                    order,
                    prepared,
                    info,
                    texture,
                    nodes,
                )
            )
        results.sort(key=lambda item: item[0], reverse=True)
        for result_id, result in enumerate(results[:8]):
            (
                rank,
                candidate_id,
                order,
                prepared,
                info,
                texture,
                nodes,
            ) = result
            print(
                "PERM",
                result_id,
                "candidate=%d" % candidate_id,
                "order=%s" % (order,),
                "rank=%.3f" % rank,
                "coverage=%.3f" % info["coverage"],
                "internal=%.3f" % info["internal_quality"],
                "texture=%.3f" % texture["score"],
                "seams=%d" % texture["seam_count"],
                "nodes=%d" % nodes,
            )
            output_path = (
                os.path.splitext(metadata_path)[0]
                + "_permutation_%02d.png" % result_id
            )
            save_layout_preview(
                frame_bgr,
                pieces,
                prepared,
                output_path,
            )
        return
    if "--candidates" in sys.argv:
        from cpp_rectangle_solver import solve as solve_cpp
        from main import prepare_layout_for_execution

        for candidate_id, (fill_ratio, position_step) in enumerate(
            (
                (0.98, 3),
                (0.96, 4),
                (0.92, 3),
                (0.88, 4),
                (0.84, 3),
                (0.80, 4),
                (0.80, 3),
                (0.76, 3),
            )
        ):
            layout, score, nodes, info = solve_cpp(
                pieces,
                fill_ratio=fill_ratio,
                position_step=position_step,
            )
            if layout is None:
                print(
                    "CANDIDATE",
                    candidate_id,
                    fill_ratio,
                    position_step,
                    "NONE",
                    nodes,
                )
                continue
            info = dict(info)
            prepared, repair = prepare_layout_for_execution(
                layout,
                info,
                tuple(metadata["roi"]),
            )
            if prepared is None:
                print(
                    "CANDIDATE",
                    candidate_id,
                    fill_ratio,
                    position_step,
                    "REJECT",
                    repair,
                )
                continue
            texture = score_layout_texture(
                frame_rgb,
                pieces,
                prepared,
            )
            print(
                "CANDIDATE",
                candidate_id,
                fill_ratio,
                position_step,
                "shape=%.3f" % score,
                "coverage=%.3f" % info["coverage"],
                "internal=%.3f" % info["internal_quality"],
                "boundary=%.3f" % info["boundary_quality"],
                "texture=%.3f" % texture["score"],
                "confidence=%.3f" % texture["confidence"],
                "seams=%d" % texture["seam_count"],
                "nodes=%d" % nodes,
            )
            output_path = (
                os.path.splitext(metadata_path)[0]
                + "_candidate_%02d.png" % candidate_id
            )
            save_layout_preview(
                frame_bgr,
                pieces,
                prepared,
                output_path,
            )
        return
    if "--worker" in sys.argv:
        from main import solve_card_piece_set_worker

        result = solve_card_piece_set_worker(
            frame_rgb,
            pieces,
            tuple(metadata["roi"]),
        )
    elif "--normal" in sys.argv:
        from main import solve_piece_set_worker

        result = solve_piece_set_worker(
            pieces,
            tuple(metadata["roi"]),
        )
    else:
        result = solve_card_face(
            frame_rgb,
            pieces,
            node_limit=180000,
            time_limit_s=20.0,
        )
    print(
        "CARD_REPLAY layout=%s score=%.3f nodes=%d time=%.1fms"
        % (
            result["layout"] is not None,
            result["score"],
            result["nodes"],
            result["elapsed_ms"],
        )
    )
    print("INFO", result["info"])
    if result["layout"] is not None:
        texture = score_layout_texture(
            frame_rgb,
            pieces,
            result["layout"],
        )
        print("TEXTURE", texture)
        print(
            "LAYOUT",
            {
                piece_id: polygon.round(2).tolist()
                for piece_id, polygon in result["layout"].items()
            },
        )
        output_path = os.path.splitext(metadata_path)[0] + "_card_replay.png"
        save_layout_preview(
            frame_bgr,
            pieces,
            result["layout"],
            output_path,
        )
        print("PREVIEW", output_path)


if __name__ == "__main__":
    main()
