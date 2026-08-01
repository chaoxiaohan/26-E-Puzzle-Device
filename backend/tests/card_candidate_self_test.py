import numpy as np

from main import (
    card_candidates_are_confident,
    card_layout_signature,
    select_card_candidate,
)


horizontal = {
    0: np.asarray(
        [(0, 5), (30, 5), (30, 15), (0, 15)],
        dtype=np.float64,
    ),
}
vertical = {
    0: np.asarray(
        [(10, -5), (20, -5), (20, 25), (10, 25)],
        dtype=np.float64,
    ),
}
if card_layout_signature(horizontal) == card_layout_signature(vertical):
    raise RuntimeError("pose deduplication discarded rotation")


def candidate(
    texture_score,
    index_score=0.5,
    index_confidence=0.0,
    geometry_tier=3,
    assignment=(0, 1, 2, 3),
    global_score=0.5,
    index_valid=None,
    index_locked=False,
):
    return {
        "base_rank": 0.75,
        "layout": horizontal,
        "pattern_layout": horizontal,
        "info": {
            "geometry_tier": geometry_tier,
            "texture_score": texture_score,
            "texture_confidence": 1.0,
            "global_pattern_score": global_score,
            "global_pattern_confidence": 1.0,
            "rank_index_score": index_score,
            "rank_index_confidence": index_confidence,
            "rank_index_valid": index_valid,
            "rank_index_locked": index_locked,
            "card_assignment": assignment,
            "constraint_report": {
                "coverage": 0.95,
                "internal_match": 0.88,
                "corners": 1.0,
                "outer_piece_ratio": 1.0,
                "boundary_min_coverage": 0.95,
                "boundary_angle_error": 2.0,
            },
        },
    }


plain_best = candidate(0.65)
index_supported = candidate(0.65, 1.0, 1.0, index_locked=True)
selected = select_card_candidate([plain_best, index_supported])
if selected is not index_supported:
    raise RuntimeError("high-confidence index did not break a close tie")

clear_best = candidate(0.85, 0.0, 1.0)
selected = select_card_candidate([clear_best, index_supported])
if selected is not index_supported:
    raise RuntimeError("high-confidence outer-corner lock was ignored")

tier_two_pattern = candidate(0.70, geometry_tier=2)
tier_three_wrong = candidate(0.43, geometry_tier=3)
selected = select_card_candidate([tier_two_pattern, tier_three_wrong])
if selected is not tier_two_pattern:
    raise RuntimeError("geometry tier overrode a better safe pattern")

unsafe_pattern = candidate(0.95, geometry_tier=1)
selected = select_card_candidate([tier_two_pattern, unsafe_pattern])
if selected is not tier_two_pattern:
    raise RuntimeError("unsafe candidate entered the normal selection pool")

repeated_pattern = candidate(0.67, global_score=0.56)
diagonal_pattern = candidate(
    0.65,
    index_score=0.98,
    index_confidence=1.0,
    global_score=0.84,
    index_locked=True,
)
selected = select_card_candidate([repeated_pattern, diagonal_pattern])
if selected is not diagonal_pattern:
    raise RuntimeError("reliable diagonal evidence did not resolve repeated pips")

early_index = candidate(
    0.68,
    index_score=0.98,
    index_confidence=0.95,
    geometry_tier=2,
    index_valid=True,
    index_locked=True,
)
early_other = candidate(0.62, assignment=(1, 0, 2, 3))
if not card_candidates_are_confident([early_index, early_other]):
    raise RuntimeError("reliable index evidence did not stop extended search")

print("CARD_CANDIDATE_OK")
