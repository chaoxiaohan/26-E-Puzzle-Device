from card_joint_solver import relative_texture_matches


def main():
    a = (0, 1, 0, 160, False)
    b = (1, 3, 0, 160, True)
    c = (2, 3, 0, 160, True)
    d = (3, 1, 0, 160, False)
    pairs = {(a, b): (0.25, 0.8), (a, c): (0.05, 0.8), (d, c): (0.35, 0.8)}
    correct = {"score": 0.25, "confidence": 1.0,
               "seams": [(0.25, 0.8, 0, 1, 80)], "pair_keys": [(a, b)]}
    wrong = {"score": 0.05, "confidence": 1.0,
             "seams": [(0.05, 0.8, 0, 2, 80)], "pair_keys": [(a, c)]}
    matched = relative_texture_matches(correct, pairs)
    rejected = relative_texture_matches(wrong, pairs)
    assert matched["score"] >= 0.62, "best compatible printed seam was rejected only for its absolute contrast"
    assert matched["score"] > rejected["score"] + 0.30
    blank = {"score": 0.5, "confidence": 0.0,
             "seams": [(1.0, 0.0, 0, 1, 80)], "pair_keys": [(a, b)]}
    neutral = relative_texture_matches(blank, {(a, b): (1.0, 0.0)})
    assert neutral["score"] == 0.5 and neutral["confidence"] == 0.0
    print("CARD_RELATIVE_TEXTURE_OK")


if __name__ == '__main__':
    main()
