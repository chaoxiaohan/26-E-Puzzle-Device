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
    parser.add_argument('--recognition', action='store_true',
                        help='Allow search-count changes and bounded-score variation in rejected plain-paper controls')
    args = parser.parse_args()
    records = []
    for path in sorted(args.baseline.glob('20*.json')):
        other = args.updated / path.name
        assert other.exists(), other
        first = json.loads(path.read_text(encoding='utf-8'))
        second = json.loads(other.read_text(encoding='utf-8'))
        changed = list(differences(first, second))
        recognition_changes=[key for key in changed if key.rsplit('/',1)[-1] not in {'nodes','card_search_nodes'}]
        a_info,b_info=first.get('info') or {},second.get('info') or {}
        negative=(first['kind']=='plain' and first['status']!='VERIFIED' and second['status']!='VERIFIED'
                  and not a_info.get('card_execution_ready',False)
                  and not b_info.get('card_execution_ready',False))
        timed_negative=(negative and a_info.get('card_search_complete') is False
                        and b_info.get('card_search_complete') is False)
        score_changes=[key for key in recognition_changes if key.rsplit('/',1)[-1]
                       in {'score','selection_score','selection_margin','texture_score','texture_selection_margin'}]
        if timed_negative:
            recognition_changes=[key for key in recognition_changes if key.rsplit('/',1)[-1]
                not in {'score','selection_score','selection_margin','texture_score','texture_selection_margin'}]
        images_equal = True
        image_checks={}
        for suffix in ('.png', '-candidates.jpg'):
            a = path.with_name(path.stem + suffix)
            b = other.with_name(path.stem + suffix)
            equal=a.exists() == b.exists()
            if a.exists() and b.exists():
                equal &= hashlib.sha256(a.read_bytes()).digest() == hashlib.sha256(b.read_bytes()).digest()
            image_checks[suffix]=bool(equal)
            images_equal &= equal
        records.append({'capture': path.stem, 'kind': first['kind'], 'baseline_seconds': first['seconds'],
                        'updated_seconds': second['seconds'], 'status': second['status'],
                        'speedup': first['seconds'] / max(1e-9, second['seconds']),
                        'differences': changed, 'images_identical': bool(images_equal),
                        'primary_image_identical':image_checks['.png'],
                        'candidate_image_identical':image_checks['-candidates.jpg'],
                        'recognition_differences':recognition_changes,
                        'time_limited_negative_score_variation':timed_negative and bool(score_changes),
                        'recognition_passed':not recognition_changes and image_checks['.png']
                            and (image_checks['-candidates.jpg'] or (timed_negative and bool(score_changes)))})
    assert records, 'No replay records'
    result = {'cases': records, 'count': len(records),
              'decisions_identical': all(not r['differences'] for r in records),
              'images_identical': all(r['images_identical'] for r in records),
              'primary_images_identical':all(r['primary_image_identical'] for r in records),
              'recognition_passed':all(r['recognition_passed'] for r in records),
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
    if args.recognition:
        assert result['recognition_passed'], 'Recognition regression'
    else:
        assert result['decisions_identical'] and result['images_identical'], 'Replay regression'


if __name__ == '__main__':
    main()
