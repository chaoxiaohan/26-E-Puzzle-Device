"""Run from the detector directory: python -m tests.card_pose_self_test."""

import itertools

import numpy as np

from card_face_solver import (
    _best_similarity_pose,
    _rigid_similarity_poses,
    generate_all_slot_layouts,
    generate_shape_swap_layouts,
)


def signed_area(points):
    return float(np.sum(
        points[:, 0] * np.roll(points[:, 1], -1)
        - points[:, 1] * np.roll(points[:, 0], -1)
    ) * 0.5)


def check_rigid(source, transformed):
    before = np.linalg.norm(source[:, None] - source[None, :], axis=2)
    after = np.linalg.norm(transformed[:, None] - transformed[None, :], axis=2)
    assert np.allclose(before, after, atol=1e-7), "pose changed piece dimensions"
    assert np.isclose(signed_area(source), signed_area(transformed)), "pose reflected piece"


def fixtures(shape, count=4):
    pieces = [{"points": shape + (index * 130, index * 17)}
              for index in range(count)]
    slots = {index: shape + (index * 150, 200)
             for index in range(count)}
    return pieces, slots


def check_symmetric_family(shape, orientations):
    pieces, slots = fixtures(shape)
    for generate in (generate_shape_swap_layouts, generate_all_slot_layouts):
        candidates = generate(pieces, slots)
        assert len(candidates) == 24 * orientations ** 4, "independent orientations missing"
        signatures = set()
        assignments = {}
        for layout, assignment in candidates:
            signatures.add(tuple(np.round(layout[index], 6).tobytes()
                                 for index in range(4)))
            assignments[assignment] = assignments.get(assignment, 0) + 1
            for slot_id, source_id in enumerate(assignment):
                check_rigid(pieces[source_id]["points"], layout[source_id])
                assert np.allclose(np.mean(layout[source_id], axis=0),
                                   np.mean(slots[slot_id], axis=0))
        assert len(signatures) == len(candidates), "duplicate ordered-vertex poses"
        assert set(assignments) == set(itertools.permutations(range(4)))
        assert set(assignments.values()) == {orientations ** 4}


def check_asymmetric_family(shape):
    pieces, slots = fixtures(shape, 2)
    # Different contour starting vertex and winding must not imply a reflection.
    pieces[1]["points"] = np.roll(pieces[1]["points"][::-1], 1, axis=0)
    for generate in (generate_shape_swap_layouts, generate_all_slot_layouts):
        candidates = generate(pieces, slots)
        assert {assignment for _, assignment in candidates} == {(0, 1), (1, 0)}
        assert len(candidates) == 2, "asymmetric shapes gained false symmetry"
        for layout, _ in candidates:
            for index in range(2):
                check_rigid(pieces[index]["points"], layout[index])


def run():
    rectangle = np.asarray([(0, 0), (80, 0), (80, 30), (0, 30)], dtype=float)
    square = np.asarray([(0, 0), (40, 0), (40, 40), (0, 40)], dtype=float)
    check_symmetric_family(rectangle, 2)  # 24 assignments * 16 orientations = 384.
    check_symmetric_family(square, 4)  # 24 assignments * 256 orientations = 6144.
    check_asymmetric_family(np.asarray([(0, 0), (75, 0), (12, 41)], dtype=float))
    check_asymmetric_family(np.asarray([(0, 0), (80, 0), (61, 35), (9, 35)], dtype=float))

    noise = np.asarray([(0.2, -0.1), (-0.3, 0.2), (0.1, 0.3), (0.1, -0.2)])
    for shape, count in ((rectangle, 2), (square, 4)):
        poses = _rigid_similarity_poses(shape, shape + noise + (30, 100))
        assert len(poses) == count, "contour noise discarded a symmetric direction"
        for target_center, source_center, rotation, scale, _ in poses:
            assert scale == 1.0
            assert np.allclose(rotation.T @ rotation, np.eye(2))
            assert np.isclose(np.linalg.det(rotation), 1.0)
            check_rigid(shape, (shape - source_center) @ rotation.T + target_center)

    assert not _rigid_similarity_poses(rectangle, rectangle * 1.5)
    pieces = [{"points": rectangle}, {"points": rectangle * 1.5 + (150, 0)}]
    slots = {index: piece["points"] + (0, 100) for index, piece in enumerate(pieces)}
    for generate in (generate_shape_swap_layouts, generate_all_slot_layouts):
        assert {assignment for _, assignment in generate(pieces, slots)} == {(0, 1)}

    # Keep rendering callers' existing best-similarity tuple and scale behavior.
    pose = _best_similarity_pose(rectangle, rectangle * 1.5 + (10, 20))
    assert len(pose) == 5 and np.isclose(pose[3], 1.5) and pose[-1] < 1e-7
    print("CARD_POSE_OK")


if __name__ == "__main__":
    run()
