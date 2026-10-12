import numpy as np

from card_joint_solver import layout_pose_key
from main import card_candidates_are_confident, card_execution_ready, card_layout_signature, select_card_candidate


def candidate(texture, flipped=False, confidence=1.0, index=0.5, locked=False, tier=3):
    polygon = np.array([(0, 0), (80, 0), (80, 30), (0, 30)], dtype=float)
    second = polygon + (80, 0)
    if flipped:
        second = 2 * second.mean(axis=0) - second
    layout = {0: polygon, 1: second}
    return {"base_rank": texture, "layout": layout, "pattern_layout": layout,
            "info": {"card_joint_search": True, "geometry_tier": tier,
                     "texture_score": texture, "texture_confidence": confidence,
                     "global_pattern_score": 0.5, "global_pattern_confidence": 0.0,
                     "rank_index_score": index, "rank_index_confidence": 1.0,
                     "rank_index_locked": locked, "card_assignment": (0, 1),
                     "constraint_report": {"coverage": 0.96, "internal_match": 0.90,
                                           "corners": 1.0, "outer_piece_ratio": 1.0}}}


good = candidate(0.90, index=0.0)
wrong = candidate(0.70, flipped=True, index=1.0, locked=True)
assert card_layout_signature(good["layout"]) != card_layout_signature(wrong["layout"])
selected = select_card_candidate([wrong, good])
assert selected is good, "a corner-index lock overrode stronger seam evidence"
assert card_execution_ready(good["info"])

safe = candidate(0.70, tier=2)
unsafe = candidate(0.95, flipped=True, tier=1)
assert select_card_candidate([unsafe, safe]) is safe
assert not card_execution_ready(safe["info"]), "a single incomplete pool cannot prove a unique solution"

first, second = candidate(0.70), candidate(0.69, flipped=True)
assert not card_candidates_are_confident([first, second]), "same assignment hid different piece orientations"
assert first["info"]["selection_candidate_count"] == 2

blank = candidate(0.5, confidence=0.0, index=1.0, locked=True)
other_blank = candidate(0.5, flipped=True, confidence=0.0)
assert not card_candidates_are_confident([blank, other_blank])
assert blank["info"]["card_status"] == "WEAK_TEXTURE"

duplicate = candidate(0.90, index=0.0)
rotation = np.array([[0.0, -1.0], [1.0, 0.0]])
duplicate["pattern_layout"] = {index: polygon @ rotation.T + (123, 67)
                               for index, polygon in duplicate["layout"].items()}
assert layout_pose_key(duplicate["pattern_layout"]) == layout_pose_key(good["pattern_layout"])
selected = select_card_candidate([duplicate, good, wrong])
assert selected["info"]["selection_candidate_count"] == 2
assert card_execution_ready(selected["info"])

single = candidate(0.9)
single["info"].update(card_search_complete=True, card_candidate_pool_complete=False,
                      card_generated_candidate_count=64)
select_card_candidate([single])
assert not card_execution_ready(single["info"]), "truncated candidates created false uniqueness"
print("CARD_CANDIDATE_OK")
