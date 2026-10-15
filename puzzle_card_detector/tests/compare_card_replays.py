"""Compare full replay decisions, poses and ranking evidence, excluding timing."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics


def differences(first, second, path=''):
    if isinstance(first, dict) and isinstance(second, dict):
        ignored = {'seconds', 'elapsed_ms', 'environment'}
        keys = (first.keys() | second.keys()) - ignored
        for key in sorted(keys):
            if key not in first or key not in second:
                yield path + '/' + key
            else:
                yield from differences(first[key], second[key], path + '/' + key)
    elif isinstance(first, list) and isinstance(second, list):
        if len(first) != len(second):
            yield path + '/length'
        else:
            for index, (a, b) in enumerate(zip(first, second)):
                yield from differences(a, b, path + '/' + str(index))
    elif isinstance(first, (float, int)) and isinstance(second, (float, int)):
        if not math.isclose(first, second, rel_tol=1e-9, abs_tol=1e-9):
            yield path
    elif first != second:
        yield path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('baseline', type=Path)
    parser.add_argument('updated', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    records = []
    for path in sorted(args.baseline.glob('20*.json')):
        other = args.updated / path.name
        assert other.exists(), other
        first = json.loads(path.read_text(encoding='utf-8'))
        second = json.loads(other.read_text(encoding='utf-8'))
        changed = list(differences(first, second))
        images_equal = True
        for suffix in ('.png', '-candidates.jpg'):
            a = path.with_name(path.stem + suffix)
            b = other.with_name(path.stem + suffix)
            images_equal &= a.exists() == b.exists()
            if a.exists() and b.exists():
                images_equal &= hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
        records.append({'capture': path.stem, 'kind': first['kind'], 'baseline_seconds': first['seconds'],
                        'updated_seconds': second['seconds'], 'status': second['status'],
                        'speedup': first['seconds'] / max(1e-9, second['seconds']),
                        'differences': changed, 'images_identical': bool(images_equal)})
    assert records, 'No replay records'
    result = {'cases': records, 'count': len(records),
              'decisions_identical': all(not r['differences'] for r in records),
              'images_identical': all(r['images_identical'] for r in records),
              'baseline_total_seconds': sum(r['baseline_seconds'] for r in records),
              'updated_total_seconds': sum(r['updated_seconds'] for r in records),
              'median_case_speedup': statistics.median(r['speedup'] for r in records)}
    result['total_speedup'] = result['baseline_total_seconds'] / result['updated_total_seconds']
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}))
    for record in records:
        if record['differences'] or not record['images_identical']:
            print(json.dumps(record))
    assert result['decisions_identical'] and result['images_identical'], 'Replay regression'


if __name__ == '__main__':
    main()
