import numpy as np

from card_face_solver import _compare_edge_strips


def make_strip():
    strip = np.full((6, 96, 3), 245.0, dtype=np.float32)
    strip[:, 14:30] = (220.0, 25.0, 35.0)
    strip[:, 62:78] = (20.0, 20.0, 20.0)
    return strip


first = make_strip()
correct = make_strip()
wrong = np.full_like(first, 245.0)
wrong[:, 14:30] = (20.0, 20.0, 20.0)
wrong[:, 62:78] = (220.0, 25.0, 35.0)
valid = np.ones((6, 96), dtype=bool)

correct_quality, correct_evidence = _compare_edge_strips(
    (first, valid),
    (correct, valid),
)
wrong_quality, wrong_evidence = _compare_edge_strips(
    (first, valid),
    (wrong, valid),
)
if correct_quality <= wrong_quality + 0.20:
    raise RuntimeError(
        "spatial order was lost: %.3f %.3f"
        % (correct_quality, wrong_quality)
    )
if min(correct_evidence, wrong_evidence) < 0.30:
    raise RuntimeError("pattern evidence is unexpectedly low")

print(
    "CARD_TEXTURE_BAND_OK correct=%.3f wrong=%.3f evidence=%.3f"
    % (correct_quality, wrong_quality, correct_evidence)
)
