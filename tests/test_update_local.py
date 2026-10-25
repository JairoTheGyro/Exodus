"""Updater regression tests; no Git mutation, live Docker, credentials or data."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('exodus_update_local', Path(__file__).parents[1] / 'scripts/update_local.py')
updater = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = updater
SPEC.loader.exec_module(updater)
OLD, NEW = 'a' * 40, 'b' * 40


def configuration(root):
    return {'services': {
        'odysseus': {'build': {'context': str(root), 'dockerfile': 'Dockerfile'}, 'volumes': [
            {'type': 'bind', 'source': str(root / 'static'), 'target': '/app/static', 'read_only': True},
            {'type': 'bind', 'source': str(root / 'src/mounted.py'), 'target': '/app/src/mounted.py', 'read_only': True},
            {'type': 'bind', 'source': str(root / 'data'), 'target': '/app/data'},
        ], 'depends_on': {'searxng': {}, 'chromadb': {}}},
        'searxng': {'image': 'searxng:pinned', 'volumes': [
            {'type': 'bind', 'source': str(root / 'config/searxng'), 'target': '/config', 'read_only': True},
        ]},
        'chromadb': {'image': 'chroma:latest', 'volumes': [{'type': 'volume', 'source': 'chroma-data', 'target': '/data'}]},
        'harness': {'build': {'context': str(root / 'integrations/harness')}, 'volumes': [
            {'type': 'bind', 'source': str(root / 'integrations/harness/supervisor.mjs'), 'target': '/supervisor.mjs', 'read_only': True},
        ]},
        'vaultwarden-gateway': {'image': 'caddy:2-alpine', 'volumes': [
            {'type': 'bind', 'source': str(root / 'config/vaultwarden/Caddyfile'), 'target': '/etc/caddy/Caddyfile', 'read_only': True},
        ]},
    }, 'volumes': {'chroma-data': {}}, 'networks': {'default': {}, 'vault_private': {'internal': True}}}


class FakeRunner:
    def __init__(self, root):
        self.root, self.calls = root, []
        self.current = configuration(root)
        self.future = copy.deepcopy(self.current)
        self.head, self.target = OLD, NEW
        self.branch, self.dirty, self.origin = 'main', '', 'https://github.com/JairoTheGyro/Exodus.git'
        self.paths = ['static/js/home.js']
        self.tracked = ['docker-compose.yml', 'docker-compose.override.yml', *self.paths]
        self.docker_available = True
        self.fail_build = False
        self.fail_up = False
        self.fail_backup = False
        self.missing_images = set()
        self.containers = [{'service': name, 'hash': name + '-hash', 'running': True, 'oneoff': 'False',
                            'directory': str(root), 'files': ','.join(str(root / p) for p in updater.DEFAULT_FILES)} for name in self.current['services']]

    def run(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == sys.executable:  # scripts/odysseus-backup snapshot
            if self.fail_backup: raise updater.UpdateError('Backup failed')
            return ''
        if args[:3] == ['docker', 'image', 'inspect'] and args[3:5] == ['--format', '{{.Id}}']:
            if args[-1] in self.missing_images: raise updater.UpdateError('No such image')
            return 'sha256:feed\n'
        if args[:2] == ['docker', 'tag']: return ''
        if args[:3] == ['git', 'reset', '--hard']:
            self.head = args[3]
            return ''
        if args[:2] == ['git', 'rev-parse']:
            return {'--show-toplevel': str(self.root), 'HEAD': self.head, 'FETCH_HEAD': self.target,
                    '--git-path': '.git/exodus-update.json'}[args[2]] + '\n'
        if args[:2] == ['git', 'branch']: return self.branch + '\n'
        if args[:2] == ['git', 'status']: return self.dirty
        if args[:3] == ['git', 'remote', 'get-url']: return self.origin + '\n'
        if args[:2] == ['git', 'merge-base']: return ''
        if args[:2] == ['git', 'fetch']: return ''
        if args[:2] == ['git', 'pull']:
            self.head = self.target
            return ''
        if args[:2] == ['git', 'ls-tree']: return '\0'.join(self.tracked) + '\0'
        if args[:2] == ['git', 'diff']: return '\0'.join(self.paths) + '\0'
        if args[:2] == ['git', 'show']: return 'services:\n  odysseus: {}\n'
        if args[:2] == ['docker', 'info']:
            if not self.docker_available: raise updater.UpdateError('Docker unavailable')
            return 'test\n'
        if args[:2] == ['docker', 'ps']: return 'fake-id\n' if self.containers else ''
        if args[:2] == ['docker', 'inspect']: return '\n'.join(json.dumps(c) for c in self.containers)
        if args[:2] == ['docker', 'compose']:
            if 'version' in args: return 'test\n'
            if '--hash' in args: return '\n'.join(f'{name} {name}-hash' for name in self.current['services'])
            if '--format' in args:
                preview = any('/exodus-update-' in arg for arg in args)
                return json.dumps(self.future if preview or self.head == self.target else self.current)
            if 'build' in args:
                if self.fail_build: raise updater.UpdateError('Build failed')
                return ''
            if 'up' in args:
                if self.fail_up: raise updater.UpdateError('Health check failed after partial deployment')
                return ''
        raise AssertionError('Unexpected command: ' + repr(args))


class UpdaterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for name in updater.DEFAULT_FILES: (self.root / name).write_text('services: {}\n')
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/odysseus-backup').write_text('# stand-in; the fake runner records the call\n')
        self.runner = FakeRunner(self.root)
        self.messages = []

    def update(self, **kwargs):
        return updater.update(self.runner, self.root, say=self.messages.append, **kwargs)

    def plan(self, paths, before=None, after=None):
        before = before or self.runner.current
        return updater.plan_update(self.root, paths, before, after or before,
                                   self.runner.containers, {c['service']: c['hash'] for c in self.runner.containers})

    def test_expected_revision_must_match_github(self):
        with self.assertRaises(updater.UpdateError) as caught:
            self.update(expect='f' * 40)
        self.assertIn('changed after this update was approved', str(caught.exception))
        self.assertFalse(any(c[:2] == ['git', 'pull'] for c in self.runner.calls))
        self.runner.calls.clear()
        self.update(expect=self.runner.target)
        self.assertIn(['git', 'pull', '--ff-only', 'origin', 'main'], self.runner.calls)

    def test_mounted_ui_recreates_without_build_and_retains_data(self):
        private = self.root / '.env'; private.write_text('DO_NOT_PRINT=private-value\n')
        data = self.root / 'data'; data.mkdir(); (data / 'database.db').write_bytes(b'private database')
        plan = self.update()
        self.assertEqual(plan.recreate, {'odysseus'})
        self.assertFalse(plan.build)
        self.assertIn(['git', 'pull', '--ff-only', 'origin', 'main'], self.runner.calls)
        up = next(c for c in self.runner.calls if c[:2] == ['docker', 'compose'] and 'up' in c)
        self.assertIn('--no-deps', up); self.assertIn('--no-build', up); self.assertIn('--wait', up)
        self.assertEqual(up[up.index('--pull') + 1], 'missing')
        self.assertEqual(up[-1], 'odysseus')
        self.assertEqual(private.read_text(), 'DO_NOT_PRINT=private-value\n')
        self.assertEqual((data / 'database.db').read_bytes(), b'private database')
        self.assertNotIn('private-value', ''.join(self.messages))
        state = json.loads((self.root / '.git/exodus-update.json').read_text())
        self.assertEqual(state['applied'], NEW)
        self.assertEqual(state['rollback']['commit'], OLD)  # where --rollback goes back to

    def test_python_and_dependency_build_detection(self):
        self.assertFalse(self.plan(['src/mounted.py']).build)
        self.assertEqual(self.plan(['src/not-mounted.py']).build, {'odysseus'})
        for path in ['requirements.txt', 'requirements-optional.txt', 'Dockerfile', 'docker/entrypoint.sh', '.dockerignore']:
            with self.subTest(path=path): self.assertEqual(self.plan([path]).build, {'odysseus'})

    def test_nested_build_context_and_bound_companion_configs(self):
        self.assertEqual(self.plan(['integrations/harness/package.json']).build, {'harness'})
        self.assertFalse(self.plan(['integrations/harness/supervisor.mjs']).build)
        self.assertEqual(self.plan(['integrations/harness/supervisor.mjs']).recreate, {'harness'})
        self.assertEqual(self.plan(['config/searxng/settings.yml']).recreate, {'searxng'})
        self.assertFalse(self.plan(['config/vaultwarden/Caddyfile']).build)
        self.assertEqual(self.plan(['config/vaultwarden/Caddyfile']).recreate, {'vaultwarden-gateway'})

    def test_docs_and_tests_do_not_touch_containers(self):
        self.runner.paths = ['docs/guide.md', 'tests/test_update_local.py', 'SOVEREIGN_PRINCIPLES.md', 'scripts/update_local.py',
                             'scripts/cloud_setup.sh', 'scripts/cloud_test.py', 'requirements-cloud-test.txt']
        plan = self.update()
        self.assertFalse(plan.build | plan.recreate)
        self.assertFalse(any('up' in c or 'build' in c for c in self.runner.calls))

    def test_compose_service_configuration_and_ignored_env_changes(self):
        future = copy.deepcopy(self.runner.current)
        future['services']['odysseus']['environment'] = {'SAFE_SETTING': 'new'}
        self.assertEqual(self.plan(['docker-compose.yml'], after=future).recreate, {'odysseus'})
        self.runner.containers[0]['hash'] = 'old-env-hash'
        self.runner.paths = []
        plan = self.update()
        self.assertEqual(plan.recreate, {'odysseus'})
        self.assertFalse(plan.build)

    def test_network_membership_can_recreate_but_storage_migration_stops(self):
        future = copy.deepcopy(self.runner.current)
        future['services']['odysseus']['networks'] = {'default': {}, 'vault_private': {}}
        self.assertEqual(self.plan(['docker-compose.yml'], after=future).recreate, {'odysseus'})
        cases = []
        changed = copy.deepcopy(self.runner.current); changed['networks']['vault_private']['internal'] = False; cases.append(changed)
        changed = copy.deepcopy(self.runner.current); changed['services']['odysseus']['volumes'][-1]['source'] = '/different/data'; cases.append(changed)
        changed = copy.deepcopy(self.runner.current); del changed['volumes']['chroma-data']; cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(updater.UpdateError): self.plan(['docker-compose.yml'], after=changed)

    def test_only_needed_stopped_dependencies_are_started(self):
        next(c for c in self.runner.containers if c['service'] == 'searxng')['running'] = False
        self.assertEqual(self.plan(['static/app.js']).recreate, {'odysseus', 'searxng'})

    def test_dirty_and_untracked_files_refused_before_fetch(self):
        for dirty in [' M static/app.js\0', '?? draft.txt\0']:
            self.runner.dirty = dirty; self.runner.calls.clear()
            with self.assertRaises(updater.UpdateError): self.update()
            self.assertFalse(any(c[:2] == ['git', 'fetch'] for c in self.runner.calls))
            self.assertFalse(any(c[0] == 'docker' for c in self.runner.calls))

    def test_branch_and_origin_guards(self):
        self.runner.branch = 'feature'
        with self.assertRaises(updater.UpdateError): self.update()
        self.runner.branch = 'main'
        for origin in ['https://github.com/other/Exodus.git', 'https://token@github.com/JairoTheGyro/Exodus.git', 'file:///tmp/repo', 'https://github.com/JairoTheGyro/Exodus.git\nhttps://other.example/repo']:
            self.runner.origin = origin
            with self.subTest(origin=origin), self.assertRaises(updater.UpdateError): self.update()
        for origin in ['git@github.com:JairoTheGyro/Exodus.git', 'ssh://git@github.com/JairoTheGyro/Exodus', 'https://github.com/JairoTheGyro/Exodus.git']:
            self.assertIsNotNone(updater.REMOTE.fullmatch(origin))

    def test_docker_offline_stops_before_fetch_or_pull(self):
        self.runner.docker_available = False
        with self.assertRaises(updater.UpdateError): self.update()
        self.assertFalse(any(c[:2] in (['git', 'pull'], ['git', 'fetch']) for c in self.runner.calls))

    def test_incoming_private_data_is_refused_before_pull(self):
        for path in ['.env', '.env.production', 'data/app.db', 'config/chroma_data/x', 'backups/vault.tar',
                     'app.db', 'db.sqlite3-shm', 'db.sqlite-wal', 'backup.db-journal', 'private.pem', 'tls/private.key', 'id_ed25519']:
            self.runner.tracked = [path]; self.runner.calls.clear()
            with self.subTest(path=path), self.assertRaises(updater.UpdateError): self.update()
            self.assertFalse(any(c[:2] == ['git', 'pull'] for c in self.runner.calls))

    def test_active_tls_overlay_is_preserved(self):
        tls = self.root / 'docker-compose.vaultwarden-tls.yml'; tls.write_text('services: {}\n')
        self.runner.containers[0]['files'] += ',' + str(tls)
        files = updater.compose_files(self.root, self.runner.containers)
        self.assertEqual(files[-1], tls)
        self.assertEqual(len(files), 3)
        self.update(dry_run=True)
        self.assertTrue(any('config' in c and str(tls) in c for c in self.runner.calls))

    def test_wrong_checkout_and_conflicting_overlays_are_refused(self):
        self.runner.containers[0]['directory'] = '/other/checkout'
        with self.assertRaises(updater.UpdateError): self.update()
        self.runner.containers[0]['directory'] = str(self.root)
        extra = self.root / 'custom.yml'; extra.write_text('services: {}\n')
        self.runner.containers[0]['files'] = str(extra)
        with self.assertRaises(updater.UpdateError): self.update()

    def test_preview_never_pulls_or_reloads_or_writes_checkpoint(self):
        self.update(dry_run=True)
        self.assertTrue(any(c[:2] == ['git', 'fetch'] for c in self.runner.calls))
        self.assertFalse(any(c[:2] == ['git', 'pull'] or 'up' in c or 'build' in c for c in self.runner.calls))
        self.assertFalse((self.root / '.git/exodus-update.json').exists())

    def test_failed_build_retains_retry_baseline(self):
        self.runner.paths = ['requirements.txt']; self.runner.fail_build = True
        with self.assertRaises(updater.UpdateError): self.update()
        self.assertEqual(json.loads((self.root / '.git/exodus-update.json').read_text())['applied'], OLD)
        self.assertFalse(any('up' in c for c in self.runner.calls))
        self.runner.fail_build = False; self.runner.calls.clear()
        self.update()
        self.assertIn(['git', 'diff', '--name-only', '-z', OLD, NEW], self.runner.calls)
        self.assertTrue(any('build' in c for c in self.runner.calls))

    def test_partial_reload_failure_is_retried_from_checkpoint(self):
        self.runner.fail_up = True
        with self.assertRaises(updater.UpdateError): self.update()
        self.assertEqual(self.runner.head, NEW, 'A deployment failure must not reset source')
        self.assertEqual(json.loads((self.root / '.git/exodus-update.json').read_text())['applied'], OLD)
        self.runner.fail_up = False; self.runner.calls.clear()
        plan = self.update()
        self.assertEqual(plan.recreate, {'odysseus'})
        self.assertTrue(any('up' in c for c in self.runner.calls))
        self.assertEqual(json.loads((self.root / '.git/exodus-update.json').read_text())['applied'], NEW)

    def test_ignored_env_storage_move_does_not_switch_databases(self):
        self.runner.containers[0]['mounts'] = [{'Type': 'bind', 'Source': '/original/data', 'Destination': '/app/data', 'RW': True}]
        with self.assertRaises(updater.UpdateError): self.update()
        self.assertFalse(any(c[:2] == ['git', 'pull'] for c in self.runner.calls))

    def test_desktop_bind_alias_requires_verified_desktop_daemon(self):
        original = str(self.root / 'data')
        current = self.runner.containers[0]
        current['mounts'] = [{'Type': 'bind', 'Source': '/host_mnt' + original, 'Destination': '/app/data', 'RW': True}]
        with self.assertRaises(updater.UpdateError): self.plan([])
        current['desktop_host'] = True
        self.plan([])
        current['mounts'][0]['Source'] = '/host_mnt' + original + '-different'
        with self.assertRaises(updater.UpdateError): self.plan([])
        current['mounts'][0]['Source'] = '/run/desktop/mnt/host' + original
        self.plan([])

    def test_declared_anonymous_image_volume_is_retained(self):
        current = next(c for c in self.runner.containers if c['service'] == 'searxng')
        current['mounts'] = [{'Type': 'volume', 'Name': 'c' * 64, 'Destination': '/var/cache/searxng', 'RW': True}]
        with self.assertRaises(updater.UpdateError): self.plan([])
        current['image_volumes'] = ['/var/cache/searxng']
        self.plan([])
        current['mounts'][0]['Name'] = 'unexplained-named-data'
        with self.assertRaises(updater.UpdateError): self.plan([])

    def test_declared_named_alias_must_remain_explicitly_mounted(self):
        current = next(c for c in self.runner.containers if c['service'] == 'chromadb')
        current['image_volumes'] = ['/legacy-data']
        current['mounts'] = [
            {'Type': 'volume', 'Name': 'sovereign-hub_chroma-data', 'Destination': '/legacy-data', 'RW': True},
            {'Type': 'volume', 'Name': 'sovereign-hub_chroma-data', 'Destination': '/data', 'RW': True},
        ]
        self.plan([])
        current['mounts'][0]['Name'] = 'sovereign-hub_unexpected-data'
        with self.assertRaises(updater.UpdateError): self.plan([])

    def test_image_inspection_handles_images_without_volume_declarations(self):
        class InspectionRunner:
            def run(self, args):
                if args[:2] == ['docker', 'ps']: return 'id-1\nid-2\n'
                if args[:2] == ['docker', 'inspect']:
                    return '\n'.join(json.dumps(c) for c in [
                        {'service': 'app', 'image': 'sha256:app'},
                        {'service': 'search', 'image': 'sha256:search'},
                    ])
                if args[:3] == ['docker', 'image', 'inspect']:
                    return '\n'.join(json.dumps(i) for i in [
                        {'image': 'sha256:app', 'volumes': None},
                        {'image': 'sha256:search', 'volumes': {'/cache': {}}},
                    ])
                if args[:2] == ['docker', 'info']: return 'Docker Desktop\n'
                raise AssertionError(args)
        actual = updater.inspect_containers(InspectionRunner())
        self.assertEqual(actual[0]['image_volumes'], [])
        self.assertEqual(actual[1]['image_volumes'], ['/cache'])
        self.assertTrue(all(c['desktop_host'] for c in actual))

    def test_deleted_file_mount_stops_before_pull(self):
        self.runner.paths = ['src/mounted.py']
        self.runner.tracked = ['docker-compose.yml', 'docker-compose.override.yml']
        with self.assertRaises(updater.UpdateError): self.update()
        self.assertFalse(any(c[:2] == ['git', 'pull'] for c in self.runner.calls))

    def test_runner_uses_checkout_not_callers_cwd_and_redacts_failures(self):
        failed = subprocess.CompletedProcess(['docker'], 1, 'private output', 'PRIVATE_TOKEN=secret')
        with patch.object(updater.subprocess, 'run', return_value=failed) as run:
            with self.assertRaises(updater.UpdateError) as caught: updater.Runner(self.root).run(['docker', 'info'])
        self.assertEqual(run.call_args.kwargs['cwd'], self.root)
        self.assertNotIn('secret', str(caught.exception)); self.assertNotIn('private', str(caught.exception))


if __name__ == '__main__': unittest.main()
