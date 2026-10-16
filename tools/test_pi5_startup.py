"""Linux launcher integration with fake processes; no camera, GTK or serial I/O."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


class StartupTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='puzzle-pi5-launch-')).resolve()
        self.home = self.root / 'home with spaces'
        self.backend = self.home / 'puzzle_card_detector'
        self.ui = self.home / 'puzzle_flutter_ui'
        source = Path(__file__).resolve().parents[1]
        for name in ('puzzle_card_detector', 'puzzle_flutter_ui'):
            (self.home / name).mkdir(parents=True)
            text = (source / name / ('start.sh' if name == 'puzzle_card_detector' else 'start_ui.sh')).read_text()
            text = text.replace('/tmp/puzzle_backend.log', str(self.root / 'backend.log'))
            (self.home / name / ('start.sh' if name == 'puzzle_card_detector' else 'start_ui.sh')).write_text(text)
        runtime = self.root / 'runtime'
        runtime.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in
                    ('DISPLAY', 'WAYLAND_DISPLAY', 'FLUTTER_LINUX_RENDERER', 'PUZZLE_PYTHON', 'PUZZLE_BACKEND_DIR')}
        self.env.update(XDG_RUNTIME_DIR=str(runtime), DISPLAY=':77', TEST_ROOT=str(self.root))
        self.python = self.backend / '.venv/bin/python'
        self.python.parent.mkdir(parents=True)
        self.python.write_text('#!/bin/sh\necho started >> "$TEST_ROOT/backend-starts"\nsleep .3\n')
        self.python.chmod(0o755)
        (self.backend / 'rectangle_solver.cpp').touch()
        (self.backend / 'librectangle_solver.so').touch()
        binary = self.ui / 'build/linux/arm64/release/bundle/puzzle_flutter_ui'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/usr/bin/python3\nimport json,os\nfrom pathlib import Path\n'
                          'Path(os.environ["TEST_ROOT"],"ui.json").write_text(json.dumps({k:os.environ.get(k) for k in '
                          '["DISPLAY","WAYLAND_DISPLAY","FLUTTER_LINUX_RENDERER","PUZZLE_PYTHON","PUZZLE_BACKEND_DIR"]}))\n')
        binary.chmod(0o755)

    def tearDown(self):
        # The fake detached backend exits within .3 seconds.
        time.sleep(.35)
        assert self.root.parent == Path(tempfile.gettempdir()).resolve()
        assert self.root.name.startswith('puzzle-pi5-launch-')
        shutil.rmtree(self.root)

    def launch(self):
        return subprocess.run(['bash', str(self.ui / 'start_ui.sh')], env=self.env, capture_output=True, text=True, timeout=5)

    def test_x11_and_native_renderer_default(self):
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((self.root / 'ui.json').read_text())
        self.assertEqual(state['DISPLAY'], ':77')
        self.assertIsNone(state['FLUTTER_LINUX_RENDERER'])
        self.assertEqual(state['PUZZLE_BACKEND_DIR'], str(self.backend))

    def test_preserve_wayland_and_explicit_renderer(self):
        self.env.pop('DISPLAY')
        self.env.update(WAYLAND_DISPLAY='wayland-7', FLUTTER_LINUX_RENDERER='software')
        result = self.launch()
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads((self.root / 'ui.json').read_text())
        self.assertIsNone(state['DISPLAY'])
        self.assertEqual(state['WAYLAND_DISPLAY'], 'wayland-7')
        self.assertEqual(state['FLUTTER_LINUX_RENDERER'], 'software')

    def test_missing_runtime_does_not_start_backend(self):
        self.python.unlink()
        result = self.launch()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.root / 'backend-starts').exists())

    def test_backend_lock_prevents_duplicate_start(self):
        command = ['bash', str(self.backend / 'start.sh')]
        first = subprocess.Popen(command, env=self.env)
        try:
            deadline = time.monotonic() + 3
            while not (self.root / 'backend-starts').exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue((self.root / 'backend-starts').exists())
            second = subprocess.run(command, env=self.env, timeout=3)
            self.assertEqual(second.returncode, 0)
        finally:
            first.wait(timeout=3)
        self.assertEqual((self.root / 'backend-starts').read_text().splitlines(), ['started'])


if __name__ == '__main__':
    unittest.main()
