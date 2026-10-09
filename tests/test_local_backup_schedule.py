"""LaunchAgent creation in temporary directories; launchctl is always mocked."""
import importlib.util
import os
import sys
from pathlib import Path
import plistlib
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('setup_local_backups', Path(__file__).parents[1] / 'scripts/setup_local_backups.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


@pytest.fixture
def layout(tmp_path):
    root = tmp_path / 'Project with spaces'
    (root / 'scripts').mkdir(parents=True)
    (root / 'scripts/odysseus-backup').write_text('synthetic command')
    (root / '.env').write_text('SYNTHETIC_TEST=true')
    python = tmp_path / 'python executable'
    python.symlink_to(sys.executable)
    return root, python, tmp_path / 'home'


def test_install_daily_three_private_job_without_immediate_run(layout):
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1 if args[1] == 'print' else 0)
    root, python, home = layout
    result = setup.install(root, python, home, 501, runner)
    path = Path(result['plist'])
    config = plistlib.loads(path.read_bytes())
    assert config['ProgramArguments'] == [str(python), str(root / 'scripts/odysseus-backup'),
        'snapshot', '--include-env', '--include-attachments', '--keep', '3']
    assert config['StartCalendarInterval'] == {'Hour': 3, 'Minute': 0}
    assert config['RunAtLoad'] is False
    assert config['Umask'] == 0o077
    assert path.stat().st_mode & 0o777 == 0o600
    assert (root / 'backups/automation/backup.log').stat().st_mode & 0o777 == 0o600
    assert (root / 'backups/automation').stat().st_mode & 0o777 == 0o700
    assert calls == [['launchctl', 'print', 'gui/501/local.exodus.backup'],
        ['launchctl', 'bootstrap', 'gui/501', str(path)]]
    assert b'SYNTHETIC_TEST' not in path.read_bytes()


def test_bootstrap_failure_removes_new_plist(layout):
    root, python, home = layout
    def runner(*args, **kwargs):
        return SimpleNamespace(returncode=1)
    with pytest.raises(RuntimeError, match='no automatic backup'):
        setup.install(root, python, home, 501, runner)
    assert not list((home / 'Library/LaunchAgents').glob('*.plist'))


def test_existing_different_job_is_not_replaced(layout):
    root, python, home = layout
    target = home / 'Library/LaunchAgents/local.exodus.backup.plist'
    target.parent.mkdir(parents=True)
    payload = plistlib.dumps({'Label': setup.LABEL, 'ProgramArguments': ['other']})
    target.write_bytes(payload)
    with pytest.raises(RuntimeError, match='different'):
        setup.install(root, python, home, 501)
    assert target.read_bytes() == payload


def test_existing_matching_loaded_job_is_idempotent(layout):
    root, python, home = layout
    target = home / 'Library/LaunchAgents/local.exodus.backup.plist'
    target.parent.mkdir(parents=True)
    target.write_bytes(plistlib.dumps(setup.job_config(root, python, home, 501)))
    calls = []
    def runner(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)
    assert setup.install(root, python, home, 501, runner)['already_loaded']
    assert len(calls) == 1


def test_symlink_log_is_refused_without_touching_target(layout, tmp_path):
    root, python, home = layout
    outside = tmp_path / 'outside'
    outside.write_text('keep')
    logs = root / 'backups/automation'
    logs.mkdir(parents=True)
    (logs / 'backup.log').symlink_to(outside)
    with pytest.raises(OSError):
        setup.install(root, python, home, 501, lambda *a, **kw: SimpleNamespace(returncode=1))
    assert outside.read_text() == 'keep'
