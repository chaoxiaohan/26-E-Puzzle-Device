import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pi5_deploy as deploy


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix='puzzle-pi5-test-')).resolve()
        self.patch = patch.object(deploy, 'project_processes', return_value=[])
        self.patch.start()
        for name in ('puzzle_card_detector', 'puzzle_flutter_ui'):
            folder = self.home / name
            folder.mkdir()
            (folder / 'old-source').write_text(name)
        backend = self.home / 'puzzle_card_detector'
        (backend / 'serial_settings.json').write_text('{"calibration":"original"}')
        (backend / 'custom-calibration.json').write_text('{"custom":7}')
        (backend / 'captures').mkdir()
        (backend / 'captures/photo.png').write_bytes(b'original-photo')

    def tearDown(self):
        self.patch.stop()
        assert self.home.parent == Path(tempfile.gettempdir()).resolve()
        assert self.home.name.startswith('puzzle-pi5-test-')
        shutil.rmtree(self.home)

    def release(self, name):
        root = self.home / '.local/share/puzzle-device/releases' / name
        for relative in ('puzzle_card_detector/main.py', 'puzzle_card_detector/.venv/bin/python',
                         'puzzle_card_detector/librectangle_solver.so',
                         'puzzle_flutter_ui/build/linux/arm64/release/bundle/puzzle_flutter_ui'):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('test artifact ' + name)
        (root / 'puzzle_card_detector/serial_settings.json').write_text('{"calibration":"repository-default"}')
        record = {'activated': False, 'target': 'raspberry-pi5-aarch64',
                  'sha256': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for p in deploy.payload_files(root)}}
        (root / 'prepared.json').write_text(json.dumps(record))
        return root

    def test_preserve_settings_captures_and_rollback(self):
        release = self.release('first')
        backup = deploy.activate(release, self.home)
        backend = self.home / 'puzzle_card_detector'
        self.assertTrue(backend.is_symlink())
        self.assertEqual(json.loads((backend / 'serial_settings.json').read_text())['calibration'], 'original')
        self.assertEqual(json.loads((backend / 'custom-calibration.json').read_text())['custom'], 7)
        self.assertEqual((backend / 'captures/photo.png').read_bytes(), b'original-photo')
        (backend / 'captures/new.png').write_bytes(b'new-photo')
        deploy.rollback(backup, self.home)
        self.assertFalse(backend.is_symlink())
        self.assertEqual((backend / 'old-source').read_text(), 'puzzle_card_detector')
        self.assertEqual((backend / 'captures/new.png').read_bytes(), b'new-photo')
        self.assertTrue(release.exists())

    def test_second_update_and_two_rollbacks(self):
        first = deploy.activate(self.release('first'), self.home)
        second = deploy.activate(self.release('second'), self.home)
        deploy.rollback(second, self.home)
        self.assertTrue((self.home / 'puzzle_card_detector').is_symlink())
        deploy.rollback(first, self.home)
        self.assertEqual((self.home / 'puzzle_card_detector/captures/photo.png').read_bytes(), b'original-photo')

    def test_failed_switch_restores_both_original_directories(self):
        release = self.release('failed')
        original = Path.symlink_to
        def fail_ui(path, target, **kwargs):
            if path == self.home / 'puzzle_flutter_ui':
                raise OSError('simulated link failure')
            return original(path, target, **kwargs)
        with patch.object(Path, 'symlink_to', fail_ui), self.assertRaises(OSError):
            deploy.activate(release, self.home)
        for name in ('puzzle_card_detector', 'puzzle_flutter_ui'):
            self.assertFalse((self.home / name).is_symlink())
            self.assertTrue((self.home / name / 'old-source').exists())

    def test_reject_changed_payload_and_running_program(self):
        release = self.release('changed')
        (release / 'puzzle_card_detector/main.py').write_text('changed')
        with self.assertRaises(RuntimeError):
            deploy.activate(release, self.home)
        release = self.release('running')
        with patch.object(deploy, 'project_processes', return_value=[123]), self.assertRaises(RuntimeError):
            deploy.activate(release, self.home)
        self.assertFalse((self.home / 'puzzle_card_detector').is_symlink())

    def test_refuse_wrong_host_before_installing(self):
        with patch.object(deploy.platform, 'machine', return_value='x86_64'), self.assertRaises(RuntimeError):
            deploy.preflight(Path('/missing/flutter'))


if __name__ == '__main__':
    unittest.main()
