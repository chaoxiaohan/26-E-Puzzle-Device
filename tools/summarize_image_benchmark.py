"""Aggregate an immutable board replay into per-image and per-trial evidence."""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import statistics


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', type=Path)
    parser.add_argument('--reference', type=Path, required=True)
    args = parser.parse_args()
    task = args.task
    cases = json.loads((task / 'green-cases.json').read_text())['cases']
    records = json.loads((task / 'results/results.json').read_text())
    assert records['completed'] == records['total'] == len(cases) * 3 + sum(c['kind'] == 'plain' for c in cases)
    assert all(r['exit_code'] == 0 for r in records['cases'])
    rows = []
    reference_checks = []
    for number, case in enumerate(cases, 1):
        name = case['capture']
        mode = 'NORMAL' if case['kind'] == 'plain' else 'CARD'
        trials = [r for r in records['cases'] if r['capture'] == name and r['mode'] == mode]
        assert len(trials) == 3
        representative = sorted(trials, key=lambda r: r['timings_ms']['analysis'])[1]
        relative = f"results/{mode.lower()}/run-{representative['repeat']}/{name}"
        hashes = [digest(task / f"results/{mode.lower()}/run-{r['repeat']}/{name}.png")
                  for r in trials if r['layout_found']]
        row = {'id': 'G%02d' % number, 'capture': name, 'kind': case['kind'], 'mode': mode,
               'status': representative['status'], 'status_stable': len({r['status'] for r in trials}) == 1,
               'image_stable': len(set(hashes)) == 1 and len(hashes) == 3,
               'piece_count': representative['piece_count'],
               'representative_run': representative['repeat'], 'representative_path': relative,
               'layout_found': representative['layout_found'], 'method': representative['method'],
               'score': representative['score'], 'nodes': representative['nodes'],
               'peak_rss_mib': max(r['max_rss_kib'] / 1024 for r in trials),
               'original_sha256': case['capture_data']['raw_sha256'],
               'output_sha256': digest(task / (relative + '.png')) if representative['layout_found'] else None,
               'roi': case['capture_data']['roi'], 'timings_ms': {
                   key: {'median': statistics.median(r['timings_ms'][key] for r in trials),
                         'min': min(r['timings_ms'][key] for r in trials),
                         'max': max(r['timings_ms'][key] for r in trials)}
                   for key in ('image_decode', 'detect', 'solve', 'post_preview', 'analysis')},
               'trial_analysis_ms': [r['timings_ms']['analysis'] for r in trials],
               'geometry': representative['info'].get('constraint_report', {}),
               'selection_margin': representative['info'].get('selection_margin'),
               'execution_ready': representative['info'].get('card_execution_ready', False)}
        reference = args.reference / (name + '.json')
        if case['kind'] != 'plain' and reference.exists():
            previous = json.loads(reference.read_text())
            for trial in trials:
                image = task / f"results/card/run-{trial['repeat']}/{name}.png"
                reference_checks.append({'capture': name, 'repeat': trial['repeat'],
                                         'status_equal': previous['status'] == trial['status'],
                                         'png_identical': digest(reference.with_suffix('.png')) == digest(image)})
        rows.append(row)
    groups = {}
    for key, group in (('all', rows), ('cards', [r for r in rows if r['mode'] == 'CARD']),
                       ('plain', [r for r in rows if r['mode'] == 'NORMAL']),
                       ('historical_cards', [r for r in rows if r['mode'] == 'CARD' and r['capture'] < '202610'])):
        groups[key] = {'images': len(group), 'status_counts': dict(collections.Counter(r['status'] for r in group)),
                       'layout_count': sum(r['layout_found'] for r in group),
                       'timings_ms': {stage: {'median_of_image_medians': statistics.median(r['timings_ms'][stage]['median'] for r in group),
                                              'max_image_median': max(r['timings_ms'][stage]['median'] for r in group),
                                              'max_single_run': max(r['timings_ms'][stage]['max'] for r in group)}
                                      for stage in ('detect', 'solve', 'analysis')}}
    negatives = [r for r in records['cases'] if r['kind'] == 'plain' and r['mode'] == 'CARD']
    result = {'date': '2026-10-18', 'device': 'Raspberry Pi 5 Model B Rev 1.1',
              'runtime_source_revision': '02505cf', 'repeats': 3, 'total_runs': records['total'],
              'groups': groups, 'cases': rows, 'reference_checks': reference_checks,
              'reference_identical': all(r['status_equal'] and r['png_identical'] for r in reference_checks),
              'negative_control': {'images': len(negatives), 'auto_approved': sum(r['status'] == 'VERIFIED' for r in negatives),
                                   'statuses': dict(collections.Counter(r['status'] for r in negatives))},
              'temperature_min_c': min(r[t]['temperature_c'] for r in records['cases'] for t in ('telemetry_before', 'telemetry_after')),
              'temperature_max_c': max(r[t]['temperature_c'] for r in records['cases'] for t in ('telemetry_before', 'telemetry_after')),
              'throttle_values': sorted({r[t]['throttled'] for r in records['cases'] for t in ('telemetry_before', 'telemetry_after')}),
              'peak_process_rss_mib': max(r['max_rss_kib']/1024 for r in records['cases']),
              'all_statuses_stable': all(r['status_stable'] for r in rows),
              'all_primary_images_stable': all(r['image_stable'] for r in rows)}
    (task / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    with (task / 'per-image.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        keys = ['id','capture','kind','mode','status','piece_count','detect_median_ms','solve_median_ms',
                'analysis_median_ms','analysis_min_ms','analysis_max_ms','peak_rss_mib','method','score','nodes','representative_run']
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            flat = {k: row[k] for k in keys if k in row}
            for stage in ('detect','solve','analysis'):
                flat[stage+'_median_ms'] = row['timings_ms'][stage]['median']
            flat['analysis_min_ms'] = row['timings_ms']['analysis']['min']
            flat['analysis_max_ms'] = row['timings_ms']['analysis']['max']
            writer.writerow(flat)
    with (task / 'all-trials.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        keys = ['capture','kind','mode','repeat','status','piece_count','detect_ms','solve_ms','analysis_ms',
                'image_decode_ms','post_preview_ms','process_wall_seconds','cpu_seconds','max_rss_kib','exit_code']
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in records['cases']:
            flat = {k: row[k] for k in keys if k in row}
            flat.update({k+'_ms': v for k,v in row['timings_ms'].items()})
            writer.writerow(flat)
    print(json.dumps({k: v for k,v in result.items() if k not in ('cases','reference_checks')}, indent=2))


if __name__ == '__main__':
    main()
