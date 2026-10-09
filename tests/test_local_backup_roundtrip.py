"""Synthetic local backup round trips. Never open the operator's data or .env."""
import io
import os
import sqlite3
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.helpers.cli_loader import load_script


@pytest.fixture
def backup(tmp_path, monkeypatch):
    cli = load_script('odysseus-backup')
    root = tmp_path / 'repo'
    root.mkdir()
    data = root / 'data'
    data.mkdir()
    monkeypatch.setattr(cli, '_REPO_ROOT', root)
    monkeypatch.setattr(cli, '_DATA_DIR', data)
    monkeypatch.setattr(cli, '_BACKUP_DIR', root / 'backups')
    results = []
    monkeypatch.setattr(cli, 'emit', lambda value, args: results.append(value))
    cli.results = results
    return cli


def options(**kw):
    return SimpleNamespace(**(dict(out=None, keep=None, include_env=False,
        include_attachments=False, include_research=False, pretty=False) | kw))


def make_db(path, value='saved'):
    path.parent.mkdir(exist_ok=True, parents=True)
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE items (value TEXT)')
    connection.execute('INSERT INTO items VALUES (?)', (value,))
    connection.commit()
    return connection


def test_roundtrip_all_sqlite_types_key_documents_scratchpad_vault(backup):
    data = backup._DATA_DIR
    connections = [make_db(data / name, name) for name in (
        'app.db', 'workspace-home.sqlite3', 'mail.sqlite', 'vaultwarden/db.sqlite3')]
    # Keep connections open: writes may still be in their WAL files.
    files = {
        '.app_key': b'synthetic-encryption-key', 'documents/id/a.md': b'local document',
        'scratchpad.md': b'fleeting thought', 'scratchpad.json': b'{"revision": 3}',
        'vaultwarden/attachments/id/file': b'vault attachment',
        'vaultwarden/rsa_key.pem': b'synthetic vault key',
        'vaultwarden-tls/key.pem': b'synthetic TLS key',
        'vaultwarden-access/admin-password.txt': b'synthetic admin password',
    }
    for name, body in files.items():
        path = data / name
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_bytes(body)
        os.utime(path, (1728000000, 1728000000))
    backup.cmd_snapshot(options())
    archive = Path(backup.results[-1]['path'])
    assert archive.stat().st_mode & 0o777 == 0o600
    assert archive.parent.stat().st_mode & 0o777 == 0o700
    assert backup.results[-1]['sqlite_snapshots'] == 4
    with tarfile.open(archive) as tar:
        names = tar.getnames()
        assert not any(n.endswith(('-wal', '-shm', '-journal')) for n in names)
        assert all(m.mode == (0o700 if m.isdir() else 0o600) for m in tar)
    for connection in connections:
        connection.close()
    (data / '.app_key').write_text('changed key')
    backup.cmd_restore(SimpleNamespace(path=str(archive), yes=True, restore_env=False))
    for name, body in files.items():
        assert (data / name).read_bytes() == body
        assert (data / name).stat().st_mode & 0o777 == 0o600
        assert (data / name).stat().st_mtime == 1728000000
    for name in ('app.db', 'workspace-home.sqlite3', 'mail.sqlite', 'vaultwarden/db.sqlite3'):
        with sqlite3.connect(data / name) as db:
            assert db.execute('SELECT value FROM items').fetchone() == (name,)
            assert db.execute('PRAGMA quick_check').fetchone() == ('ok',)
    for folder, _, _ in os.walk(data):
        assert Path(folder).stat().st_mode & 0o777 == 0o700
    assert list(backup._REPO_ROOT.glob('data.before-restore-*'))


def test_corrupt_database_fails_closed_without_partial_or_raw_copy(backup):
    (backup._DATA_DIR / 'broken.sqlite3').write_bytes(b'not a sqlite database')
    with pytest.raises(sqlite3.DatabaseError):
        backup.cmd_snapshot(options())
    assert not list(backup._BACKUP_DIR.glob('*'))
    assert (backup._DATA_DIR / 'broken.sqlite3').read_bytes() == b'not a sqlite database'


