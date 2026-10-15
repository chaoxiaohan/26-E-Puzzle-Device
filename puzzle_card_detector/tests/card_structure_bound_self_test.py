"""Check score bounds against full scoring and exhaustive corner ranking."""
import card_corner_solver
import card_structure
from tests.card_performance_equivalence_self_test import same
from tests.card_structure_self_test import scene


def main():
    frame, pieces, expected = scene()
    original = card_corner_solver.score_layout_structure
    calls = []

    def checked(*args, **kwargs):
        result = original(*args, **kwargs)
        full = original(*args, **dict(kwargs, minimum_score=None))
        forced = original(*args, **dict(kwargs, minimum_score=1.1))
        if forced.get('pruned'):
            assert forced['score'] + 1e-12 >= full['score'], (forced, full)
        if result.get('pruned'):
            assert full['score'] < kwargs['minimum_score']
        else:
            same(result, full)
        calls.append(result.get('pruned', False))
        return result

    try:
        card_corner_solver.score_layout_structure = checked
        bounded = card_corner_solver.generate_corner_card_candidates(frame, pieces, cache={})
        card_corner_solver.score_layout_structure = lambda *args, **kwargs: original(*args, **dict(kwargs, minimum_score=None))
        exhaustive = card_corner_solver.generate_corner_card_candidates(frame, pieces, cache={})
    finally:
        card_corner_solver.score_layout_structure = original
    bounded.pop('elapsed_ms')
    exhaustive.pop('elapsed_ms')
    same(bounded, exhaustive)
    assert calls
    print('CARD_STRUCTURE_BOUND_OK candidates=%d pruned=%d' % (len(calls), sum(calls)))


if __name__ == '__main__':
    main()
