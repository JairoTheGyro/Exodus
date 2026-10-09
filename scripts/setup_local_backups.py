#!/usr/bin/env python3
"""Prepare/install one lightweight daily macOS launchd job for local backups.

Default is a read-only preview. --install loads the job, without running a
backup immediately. It never starts a container or exposes local credentials.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LABEL = 'local.exodus.backup'


def job_config(root, python, home, uid):
    root, python, home = Path(root), Path(python), Path(home)
    return {
        'Label': LABEL,
        'ProgramArguments': [str(python), str(root / 'scripts/odysseus-backup'),
                             'snapshot', '--include-env', '--include-attachments', '--keep', '3'],
        'WorkingDirectory': str(root),
        'StartCalendarInterval': {'Hour': 3, 'Minute': 0},
        'RunAtLoad': False,
        'ProcessType': 'Background',
        'LowPriorityIO': True,
        'Nice': 10,
        'Umask': 0o077,
        'StandardOutPath': str(root / 'backups/automation/backup.log'),
        'StandardErrorPath': str(root / 'backups/automation/backup-error.log'),
        # No environment credentials or shell command interpolation in this file.
        'EnvironmentVariables': {'PYTHONDONTWRITEBYTECODE': '1'},
    }


def _private_directory(path):
    if path.is_symlink():
        raise RuntimeError('Backup setup refuses symbolic-link private directories')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def install(root, python, home, uid, runner=subprocess.run):
    root, python, home = Path(root), Path(python), Path(home)
    if not python.is_file() or not os.access(python, os.X_OK):
        raise RuntimeError('The selected Python executable is not available')
    if not (root / 'scripts/odysseus-backup').is_file():
        raise RuntimeError('The existing backup command is missing')
    if not (root / '.env').is_file() or (root / '.env').is_symlink():
        raise RuntimeError('Expected the regular local .env file for environment backup')
    config = job_config(root, python, home, uid)
    folder = home / 'Library/LaunchAgents'
    target = folder / (LABEL + '.plist')
    previous = None
    if target.is_symlink():
        raise RuntimeError('Refusing a symbolic-link LaunchAgent file')
    if target.exists():
        previous = target.read_bytes()
        if plistlib.loads(previous) != config:
            raise RuntimeError('A different backup LaunchAgent already exists; review it before replacing it')
    domain = 'gui/' + str(uid)
    active = runner(['launchctl', 'print', domain + '/' + LABEL], capture_output=True)
    if active.returncode == 0:
        if previous is None:
            raise RuntimeError('A loaded backup job exists without the expected configuration; review it first')
        return {'ok': True, 'installed': True, 'already_loaded': True, 'plist': str(target)}
    _private_directory(root / 'backups')
    logs = root / 'backups/automation'
    _private_directory(logs)
    for name in ('backup.log', 'backup-error.log'):
        path = logs / name
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix='.exodus-backup-', dir=folder)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), 0o600)
            plistlib.dump(config, output)
            output.flush()
            os.fsync(output.fileno())
        if previous is None:
            # No-clobber publication if another process configures the same job.
            os.link(temporary, target)
        result = runner(['launchctl', 'bootstrap', domain, str(target)], capture_output=True)
        if result.returncode:
            if previous is None:
                target.unlink(missing_ok=True)
            raise RuntimeError('launchd refused the backup job; no automatic backup has been activated')
    finally:
        temporary.unlink(missing_ok=True)
    return {'ok': True, 'installed': True, 'already_loaded': False, 'plist': str(target)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true', help='install and load daily 03:00 job; does not run immediately')
    parser.add_argument('--python', default=sys.executable, help='absolute host Python 3 executable used by launchd')
    args = parser.parse_args()
    python = Path(args.python).resolve()
    summary = {'daily_local_time': '03:00', 'keep_newest': 3,
               'destination': str(ROOT / 'backups'), 'includes_environment': True,
               'includes_cached_mail_attachments': True, 'encrypted': False,
               'immediate_run': False, 'off_device': False,
               'limits': ['Mac must be awake/logged in; sleeping jobs run after wake',
                          'Docker named volumes and external/custom data directories are not included',
                          'Stop writers for a coherent snapshot across files and databases']}
    if args.install:
        if sys.platform != 'darwin':
            raise RuntimeError('This installer is only for the local macOS host')
        summary.update(install(ROOT, python, Path.home(), os.getuid()))
    else:
        summary.update({'installed': False, 'preview_only': True})
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        print('Backup setup failed: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