def test_backup_failure_does_not_publish_partial_archive(backup, monkeypatch):
    (backup._DATA_DIR / 'document.txt').write_text('saved')
    def failure(*args, **kwargs):
        raise OSError('synthetic full disk')
    monkeypatch.setattr(backup.os, 'link', failure)
    with pytest.raises(OSError, match='full disk'):
        backup.cmd_snapshot(options())
    assert not list(backup._BACKUP_DIR.glob('*'))


def test_snapshot_never_follows_symlink_sources_and_does_not_change_files(backup):
    outside = backup._REPO_ROOT / 'outside'
    outside.mkdir()
    (outside / 'secret').write_text('must not copy')
    data = backup._DATA_DIR
    (data / 'linked-dir').symlink_to(outside, target_is_directory=True)
    (data / 'linked-file').symlink_to(outside / 'secret')
    regular = data / 'normal.txt'
    regular.write_text('normal')
    before = regular.stat()
    backup.cmd_snapshot(options())
    with tarfile.open(backup.results[-1]['path']) as archive:
        assert archive.getnames() == ['data', 'data/normal.txt']
    assert regular.read_text() == 'normal'
    assert regular.stat().st_mtime_ns == before.st_mtime_ns
    assert (outside / 'secret').read_text() == 'must not copy'


def test_open_source_rejects_swapped_directory_symlink(backup):
    outside = backup._REPO_ROOT / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('not data')
    (backup._DATA_DIR / 'swapped').symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        backup._open_source(backup._DATA_DIR / 'swapped' / 'secret.txt')


def test_preserves_non_database_sidecars(backup):
    (backup._DATA_DIR / 'draft-wal').write_bytes(b'ordinary file')
    backup.cmd_snapshot(options())
    with tarfile.open(backup.results[-1]['path']) as archive:
        assert archive.extractfile('data/draft-wal').read() == b'ordinary file'


def test_existing_archive_or_output_symlink_is_never_overwritten(backup):
    existing = backup._REPO_ROOT / 'keep.tar.gz'
    existing.write_bytes(b'keep')
    with pytest.raises(SystemExit):
        backup.cmd_snapshot(SimpleNamespace(out=str(existing), keep=None,
            include_env=False, include_research=False, include_attachments=False))
    assert existing.read_bytes() == b'keep'
    link = backup._REPO_ROOT / 'link.tar.gz'
    link.symlink_to(existing)
    with pytest.raises(SystemExit):
        backup.cmd_snapshot(SimpleNamespace(out=str(link), keep=None,
            include_env=False, include_research=False, include_attachments=False))
    assert existing.read_bytes() == b'keep'


def test_explicit_retention_keeps_three_and_leaves_manual_archives(backup):
    backup._BACKUP_DIR.mkdir()
    manual = backup._BACKUP_DIR / 'odysseus-backup-20260101-030000.tar.gz'
    manual.write_bytes(b'old manual filename')
    unrelated = backup._BACKUP_DIR / 'vault-migration.tar'
    unrelated.write_bytes(b'migration')
    for _ in range(5):
        args = options()
        args.keep = 3
        backup.cmd_snapshot(args)
    generated = list(backup._BACKUP_DIR.glob('odysseus-backup-*-*-*.tar.gz'))
    assert len(generated) == 3
    assert manual.read_bytes() == b'old manual filename'
    assert unrelated.read_bytes() == b'migration'
    assert backup.results[-1]['retention_removed'] == 1


def test_default_does_not_delete_any_archives(backup):
    for _ in range(4):
        backup.cmd_snapshot(options())
    assert len(list(backup._BACKUP_DIR.glob('*.tar.gz'))) == 4


def test_environment_is_opt_in_and_restore_preserves_it_by_default(backup):
    environment = backup._REPO_ROOT / '.env'
    environment.write_text('SYNTHETIC_SETTING=first\n')
    backup.cmd_snapshot(options())
    with tarfile.open(backup.results[-1]['path']) as archive:
        assert '.env' not in archive.getnames()
    args = options()
    args.include_env = True
    backup.cmd_snapshot(args)
    filename = backup.results[-1]['path']
    environment.write_text('SYNTHETIC_SETTING=current\n')
    backup.cmd_restore(SimpleNamespace(path=filename, yes=True, restore_env=False))
    assert environment.read_text() == 'SYNTHETIC_SETTING=current\n'
    backup.cmd_restore(SimpleNamespace(path=filename, yes=True, restore_env=True))
    assert environment.read_text() == 'SYNTHETIC_SETTING=first\n'
    assert environment.stat().st_mode & 0o777 == 0o600
    assert next(backup._REPO_ROOT.glob('.env.before-restore-*')).read_text() == 'SYNTHETIC_SETTING=current\n'


