"""Replay green captures without camera, serial commands, or runtime setting writes.

Each repetition uses a fresh process. The timer starts after imports and image
decoding; solve time is the deployed worker call, including its CARD previews.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time


def plain(value):
    if hasattr(value, 'tolist'):
        return value.tolist()
    if hasattr(value, 'item'):
        return value.item()
    raise TypeError(type(value).__name__)


def telemetry():
    result = {}
    for name, path in (
        ('temperature_c', '/sys/class/thermal/thermal_zone0/temp'),
        ('frequency_khz', '/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq'),
    ):
        try:
            result[name] = int(Path(path).read_text()) / (1000 if name == 'temperature_c' else 1)
        except OSError:
            pass
    command = subprocess.run(['vcgencmd', 'get_throttled'], capture_output=True, text=True)
    result['throttled'] = command.stdout.strip()
    return result


def run_one(args):
    import resource
    os.environ['PUZZLE_HEADLESS'] = '1'
    os.environ['PUZZLE_UI_DIR'] = str(args.output / 'isolated-runtime')
    sys.path.insert(0, str(args.backend.resolve()))
    import cv2
    import main as backend
    from card_face_solver import close_card_pattern_layout, render_layout_preview
    from cpp_rectangle_solver import load_library
    cv2.setNumThreads(1)
    assert load_library(str(args.backend / 'librectangle_solver.so')) is not None
    case = next(c for c in json.loads((args.dataset / 'green-cases.json').read_text())['cases']
                if c['capture'] == args.one)
    assert case['background'] == 'green'
    data = case['capture_data']
    image = args.dataset / 'originals' / (args.one + '_raw.png')
    assert hashlib.sha256(image.read_bytes()).hexdigest() == data['raw_sha256']
    load_start = time.perf_counter()
    frame = cv2.cvtColor(cv2.imread(str(image)), cv2.COLOR_BGR2RGB)
    load_ms = (time.perf_counter() - load_start) * 1000
    before = telemetry()
    cpu_start = time.process_time()
    start = time.perf_counter()
    pieces, detection = backend.detect_pieces(frame, tuple(data['roi']), **data['detection_parameters'])
    detected_at = time.perf_counter()
    if args.mode == 'CARD':
        result = backend.solve_card_piece_set_worker(frame, pieces, tuple(data['roi']))
    else:
        result = backend.solve_piece_set_worker(pieces, tuple(data['roi']), short_edge_protection=True)
    solved_at = time.perf_counter()
    info = result.get('info') or {}
    layout = result.get('layout')
    pattern = close_card_pattern_layout(layout, info) if layout is not None else None
    preview = result.get('preview_rgb')
    if preview is None and pattern is not None:
        preview = render_layout_preview(frame, result.get('pieces', pieces), pattern, fill_rectangle=True)
    preview_at = time.perf_counter()
    cpu_seconds = time.process_time() - cpu_start
    destination = args.output / args.mode.lower() / ('run-%d' % args.repeat)
    destination.mkdir(parents=True, exist_ok=True)
    if preview is not None:
        cv2.imwrite(str(destination / (args.one + '.png')), cv2.cvtColor(preview, cv2.COLOR_RGB2BGR))
    status = info.get('card_status', 'NO_LAYOUT') if args.mode == 'CARD' else (
        info.get('execution_mode', 'LAYOUT') if layout is not None else 'NO_LAYOUT')
    record = {'capture': args.one, 'kind': case['kind'], 'mode': args.mode, 'repeat': args.repeat,
              'status': status, 'method': info.get('method'), 'layout_found': layout is not None,
              'piece_count': len(pieces), 'seconds': solved_at - detected_at,
              'timings_ms': {'image_decode': load_ms, 'detect': (detected_at - start) * 1000,
                             'solve': (solved_at - detected_at) * 1000,
                             'post_preview': (preview_at - solved_at) * 1000,
                             'analysis': (preview_at - start) * 1000},
              'cpu_seconds': cpu_seconds, 'max_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              'telemetry_before': before, 'telemetry_after': telemetry(),
              'score': result.get('score'), 'nodes': result.get('nodes'), 'info': info,
              'source_pieces': result.get('pieces', pieces), 'pattern_layout': pattern,
              'candidate_count': len(result.get('candidate_pool', [])),
              'source_sha256': data['raw_sha256'], 'roi': data['roi'],
              'environment': platform.platform(), 'detection': 'fresh',
              'short_edge_protection': args.mode == 'NORMAL'}
    (destination / (args.one + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2, default=plain))
    print(json.dumps({k: record[k] for k in ('capture', 'mode', 'repeat', 'status', 'timings_ms')}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--one')
    parser.add_argument('--mode', choices=('CARD', 'NORMAL'))
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--only-normal', action='store_true', help='Rerun NORMAL rows and merge into existing results')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.one:
        run_one(args)
        return
    cases = json.loads((args.dataset / 'green-cases.json').read_text())['cases']
    assert cases and all(c['background'] == 'green' for c in cases)
    jobs = [(case, 'NORMAL' if case['kind'] == 'plain' else 'CARD', repeat)
            for repeat in range(1, args.repeats + 1) for case in cases]
    jobs += [(case, 'CARD', 1) for case in cases if case['kind'] == 'plain']
    previous = None
    if args.only_normal:
        jobs = [job for job in jobs if job[1] == 'NORMAL']
        previous = json.loads((args.output / 'results.json').read_text())
    records = []
    for case, mode, repeat in jobs:
        path = args.output / mode.lower() / ('run-%d' % repeat) / (case['capture'] + '.json')
        command = [sys.executable, __file__, '--dataset', str(args.dataset), '--backend', str(args.backend),
                   '--output', str(args.output), '--one', case['capture'], '--mode', mode, '--repeat', str(repeat)]
        started = time.perf_counter()
        try:
            process = subprocess.run(command, capture_output=True, timeout=args.timeout)
            log = process.stdout + process.stderr
            code = process.returncode
        except subprocess.TimeoutExpired as error:
            log = (error.stdout or b'') + (error.stderr or b'')
            code = 124
        path.parent.mkdir(parents=True, exist_ok=True)
        path.with_suffix('.log').write_bytes(log)
        record = json.loads(path.read_text()) if code == 0 and path.exists() else {
            'capture': case['capture'], 'kind': case['kind'], 'mode': mode, 'repeat': repeat,
            'status': 'TIMEOUT' if code == 124 else 'ERROR'}
        record.update(exit_code=code, process_wall_seconds=time.perf_counter() - started)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=plain))
        records.append({k: v for k, v in record.items() if k not in ('source_pieces', 'pattern_layout')})
        summary = {'completed': len(records), 'total': len(jobs), 'cases': records}
        (args.output / 'progress.tmp').write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=plain))
        (args.output / 'progress.tmp').replace(args.output / ('results-normal.json' if args.only_normal else 'results.json'))
        print('%d/%d %s %s %d %s %.3fs' % (len(records), len(jobs), case['capture'], mode, repeat,
                                          record['status'], record['process_wall_seconds']), flush=True)
    if previous is not None:
        replacements = {(r['capture'], r['mode'], r['repeat']): r for r in records}
        previous['cases'] = [replacements.get((r['capture'], r['mode'], r['repeat']), r) for r in previous['cases']]
        previous['normal_short_edge_protection'] = True
        (args.output / 'results.json').write_text(json.dumps(previous, ensure_ascii=False, indent=2, default=plain))
    if any(r['exit_code'] for r in records):
        raise SystemExit('Some runs failed; inspect results.json')


if __name__ == '__main__':
    main()
