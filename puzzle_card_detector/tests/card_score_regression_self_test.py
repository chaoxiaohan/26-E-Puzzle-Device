# -*- coding: utf-8 -*-

import cv2
import numpy as np

from card_face_solver import score_rank_index_diagonal
from main import card_candidate_primary_score


def make_candidate(index_score, index_confidence):
    return {
        "info": {
            "texture_score": 0.64,
            "texture_confidence": 0.85,
            "global_pattern_score": 0.60,
            "global_pattern_confidence": 0.80,
            "rank_index_score": index_score,
            "rank_index_confidence": index_confidence,
            "constraint_report": {
                "coverage": 0.93,
                "internal_match": 0.88,
                "corners": 1.0,
                "outer_piece_ratio": 1.0,
                "boundary_min_coverage": 0.94,
                "boundary_angle_error": 2.0,
            },
        },
    }


def main():
    card = np.full((160, 250, 3), 245, dtype=np.uint8)
    red = (220, 25, 35)
    cv2.putText(
        card,
        "7",
        (8, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        red,
        3,
        cv2.LINE_AA,
    )
    diamond = np.array(
        [[43, 13], [52, 22], [43, 31], [34, 22]],
        dtype=np.int32,
    )
    cv2.fillPoly(card, [diamond], red)
    corner = cv2.rotate(card[:48, :64], cv2.ROTATE_180)
    card[-48:, -64:] = corner
    polygon = np.array(
        [[0, 0], [249, 0], [249, 159], [0, 159]],
        dtype=np.float32,
    )
    pieces = [{"points": polygon}]
    layout = {0: polygon.copy()}

    correct = score_rank_index_diagonal(card, pieces, layout)
    same_side_card = card.copy()
    same_side_card[-48:, -64:] = 245
    same_side_card[-48:, :64] = corner
    same_side = score_rank_index_diagonal(
        same_side_card,
        pieces,
        layout,
    )
    assert correct["valid"] is True, correct
    assert same_side["valid"] is False, same_side
    assert correct["score"] > same_side["score"] + 0.5

    neutral = card_candidate_primary_score(make_candidate(0.5, 0.0))
    supported = card_candidate_primary_score(
        make_candidate(correct["score"], correct["confidence"])
    )
    contradicted = card_candidate_primary_score(
        make_candidate(same_side["score"], same_side["confidence"])
    )
    assert supported > neutral + 0.01
    assert contradicted < neutral - 0.01
    print(
        "CARD_SCORE_REGRESSION_OK correct=%.3f neutral=%.3f wrong=%.3f"
        % (supported, neutral, contradicted)
    )


if __name__ == "__main__":
    main()
