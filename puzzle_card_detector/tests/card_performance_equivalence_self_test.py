"""Differential checks against a preserved pre-optimization backend directory."""
import argparse
import importlib.util
from pathlib import Path

import cv2
import numpy as np

import card_structure
import layout_constraints


def load_reference(directory, name):
    spec = importlib.util.spec_from_file_location('reference_' + name, directory / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def same(a, b):
    if isinstance(a, dict):
        assert a.keys() == b.keys()
        for key in a:
            same(a[key], b[key])
    elif isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            same(x, y)
    elif isinstance(a, (np.ndarray, float, int, np.number)):
        np.testing.assert_allclose(a, b, rtol=1e-12, atol=1e-12)
    else:
        assert a == b, (a, b)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    args = parser.parse_args()
    geometry = load_reference(args.baseline, 'layout_constraints')
    structure = load_reference(args.baseline, 'card_structure')
    rng = np.random.default_rng(815)
    cv2.setNumThreads(1)
    shape_cache={}
    for index in range(1000):
        a=rng.integers(0,2,tuple(rng.integers(1,45,2)),dtype=np.uint8)
        b=rng.integers(0,2,tuple(rng.integers(1,45,2)),dtype=np.uint8)
        if index%10==0:
            a[:]=0
        for first,second in ((a,b),(b,a),(a[::-1,::-1],b),(a.T,b)):
            same(structure._shape_similarity(first,second),card_structure._shape_similarity(first,second,shape_cache))
    for index in range(3000):
        first = rng.uniform(-100, 200, (2, 2))
        second = first + rng.uniform(-20, 20, (2, 2)) if index % 2 else rng.uniform(-100, 200, (2, 2))
        if index % 100 == 0:
            second[1] = second[0]
        tolerance = float(rng.uniform(1, 20))
        same(geometry._edge_match(first, second, tolerance), layout_constraints._edge_match(first, second, tolerance))
    for index in range(100):
        layout = {}
        for piece in range(4):
            points = rng.uniform(0, 100, (5, 2)).astype(np.float32)
            layout[piece] = cv2.convexHull(points).reshape(-1, 2).astype(float)
        same(geometry._raster_metrics(layout, 100, 100), layout_constraints._raster_metrics(layout, 100, 100))
    for index in range(30):
        ink = np.zeros((180, 120), np.uint8)
        for _ in range(30):
            x, y = rng.integers(0, 120), rng.integers(0, 180)
            cv2.putText(ink, str(rng.integers(0, 10)), (int(x), int(y)), cv2.FONT_HERSHEY_SIMPLEX, .4, 1, 1)
        ink = ink > 0
        same(structure._index_evidence(ink, [], shape_cache={}), card_structure._index_evidence(ink, [], shape_cache={}))
    print('CARD_PERFORMANCE_EQUIVALENCE_OK shapes=4000 edges=3000 rasters=100 index_masks=30')


if __name__ == '__main__':
    main()
