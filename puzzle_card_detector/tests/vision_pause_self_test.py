"""运行真实主循环，验证异步等待时冻结视觉且仍响应控制与串口。"""

import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import main as backend
from maix import _ImageFrame
from ui_bridge import UiBridge


def run_case(mode, outcome, headless=True):
    context = SimpleNamespace(loop=0, now=100.0, reads=0, detections=0,
                              displays=0, services=0, queries=0, futures=[],
                              states=[], sleeps=[], timer_calls=0, stop_sent=False)
    pieces = []
    for index in range(4):
        x, y = 400 + index % 2 * 120, 80 + index // 2 * 160
        points = [(x, y), (x + 100, y), (x + 100, y + 140), (x, y + 140)]
        pieces.append({'points': points, 'center': (x + 50, y + 70), 'area': 14000.0,
                       'angle': 0.0, 'longest_edge': (points[1], points[2]), 'solidity': 1.0})

    class Camera:
        last_error = ''

        def __init__(self, *args):
            pass

        def read(self):
            context.reads += 1
            rgb = np.full((720, 1280, 3), (0, 120, 0), dtype=np.uint8)
            for piece in pieces:
                x, y = piece['points'][0]
                rgb[y:y + 140, x:x + 100] = 245
            rgb[0, 0, 0] = context.reads
            return _ImageFrame(rgb)

        def close(self):
            pass

    class Display:
        def width(self):
            return 1280

        def height(self):
            return 720

        def show(self, image):
            context.displays += 1

    class Serial:
        def service(self):
            context.services += 1

        def state(self):
            return {'serial_connected': False}

        def configure(self, **kwargs):
            pass

        def query_position(self):
            context.queries += 1

        def disconnect(self):
            pass

    class Future:
        def __init__(self, frame):
            self.submitted = context.loop
            self.frame = frame
            self.digest = hashlib.sha256(frame.tobytes()).hexdigest()
            self.cancelled = False
            self.result_calls = 0

        def done(self):
            return self.cancelled or context.loop >= self.submitted + 6

        def cancel(self):
            self.cancelled = True

        def result(self):
            self.result_calls += 1
            if outcome == 'error':
                raise RuntimeError('simulated worker failure')
            layout = {}
            for index, piece in enumerate(pieces):
                layout[index] = np.asarray(piece['points'], dtype=float) - piece['points'][0] + (index % 2 * 100, index // 2 * 140)
            info = {'ratio': 200 / 280, 'solve_scale': 1.0, 'width': 200.0, 'height': 280.0,
                    'method': 'test-result', 'execution_mode': 'EXEC', 'card_mode': mode == 'CARD',
                    'card_status': 'VERIFIED', 'card_execution_ready': True}
            return {'layout': layout, 'score': 0.9, 'nodes': 1, 'elapsed_ms': 1200.0,
                    'info': info, 'pieces': pieces, 'mode': mode,
                    'preview_rgb': np.full((140, 100, 3), (0, 120, 0), np.uint8)}

    class Executor:
        _processes = {}

        def submit(self, worker, *args):
            future = Future(args[0] if mode == 'CARD' else np.zeros((1, 1, 3), np.uint8))
            context.futures.append(future)
            return future

        def shutdown(self, **kwargs):
            pass

    class Bridge(UiBridge):
        def read_control(self):
            if context.loop == 2:
                return {'mode': mode, 'action': 'solve'}
            if context.futures:
                future = context.futures[0]
                if context.loop == future.submitted + 2:
                    return {'action': 'platform_query_position'}
                if outcome == 'stop' and context.loop == future.submitted + 4:
                    context.stop_sent = True
                    return {'action': 'stop_solve'}
            return None

        def publish_live(self, *args, **kwargs):
            super().publish_live(*args, force=True)

        def publish_state(self, state, force=False):
            super().publish_state(state, force=True)
            frame_digest = hashlib.sha256(Path(self.frame_path).read_bytes()).hexdigest()
            context.states.append(dict(state, frame_revision=self.frame_revision,
                                       result_available=self.result_available,
                                       jpeg_sha256=frame_digest, loop=context.loop,
                                       reads=context.reads, detections=context.detections,
                                       displays=context.displays, services=context.services))

    def need_exit():
        context.loop += 1
        context.now += 0.25
        return context.loop > 22

    def detect(*args, **kwargs):
        context.detections += 1
        return pieces, {'threshold': 128, 'mask': np.full((700, 520), 255, np.uint8),
                        'polarity': 'LIGHT', 'green_auto_values': None}

    def sleep(seconds):
        context.sleeps.append(seconds)
        context.now += seconds

    def timer(*args):
        context.timer_calls += 1
        return False

    with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {
        'PUZZLE_UI_DIR': directory, 'PUZZLE_HEADLESS': '1' if headless else '0',
        'PUZZLE_PORTRAIT': '0',
    }), patch.multiple(backend,
        RecoveringCamera=Camera, UiBridge=Bridge, SerialController=Serial,
        create_solver_executor=Executor, detect_pieces=detect,
        load_roi=lambda *args: (380, 10, 520, 700), load_vision_settings=lambda: {},
        save_vision_settings=lambda *args: None, load_templates=lambda: [],
        load_card_scoring_settings=lambda: {},
        build_stable_piece_set=lambda entries: pieces if entries else None,
        build_last_resort_layout=lambda *args: (None, 0.0, None),
        print_motion_plan=lambda *args: None, show_card_assembly_preview=lambda *args: None,
        print_detection=lambda *args: None, competition_timeout_reached=timer,
        time=SimpleNamespace(monotonic=lambda: context.now, sleep=sleep),
    ), patch.object(backend.app, 'need_exit', need_exit), \
        patch.object(backend.display, 'Display', Display), \
        patch.object(backend.touchscreen, 'TouchScreen', lambda: SimpleNamespace(read=lambda: (0, 0, False))), \
        patch.object(backend.cv2, 'waitKey', return_value=-1) as wait_key:
        backend.main()

    assert len(context.futures) == 1, len(context.futures)
    future = context.futures[0]
    paused = [state for state in context.states if state.get('vision_paused')]
    assert len(paused) >= 3, len(paused)
    # 提交当轮发布最后一帧；随后的等待循环不再读相机、检测或更新 JPEG。
    assert len({state['reads'] for state in paused}) == 1
    assert len({state['detections'] for state in paused}) == 1
    assert len({state['frame_revision'] for state in paused}) == 1
    assert len({state['jpeg_sha256'] for state in paused}) == 1
    assert all(state['solving'] and state['camera_ok'] for state in paused)
    assert all(state['fps'] == 0.0 for state in paused[1:])
    assert context.queries == 1
    assert context.services == len(context.states)
    assert paused[-1]['services'] > paused[0]['services']
    assert context.sleeps and all(value == 0.05 for value in context.sleeps)
    assert context.states[-1]['reads'] > paused[-1]['reads']
    assert context.states[-1]['frame_revision'] > paused[-1]['frame_revision']
    assert not context.states[-1]['vision_paused'] and not context.states[-1]['solving']
    assert hashlib.sha256(future.frame.tobytes()).hexdigest() == future.digest
    assert wait_key.call_count == (len(context.sleeps) if not headless else 0)
    if outcome == 'stop':
        assert context.stop_sent and future.cancelled and future.result_calls == 0
        assert any(state['solver_message'] == 'STOPPED' for state in context.states)
    else:
        assert future.result_calls == 1 and not future.cancelled
        if outcome == 'error':
            assert any(state['solver_message'] == ('CARD ERROR' if mode == 'CARD' else 'SOLVE ERROR') for state in context.states)
        else:
            assert context.states[-1]['result_available']
            assert len(context.states[-1]['solved_display']) == 4
            assert context.states[-1]['motion_plan_count'] == 4
    print('VISION_PAUSE_OK', mode, outcome, 'headless' if headless else 'native',
          'paused_states', len(paused), 'camera_reads', context.reads,
          'serial_services', context.services)


def main():
    for mode in ['CARD', 'NORMAL']:
        for outcome in ['complete', 'stop', 'error']:
            run_case(mode, outcome)
    run_case('CARD', 'complete', headless=False)


if __name__ == '__main__':
    main()
