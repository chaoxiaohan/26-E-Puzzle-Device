"""Build on a Pi 5, then switch the existing launch paths with rollback."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import uuid


def contained(path, root):
    path, root = path.resolve(), root.resolve()
    if path == root or root not in path.parents:
        raise RuntimeError('Path is outside the installation directory: ' + str(path))
    return path


def run(command, cwd=None):
    subprocess.run([str(value) for value in command], cwd=cwd, check=True)


def check_pi():
    if platform.system() != 'Linux' or platform.machine() not in ('aarch64', 'arm64'):
        raise RuntimeError('Build and install on 64-bit Raspberry Pi OS/Linux, not this host.')
    if os.geteuid() == 0:
        raise RuntimeError('Run as your normal Pi desktop user, not root; the installer invokes sudo only for system setup.')
    model = Path('/proc/device-tree/model').read_text().rstrip('\0\n')
    if 'Raspberry Pi 5' not in model:
        raise RuntimeError('Expected Raspberry Pi 5, found: ' + model)
    if not (3, 10) <= sys.version_info[:2] < (3, 14):
        raise RuntimeError('The pinned dependencies require Python 3.10-3.13. Set PUZZLE_SETUP_PYTHON to that interpreter.')
    return {'model': model, 'architecture': platform.machine(), 'python': sys.version,
            'hardware_validated': False}


def preflight(flutter):
    info = check_pi()
    if not flutter.is_file() or not os.access(flutter, os.X_OK):
        raise RuntimeError('Flutter SDK missing. Set --flutter-bin or FLUTTER_BIN (the saved project used Flutter 3.44.8 / Dart 3.12.2).')
    return dict(info, flutter=str(flutter))


def project_processes(home, proc=Path('/proc')):
    targets = [(home / name).resolve() for name in ('puzzle_card_detector', 'puzzle_flutter_ui')]
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            name = (entry / 'comm').read_text()
            if 'python' not in name and 'puzzle' not in name:
                continue
            args = (entry / 'cmdline').read_bytes().decode().split('\0')
            cwd = (entry / 'cwd').resolve()
            for arg in args[:3]:
                if Path(arg).name not in ('main.py', 'puzzle_flutter_ui'):
                    continue
                path = (cwd / arg).resolve()
                if any(target in path.parents for target in targets):
                    found.append(int(entry.name))
                    break
        except (OSError, UnicodeError):
            continue
    return found


def payload_files(release):
    for name in ('puzzle_card_detector', 'puzzle_flutter_ui'):
        for path in sorted((release / name).rglob('*')):
            relative = path.relative_to(release)
            if any(part in ('.venv', '__pycache__', '.dart_tool', 'captures', 'ephemeral') for part in relative.parts):
                continue
            if 'build' in relative.parts and 'bundle' not in relative.parts:
                continue
            if path.is_file() and not (relative.parent == Path('puzzle_card_detector') and path.suffix == '.json'):
                yield path


def verify_release(release):
    record = json.loads((release / 'prepared.json').read_text())
    if record.get('activated'):
        raise RuntimeError('This release was already activated; prepare a new release for another update.')
    if record.get('target') != 'raspberry-pi5-aarch64':
        raise RuntimeError('Not a prepared Raspberry Pi 5 release')
    for name, digest in record['sha256'].items():
        path = contained(release / name, release)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Prepared release changed: ' + name)
    for name in ('puzzle_card_detector/.venv/bin/python',
                 'puzzle_card_detector/librectangle_solver.so',
                 'puzzle_flutter_ui/build/linux/arm64/release/bundle/puzzle_flutter_ui'):
        if not (release / name).is_file():
            raise RuntimeError('Incomplete prepared release: ' + name)
    return record


def prepare(root, home, flutter, skip_apt=False, wheelhouse=None):
    if not skip_apt:
        run(['sudo', 'apt-get', 'update'])
        run(['sudo', 'apt-get', 'install', '-y', 'python3-venv', 'g++', 'pkg-config',
             'v4l-utils', 'libgtk-3-dev', 'libgl1', 'libusb-1.0-0', 'clang', 'cmake', 'ninja-build'])
    release = home / '.local/share/puzzle-device/releases' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
    release.mkdir(parents=True)
    for name in ('puzzle_card_detector', 'puzzle_flutter_ui'):
        shutil.copytree(root / name, release / name, ignore=shutil.ignore_patterns(
            '.git', '.venv', '__pycache__', '.dart_tool', 'build', 'ephemeral', 'captures',
            '*.pyc', '*.log', '*.so', '*.dll', '.flutter-plugins-dependencies'))
    backend, ui = release / 'puzzle_card_detector', release / 'puzzle_flutter_ui'
    # The venv stays at this permanent path; moving it would break its shebangs.
    run([sys.executable, '-m', 'venv', backend / '.venv'])
    python = backend / '.venv/bin/python'
    command = [python, '-m', 'pip', 'install', '--only-binary=:all:', '-r', backend / 'requirements-pi5.txt']
    if wheelhouse:
        command.extend(['--no-index', '--find-links', wheelhouse])
    run(command)
    run(['bash', backend / 'build_cpp_solver.sh'])
    run([python, '-c', 'from cpp_rectangle_solver import load_library; assert load_library() is not None'], cwd=backend)
    run([flutter, 'pub', 'get'], cwd=ui)
    run([flutter, 'build', 'linux', '--release'], cwd=ui)
    record = {'created_at': datetime.now().isoformat(), 'activated': False, 'target': 'raspberry-pi5-aarch64',
              'sha256': {str(p.relative_to(release)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in payload_files(release)}}
    (release / 'prepared.json').write_text(json.dumps(record, indent=2))
    verify_release(release)
    return release


def configure_access(release):
    import pwd
    user = pwd.getpwuid(os.getuid()).pw_name
    rule = Path('/etc/udev/rules.d/99-puzzle-ch340.rules')
    if not rule.exists() and not rule.is_symlink():
        run(['sudo', 'install', '-m', '0644', release / 'puzzle_card_detector/99-puzzle-ch340.rules', rule])
    else:
        print('Preserved the existing CH340 udev rule.')
    for group in ('dialout', 'video', 'render'):
        if subprocess.run(['getent', 'group', group], stdout=subprocess.DEVNULL).returncode == 0:
            run(['sudo', 'usermod', '-aG', group, user])
    run(['sudo', 'udevadm', 'control', '--reload-rules'])
    print('New group permissions require a new login; reconnect USB devices for the udev alias.')


def activate(release, home):
    home, release = home.resolve(), release.resolve()
    contained(release, home / '.local/share/puzzle-device/releases')
    record = verify_release(release)
    names = ('puzzle_card_detector', 'puzzle_flutter_ui')
    for name in names:
        contained(home / name, home)
    active = project_processes(home)
    if active:
        raise RuntimeError('Close the current puzzle UI/backend before activating; active PIDs: ' + str(active))
    backend = release / names[0]
    for config in (home / names[0]).glob('*.json'):
        shutil.copy2(config, backend / config.name)
    capture = home / names[0] / 'captures'
    original_capture = capture.resolve() if capture.exists() else None
    original_backend = (home / names[0]).resolve()
    backup = home / '.local/share/puzzle-device/backups' / release.name
    backup.mkdir(parents=True, exist_ok=False)
    moved, linked = [], []
    try:
        for name in names:
            source, destination = home / name, backup / name
            contained(source, home)
            contained(destination, home)
            if source.exists() or source.is_symlink():
                source.rename(destination)
                moved.append(name)
            source.symlink_to(release / name, target_is_directory=True)
            linked.append(name)
        if original_capture:
            # A real directory was moved into the backup; an earlier release
            # symlink still points to its permanent location.
            if original_backend == home / names[0]:
                original_capture = backup / names[0] / 'captures'
            (backend / 'captures').symlink_to(original_capture, target_is_directory=True)
        (backup / 'rollback.json').write_text(json.dumps({'release': str(release), 'moved': moved}, indent=2))
        record['activated'] = True
        (release / 'prepared.json').write_text(json.dumps(record, indent=2))
    except Exception:
        for name in reversed(linked):
            target = home / name
            if target.is_symlink() and target.resolve() == release / name:
                target.unlink()
        for name in reversed(moved):
            (backup / name).rename(home / name)
        raise
    return backup


def rollback(backup, home):
    home, backup = home.resolve(), backup.resolve()
    contained(backup, home / '.local/share/puzzle-device/backups')
    record = json.loads((backup / 'rollback.json').read_text())
    release = contained(Path(record['release']), home / '.local/share/puzzle-device/releases')
    if project_processes(home):
        raise RuntimeError('Close the puzzle UI/backend before rollback.')
    names = ('puzzle_card_detector', 'puzzle_flutter_ui')
    if any(name not in names for name in record['moved']):
        raise RuntimeError('Invalid rollback record')
    for name in names:
        target = home / name
        if not target.is_symlink() or target.resolve() != release / name:
            raise RuntimeError('Installation path changed; preserved backup: ' + str(backup))
        if name in record['moved']:
            contained(backup / name, home)
            if not (backup / name).exists():
                raise RuntimeError('Missing backup: ' + name)
    for name in names:
        (home / name).unlink()
        if name in record['moved']:
            (backup / name).rename(home / name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--check', action='store_true', help='Read-only Pi/SDK preflight')
    parser.add_argument('--skip-apt', action='store_true', help='System build dependencies are already installed')
    action.add_argument('--prepare-only', action='store_true', help='Build a release without changing launch paths')
    action.add_argument('--activate', type=Path, help='Activate a previously prepared release')
    action.add_argument('--rollback', type=Path, help='Restore an installation backup')
    parser.add_argument('--flutter-bin', type=Path, default=Path(os.environ.get('FLUTTER_BIN', str(Path.home() / 'flutter/bin/flutter'))))
    parser.add_argument('--wheelhouse', type=Path)
    args = parser.parse_args()
    home = Path.home()
    if args.rollback:
        rollback(args.rollback, home)
        print('ROLLBACK_OK')
        return
    if args.activate:
        check_pi()
        contained(args.activate, home / '.local/share/puzzle-device/releases')
        verify_release(args.activate.resolve())
        configure_access(args.activate.resolve())
        print('BACKUP=' + str(activate(args.activate, home)))
        return
    info = preflight(args.flutter_bin.resolve())
    print(json.dumps(info, ensure_ascii=False))
    if args.check:
        return
    root = Path(__file__).resolve().parents[1]
    release = prepare(root, home, args.flutter_bin.resolve(), args.skip_apt, args.wheelhouse)
    print('PREPARED=' + str(release))
    if not args.prepare_only:
        configure_access(release)
        print('BACKUP=' + str(activate(release, home)))
        print('Start from your desktop: bash "$HOME/puzzle_flutter_ui/start_ui.sh"')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError) as error:
        raise SystemExit(str(error))