def test_restore_failure_leaves_original_data_and_environment(backup, monkeypatch):
    (backup._DATA_DIR / 'keep.txt').write_text('original')
    environment = backup._REPO_ROOT / '.env'
    environment.write_text('CURRENT=synthetic\n')
    backup.cmd_snapshot(options())
    filename = backup.results[-1]['path']
    def failure(*args):
        raise OSError('synthetic extraction failure')
    monkeypatch.setattr(backup, '_extract_restore_members', failure)
    with pytest.raises(OSError, match='extraction'):
        backup.cmd_restore(SimpleNamespace(path=filename, yes=True, restore_env=False))
    assert (backup._DATA_DIR / 'keep.txt').read_text() == 'original'
    assert environment.read_text() == 'CURRENT=synthetic\n'
    assert not list(backup._REPO_ROOT.glob('data.before-restore-*'))


def test_verify_reads_truncated_payload_not_just_headers(backup):
    (backup._DATA_DIR / 'payload').write_bytes(os.urandom(200000))
    backup.cmd_snapshot(options())
    filename = Path(backup.results[-1]['path'])
    filename.write_bytes(filename.read_bytes()[:-100])
    with pytest.raises((SystemExit, EOFError)):
        backup.cmd_verify(SimpleNamespace(path=str(filename), pretty=False))


def test_large_file_snapshot_streams_without_reading_entire_file(backup):
    import tracemalloc
    path = backup._DATA_DIR / 'large-local-upload.bin'
    with path.open('wb') as stream:
        for _ in range(32):
            stream.write(b'x' * 1024 * 1024)
    tracemalloc.start()
    try:
        backup.cmd_snapshot(options())
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 5 * 1024 * 1024, peak
    with tarfile.open(backup.results[-1]['path']) as archive:
        assert archive.getmember('data/large-local-upload.bin').size == 32 * 1024 * 1024


def test_restore_publication_failure_rolls_back_data_and_environment(backup, monkeypatch):
    data = backup._DATA_DIR
    (data / 'keep.txt').write_text('saved')
    environment = backup._REPO_ROOT / '.env'
    environment.write_text('SYNTHETIC=saved\n')
    backup.cmd_snapshot(options(include_env=True))
    filename = backup.results[-1]['path']
    (data / 'keep.txt').write_text('current')
    environment.write_text('SYNTHETIC=current\n')
    original = backup.os.rename
    def rename(source, destination):
        if '.exodus-restore-' in str(source) and Path(source).name == 'data':
            raise OSError('synthetic publish failure')
        return original(source, destination)
    monkeypatch.setattr(backup.os, 'rename', rename)
    with pytest.raises(OSError, match='publish failure'):
        backup.cmd_restore(SimpleNamespace(path=filename, yes=True, restore_env=True))
    assert (data / 'keep.txt').read_text() == 'current'
    assert environment.read_text() == 'SYNTHETIC=current\n'


def test_restore_private_folders_stay_out_of_git_and_docker_context(tmp_path):
    import subprocess
    repo = Path(__file__).parents[1]
    sandbox = tmp_path / 'ignore-check'
    sandbox.mkdir()
    (sandbox / '.gitignore').write_text((repo / '.gitignore').read_text())
    subprocess.run(['git', 'init', '-q', str(sandbox)], check=True)
    private = ['data.before-restore-20261006-030000-123456/plain-note.md',
               '.exodus-restore-synthetic/private.txt']
    for name in private:
        result = subprocess.run(['git', '-C', str(sandbox), 'check-ignore', name],
                                capture_output=True, text=True)
        assert result.returncode == 0, name
    assert subprocess.run(['git', '-C', str(sandbox), 'check-ignore',
                           'src/data.before-restore-parser.py'], capture_output=True).returncode == 1
    dockerignore = (repo / '.dockerignore').read_text().splitlines()
    assert '/data.before-restore-*/' in dockerignore
    assert '/.exodus-restore-*/' in dockerignore
